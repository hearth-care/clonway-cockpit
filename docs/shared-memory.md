# Shared company memory (read)

`clonway_cockpit.shared_memory` is the **read** side of the persona platform's shared
company memory — a CRM / staff handbook of *facts about the shared world* (the people,
the calendar, the owner's preferences, suppliers) that every persona can look up. The
framework ships the **reader + format**, never the data; a consumer injects a handbook
directory. Read-only: the owner-only governed **write** is a separate slice. See the
design spec at
[`superpowers/specs/2026-06-08-shared-memory-design.md`](superpowers/specs/2026-06-08-shared-memory-design.md)
and the platform context in [`persona-platform-architecture.md`](persona-platform-architecture.md).

## The format

A handbook is a directory of markdown files, **one fact per file**:

```markdown
---
name: acme-supplier          # optional — defaults to the file stem
kind: supplier               # required — person | calendar | preference | supplier | staff | …
summary: ACME Care Supplies — PPE; 30-day terms.   # required — high-signal one-liner
source: owner                # optional — `owner` = shared truth (enforced by the write slice)
as_of: 2026-06-08            # optional — freshness, so a persona can cite "as of …"
---
The body: anything else worth knowing about the fact.
```

A file missing `kind` or `summary` is **skipped** (it isn't a fact) — so a `README.md`
or notes file in the directory is ignored. Secrets / PII discipline is the consumer's:
a real handbook lives in a configured, gitignored directory, never in a repo. See the
illustrative `examples/handbook/`.

## Reading

```python
from pathlib import Path
from clonway_cockpit.shared_memory import SharedMemory

mem = SharedMemory(Path("/path/to/handbook"))

mem.all()                          # every fact, sorted by name
mem.all(kind="preference")         # just the preferences
mem.get("acme-supplier")           # one fact by name, or None
mem.recall("ppe supplier")         # keyword recall, best matches first
mem.recall("ppe", kind="supplier", limit=3)
```

`recall` is dependency-free keyword scoring: +2 per query word found in a fact's
`name`/`summary` (high signal), +1 in its `kind`/`body`; non-matches are excluded;
results sort by score, then by `name` for ties. An empty query returns `[]`.

Matching is **substring and case-insensitive**, not word-boundary or semantic: a query
word matches anywhere (so `art` would also match "started"), a repeated query word
counts repeatedly, and leading/trailing punctuation on query words is stripped (so
`"PPE supplier?"` and `"ppe,"` still match). `kind` filtering is case-insensitive;
`get(name)` is an exact slug match. For precise or meaning-based lookup, semantic recall
is a later enhancement.

## Robustness

Every read degrades quietly — a missing directory or a malformed file yields fewer
facts, never an exception (a persona must not fall over looking something up). Facts
are loaded once and cached; construct a new `SharedMemory` to pick up on-disk edits.

## Writing (governed)

Writes go through `GovernedWriter`, which enforces the **trust boundary**: a fact is
promoted to shared memory **only when its `source` is the owner**. Quoted / outsider
content is refused, never auto-promoted — one poisoned fact must not infect every
persona.

```python
from clonway_cockpit.shared_memory import GovernedWriter, OWNER, WriteRefused

writer = GovernedWriter(Path("/path/to/handbook"))
writer.write(name="acme-supplier", kind="supplier",
             summary="ACME — PPE; 30-day terms.", source=OWNER,
             body="Primary PPE supplier.")          # → writes acme-supplier.md, returns the Fact

writer.write(name="bank", kind="preference", summary="...", source="quoted")  # raises WriteRefused
```

The writer **trusts the `source` it is given** — the caller must set it honestly from
the message trust boundary (`operator` vs `quoted`); the gate is the backstop. It is
**fail-closed**: a refused write (non-owner source, a `name` that isn't a safe
`[a-z0-9][a-z0-9_-]*` slug, or an empty/multi-line `kind`/`summary`/`as_of`) writes
nothing. Every value rendered into the frontmatter is single-line-validated, so none can
inject extra keys.
A written fact round-trips through `SharedMemory`; writing an existing `name` overwrites
it (the owner updating shared truth). `as_of` defaults to today (UTC).

## Scope

The governed write above is the owner-only promotion gate. Still later: quarantine
*storage* for refused content, per-persona private memory, an edit/audit history, and
semantic recall.
