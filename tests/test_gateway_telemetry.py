from pathlib import Path

from clonway_cockpit.gateway.telemetry import load_events, record_call


def _record(base: Path, **over: object) -> None:
    kw: dict[str, object] = dict(
        role="chat",
        provider="openai_compatible",
        model="gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=20,
        est_cost=0.0001,
        ok=True,
        err=None,
    )
    kw.update(over)
    record_call(base, **kw)  # type: ignore[arg-type]


def test_record_then_load_roundtrip(tmp_path: Path):
    _record(tmp_path)
    _record(
        tmp_path, ok=False, err="GatewayError", prompt_tokens=0, completion_tokens=0, est_cost=None
    )
    events = load_events(tmp_path)
    assert len(events) == 2
    first = events[0]
    assert first["role"] == "chat"
    assert first["model"] == "gpt-4o-mini"
    assert first["prompt_tokens"] == 10
    assert first["completion_tokens"] == 20
    assert first["ok"] is True
    assert "ts" in first
    assert events[1]["ok"] is False
    assert events[1]["err"] == "GatewayError"
    assert events[1]["est_cost"] is None


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_events(tmp_path / "nope") == []


def test_record_never_crashes_on_unwritable_base(tmp_path: Path):
    # base path lives *inside* a regular file → mkdir/open must fail and be swallowed
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    bad_base = blocker / "sub"
    _record(bad_base)  # must NOT raise
    assert load_events(bad_base) == []
