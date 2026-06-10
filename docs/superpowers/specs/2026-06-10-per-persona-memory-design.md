# Private per-persona working memory — format + read/write (design)

**Status:** approved-to-build (owner picked PR #74 "per-persona multi-turn memory" to implement,
2026-06-10). Autonomous design grounded in the persona-platform vision and the two-tier-memory
architecture decision; the implementation PR is left **open for the owner's review** because the
private/shared separation is a boundary.
**Slice:** the **private** tier of two-tier memory — see
[`docs/persona-platform-architecture.md`](../../persona-platform-architecture.md), "Two-tier memory".
It realizes the "per-persona multi-turn memory" line in Delivery → *Still ahead*. The **shared**
tier's format + read + governed write are slices 4–6, merged (`shared_memory.py`).
**Goal:** give each persona an **isolated, private working memory** — its own notes ("the
bookkeeper's Xero notes, the marketer's campaign state"), optionally scoped per **thread/space** for
true multi-turn session memory. No other persona can read it; the owner-only shared-promotion
boundary (slice 6) is untouched.

## Why this slice

The architecture's two-tier memory has two halves. The **shared** tier (everyone reads; only the
owner writes) shipped in slices 4–6. The **private** tier is the other half: each persona owns
working memory nobody else reads — and, for true multi-turn over Chat, that memory is **scoped per
thread/space** so a conversation can accumulate context. Private writes are **not** a
shared-blast-radius concern (a persona's own notes reach only itself), so — unlike the shared tier —
private writes are **not owner-gated**. The load-bearing guarantee here is **isolation**, not
provenance: persona A can never read persona B's memory, and one thread's session memory does not
bleed into another.

## The two isolation dimensions

1. **Persona isolation (hard boundary — the whole point).** Each persona's store is a separate
   subtree keyed by its **handle** (already a strict slug, `[a-z0-9][a-z0-9_-]*`, so it is path-safe
   — re-validated at the boundary for defence in depth). The API only ever reads/writes within one
   handle's subtree, so cross-persona reads are **structurally impossible**, not merely policy.
2. **Thread/space scoping (multi-turn).** Within a persona, memory is partitioned into:
   - **working** — persona-global notes that persist across all of the persona's conversations (the
     Xero notes, the campaign state).
   - **thread(scope)** — per-thread/space session memory for true multi-turn, keyed by the Chat
     space/thread id (slug-validated).

   On disk: `<base>/<handle>/working/` and `<base>/<handle>/threads/<scope>/`. The `working/` vs
   `threads/` split means a thread literally named `working` can never collide with the
   persona-global store.

## Scope

**In:** `private_memory.py` — a `PersonaMemory(base, handle)` entry point exposing `.working` and
`.thread(scope)` `PrivateScope` views; each view supports read (`get` / `all` / `recall`) and write
(`remember` / `forget`). Reuses the slice-4 markdown + frontmatter `Fact` format (**defined once**).
Best-effort, never-crash reads. Self-verifiable tests + a usage doc.

**Out (later / not this slice):** promotion of a private note into shared memory (that is the
owner-gated path and already exists as `GovernedWriter` — this slice deliberately does **not** add a
second write path into shared truth); semantic/embedding recall (keyword recall is the walking
skeleton, as in slice 4); a memory reflector / summariser; the conversation-layer wiring that
constructs a persona's `thread(scope)` from a real Chat space id (that arrives with the transport
slice, PR #73); encryption-at-rest (the consumer's directory discipline, same as the shared
handbook).

## The format (reused, defined once)

A private note is the **same** `Fact` as a shared fact — markdown + flat frontmatter
(`name` / `kind` / `summary` / `source` / `as_of`), one note per file. `private_memory.py` imports
the format primitives from `shared_memory.py` (the read parses, the write renders — the format lives
in **one** module). The only differences are **where** notes live (a per-persona, per-scope
directory) and **who** may write (the persona itself, freely — no owner gate).

`source` on a private note records provenance for the persona's own benefit (e.g. "the resident's
daughter said…"), but it is **advisory only here** and carries no promotion power — a private note
never becomes shared truth without going back through `GovernedWriter(source=OWNER)`.

## The API (`clonway_cockpit/private_memory.py`)

```python
WORKING = "working"   # the reserved persona-global scope directory

class PersonaMemory:
    """One persona's private memory, isolated by handle. Inject the private-memory root."""
    def __init__(self, base: Path, handle: str) -> None: ...   # validates handle is a safe slug
    @property
    def working(self) -> PrivateScope: ...                      # <base>/<handle>/working
    def thread(self, scope: str) -> PrivateScope: ...           # <base>/<handle>/threads/<scope>

class PrivateScope:
    """Read + write over one (persona, scope) directory. Reads never raise; writes validate."""
    # read (best-effort, never-crash — same posture as SharedMemory)
    def get(self, name: str) -> Fact | None: ...
    def all(self, *, kind: str | None = None) -> list[Fact]: ...
    def recall(self, query: str, *, kind: str | None = None, limit: int | None = None) -> list[Fact]: ...
    # write (NOT owner-gated — private working memory is the persona's own; isolation is the guard)
    def remember(self, *, name: str, kind: str, summary: str, body: str = "",
                 as_of: str | None = None) -> Fact: ...
    def forget(self, name: str) -> bool: ...
```

- `remember` validates `name` is a safe slug (it becomes a filename — rejects traversal) and that
  `kind` / `summary` / `as_of` are single-line (no frontmatter injection), reusing the slice-4/6
  validators. Invalid input raises **`ValueError`** — a programming error in the persona's own code,
  **not** `WriteRefused`, which is reserved for the shared-tier trust boundary. Writing an existing
  `name` overwrites it (updating a note). `as_of` defaults to today (UTC).
- `forget(name)` deletes the note file, returning `True` if it existed, `False` otherwise. Never
  raises on a missing note or missing scope.
- `recall` is the **same** dependency-free keyword scorer as `SharedMemory` (+2 per token in
  `name`/`summary`, +1 in `kind`/`body`), reused — not reimplemented.
- A `PrivateScope` loads its directory lazily and caches; construct a new one (via a new
  `PersonaMemory` or another `.thread(...)` / `.working`) to pick up on-disk edits — same contract
  as `SharedMemory`.

## Isolation & safety (the tests that matter)

- **Cross-persona:** a note written under handle `bob` is invisible to `PersonaMemory(base, "alice")`
  via `get` / `all` / `recall`. Two personas sharing one `base` never see each other's notes.
- **Cross-thread:** a note in `thread("t1")` is not returned by `thread("t2")` or by `working`;
  `working` notes are not returned by any `thread(...)`.
- **Path traversal:** a `handle` or `scope` that isn't a safe slug (`..`, `a/b`, `/abs`, `has.dot`,
  empty) is refused at construction (`ValueError`) — the store can never escape the persona's
  subtree. A note `name` that isn't a safe slug is refused by `remember`.
- **The shared boundary holds:** a `PrivateScope.remember(...)` writes nothing into the shared
  handbook; a fact becomes shared truth **only** via `GovernedWriter(source=OWNER)`. (Regression
  test: a private write is not visible through `SharedMemory` pointed at the shared dir.)
- **Never-crash reads:** a missing base / handle / scope dir → empty results; a malformed note file
  alongside good ones is skipped, never raised — the same calm-and-robust posture as `SharedMemory`.

## Errors & robustness

There is no error path a *read* should raise on: missing dir → `[]` / `None`; `recall("")` → `[]`; a
malformed file is skipped. Writes raise `ValueError` only on programmer error (an unsafe `name`, a
multi-line `kind`/`summary`/`as_of`), and **fail-closed** — a refused write creates nothing. This
mirrors `shared_memory.py`'s never-crash reads and validate-before-disk writes.

## Dependency packaging

**Zero new runtime dependency** — stdlib only, reusing `shared_memory.py`'s format primitives. The
framework stays `rich`-only.

## Testing & acceptance

Fully self-verifiable (no external service) — so this slice goes all the way to a green, mergeable
PR; the owner reviews because the private/shared separation is a boundary. Maps to PR #74's
acceptance criteria:

- **"A persona can remember context within its own thread/space"** → `remember` then `recall` / `get`
  round-trips within `thread(scope)` and within `working`.
- **"Private memory does not leak across personas"** → the cross-persona + cross-thread +
  path-traversal isolation tests above.
- **"Shared memory writes require owner confirmation"** → the shared boundary holds: private writes
  never reach `SharedMemory`; promotion still requires `GovernedWriter(source=OWNER)` (a test asserts
  a private note is not visible in the shared dir, and that the only promotion path remains
  owner-gated).

**Docs in the PR:** this spec + `docs/private-memory.md` (format + API + isolation + the boundary),
and a Delivery-table row in `docs/persona-platform-architecture.md`.
