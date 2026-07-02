# Private per-persona memory

`clonway_cockpit.private_memory` is the **private** tier of the persona platform's two-tier
memory — the counterpart to the shared
[`shared_memory`](shared-memory.md) handbook. Where shared memory is *facts about the shared world*
that **every** persona reads and only the **owner** writes, private memory is each persona's own
working notes — "the bookkeeper's Xero notes, the marketer's campaign state" — that **nobody else
reads**. It can also be **scoped per thread/space** so a single conversation accumulates context for
true multi-turn. Platform context: [`persona-platform-architecture.md`](persona-platform-architecture.md),
"Two-tier memory"; design spec:
[`superpowers/specs/2026-06-10-per-persona-memory-design.md`](superpowers/specs/2026-06-10-per-persona-memory-design.md).

The framework ships the **reader/writer + format**, never the data: a consumer injects a
private-memory root directory (like every other framework seam).

## The two isolation dimensions

1. **Persona isolation — the whole point.** Each persona's store is a separate subtree keyed by its
   `handle`. Because the API only ever reads and writes within one handle's subtree, persona A
   **cannot** read persona B's memory — that is *structural*, not a policy you have to remember.
2. **Thread/space scoping.** Within a persona, `working` is persona-global (notes that persist
   across all of its conversations); `thread(scope)` is per-thread/space session memory. On disk:

   ```
   <root>/<handle>/working/<name>.md          # persona-global working memory
   <root>/<handle>/threads/<scope>/<name>.md  # per-thread/space session memory
   ```

   The `working/` vs `threads/` split means a thread literally named `working` can never collide
   with the persona-global store.

## The format

A private note is the **same** `Fact` as a shared fact — markdown + flat frontmatter, one note per
file — reused from `shared_memory` (the format is defined once: the read parses, the write renders).
`kind`/`summary` are the only required fields; `name` defaults to the file stem.

```markdown
---
name: xero-mfa
kind: note
summary: Xero login uses MFA via the authenticator app on the office phone.
as_of: 2026-06-10
---
Recovery codes are in the safe. Dana set this up in March.
```

`source` on a private note is an **optional, advisory** field — it records provenance for the
persona's own benefit ("the resident's daughter said…") but carries no promotion power. A private
note never becomes shared truth without going back through the owner-gated `GovernedWriter` (see
below).

## Using it

```python
from pathlib import Path
from clonway_cockpit.private_memory import PersonaMemory

mem = PersonaMemory(Path("/configured/private-root"), "milo")   # handle is slug-validated

# persona-global working memory
mem.working.remember(name="xero-mfa", kind="note",
                     summary="Xero login uses MFA on the office phone.",
                     source="the daughter")    # source is optional, advisory provenance
mem.working.recall("xero login")        # keyword recall, best matches first
mem.working.get("xero-mfa")             # one note by name, or None
mem.working.all(kind="note")            # every note of a kind, sorted by name
mem.working.forget("xero-mfa")          # delete; True if it existed

# per-thread/space session memory (multi-turn). `scope` must be a SLUG, so a raw Chat space
# id is normalised first — the transport slice (#73) owns that step:
scope = "spaces/AAAAbCdEf".lower().replace("/", "-")   # -> "spaces-aaaabcdef"
mem.thread(scope).remember(name="ask", kind="note",
                           summary="owner asked for the Q2 figures")
mem.thread(scope).recall("Q2 figures")
mem.forget_thread(scope)               # deletes the whole per-thread scope; True iff it existed
```

`thread(scope)` validates `scope` as a slug, so a raw Google Chat space id (`spaces/AAAA…`, which
has `/` and mixed case) is **not** accepted as-is — the caller normalises it to a slug first (lower
+ replace `/`, or hash). That normalisation contract belongs to the Chat transport slice.

`recall` is the **same** dependency-free keyword scorer as `SharedMemory` (+2 per query word in a
note's `name`/`summary`, +1 in its `kind`/`body`; non-matches excluded; sorted by score then name;
empty query → `[]`). `all`, `get`, and `recall` accept an optional `kind` filter.

## Reads never crash; writes validate

Every **read** degrades quietly — a missing root / handle / scope directory yields no notes, and a
malformed file is skipped, never raised (a persona must not fall over looking something up). That
skip is **silent**: an empty result from `all()`/`recall()` can mean a missing directory, an empty
one, *or* every file malformed — they are indistinguishable by design (the calm-and-robust contract).
Notes load once per scope and are cached; open a fresh scope (`mem.working` / `mem.thread(...)`) to
pick up on-disk edits — the same contract as `SharedMemory`. For a sequence of reads, hold one scope
in a local rather than re-accessing `mem.working` each time (each access reloads the directory).

`remember` **validates before touching disk** and is fail-closed: `name` must be a safe slug —
lower-case, bounded length, so it both rejects path traversal and can't overflow a filename — and
`kind`/`summary`/`source`/`as_of` must be single-line (else a newline would inject extra frontmatter
keys). A CRLF `body` is normalised to `\n` so it round-trips exactly. Invalid input raises
**`ValueError`** and writes nothing. Writing an existing `name` overwrites it (updating a note);
`as_of` defaults to today (UTC). Writes use the framework atomic-write primitive: render the whole
Fact to a temp sibling and `os.replace` it, so a failed replace leaves the prior file intact and no
`.tmp` litter.

`forget(name)` returns `True` if the note existed, `False` if it did not — a genuine filesystem
error (e.g. a permission denial) **propagates** rather than being mistaken for "wasn't there".
`PersonaMemory.forget_thread(scope)` validates the scope and removes
`<root>/<handle>/threads/<scope>/` recursively; it is the library engine behind the thread-memory
operator deletion command.

Why `ValueError` and not `WriteRefused`? Because private writes are **not a trust boundary** — a bad
private write is a programming error in the persona's own code, not an attempt to poison shared
truth. `WriteRefused` is reserved for the shared tier's owner-gate.

## The boundary with shared memory

Private writes are **not owner-gated** — a persona freely writes its own notes, because they reach
only that persona (no shared blast radius). The isolation *is* the guard. What this tier deliberately
does **not** do is provide a second path into **shared** truth: a `PrivateScope.remember(...)` writes
nothing into the shared handbook, and the only way a fact becomes shared truth remains
`GovernedWriter(source=OWNER)`. So "tell once, all learn" stays owner-governed, while each persona
still keeps its own private working memory. Secrets/PII discipline is the consumer's: a real private
root lives in a configured, gitignored directory, never in a repo.

Persona isolation is enforced at the API: `handle`, `scope`, and note `name` are all slug-validated,
so no value supplied through the interface can traverse out of a persona's subtree, and the API only
ever creates files (it never follows or creates symlinks across personas). The one assumption it
*does* make is that the injected root is trusted — if a process can pre-plant a symlink inside the
root, that is filesystem access outside this module's threat model (the same caveat applies to the
shared handbook). Keep the root owned and writable only by the cockpit.

## Scope

Still later: promoting a confirmed private note into shared memory through the owner gate, semantic
recall, model-quality summarisation, and age-based retention policy.
