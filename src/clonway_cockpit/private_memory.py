"""Private per-persona working memory — the *private* tier of the persona platform's two-tier
memory (the shared tier is ``shared_memory.py``). Each persona owns an **isolated** store nobody
else reads: its own working notes ("the bookkeeper's Xero notes, the marketer's campaign state"),
optionally scoped per **thread/space** so a conversation can accumulate context for true multi-turn.

Two isolation dimensions:

- **Persona isolation (hard boundary — the whole point).** Each persona's store is a separate
  subtree keyed by its ``handle`` (a slug, so it is path-safe — re-validated here for defence in
  depth). The API only ever reads/writes within one handle's subtree, so cross-persona reads are
  *structurally* impossible, not merely policy.
- **Thread/space scoping.** Within a persona, ``working`` holds persona-global notes that persist
  across all its conversations; ``thread(scope)`` holds per-thread/space session memory. On disk:
  ``<base>/<handle>/working/`` and ``<base>/<handle>/threads/<scope>/`` — the ``working/`` vs
  ``threads/`` split means a thread literally named ``working`` can never collide.

Private writes are **not** owner-gated — a persona's own notes reach only itself, so there is no
shared blast radius. The load-bearing guarantee here is **isolation**, not provenance. The
owner-only promotion into *shared* truth stays exactly where it is (``GovernedWriter``); a private
note never becomes shared truth without going back through that gate. The on-disk **format** is the
same ``Fact`` as a shared fact — reused from ``shared_memory`` (the format is defined once).

See ``docs/private-memory.md`` and the design spec
``docs/superpowers/specs/2026-06-10-per-persona-memory-design.md``.
"""

from __future__ import annotations

from pathlib import Path

from clonway_cockpit.shared_memory import (
    Fact,
    SharedMemory,
    is_safe_slug,
    render_fact,
    single_line,
    today,
)

WORKING = "working"
"""The reserved per-persona scope directory for persona-global working memory."""

_THREADS = "threads"
"""Parent directory for per-thread/space scoped memory (kept separate from ``working``)."""


def _require_slug(value: str, what: str) -> str:
    """Validate a string that becomes a path segment/filename. Raises ``ValueError`` (a private
    programmer error — *not* ``WriteRefused``, which is the shared-tier trust boundary)."""
    if not is_safe_slug(value):
        raise ValueError(
            f"invalid {what} {value!r}: must be a lower-case slug [a-z0-9][a-z0-9_-]* "
            "(rejects path traversal and odd filenames)"
        )
    return value


class PrivateScope:
    """Read + write over **one** (persona, scope) directory. Reads are best-effort and never
    raise (a persona must not fall over looking something up — same posture as ``SharedMemory``);
    writes validate before touching disk and are fail-closed.

    Construct a fresh scope (via :class:`PersonaMemory`) to pick up on-disk edits — like
    ``SharedMemory``, a scope loads once and caches; a ``remember``/``forget`` refreshes its own
    view so reads-after-write within the same instance are consistent.
    """

    def __init__(self, base: Path) -> None:
        self._base = base
        self._reader = SharedMemory(base)

    # --- read (delegated to the shared reader — the load/recall logic is defined once) ---

    def get(self, name: str) -> Fact | None:
        return self._reader.get(name)

    def all(self, *, kind: str | None = None) -> list[Fact]:
        return self._reader.all(kind=kind)

    def recall(
        self, query: str, *, kind: str | None = None, limit: int | None = None
    ) -> list[Fact]:
        return self._reader.recall(query, kind=kind, limit=limit)

    # --- write (NOT owner-gated — private working memory is the persona's own) ---

    def remember(
        self,
        *,
        name: str,
        kind: str,
        summary: str,
        body: str = "",
        as_of: str | None = None,
    ) -> Fact:
        """Write (or overwrite) one private note. ``name`` becomes the filename, so it must be a
        safe slug; ``kind``/``summary``/``as_of`` must be single-line (else a newline would inject
        extra frontmatter keys). Invalid input raises ``ValueError`` and writes nothing. ``as_of``
        defaults to today (UTC). The note round-trips through :meth:`get`/:meth:`recall`."""
        _require_slug(name, "name")
        kind = single_line(kind, "kind")
        summary = single_line(summary, "summary")
        stamp = single_line(as_of, "as_of") if as_of else today()
        clean_body = body.strip()
        self._base.mkdir(parents=True, exist_ok=True)
        path = self._base / f"{name}.md"
        # source is empty for a private note — provenance carries no promotion power here, and the
        # boundary that keeps this out of shared truth is the *directory*, not this field.
        path.write_text(render_fact(name, kind, summary, "", stamp, clean_body), encoding="utf-8")
        self._reader = SharedMemory(self._base)  # refresh: reads-after-write are consistent
        return Fact(
            name=name,
            kind=kind,
            summary=summary,
            body=clean_body,
            source=None,
            as_of=stamp,
            path=path,
        )

    def forget(self, name: str) -> bool:
        """Delete one note, returning ``True`` if it existed, ``False`` otherwise. Never raises on
        a missing note or scope. An unsafe ``name`` simply isn't a real note → ``False`` (it can
        never resolve to a path outside this scope)."""
        if not is_safe_slug(name):
            return False
        path = self._base / f"{name}.md"
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError:
            return False
        self._reader = SharedMemory(self._base)  # refresh after the delete
        return True


class PersonaMemory:
    """One persona's private memory, isolated by ``handle``. Inject the private-memory root
    (``base``); the framework ships no data. ``working`` is the persona-global store; ``thread``
    opens a per-thread/space scoped store for multi-turn session memory."""

    def __init__(self, base: Path, handle: str) -> None:
        self._base = base
        self._handle = _require_slug(handle, "handle")

    @property
    def working(self) -> PrivateScope:
        """The persona-global working store (``<base>/<handle>/working``)."""
        return PrivateScope(self._base / self._handle / WORKING)

    def thread(self, scope: str) -> PrivateScope:
        """A per-thread/space scoped store (``<base>/<handle>/threads/<scope>``) for multi-turn
        session memory. ``scope`` (a Chat space/thread id) must be a safe slug."""
        _require_slug(scope, "scope")
        return PrivateScope(self._base / self._handle / _THREADS / scope)
