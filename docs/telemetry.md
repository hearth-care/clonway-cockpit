# Run telemetry (`clonway_cockpit.obs`)

`make_obs(worker_id=...)` builds a worker's `(event, run_session)` pair. `run_session` wraps a
run, buffers its events, and on exit uploads them as one JSONL object to the shared fleet bucket
at `logs/<worker_id>/<YYYY-MM-DD>/<run_id>.jsonl`. The wire shape is documented in the module
docstring of `src/clonway_cockpit/obs/_telemetry.py`; this page covers where the upload goes and
how a worker can tell that it happened.

## Which bucket

There is no built-in bucket name. The upload goes to, in this order:

1. the `bucket=` argument to `make_obs` (or to `flush_buffer` / `flush_buffer_outcome`);
2. the `CLONWAY_FLEET_BUCKET` environment variable, read when the upload happens;
3. nowhere. With neither, nothing is uploaded and one info line is logged:
   `no fleet bucket configured: reminders are not being published`.

The reason: a default name let an ordinary test run on a machine with working cloud
credentials write into live fleet storage. Pair this with the test guard
(`clonway_cockpit.testing.no_live_storage`, see below).

## Did the upload happen

`run_session` is a context manager and cannot return a value, so the outcome is available in
three places:

| Where | What you get |
|---|---|
| `flush_buffer_outcome(buffer, ...)` | A `FleetStorageOutcome`: `"ok"` (uploaded, or the buffer was empty), `"not_configured"` (no bucket), `"failed"` (the upload raised). |
| `flush_buffer(buffer, ...)` | The existing boolean: `True` only for `"ok"`. `False` means not uploaded; use `flush_buffer_outcome` to tell which. |
| `last_flush_outcome(worker_id)` | The outcome of the latest non-empty flush for that worker in this process, so it covers the upload `run_session` makes on exit. `None` if the runtime gate skipped the upload. |

A failed upload logs **one warning** with the exception type and the object path, for example
`fleet storage failed (Forbidden) for gs://<bucket>/logs/<worker>/<date>/<run_id>.jsonl`. It
never logs the event contents. Neither function raises: telemetry never breaks a worker run.
Before this change a credentials or permission failure was logged at debug and was invisible.

The runtime gate is unchanged: a worker that declares `runtime_env` uploads only when that
variable is `cloud_run` (or `CLONWAY_OBS_FORCE_FLUSH=1`).

## Keeping tests off live storage

Add one line to the worker's `tests/conftest.py`:

```python
pytest_plugins = ["clonway_cockpit.testing.no_live_storage"]
```

For every test the plugin points `HOME` and the gcloud configuration at a temporary directory,
clears `GOOGLE_APPLICATION_CREDENTIALS` and `CLONWAY_FLEET_BUCKET`, and makes building a Google
Cloud Storage client fail the test with a message naming the test. Worker-specific bucket
variables are cleared too when listed in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
no_live_storage_env_vars = ["MYWORKER_FLEET_BUCKET"]
```

A test that is meant to reach real storage is marked `@pytest.mark.live_storage`; that lifts
the client block only, so such a test supplies its own credentials and bucket.
