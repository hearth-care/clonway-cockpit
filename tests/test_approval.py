"""Reference authorization policies (the cockpit write-gate seam)."""

from __future__ import annotations

import io

from clonway_cockpit import approval


def test_deny_all_never_authorizes():
    assert approval.deny_all({"token": "gate-1", "equivalent_cli": "x post"}) is False


def test_approve_all_always_authorizes():
    assert approval.approve_all({"token": "gate-1"}) is True


def test_prompt_human_yes_authorizes():
    out = io.StringIO()
    assert (
        approval.prompt_human({"equivalent_cli": "x post"}, input_fn=lambda: "y", out=out) is True
    )
    assert "x post" in out.getvalue()  # the proposal is shown to the human


def test_prompt_human_no_and_empty_decline():
    out = io.StringIO()
    assert approval.prompt_human({}, input_fn=lambda: "n", out=out) is False
    assert approval.prompt_human({}, input_fn=lambda: "", out=out) is False


def test_prompt_human_writes_to_given_stream_not_stdout(capsys):
    out = io.StringIO()
    approval.prompt_human({"equivalent_cli": "x post"}, input_fn=lambda: "n", out=out)
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing leaked to stdout (the JSON channel stays clean)
    assert "Apply:" in out.getvalue()


# --- WS-B: AllowlistPolicy (autonomous, money-direction excluded) ------------


def test_allowlist_policy_approves_allowlisted_reversible():
    p = approval.AllowlistPolicy({"schedule-bills"})
    assert p({"capability_key": "schedule-bills", "money_movement": False}) is True


def test_allowlist_policy_refuses_capability_not_in_allowlist():
    p = approval.AllowlistPolicy({"schedule-bills"})
    assert p({"capability_key": "reconcile-settle", "money_movement": False}) is False


def test_allowlist_policy_refuses_money_movement_even_if_allowlisted():
    p = approval.AllowlistPolicy({"pay-supplier"})
    # allowlisted by key, but money_movement → the structural line refuses it
    assert p({"capability_key": "pay-supplier", "money_movement": True}) is False


def test_allowlist_policy_refuses_missing_key():
    assert approval.AllowlistPolicy({"x"})({"money_movement": False}) is False


def test_empty_allowlist_authorizes_nothing():
    p = approval.AllowlistPolicy(set())
    assert p({"capability_key": "schedule-bills"}) is False
