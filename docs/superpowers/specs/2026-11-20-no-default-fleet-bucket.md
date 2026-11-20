# No built-in fleet bucket

Date: 2026-11-20. Package: T1a.

## What happened

An ordinary test run of one worker, on a developer machine that had working cloud credentials,
wrote test reminders into the live shared fleet storage bucket and replaced a live file there
with an empty one. Three framework modules (the signal emitter and subscriber, run telemetry,
and the audit log) carried the live bucket's name as a built-in default. The machine's
credentials were valid, so the writes succeeded. Where a write did fail, the failure was caught
and logged at debug level or not at all, so nothing showed that a worker was publishing, or
failing to publish, to the wrong place. One worker has since protected its own suite; every
other worker built on this framework was equally exposed.

## Rule chosen

One rule, applied in every function, class and factory that used to default to the bucket
(`emit_signals`, `failure_to_signal`, `poll`, `GcsCursorStore`, `make_obs`, `flush_buffer`,
`make_audit_sink`). The bucket is, in order:

1. the explicit `bucket=` argument;
2. the `CLONWAY_FLEET_BUCKET` environment variable, read at call time;
3. none. The function does nothing, logs `no fleet bucket configured: reminders are not being
   published` once per process at info level, and returns a result the caller can inspect. It
   never raises and never falls back to a name.

Keyword names and positions are unchanged, so a worker that already passes `bucket=` needs no
change. The shared logic is in `src/clonway_cockpit/fleet_bucket.py`.

### Making failure visible without raising

Workers call these functions inside scheduled jobs, so none of them starts raising. Each reports
through its existing return:

| Function | Unconfigured | Upload or read failed |
|---|---|---|
| `emit_signals` | `EmitResult` (a tuple of the built signals) with `.outcome == "not_configured"` | same tuple with `.outcome == "failed"` |
| `failure_to_signal` callback | returns `None`; one info line | returns `None`; one warning |
| `poll` | `PollResult` (a list, empty) with `.outcome == "not_configured"` | `PollResult` with `.outcome == "failed"` |
| `GcsCursorStore.load` / `save` | `None` / no-op; `.last_outcome == "not_configured"` | `None` / unchanged raising rules; `.last_outcome == "failed"` |
| `flush_buffer` | `False` | `False` |
| `flush_buffer_outcome` (new) | `"not_configured"` | `"failed"` |
| `run_session` (via `last_flush_outcome(worker_id)`) | `"not_configured"` | `"failed"` |
| audit sink `.flush()` | `False`; `.last_outcome == "not_configured"` | `False`; `.last_outcome == "failed"` |

A failed upload or read logs one warning with the exception type and the object path, never the
contents. Credentials and permission errors, formerly debug-only, are warnings too.

## Test guard

`clonway_cockpit.testing.no_live_storage` is a pytest plugin (autouse fixture plus a
`live_storage` marker) that isolates `HOME` and the gcloud configuration, clears the bucket and
credential variables, and makes building a Google Cloud Storage client fail the test unless it is
marked `live_storage`. The failure is a pytest outcome, which is not an `Exception`, so a
best-effort writer's broad `except Exception` cannot hide it. This repository's own suite uses
the plugin, and `worker-template/` loads it.

`clonway_cockpit/testing.py` became the package `clonway_cockpit/testing/`; the existing
`clonway_cockpit.testing` import and `pytest_plugins = ["clonway_cockpit.testing"]` still work.

## What each worker does at its next pin bump

- [ ] Search the worker for `emit_signals(`, `FACTORY.emit(`, `failure_to_signal(`, `poll(`,
      `GcsCursorStore(`, `make_obs(`, `flush_buffer(` and `make_audit_sink(`. Any call that
      relied on the default bucket must pass `bucket=` or the worker's environment must set
      `CLONWAY_FLEET_BUCKET`.
- [ ] Cloud Run service or job: add `CLONWAY_FLEET_BUCKET` to its environment (or pass
      `bucket=` from the worker's config). Until then it publishes nothing.
- [ ] Look for the info line `no fleet bucket configured` in the logs after the first run; its
      absence plus a returned outcome of `"ok"` confirms publishing.
- [ ] Tests that assert an upload must now configure a bucket (`monkeypatch.setenv`).
- [ ] Add `pytest_plugins = ["clonway_cockpit.testing.no_live_storage"]` to `tests/conftest.py`,
      list any worker-specific bucket variables in `no_live_storage_env_vars`, and mark the rare
      test that must reach real storage with `@pytest.mark.live_storage`.
- [ ] Anything that checks `flush_buffer(...)` for truthiness keeps working; use
      `flush_buffer_outcome` to distinguish "no bucket" from "failed".
