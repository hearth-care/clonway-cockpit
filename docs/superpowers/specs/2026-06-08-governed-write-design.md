# Shared company memory — slice 6, governed write (design)

**Status:** approved-to-build (owner: "build slice 6 (governed write)", 2026-06-08). Autonomous
design grounded in the vision memory; the PR is left **open for the owner's review** because this is
the security boundary.
**Slice:** #6 of the persona platform — see [`docs/persona-platform-architecture.md`](../../persona-platform-architecture.md),
"Two-tier memory → the write trust-boundary". Builds on slice 4 (the read side,
`shared_memory.py`, merged).
**Goal:** a **governed write** path into the shared handbook that enforces the trust boundary — only
the **owner's** word becomes shared truth; anything quoted/forwarded from an outsider is **refused**,
never auto-promoted. "One poisoned fact ('the home's bank details changed') must not infect five
agents."

## Why this is its own slice, and why it's the dangerous half

Reads are harmless; **writes are shared blast radius** — a single bad shared fact reaches every
persona. So the write path is gated where the read path is open. The gate is deliberately simple and
fail-closed: a fact is promoted **only** when its provenance is the owner. This mirrors the WS-D
message trust boundary (`OPERATOR` commands vs `QUOTED` data) lifted to the memory-write edge.

## The trust model (the whole point)

Every write carries a **`source`** (provenance). `GovernedWriter` promotes a fact **only if
`source == OWNER`** (`"owner"`); any other source (`"quoted"`, an outsider, anything) is **refused
with `WriteRefused`** and **nothing is written**. The writer trusts the `source` value it is given;
**the caller is responsible for setting it honestly** — i.e. the conversation layer passes
`source=OWNER` only for a message from the verified operator, never for quoted/forwarded content.
The writer's gate is the necessary backstop; the caller's honesty about provenance is the other half
(documented, enforced where the two meet in a later wiring slice).

## Scope

**In:** a `GovernedWriter` that validates + writes one fact file (owner-gated), and a `WriteRefused`
error. It renders exactly the frontmatter the slice-4 reader parses, so a written fact **round-trips**
through `SharedMemory`. Lives in `shared_memory.py` (the format is defined once: read parses, write
renders).

**Out (later):** quarantine *storage* (where refused/quoted content goes — a per-conversation scratch
is a different concern; this slice only refuses promotion), per-persona private memory, edit-history /
audit log of writes, and the conversation-layer wiring that decides `source` from the message
boundary.

## API (`clonway_cockpit/shared_memory.py`)

```python
OWNER = "owner"   # the only provenance that becomes shared truth

class WriteRefused(RuntimeError):
    """A write was refused — non-owner provenance, or an invalid field. Nothing was written."""

class GovernedWriter:
    def __init__(self, base: Path) -> None: ...
    def write(self, *, name: str, kind: str, summary: str, source: str,
              body: str = "", as_of: str | None = None) -> Fact: ...
```

`write`:
1. **Trust gate (first):** `source != OWNER` → `WriteRefused`, nothing written.
2. **Validation (also a security boundary — `name` becomes a filename):**
   - `name` must **`fullmatch`** `^[a-z0-9][a-z0-9_-]*$` (a lower-case slug) — this rejects path
     traversal (`../`, `/`, `..`) and odd filenames outright, so a write can never escape `base`.
     (`fullmatch`, not `match` + `$`, because `$` alone would accept a trailing newline.)
   - **Every value rendered into the frontmatter** — `kind`, `summary`, *and* `as_of` — must be
     non-empty and **single-line**, else `WriteRefused`. A newline in any of them would inject extra
     `key: value` lines that the reader's last-wins parse would honour (`source` is pinned to `owner`,
     and `body` sits after the fence, so those two can't inject).
3. **Write:** render `---`-fenced frontmatter (`name`/`kind`/`summary`/`source`/`as_of`) + body to
   `base/<name>.md` (creating `base`); `as_of` defaults to today (UTC date). Writing an existing name
   **overwrites** (the owner updating shared truth — "actually, call me Y").
4. **Return** the written `Fact` (equal, field-for-field, to what `SharedMemory.get(name)` reads back).

## Errors & security

- Fail-closed: any refusal writes **nothing** (the trust gate and validation both run before any file
  I/O). The path-traversal guard is a **slug allowlist**, not a denylist.
- One error type (`WriteRefused`) for "the write did not happen", with a message that distinguishes
  trust refusal from invalid input.
- No new runtime dependency (stdlib `re`, `datetime`, `pathlib`). Framework stays `rich`-only.

## Testing & acceptance

Fully self-verifiable.

- **Trust gate:** `source="quoted"` / `source="someone-else"` → `WriteRefused`, **no file created**.
- **Path traversal:** `name="../../etc/passwd"`, `name="a/b"`, `name=".."`, `name="Up Per"` → all
  `WriteRefused`, and **nothing is written anywhere** (assert the base dir is empty / target absent).
- **Validation:** empty/whitespace or multi-line `kind`/`summary` → `WriteRefused`.
- **Happy path + round-trip:** an owner write creates `base/<name>.md`; `SharedMemory(base).get(name)`
  returns a `Fact` equal to the returned one (name/kind/summary/source/body/as_of).
- **Overwrite:** a second owner write to the same name updates it (one fact, new summary).
- **Default `as_of`:** omitting `as_of` stamps today's UTC date.
- **Docs in the PR:** this spec + a "Writing (governed)" section in `docs/shared-memory.md`.
