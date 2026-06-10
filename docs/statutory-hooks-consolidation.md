# Statutory Hooks Checkout Consolidation

Generated: 2026-06-10

## Decision

`/Users/olliepage/Developer/clonway-cockpit` is the canonical local checkout for this repository.
Future statutory-hooks work should happen from that checkout, or from a worktree created from its
current `main`.

`/Users/olliepage/Developer/clonway-cockpit-statutory-hooks` should not be treated as a separate
project or source of truth. It points at the same GitHub repository and contains no local-only
statutory hook work to port. It can be retired or archived after the operator no longer needs the
old local directory.

## Verification

The statutory-hooks checkout was refreshed with:

```sh
git fetch --all --prune
```

It has the same remote as the canonical checkout:

```text
origin  https://github.com/hearth-care/clonway-cockpit.git
```

Its local `main` is behind current `origin/main` and has no commits ahead:

```text
HEAD:        558f6c55281af45771b74e292ffa101e61d15562
origin/main: 4d73c14d087b766c253db9d6812a9eb7f3f0c4c4
ahead/behind: 0 / 132
```

The old statutory hook branch work is already contained in current `origin/main`:

```text
21597f4 ancestor
13eb011 ancestor
e384849 ancestor
558f6c5 ancestor
```

The commits relevant to the statutory-hooks checkout history are:

```text
e384849 Merge pull request #15 from hearth-care/claude/statutory-hooks
558f6c5 Merge pull request #16 from hearth-care/claude/statutory-hooks-pass-screen
```

Both are ancestors of current `origin/main`.

After pruning, the old upstream statutory branches no longer exist as remote branches:

```text
- [deleted] -> origin/claude/statutory-hooks
- [deleted] -> origin/claude/statutory-hooks-pass-screen
```

The checkout has no tracked or untracked work. Only ignored local build/test artifacts remain:

```text
.mypy_cache/
.pytest_cache/
.ruff_cache/
.venv/
src/clonway_cockpit/__pycache__/
src/clonway_cockpit/signals/__pycache__/
tests/__pycache__/
```

## Useful Deltas

There are no useful local deltas to port. The apparent delta from
`/Users/olliepage/Developer/clonway-cockpit-statutory-hooks` to current `main` is just normal
repository history accumulated after that checkout stopped moving.

## Follow-Up

The follow-on worker-template statutory-hooks workstream can proceed from current `main` without
waiting for any code salvage from the old checkout. If it needs a branch, create a fresh worktree
from the canonical checkout rather than reusing `/Users/olliepage/Developer/clonway-cockpit-statutory-hooks`.
