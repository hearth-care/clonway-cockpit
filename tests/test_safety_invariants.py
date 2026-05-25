# tests/test_safety_invariants.py
"""SI-1 — write-gate safety characterisation tests.

Pins the load-bearing ``confirm_apply`` key contract that travels with the gate.
The xbook-side invariants SI-2 (the exact set of write-walk call sites) and SI-3
(the CLI apply dry-run default) stay in xbook — they reference xbook source/CLI
that did not move into the framework.
"""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import keys, walk
from clonway_cockpit.registry import WizardContext


def _ctx(*, read_key=None, confirm_fn=lambda _p: False) -> WizardContext:
    return WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda *a, **k: "",
        confirm_fn=confirm_fn,
        read_key=read_key,
    )


# ---- SI-1: confirm_apply key contract -------------------------------------


def test_confirm_apply_cockpit_accepts_enter_and_a():  # TS1a
    for key in (keys.ENTER, "a", "A"):
        ctx = _ctx(read_key=lambda k=key: k)
        assert walk.confirm_apply(ctx, equivalent_cli="x") is True


def test_confirm_apply_cockpit_rejects_other_keys():  # TS1b
    for key in (keys.ESC, "n", "N", "x", " "):
        ctx = _ctx(read_key=lambda k=key: k)
        assert walk.confirm_apply(ctx, equivalent_cli="x") is False


def test_confirm_apply_console_mirrors_confirm_fn():  # TS1c
    assert walk.confirm_apply(_ctx(confirm_fn=lambda _p: True), equivalent_cli="x") is True
    assert walk.confirm_apply(_ctx(confirm_fn=lambda _p: False), equivalent_cli="x") is False
