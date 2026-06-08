# Shared company memory — slice 4, format + read (design)

**Status:** approved-to-build (owner: "do next slice without waiting on me", 2026-06-08). The design
decisions below were made autonomously, grounded in the persona-platform vision memory; flagged here
for the owner's later review.
**Slice:** #4 of the persona platform — see [`docs/persona-platform-architecture.md`](../../persona-platform-architecture.md),
"Two-tier memory". This is the **shared** tier's format + a **read** API only.
**Goal:** define the shared company-memory format (a CRM / staff handbook of *facts about the shared
world* — the people, the calendar, the owner's preferences) and a dependency-free read/recall API in
`clonway-cockpit` that any persona can use to look facts up. No writes, no per-persona memory.

## Why this slice, and why read-only

The "tell once, all learn" value needs two halves: every persona can **read** shared facts, and only
the owner can **write** them (the trust boundary). They have very different blast radius — a bad read
is harmless, a bad write poisons every agent — so they are separate slices. This slice ships the
format + the read half (safe, immediately useful: slice 5 is "Milo reads shared memory"). The
**governed write** (owner-only promotion, quarantine of quoted/outsider content) is **slice 6** and is
deliberately out of scope here.

## Scope

**In:** the on-disk format (markdown + simple frontmatter), a `Fact` type, and a `SharedMemory` reader
with `get` / `all` / `recall` (zero-dependency keyword recall). Best-effort, robust loading. A small
illustrative example handbook + a usage doc.

**Out (each a later slice):** any write/edit API and the owner-only trust boundary (slice 6);
per-persona *private* memory (later); semantic/embedding recall (a later enhancement — keyword recall
is the walking-skeleton version); Milo/any persona actually wired to read it (slice 5).

## The format

A shared handbook is a **directory of markdown files**, one fact/entity per file — the same
markdown-memory pattern the framework/CLAUDE memory already uses (and the munder-difflin reference
calls markdown-first long-term memory). Each file:

```markdown
---
name: barton-house-supplier-acme
kind: supplier
summary: ACME Care Supplies — PPE + incontinence; account 4417; pays on 30-day terms.
source: owner
as_of: 2026-06-08
---
ACME is the primary PPE supplier. Rep is Dana (dana@acme.example). Switched from
the old supplier in March after two late deliveries.
```

Frontmatter fields:
- **`name`** (optional) — stable slug; **defaults to the file stem** if omitted.
- **`kind`** (required) — the fact category. Expected vocabulary: **`person`**, **`calendar`**,
  **`preference`** (the vision's "people, the calendar, the owner's preferences"), plus practical
  extensions like `supplier` / `staff`. Free-form string so the set can grow; `recall`/`all` filter on it.
- **`summary`** (required) — one line; the high-signal text for the index and for recall ranking.
- **`source`** (optional) — who asserted the fact. Forward-compatible with slice 6's trust boundary
  (`owner` = shared truth; anything else stays advisory). The reader surfaces it; it is **not**
  enforced this slice.
- **`as_of`** (optional) — freshness date, so a persona can cite "as of …" per the shared constitution.

A file missing `kind` *or* `summary` is **skipped** (treated as not-a-fact), never fatal. The format
is forgiving by design: secrets/PII discipline is the consumer's (a real care-home handbook is
sensitive — it lives in a configured/gitignored directory, never in the framework repo).

## The read API (`clonway_cockpit/shared_memory.py`)

The framework ships the **reader + format**, never the data. A consumer injects the handbook
directory (like every other framework seam).

```python
@dataclass(frozen=True)
class Fact:
    name: str
    kind: str
    summary: str
    body: str
    source: str | None
    as_of: str | None
    path: Path

class SharedMemory:
    def __init__(self, base: Path) -> None: ...
    def all(self, *, kind: str | None = None) -> list[Fact]: ...          # sorted by name
    def get(self, name: str) -> Fact | None: ...                          # exact name
    def recall(self, query: str, *, kind: str | None = None, limit: int | None = None) -> list[Fact]: ...
```

- **`recall`** is dependency-free keyword scoring: the query is lower-cased and split into tokens; each
  fact scores **+2** per token found in its `name`/`summary` (high signal) and **+1** per token found
  in its `kind`/`body`; facts scoring 0 are excluded; results sort by score desc, then `name`. Optional
  `kind` filter and `limit`. An empty query returns `[]`. (Semantic recall is a later enhancement;
  keyword recall is honest and zero-dep for the skeleton.)
- **Loading** is **best-effort and robust** (the framework's calm-and-robust contract): a missing
  `base` dir → no facts; a malformed/partial file is skipped, never raised; frontmatter is parsed by a
  tiny hand-rolled scanner (flat `key: value` lines) so the framework adds **no YAML dependency** and
  stays `rich`-only. Facts are loaded once and cached on first access (construct a new `SharedMemory`
  to pick up edits) — documented.

## Errors & robustness

There is no error path that a *read* should raise on: bad input → empty results. `recall("")` → `[]`;
unknown `name` → `None`; missing dir → `[]`. This mirrors `usage.py`'s never-crash posture, because a
persona looking something up must degrade quietly, not fall over.

## Dependency packaging

**Zero new runtime dependency** — stdlib only (`pathlib`, `dataclasses`, hand-rolled frontmatter
parse). The framework stays `rich`-only.

## Testing & acceptance

Fully self-verifiable (no external service) — so this slice can go all the way to merged.

- **Unit (CI):** frontmatter parse (with/without frontmatter, partial, extra fields); `name` defaults
  to file stem; a file missing `kind`/`summary` is skipped; `get` hit/miss; `all` + `kind` filter +
  sort; `recall` ranking (summary hit outranks body hit), `kind` filter, `limit`, empty query → `[]`;
  missing base dir → `[]`; a malformed file alongside good ones doesn't break the load.
- **Acceptance:** point `SharedMemory` at the shipped `examples/handbook/` and `recall("ppe supplier")`
  returns the ACME fact ahead of unrelated ones; `all(kind="preference")` returns only preferences.
- **Docs in the PR:** this spec + `docs/shared-memory.md` (the format + the read API + the example).
