# tests/test_signal_model.py
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import clonway_cockpit.signals.model as signal_model
from clonway_cockpit.signals.model import (
    SIGNAL_KINDS,
    Signal,  # noqa: F401 — imported for type-checking / future assertions
    _dedup_key,
    _kind_for,
    _urgency_for,
    _urgency_from_due_at,
    build_signals,
    urgency_from_due_at,
)
from clonway_cockpit.state import NeedsItem

_NOW = datetime(2026, 5, 25, 7, 15, tzinfo=UTC)


def _need(
    title="Pay run due to post",
    detail="Weekly · Fri 29 May",
    level="warn",
    cap="payroll-status",
    focus=None,
):
    return NeedsItem(title, detail, level, cap, focus)


def test_build_signals_maps_one_to_one_in_order():  # T1
    needs = (
        _need(title="Bills overdue", level="error", cap="schedule-bills", focus="overdue"),
        _need(title="Pay run due to post"),
        _need(title="DRAFT bills need approval", level="warn", cap=None),
    )
    sigs = build_signals(needs, now=_NOW, worker="xbook")
    assert [s.title for s in sigs] == [
        "Bills overdue",
        "Pay run due to post",
        "DRAFT bills need approval",
    ]
    s0 = sigs[0]
    assert s0.worker == "xbook" and s0.level == "error" and s0.capability_key == "schedule-bills"
    assert s0.focus == "overdue" and s0.state == "open" and s0.due_at is None
    assert s0.emitted_at == _NOW


@pytest.mark.parametrize(
    "title,kind",
    [
        ("Set up xbook", "action.required"),
        ("Re-authenticate Xero", "credential.expiring"),
        ("Re-authenticate Lloyds", "credential.expiring"),
        ("Sync the books", "action.required"),
        ("Sync is stale", "action.required"),
        ("Bills overdue", "action.required"),
        ("Bills due this week", "deadline.approaching"),
        ("Unmatched bank lines", "action.required"),
        ("DRAFT bills need approval", "approval.pending"),
        ("DD amount anomalies", "anomaly.detected"),
        ("Pay run needs finishing", "action.required"),
        ("Pay run due to post", "deadline.approaching"),
        ("HMRC payment coming up", "deadline.approaching"),
        ("Pension payment coming up", "deadline.approaching"),
        ("Cash getting tight", "deadline.approaching"),
        ("Next month loss-making", "deadline.approaching"),
        ("Cash outlook worsened", "anomaly.detected"),
        ("Profit outlook worsened", "anomaly.detected"),
    ],
)
def test_kind_for_known_titles(title, kind):  # T2
    assert _kind_for(title) == kind
    assert kind in SIGNAL_KINDS


def test_kind_for_unknown_title_defaults_action_required():  # T3
    assert _kind_for("Some future signal") == "action.required"


def test_lloyds_reauth_title_maps_to_credential_expiring():  # S6b follow-up
    """A distinct Lloyds/TrueLayer re-auth title maps to credential.expiring, so
    xbook can emit a per-credential title instead of reusing the Xero one. Additive:
    the Xero mapping is unchanged and an unrelated title is unaffected."""
    assert _kind_for("Re-authenticate Lloyds") == "credential.expiring"
    # The existing Xero mapping is untouched (additive, not a rename).
    assert _kind_for("Re-authenticate Xero") == "credential.expiring"
    # An unrelated title still falls through to the action.required default.
    assert _kind_for("Re-authenticate Revolut") == "action.required"


@pytest.mark.parametrize(
    "level,urgency", [("ok", "info"), ("warn", "soon"), ("error", "due"), ("weird", "info")]
)
def test_urgency_for(level, urgency):  # T4
    assert _urgency_for(level) == urgency


def test_dedup_key_stable_across_detail_distinct_across_identity():  # T5
    a = build_signals((_need(detail="in 3 days"),), now=_NOW, worker="xbook")[0]
    b = build_signals((_need(detail="tomorrow"),), now=_NOW, worker="xbook")[0]
    assert a.dedup_key == b.dedup_key  # detail excluded → stable as it escalates
    c = build_signals((_need(focus="overdue"),), now=_NOW, worker="xbook")[0]
    assert c.dedup_key != a.dedup_key  # differing focus → distinct


@pytest.mark.parametrize(
    "worker,title,capability_key,focus,source_id,expected_uuid",
    [
        # Pinned literals — changing the namespace or join-string will fail these.
        (
            "xbook",
            "Bills due this week",
            "schedule-bills",
            "overdue",
            None,
            "8c71df8f-92ca-5718-9d8c-788c998c0183",
        ),
        (
            "xhr",
            "DBS expiring",
            "staff-records",
            "employee:42",
            "dbs:42",
            "ffab3ac2-02cf-57e4-a26e-9950dc4114e8",
        ),
        (
            "xletter",
            "Campaign send window",
            None,
            None,
            "campaign:summer",
            "1968a274-103b-5c1c-afe5-e033ee646b07",
        ),
        (
            "xquill",
            "Promise due",
            "commitments",
            "thread:abc",
            "promise:abc:1",
            "58975d49-97c0-5a1d-a068-57f496385cd9",
        ),
    ],
)
def test_public_dedup_key_golden(
    worker, title, capability_key, focus, source_id, expected_uuid
):  # C12
    assert signal_model.dedup_key(worker, title, capability_key, focus, source_id) == expected_uuid
    with pytest.warns(DeprecationWarning, match="dedup_key"):
        assert _dedup_key(worker, title, capability_key, focus, source_id) == expected_uuid


def test_private_dedup_key_alias_warns_but_keeps_value():  # C12
    _PINNED = "80b0e4f8-277a-535e-8c7a-998c9d766a3b"  # xhr|DBS expiring|staff-records|None|dbs:42
    with pytest.warns(DeprecationWarning, match="dedup_key"):
        alias_value = _dedup_key("xhr", "DBS expiring", "staff-records", None, "dbs:42")
    assert alias_value == _PINNED
    assert signal_model.dedup_key("xhr", "DBS expiring", "staff-records", None, "dbs:42") == _PINNED


def test_to_wire_is_json_serialisable_with_null_due_at():  # T6
    s = build_signals((_need(),), now=_NOW, worker="xbook")[0]
    wire = s.to_wire()
    assert wire["due_at"] is None
    assert json.loads(json.dumps(wire))["emitted_at"] == _NOW.isoformat()


# --- C0b: due_at-driven urgency + per-instance dedup_key (append) ---
from datetime import date as Date  # noqa: E402


def _need_due(due_at=None, source_id=None, title="Pay run due to post", level="warn"):
    return NeedsItem(
        title, "detail", level, "payroll-status", None, due_at, source_id
    )  # positional: …, focus, due_at, source_id


@pytest.mark.parametrize(
    "due,expected",
    [
        (Date(2026, 5, 24), "overdue"),  # yesterday
        (Date(2026, 5, 25), "due"),  # today
        (Date(2026, 5, 26), "due"),  # tomorrow
        (Date(2026, 5, 27), "soon"),  # +2
        (Date(2026, 6, 1), "soon"),  # +7
        (Date(2026, 6, 2), "info"),  # +8
    ],
)
def test_urgency_from_due_at(due, expected):  # TB6
    assert urgency_from_due_at(due, "warn", _NOW) == expected


def test_private_urgency_alias_warns_but_keeps_value():  # C12
    with pytest.warns(DeprecationWarning, match="urgency_from_due_at"):
        alias_value = _urgency_from_due_at(Date(2026, 5, 26), "warn", _NOW)
    assert alias_value == signal_model.urgency_from_due_at(Date(2026, 5, 26), "warn", _NOW)


@pytest.mark.parametrize("level,urgency", [("ok", "info"), ("warn", "soon"), ("error", "due")])
def test_urgency_falls_back_to_level_when_no_due_at(level, urgency):  # TB7
    assert urgency_from_due_at(None, level, _NOW) == urgency


def test_build_signals_urgency_reflects_due_at_else_level():  # TB8
    dated = build_signals((_need_due(due_at=Date(2026, 5, 26)),), now=_NOW, worker="xbook")[0]
    assert dated.urgency == "due" and dated.due_at == Date(2026, 5, 26)
    dateless = build_signals((_need_due(due_at=None, level="ok"),), now=_NOW, worker="xbook")[0]
    assert dateless.urgency == "info" and dateless.due_at is None


def test_build_signals_default_worker_warns_for_staged_removal():  # C12
    with pytest.warns(DeprecationWarning, match="worker"):
        sig = build_signals((_need(),), now=_NOW)[0]
    assert sig.worker == "xbook"


def test_build_signals_explicit_worker_does_not_warn(recwarn):  # C12
    sig = build_signals((_need(),), now=_NOW, worker="xhr")[0]
    assert not recwarn
    assert sig.worker == "xhr"


def test_dedup_key_distinct_per_source_id_stable_across_detail():  # TB9
    a = build_signals((_need_due(source_id="4-weekly:2026-05-29"),), now=_NOW, worker="xbook")[0]
    b = build_signals((_need_due(source_id="2-weekly:2026-05-29"),), now=_NOW, worker="xbook")[0]
    assert a.dedup_key != b.dedup_key  # two concurrent cycles → distinct (E7 closed)
    c = build_signals(
        (
            NeedsItem(
                "Pay run due to post",
                "OVERDUE now",
                "warn",
                "payroll-status",
                None,
                Date(2026, 5, 29),
                "4-weekly:2026-05-29",
            ),
        ),
        now=_NOW,
        worker="xbook",
    )[0]
    assert a.dedup_key == c.dedup_key  # same instance, escalating detail → same key


def test_to_wire_carries_real_due_at_and_source_id():  # TB10
    s = build_signals(
        (_need_due(due_at=Date(2026, 5, 29), source_id="4-weekly:2026-05-29"),),
        now=_NOW,
        worker="xbook",
    )[0]
    wire = s.to_wire()
    assert wire["due_at"] == "2026-05-29"
    assert wire["source_id"] == "4-weekly:2026-05-29"
    assert json.loads(json.dumps(wire))["due_at"] == "2026-05-29"
