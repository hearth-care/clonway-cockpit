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

import shutil
import threading
from pathlib import Path

from clonway_cockpit.obs.atomicio import atomic_write_bytes
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

PRIVATE_MEMORY_LOCK = threading.RLock()
"""Process-local lock for private memory writes and whole-thread deletion."""


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

    @property
    def path(self) -> Path:
        """The on-disk scope directory. Read-only so callers do not rebuild the layout."""
        return self._base

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
        source: str = "",
        as_of: str | None = None,
    ) -> Fact:
        """Write (or overwrite) one private note. ``name`` becomes the filename, so it must be a
        safe slug; ``kind``/``summary``/``source``/``as_of`` must be single-line (else a newline
        would inject extra frontmatter keys). Invalid input raises ``ValueError`` and writes
        nothing. ``source`` is optional **advisory** provenance ("the resident's daughter said…")
        — it carries NO promotion power: a private note never becomes shared truth, which still
        requires ``GovernedWriter(source=OWNER)``; the boundary is the *directory*, not this field.
        ``as_of`` defaults to today (UTC). The note round-trips through :meth:`get`/:meth:`recall`."""
        _require_slug(name, "name")
        kind = single_line(kind, "kind")
        summary = single_line(summary, "summary")
        clean_source = single_line(source, "source") if source else ""
        stamp = single_line(as_of, "as_of") if as_of else today()
        clean_body = body.strip()
        with PRIVATE_MEMORY_LOCK:
            self._base.mkdir(parents=True, exist_ok=True)
            path = self._base / f"{name}.md"
            atomic_write_bytes(
                path,
                render_fact(name, kind, summary, clean_source, stamp, clean_body).encode("utf-8"),
            )
            self._reader = SharedMemory(self._base)  # refresh: reads-after-write are consistent
        return Fact(
            name=name,
            kind=kind,
            summary=summary,
            body=clean_body,
            source=clean_source or None,
            as_of=stamp,
            path=path,
        )

    def forget(self, name: str) -> bool:
        """Delete one note, returning ``True`` if it existed, ``False`` if it did not. An unsafe
        ``name`` is never a real note → ``False``. A genuine filesystem error (e.g. a permission
        denial) is **not** swallowed — it propagates, so a failed delete is never silently reported
        as "wasn't there" (which would falsely assure a persona that a note it tried to erase is
        gone)."""
        if not is_safe_slug(name):
            return False
        path = self._base / f"{name}.md"
        with PRIVATE_MEMORY_LOCK:
            try:
                path.unlink()
            except FileNotFoundError:
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
        """The persona-global working store (``<base>/<handle>/working``). Each access returns a
        **fresh** scope (so it reflects on-disk edits, like constructing a new ``SharedMemory``) —
        hold the returned scope in a local for a sequence of reads rather than re-accessing
        ``.working`` each time, which reloads the directory."""
        return PrivateScope(self._base / self._handle / WORKING)

    def thread(self, scope: str) -> PrivateScope:
        """A per-thread/space scoped store (``<base>/<handle>/threads/<scope>``) for multi-turn
        session memory. ``scope`` must be a safe slug: a **raw Chat space id** (e.g.
        ``spaces/AAAAbCdEf``) is not a slug, so the transport slice (#73) is responsible for
        normalising it into one (e.g. lower-casing + replacing ``/`` with ``-``, or hashing) before
        calling here. Each call returns a **fresh** scope; hold it in a local for a read sequence."""
        _require_slug(scope, "scope")
        return PrivateScope(self._base / self._handle / _THREADS / scope)

    def forget_thread(self, scope: str) -> bool:
        """Delete one per-thread/space scoped store recursively. Returns ``True`` iff it existed."""
        _require_slug(scope, "scope")
        path = self._base / self._handle / _THREADS / scope
        with PRIVATE_MEMORY_LOCK:
            if not path.exists():
                return False
            shutil.rmtree(path)
            return True
