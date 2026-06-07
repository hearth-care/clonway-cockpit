"""Shippable agent-navigability gate — the parity + conformance checks any repo runs
against ITS OWN render/model namespaces.

Promoted from clonway-cockpit's own tests so the discipline is imported, not hand-copied:
a framework bump propagates it to every consumer (the pinned-by-rev consumption model). Two
checks, used together in a consumer's CI:

* :func:`assert_render_model_parity` — STATIC: every page-framing ``render_*`` has a
  ``model_*`` twin. Catches "you added a screen and forgot its model".
* :func:`assert_drives_clean` — DYNAMIC: drive the real loop and assert no ``unstructured``
  frame reaches an agent on a real path. Catches "the model exists but is never wired" —
  the failure static review structurally cannot see.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from types import ModuleType


def page_framing_renders(render_ns: ModuleType) -> set[str]:
    """Public ``render_*`` in ``render_ns`` whose source calls ``page(`` — i.e. it frames a
    full screen, as opposed to a sub-component (``render_header``, ``render_pulse``) or a
    helper. Same heuristic the original framework contract test used."""
    out: set[str] = set()
    for name, fn in inspect.getmembers(render_ns, inspect.isfunction):
        if not name.startswith("render_"):
            continue
        try:
            src = inspect.getsource(fn)
        except OSError:  # pragma: no cover — source is always available in-tree
            continue
        if "page(" in src:
            out.add(name)
    return out


def model_twin(render_name: str) -> str:
    """``'render_foo'`` -> ``'model_foo'``."""
    return "model_" + render_name[len("render_") :]


def assert_render_model_parity(
    render_ns: ModuleType,
    model_ns: ModuleType | None = None,
    *,
    allow_unmodeled: Iterable[str] = (),
) -> None:
    """Assert every page-framing ``render_*`` in ``render_ns`` has a ``model_*`` twin in
    ``model_ns`` (defaults to ``render_ns`` — most repos co-locate them).

    ``allow_unmodeled`` is an explicit, reviewed escape hatch: a ``render_*`` deliberately
    served as ``unstructured`` (rare; document why at the call site). Empty by default, so
    forgetting a model is a hard failure."""
    models = model_ns if model_ns is not None else render_ns
    allowed = set(allow_unmodeled)
    missing: list[str] = []
    for render_name in sorted(page_framing_renders(render_ns)):
        if render_name in allowed:
            continue
        twin = model_twin(render_name)
        if not hasattr(models, twin):
            missing.append(f"{render_name} -> {twin}")
    assert not missing, (
        "page-framing render_* with no model_* twin (agent gets `unstructured`): "
        + ", ".join(missing)
    )


def assert_drives_clean(
    host,  # clonway_cockpit.shell.Host — untyped here to keep this module import-light
    keys: Iterable[str],
    *,
    allow_unstructured: bool = False,
) -> list:
    """DYNAMIC conformance: drive ``host`` headlessly over the scripted ``keys`` and assert
    no emitted screen fell through to ``unstructured`` (the agent-blind fallback). Returns
    the recorded ``ScreenModel`` stream so a caller can assert further.

    This catches a model that exists but is never wired onto a real path — the
    'advertised but not wired' failure that static review structurally cannot see (drive it,
    don't read it). ``allow_unstructured`` opts out for a path that legitimately ends on a
    setup hint (e.g. an unconfigured Doctor)."""
    from clonway_cockpit.agent import CockpitDriver  # local import: avoid an import cycle

    stream = CockpitDriver(host, keys=list(keys)).run()
    if not allow_unstructured:
        blind = [m for m in stream if m.kind == "unstructured"]
        assert not blind, (
            f"{len(blind)} screen(s) reached the agent as `unstructured` while driving "
            f"{list(keys)!r}: {[m.title for m in blind]}"
        )
    return stream
