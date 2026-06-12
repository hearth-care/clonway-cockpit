"""Framework-level fleet audit log tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from clonway_cockpit import contract, render
from clonway_cockpit.audit_log import (
    AUDIT_SCHEMA,
    EVENTS,
    AuditEvent,
    make_audit_sink,
    read_events,
)


class _FakeBlob:
    def __init__(self, store: dict[str, str], name: str) -> None:
        self._store = store
        self._name = name

    def upload_from_string(self, body: str, content_type: str | None = None) -> None:
        self._store[self._name] = body
        self._store[f"__ct__::{self._name}"] = content_type or ""


class _FakeBucket:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def bucket(self, name: str) -> _FakeBucket:
        self.store["__bucket__"] = name
        return _FakeBucket(self.store)


class _BoomClient:
    def bucket(self, name: str) -> _FakeBucket:
        raise RuntimeError("storage down")


def _event(**overrides: Any) -> AuditEvent:
    fields = {
        "ts": datetime(2026, 6, 12, 9, 30, tzinfo=UTC),
        "worker": "demo",
        "run_id": "run-1",
        "event": "gate.applied",
        "capability_key": "sync",
        "actor": "human",
        "dry_run": False,
        "money_movement": True,
        "outcome": "applied",
        "equivalent_cli": "demo sync",
        "focus": "Sync",
        "ref": "gate-1",
    }
    fields.update(overrides)
    return AuditEvent(**fields)


def test_audit_event_wire_shape_is_schema_pinned() -> None:
    event = _event()

    wire = event.to_wire()

    assert wire["schema"] == AUDIT_SCHEMA == "audit/1"
    assert set(wire) == {
        "schema",
        "ts",
        "worker",
        "run_id",
        "event",
        "capability_key",
        "actor",
        "dry_run",
        "money_movement",
        "outcome",
        "equivalent_cli",
        "focus",
        "ref",
    }
    assert AuditEvent.from_wire(wire) == event


def test_audit_event_rejects_unknown_events_and_fields() -> None:
    assert "capability.launched" in EVENTS
    with pytest.raises(ValueError, match="unknown audit event"):
        _event(event="domain.content")
    with pytest.raises(TypeError):
        AuditEvent(domain_payload={"name": "redacted"})  # type: ignore[call-arg]


def test_sink_appends_local_jsonl_and_read_events_round_trips(tmp_path: Path) -> None:
    sink = make_audit_sink("demo", base_dir=tmp_path, gcs=False)

    sink(_event(event="capability.launched", outcome=None))
    sink(_event(event="gate.offered", outcome=None))

    path = tmp_path / "2026-06-12.jsonl"
    lines = path.read_text().splitlines()
    assert [json.loads(line)["event"] for line in lines] == [
        "capability.launched",
        "gate.offered",
    ]
    assert list(read_events(tmp_path)) == [
        _event(event="capability.launched", outcome=None),
        _event(event="gate.offered", outcome=None),
    ]


def test_read_events_filters_by_since_date(tmp_path: Path) -> None:
    sink = make_audit_sink("demo", base_dir=tmp_path, gcs=False)

    sink(_event(ts=datetime(2026, 6, 11, 23, 30, tzinfo=UTC), ref="old"))
    sink(_event(ts=datetime(2026, 6, 12, 9, 30, tzinfo=UTC), ref="new"))

    assert [event.ref for event in read_events(tmp_path, since=datetime(2026, 6, 12).date())] == [
        "new"
    ]


def test_sink_mirrors_to_gcs_every_twenty_events_and_on_flush(tmp_path: Path) -> None:
    client = _FakeClient()
    sink = make_audit_sink(
        "demo",
        base_dir=tmp_path,
        gcs=True,
        storage_client_factory=lambda: client,
    )

    for idx in range(19):
        sink(_event(ref=f"gate-{idx}"))
    assert "audit/demo/2026-06-12/run-1.jsonl" not in client.store

    sink(_event(ref="gate-19"))
    body = client.store["audit/demo/2026-06-12/run-1.jsonl"]
    assert len(body.splitlines()) == 20
    assert client.store["__ct__::audit/demo/2026-06-12/run-1.jsonl"] == "application/x-ndjson"

    sink(_event(ref="gate-20"))
    sink.flush()  # type: ignore[attr-defined]
    body = client.store["audit/demo/2026-06-12/run-1.jsonl"]
    assert len(body.splitlines()) == 21


def test_sink_never_raises_when_local_or_gcs_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    sink = make_audit_sink(
        "demo",
        base_dir=blocked,
        gcs=True,
        storage_client_factory=_BoomClient,
    )

    with caplog.at_level("DEBUG", logger="demo.audit"):
        sink(_event())
        sink.flush()  # type: ignore[attr-defined]

    assert "audit sink failed" in caplog.text or "audit GCS flush failed" in caplog.text


def test_render_ledger_and_model_ledger_show_agent_readable_rows() -> None:
    events = [
        _event(ts=datetime(2026, 6, 12, 9, 30, tzinfo=UTC), event="gate.offered", outcome=None),
        _event(ts=datetime(2026, 6, 12, 9, 31, tzinfo=UTC), event="gate.applied"),
    ]

    console = Console(record=True, width=120)
    console.print(render.render_ledger(events))
    text = console.export_text()

    assert "fleet audit log" in text
    assert "09:30" in text
    assert "gate.offered" in text
    assert "gate.applied" in text

    model = render.model_ledger(events)
    assert model.kind == "audit.ledger"
    assert model.regions[0].role == "ledger"
    assert [row.id for row in model.regions[0].rows] == ["audit:0", "audit:1"]
    assert model.regions[0].rows[1].fields[4].value == "applied"


def test_render_ledger_has_model_twin_discovered_by_contract() -> None:
    assert "render_ledger" in contract.page_framing_renders(render)
    contract.assert_render_model_parity(render)
