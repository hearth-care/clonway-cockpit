# [Plan] Shared google_auth module

**Status:** draft plan — not implemented
**Source:** fleet audit 2026-06-11, item C8
**Wave:** 1

## Why

Five workers reimplement the same Google credential lifecycle — OAuth2 installed-app flow, token persistence, refresh, service-account and domain-wide-delegation client construction — with no shared code and known per-copy defects. Verified at 2026-06-11 worker `origin/main`s:

- **Token stores ×3, near-identical:** `xbook/token_store.py` (187 lines), `xhr/token_store.py` (128), `xletter/token_store.py` (127). Same documented seam in all three: "Locally that place is the OS keyring; under Cloud Run (no keyring) it's a JSON file inside the mounted GCS bucket. Both backends live behind the same three-method interface." The diffs are worker names plus which providers each store serves.
- **Interactive OAuth flow:** `xquill/oauth.py` (183 lines, `InstalledAppFlow` + keyring + refresh). The audit flagged its refresh path as having **no lock** (audit item Q2: two concurrent processes can race the refresh, invalidating each other's token — becomes a hard blocker when that worker moves to Cloud Run).
- **Service-account / DWD construction:** `xletter/workspace/gmail.py` builds `service_account.Credentials.from_service_account_info(...)` with subject delegation inline; equivalents exist in the HR worker's transport/integration modules and the bookkeeper's `workspace/` package (`gmail_oauth.py`, `drive.py`, `sheets.py` each carry their own credential bootstrap).
- **The orchestrator runs three separate token-refresh paths** (audit §6, xops assessment), one of which is refreshed manually — fragmentation at its worst.

Counting just the three token stores plus the interactive-flow module: 625 lines; with the per-worker workspace credential bootstraps the audit's "250+ fragmented lines" is comfortably exceeded. Every new worker (the admissions and procurement workers are both pre-live and about to wire credentials) will copy one of these again unless the framework provides the seam.

The framework already has the pattern for "shared module, no new hard dependency": `signals/emit.py` and `obs.py` import `google.cloud.storage` lazily and accept injected fakes, keeping `clonway-cockpit` itself dependency-light (`rich` only, per `pyproject.toml`). This plan follows that pattern with an optional extra.

## Scope

**In:**
- `clonway_cockpit.google_auth` package: token storage backends, credential resolution, refresh locking, scope declaration/validation, SA + DWD construction.
- An optional dependency extra `clonway-cockpit[google]` (google-auth, google-auth-oauthlib; workers already depend on these).
- Worker migration recipe (per-worker PRs, after a release tag).

**Out:**
- Secret Manager hydration (`secrets.py` ×4 across workers, 86–338 lines each — related but a different lifecycle: env hydration at process start vs credential objects at call time; extract separately if wanted; noted as a candidate follow-up).
- Non-Google OAuth (bank/accounting providers in the bookkeeper) — same *storage* seam may be reused, but their flows stay put.
- Any change to which identities/scopes workers actually use; no identifier values appear in this repo (public).

## Spec

### 1. Package layout

```
src/clonway_cockpit/google_auth/
  __init__.py      # public API re-exports
  store.py         # TokenStore protocol + backends
  resolve.py       # credential resolution order
  flow.py          # interactive installed-app flow (local only)
  refresh.py       # locked refresh
  service.py       # SA / DWD construction helpers
```

All `google.*` imports are lazy (inside functions / behind factories), mirroring `signals/emit.py`; module import succeeds with no google packages installed, and tests inject fakes.

### 2. `TokenStore` protocol + backends (`store.py`)

The three workers' existing three-method seam, formalised:

```python
class TokenStore(Protocol):
    def load(self, key: str) -> dict | None: ...
    def save(self, key: str, token: dict) -> None: ...
    def delete(self, key: str) -> None: ...

class KeyringTokenStore:      # service name = f"clonway-{worker_id}"
class FileTokenStore:         # JSON file per key under a base dir (the mounted-
                              # bucket case on Cloud Run); atomic write (tmp+rename),
                              # 0600 perms
class MemoryTokenStore:       # tests
def default_store(worker_id: str, *, base_dir_env: str) -> TokenStore
    # keyring importable and usable → KeyringTokenStore, else FileTokenStore
    # rooted at $<base_dir_env> — encodes the verified local-vs-Cloud-Run split
```

Token dicts are stored verbatim (whatever `google.oauth2.credentials.Credentials.to_json()` round-trips); the store never interprets contents beyond JSON.

### 3. Credential resolution order (`resolve.py`)

One documented order, applied by `resolve_credentials(spec) -> Credentials`:

1. **Injected** credentials object (tests, embedders) — wins outright.
2. **Service-account info from env**: env var *named by* the spec (`sa_info_env`) containing JSON → SA credentials; with `subject=` → DWD (delegated) credentials. Env var *names* are config; values never appear in code or docs.
3. **Stored user token**: `store.load(key)` → user `Credentials`; refreshed if expired (via §5 locking).
4. **Interactive flow** (`flow.py`) — only when `allow_interactive=True` (CLI context); never in servers/jobs: raises `CredentialsUnavailable` instead, with a remedy string suitable for a Doctor screen.

```python
@dataclass(frozen=True)
class CredentialSpec:
    worker_id: str
    key: str                      # store key, e.g. "gmail"
    scopes: tuple[str, ...]
    sa_info_env: str | None = None
    subject: str | None = None    # DWD delegation subject (operator-supplied)
    client_config_env: str | None = None  # installed-app client config JSON env
```

### 4. Scope declaration & validation

`resolve_credentials` validates that a loaded/stored token's granted scopes ⊇ `spec.scopes`; a narrower token is treated as absent (forces re-auth rather than mid-run 403s). Rationale: the fleet's safety posture leans on minimal, *declared* scopes (e.g. compose-only Gmail); making the declaration the gate catches both scope creep and silent under-grants. A `scopes_subset_ok=True` escape hatch is deliberately not provided.

### 5. Refresh locking (`refresh.py`) — fixes the xquill race (Q2)

```python
def refresh_if_needed(creds, *, store, key, lock_dir: Path | None = None) -> Credentials
```

- Advisory **file lock** per store key (`lock_dir / f"{key}.lock"`, `fcntl.flock`, blocking with timeout ~30s) around the check-expiry → refresh → save critical section. File locks work for the real deployment shapes (multi-process on one machine for launchd workers; single-container Cloud Run instances with a mounted volume).
- After acquiring the lock, **re-load from the store** before refreshing — the other process may have refreshed already (double-checked locking); saves once, returns the fresh credentials.
- Refresh failure (`RefreshError`): delete is NOT automatic; raise `CredentialsUnavailable` with the remedy string. Deleting a refresh token is an operator decision.

### 6. SA / DWD helpers (`service.py`)

```python
def sa_credentials(info: dict, scopes, *, subject: str | None = None)
def build_service(api: str, version: str, creds, **kwargs)  # thin discovery wrapper,
                                                            # cache_discovery=False
```

Nothing here encodes a real subject, project, or account — all operator-supplied at runtime (workers read them from their own config/secret layer; the fleet-level config file `~/.config/clonway/fleet.json` may name per-worker values under its `workers.<name>` keys, operator-side).

### 7. Errors & observability

One exception family: `GoogleAuthError` → `CredentialsUnavailable` (with `.remedy: str`), `ScopeMismatch`, `RefreshLockTimeout`. No credential material in any message or log line (assert in tests: exception text for a fake token never contains the token). Hook: optional `on_event: Callable[[str, dict], None]` (e.g. `token.refreshed`, `flow.completed`) so workers can route to `obs` without this package importing it.

## Implementation plan

### Phase 1 — store + spec + errors
- [ ] `store.py`, `resolve.py` types (`CredentialSpec`, errors); `MemoryTokenStore`, `FileTokenStore` (atomic write + perms test), `KeyringTokenStore` behind a lazy `keyring` import with injected fake in tests.
- [ ] Tests: round-trip per backend; `default_store` fallback when keyring import fails; file perms 0600; atomicity (no partial file on simulated crash between tmp-write and rename).

### Phase 2 — resolution + scope validation
- [ ] `resolve_credentials` with fakes for google classes (factory injection, as `signals/emit.py` does); resolution-order table tested case by case (injected > SA env > stored > interactive-or-raise).
- [ ] Scope-superset gate tests incl. the "narrower token treated as absent" path.

### Phase 3 — refresh locking
- [ ] `refresh.py` with `fcntl` lock; tests: two threads/processes racing a fake refresh perform exactly one refresh (count on the fake), lock timeout raises `RefreshLockTimeout`, double-checked reload path covered.

### Phase 4 — SA/DWD + extra + docs
- [ ] `service.py`; add `[project.optional-dependencies] google = ["google-auth>=…", "google-auth-oauthlib>=…"]` to `pyproject.toml` (versions per the workers' current pins — survey at build time); prod-import CI job must still pass **without** the extra (lazy imports proved).
- [ ] Changelog entry; usage section in `docs/onboarding-a-worker.md`; migration recipe table (worker · files deleted · spec values' env names — names only).

### Phase 5 — worker template
- [ ] Template's generated worker gains a commented `CredentialSpec` example instead of a copied token store; `make template-smoke` green.

## Acceptance criteria

- `import clonway_cockpit.google_auth` succeeds in the `uv sync --no-dev` (no-google) environment; every google-touching call path raises a clear error there instead of ImportError at import time.
- Resolution order is tested case-by-case and documented in the module docstring as a numbered list identical to Spec §3.
- The refresh race test demonstrates exactly-one-refresh under concurrency; removing the lock makes the test fail (verified once locally).
- A migrating worker can express each of its current credential bootstraps as one `CredentialSpec` + one `resolve_credentials` call — proved in the plan-review by mapping the three token stores' existing call sites (table in the migration recipe).
- No secret values, account identifiers, subjects, or project names anywhere in code, tests, fixtures, or docs (public repo); fixture tokens are obviously fake (`"token": "fake-..."`).
- `make check` green; changelog updated.

## Risks & dependencies

- **Behavioural parity with three slightly-different stores:** before coding, re-read all three `token_store.py` files at current `origin/main` and table their differences (key naming, what triggers delete, GCS-mounted path resolution). Any worker-specific behaviour that can't be expressed via `CredentialSpec`/`default_store` stays in that worker's shim — do not force it into the framework.
- **fcntl on the deployment shapes:** file locks are advisory and filesystem-dependent; verify the Cloud-Run-mounted-volume case supports `flock` (GCS FUSE caveat — if it does not, fall back to `O_CREAT|O_EXCL` lockfile with stale-lock TTL; decide at build time, test both paths).
- **Keyring in headless contexts** raises at *use* not import on some platforms — `default_store` must probe with a real set/get/delete cycle, not just import success.
- Cross-repo: migrations touch five+ workers and must each re-verify their never-send/scope invariants after the swap (those invariants are structurally tested in several workers — their suites are the gate). Out of scope here.
- Depends on release-engineering (tag to pin) for migrations; framework-side work is unblocked.

## Next-agent pickup

- Branch: `claude/shared-google-auth` off `origin/main` of `hearth-care/clonway-cockpit`, fresh worktree.
- Start with the Phase 1 store tests (TDD); the lazy-import discipline is the part most likely to regress — keep the prod-import CI job as your canary from the first commit.
- Before Phase 2, do the three-store diff survey and paste the difference table into the PR description.
- Do NOT: add google packages to the core dependencies (optional extra only); implement Secret Manager hydration (explicitly out of scope); put any real account/subject/project value in any file (public repo — use `example.invalid`-style placeholders); start worker migration PRs from this branch.
- Done = acceptance criteria verified, `make check` + prod-import green, changelog entry present.
