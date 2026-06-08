"""Shared company memory — the read side (slice 4 of the persona platform).

A *handbook* is a directory of markdown files, one fact per file, with simple
frontmatter (``name``/``kind``/``summary``/``source``/``as_of``). This module is the
dependency-free READER + format: a consumer injects the handbook directory; the
framework ships no data. It is **read-only** — the owner-only governed WRITE (the
trust boundary) is a separate slice. Loading is **best-effort and never-crash**: a
missing directory or a malformed file yields fewer facts, never an exception, because
a persona looking a fact up must degrade quietly, not fall over.

See ``docs/shared-memory.md`` and the design spec
``docs/superpowers/specs/2026-06-08-shared-memory-design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# A file is only a fact if its frontmatter carries at least these. ``name`` falls
# back to the file stem, so it is not required.
_REQUIRED = ("kind", "summary")


@dataclass(frozen=True)
class Fact:
    """One shared-world fact: a person, a calendar entry, a preference, a supplier…"""

    name: str
    kind: str
    summary: str
    body: str
    source: str | None
    as_of: str | None
    path: Path


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split leading ``---`` frontmatter (flat ``key: value`` lines) from the body.

    Dependency-free (no YAML). Returns ``({}, text)`` when there is no frontmatter or
    the opening fence is never closed.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


def _load_fact(path: Path) -> Fact | None:
    """Parse one file into a ``Fact``, or ``None`` if it isn't a valid fact (missing
    ``kind``/``summary``) or can't be read. Never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — an unreadable file is skipped, never fatal
        return None
    meta, body = parse_frontmatter(text)
    if any(not meta.get(k) for k in _REQUIRED):
        return None
    return Fact(
        name=meta.get("name") or path.stem,
        kind=meta["kind"],
        summary=meta["summary"],
        body=body,
        source=meta.get("source") or None,
        as_of=meta.get("as_of") or None,
        path=path,
    )


def _score(fact: Fact, tokens: list[str]) -> int:
    """Keyword score: +2 per token in the high-signal name/summary, +1 in kind/body."""
    name_l, summary_l = fact.name.lower(), fact.summary.lower()
    kind_l, body_l = fact.kind.lower(), fact.body.lower()
    score = 0
    for tok in tokens:
        if tok in name_l or tok in summary_l:
            score += 2
        elif tok in kind_l or tok in body_l:
            score += 1
    return score


class SharedMemory:
    """Read-only view over a handbook directory of markdown fact files.

    Facts are loaded once and cached on first access — construct a new
    ``SharedMemory`` to pick up on-disk edits.
    """

    def __init__(self, base: Path) -> None:
        self._base = base
        self._facts: list[Fact] | None = None

    def _load(self) -> list[Fact]:
        if self._facts is None:
            try:
                paths = sorted(self._base.glob("*.md"))
            except (OSError, ValueError):  # missing/unreadable dir → no facts
                paths = []
            self._facts = [f for f in (_load_fact(p) for p in paths) if f is not None]
        return self._facts

    def all(self, *, kind: str | None = None) -> list[Fact]:
        facts = self._load()
        if kind is not None:
            facts = [f for f in facts if f.kind == kind]
        return sorted(facts, key=lambda f: f.name)

    def get(self, name: str) -> Fact | None:
        for fact in self._load():
            if fact.name == name:
                return fact
        return None

    def recall(
        self, query: str, *, kind: str | None = None, limit: int | None = None
    ) -> list[Fact]:
        tokens = query.lower().split()
        if not tokens:
            return []
        candidates = self._load()
        if kind is not None:
            candidates = [f for f in candidates if f.kind == kind]
        hits = [(s, f) for s, f in ((_score(f, tokens), f) for f in candidates) if s > 0]
        hits.sort(key=lambda sf: (-sf[0], sf[1].name))
        result = [f for _s, f in hits]
        if limit is not None:
            result = result[:limit]
        return result
