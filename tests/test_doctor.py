from dataclasses import FrozenInstanceError

import pytest

from clonway_cockpit.doctor import (
    DoctorActionKind,
    Fix,
    Probe,
    action_kind,
)


def test_legacy_positional_constructors_keep_their_field_values() -> None:
    def callback() -> str:
        return "done"

    assert Fix("title", "cmd") == Fix(title="title", cmd="cmd")
    assert Fix("title", "cmd", "note") == Fix(title="title", cmd="cmd", note="note")
    assert Fix("title", "cmd", "note", callback) == Fix(
        title="title", cmd="cmd", note="note", run=callback
    )
    assert Fix("title", "cmd", "note", callback, True) == Fix(
        title="title", cmd="cmd", note="note", run=callback, confirm=True
    )
    assert Probe("name", "ok", "detail", None) == Probe(
        name="name", level="ok", detail="detail", fix=None
    )


def test_legacy_five_positional_confirm_without_run_still_constructs() -> None:
    """A pre-identity ``Fix(title, cmd, note, None, True)`` — run=None, confirm=True,
    no remedy_id/probe_id/capability_key — constructed fine on ``main`` (confirm was
    simply never consulted for a non-callback fix). The additive identity contract
    must not retroactively break that legacy positional shape."""
    fix = Fix("Re-auth in browser", "worker auth login", "opens a browser", None, True)
    assert fix.run is None
    assert fix.confirm is True


def test_action_kinds_have_stable_serialized_values() -> None:
    assert DoctorActionKind.DISPLAY_ONLY.value == "display_only"
    assert DoctorActionKind.CALLBACK.value == "callback"
    assert DoctorActionKind.OPEN_CAPABILITY.value == "open_capability"

    assert action_kind(Fix("Display", "worker explain")) is DoctorActionKind.DISPLAY_ONLY
    assert (
        action_kind(Fix("Callback", "worker fix", run=lambda: "done")) is DoctorActionKind.CALLBACK
    )
    assert (
        action_kind(Fix("Open", "worker review", capability_key="review"))
        is DoctorActionKind.OPEN_CAPABILITY
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"run": lambda: "done", "capability_key": "review"},
        {"focus": "row.1"},
        {"capability_key": "review", "confirm": True},
        {"remedy_id": "remedy.gap", "confirm": True},
        {"probe_id": "probe.gap", "confirm": True},
        {"remedy_id": "two words"},
        {"probe_id": "\t"},
        {"capability_key": " "},
        {"focus": "row\n1", "capability_key": "review"},
        {"remedy_id": "a\x00b"},
        {"probe_id": "\x00"},
        {"capability_key": "cap\x0bkey"},
    ],
)
def test_invalid_additive_action_contract_rejects(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        Fix("Invalid", "worker invalid", **kwargs)


def test_bare_confirm_without_run_or_identity_is_legacy_and_permitted() -> None:
    """Unlike the identified cases above, ``confirm=True`` with no ``run`` and no
    remedy_id/probe_id/capability_key is the legacy positional shape (see
    ``test_legacy_five_positional_confirm_without_run_still_constructs``) — it must
    stay constructible even via kwargs, not just via the positional call."""
    fix = Fix("Legacy", "worker legacy", confirm=True)
    assert fix.confirm is True


def test_models_are_frozen() -> None:
    fix = Fix("Open", "worker review", remedy_id="remedy.review", capability_key="review")
    probe = Probe("Review", "warn", "Needs attention", fix, "probe.review", "rev-1")

    with pytest.raises(FrozenInstanceError):
        fix.title = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        probe.level = "ok"  # type: ignore[misc]
