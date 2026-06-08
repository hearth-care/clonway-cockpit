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
results sort by score. An empty query returns `[]`. (Semantic recall is a later
enhancement.)

## Robustness

Every read degrades quietly — a missing directory or a malformed file yields fewer
facts, never an exception (a persona must not fall over looking something up). Facts
are loaded once and cached; construct a new `SharedMemory` to pick up on-disk edits.

## Scope

Read + format only. The governed write (owner-only promotion, quarantine of
quoted/outsider content), per-persona private memory, and semantic recall are later
slices.
