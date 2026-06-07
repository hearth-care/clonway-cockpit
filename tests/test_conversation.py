"""WS-D — the conversational operator platform (trust boundary + routing + execution).

The new platform logic is tested with an INJECTED fake drive (the worker-driving itself —
``_drive_argv`` over ``CockpitClient`` — mirrors the already-tested ``xops.drive.drive_argv`` +
``CockpitClient``, proven cross-process by WS-A's golden path). Here we pin the trust boundary,
routing, approve-seam threading, and narration.
"""

from __future__ import annotations

from clonway_cockpit import approval, conversation
from clonway_cockpit.conversation import OPERATOR, QUOTED, Conversation, Message, Plan


def _fake_drive(calls, frames):
    def drive(argv, script, *, approve):  # noqa: ANN001
        calls.append({"argv": argv, "script": tuple(script), "approve": approve})
        return list(frames)

    return drive


def _conv(*, router, launch=lambda w: ["argv", "--agent-stdio"], approve=approval.deny_all, drive):
    return Conversation(router=router, launch=launch, approve=approve, drive=drive)


# --- the trust boundary -----------------------------------------------------


def test_quoted_message_is_never_executed():
    calls: list = []
    conv = _conv(
        router=lambda m: Plan("xbook", ("c",), "draft bills"),  # router WOULD route it
        drive=_fake_drive(calls, []),
    )
    reply = conv.handle(Message("draft this week's bills", source=QUOTED))
    assert reply.acted is False
    assert calls == []  # the worker was NEVER driven from quoted content


def test_operator_message_is_routed_and_driven():
    calls: list = []
    frames = [{"kind": "home", "schema_version": "1.0"}, {"kind": "walk.review", "meta": {}}]
    conv = _conv(
        router=lambda m: Plan("xbook", ("c",), "draft bills"), drive=_fake_drive(calls, frames)
    )
    reply = conv.handle(Message("draft this week's bills", source=OPERATOR))
    assert reply.acted is True
    assert len(calls) == 1
    assert calls[0]["script"] == ("c",)


# --- routing edge cases -----------------------------------------------------


def test_no_actionable_command_does_not_drive():
    calls: list = []
    conv = _conv(router=lambda m: None, drive=_fake_drive(calls, []))
    reply = conv.handle(Message("hello", source=OPERATOR))
    assert reply.acted is False
    assert calls == []


def test_undrivable_worker_does_not_drive():
    calls: list = []
    conv = _conv(
        router=lambda m: Plan("ghost", (), ""),
        launch=lambda w: None,  # not drivable
        drive=_fake_drive(calls, []),
    )
    reply = conv.handle(Message("do a thing", source=OPERATOR))
    assert reply.acted is False
    assert "not drivable" in reply.text
    assert calls == []


# --- the approval seam is threaded to the drive -----------------------------


def test_approve_policy_reaches_the_drive():
    calls: list = []
    pol = approval.AllowlistPolicy({"schedule-bills"})
    conv = _conv(
        router=lambda m: Plan("xbook", ("c",), ""), approve=pol, drive=_fake_drive(calls, [])
    )
    conv.handle(Message("go", source=OPERATOR))
    assert calls[0]["approve"] is pol  # the human-sign-off / autonomous policy is passed through


# --- narration --------------------------------------------------------------


def test_narration_reports_applied_and_declined_and_current_screen():
    frames = [
        {"kind": "home"},
        {"kind": "walk.gate", "meta": {"status": "applied"}},
        {"kind": "walk.gate", "meta": {"status": "declined"}},
        {"kind": "walk.result", "meta": {}},
    ]
    conv = _conv(
        router=lambda m: Plan("xbook", ("c",), "draft bills"), drive=_fake_drive([], frames)
    )
    reply = conv.handle(Message("go", source=OPERATOR))
    assert "Drove xbook" in reply.text and "draft bills" in reply.text
    assert "Applied 1" in reply.text
    assert "Declined 1" in reply.text
    assert "walk.result" in reply.text


# --- the default driver is wired -------------------------------------------


def test_default_drive_is_the_framework_driver():
    conv = Conversation(router=lambda m: None, launch=lambda w: None)
    assert (
        conv._drive is conversation._drive_argv
    )  # defaults to the framework's CockpitClient driver


# --- FBA hardening: fail-safe trust default + honest empty-drive -------------


def test_unmarked_message_defaults_to_quoted_and_is_never_executed():
    # B1: the fail-safe default — a Message with no explicit source is QUOTED, not OPERATOR.
    calls: list = []
    conv = _conv(router=lambda m: Plan("xbook", ("c",), "x"), drive=_fake_drive(calls, []))
    reply = conv.handle(Message("draft this week's bills"))  # NO source given
    assert reply.acted is False
    assert calls == []  # an unmarked/forwarded message can never drive a worker


def test_operator_message_with_empty_drive_reports_not_acted():
    # B3: a worker that never paints a frame → honest "couldn't reach", not a false "Drove ...".
    conv = _conv(router=lambda m: Plan("xbook", ("c",), "draft"), drive=_fake_drive([], []))
    reply = conv.handle(Message("go", source=OPERATOR))
    assert reply.acted is False
    assert "could not reach" in reply.text.lower()
