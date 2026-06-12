"""CC-NEG-FAIL-* — HandoffFailure callback + failure_to_signal bridge tests.

Verifies:
- on_handoff_failed=None preserves existing negotiation behaviour (parity).
- Each of the four failure reasons fires with the correct fields.
- A raising callback is swallowed and does not corrupt ledger state.
- failure_to_signal emits an anomaly.detected Signal with source_id=task_id.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from clonway_cockpit.colleague import Colleague, ColleagueRegistry
from clonway_cockpit.gateway.types import Message
from clonway_cockpit.group_chat import ChatMessage, FakeChatTransport
from clonway_cockpit.handoff import (
    AskDecision,
    ClaimedFact,
    HandoffEnvelope,
    parse_envelope,
    render_envelope,
)
from clonway_cockpit.negotiation import (
    HandoffFailure,
    NegotiatedSpace,
    negotiating_responder,
)
from clonway_cockpit.persona import Persona
from clonway_cockpit.private_memory import PersonaMemory
from clonway_cockpit.reflex import ReflexBank, ReflexKit, ReflexLog, ReflexPolicy, ReflexRule
from clonway_cockpit.signals.bridge import failure_to_signal

HOLD_ASK = "@milo — hold June payroll for employee 402"
LETTER_ASK = "write to employee 402 requesting evidence"
SPACE = "spaces/FAIL-TEST"


# ---------------------------------------------------------------------------
# Shared fixtures (mirrors test_negotiation_drive.py style)
# ---------------------------------------------------------------------------


def make_colleagues() -> ColleagueRegistry:
    cols = {}
    for handle, name, domain in (
        ("vera", "Vera Hartley", "HR, right-to-work and compliance"),
        ("milo", "Milo Garth", "the books, payroll and cash"),
        ("quill", "Quill Page", "the diary, letters and correspondence"),
    ):
        persona = Persona.from_dict({"handle": handle, "name": name, "domain": domain})
        cols[handle] = Colleague(persona=persona, soul=f"You are {name} — brisk and kind.")
    return ColleagueRegistry(colleagues=cols)


def make_notice(**over) -> HandoffEnvelope:
    base = dict(
        kind="notice",
        task_id="rtw-402",
        origin="vera",
        recipient="milo",
        summary="right-to-work failed for employee 402",
        facts=(
            ClaimedFact(
                text="RTW check failed — employee 402",
                claimant="vera",
                provenance="xhr:rtw-checks/RTW-2026-0142",
            ),
        ),
        asks=(HOLD_ASK, LETTER_ASK),
    )
    base.update(over)
    return HandoffEnvelope(**base)


def agent_msg(text: str, author: str) -> ChatMessage:
    return ChatMessage.from_text(text, author=author, is_owner=False, space=SPACE)


class FakeCompleter:
    def __init__(self, results: list) -> None:
        self.results = list(results)

    def complete_structured(self, messages: list[Message], schema: dict, *, role: str) -> dict:
        return self.results.pop(0)


def build_space(
    tmp_path: Path,
    completer,
    *,
    kits=None,
    on_handoff_failed=None,
) -> tuple[ColleagueRegistry, FakeChatTransport, NegotiatedSpace]:
    colleagues = make_colleagues()
    responder = negotiating_responder(
        lambda persona, message: None,
        colleagues,
        completer,
        role="negotiate",
        memory_base=tmp_path,
        reflex_kits=kits,
    )
    transport = FakeChatTransport()
    space = NegotiatedSpace(
        space_id=SPACE,
        registry=colleagues.registry,
        transport=transport,
        responder=responder,
        owner_line="Mr Page",
        on_handoff_failed=on_handoff_failed,
    )
    return colleagues, transport, space


# ---------------------------------------------------------------------------
# Parity: callback=None must not change existing behaviour
# ---------------------------------------------------------------------------


def test_parity_stall_no_callback(tmp_path: Path) -> None:  # CC-NEG-FAIL-PAR-1
    """on_handoff_failed=None: stall text posts exactly once, nothing raises."""
    _, transport, space = build_space(tmp_path, FakeCompleter([]))
    space.post_notice("vera", make_notice(recipient="vera"))  # nobody to respond → stall
    texts = [text for _, text in transport.posted]
    assert len(texts) == 1
    assert "unresolved handoff #rtw-402" in texts[0]


def test_parity_full_negotiation_no_callback(tmp_path: Path) -> None:  # CC-NEG-FAIL-PAR-2
    """Full accept/decline/redirect cycle works without a callback wired."""
    # Milo responds first; quill receives the redirect and also responds.
    completer = FakeCompleter(
        [
            {
                "say": "on it",
                "decisions": [
                    {"ask": HOLD_ASK, "decision": "accept"},
                    {"ask": LETTER_ASK, "decision": "decline", "redirect": "quill"},
                ],
            },
            {
                "say": "will write",
                "decisions": [{"ask": LETTER_ASK, "decision": "accept"}],
            },
        ]
    )
    _, transport, space = build_space(tmp_path, completer)
    space.post_notice("vera", make_notice())
    texts = [text for _, text in transport.posted]
    # A response was posted; the plan (with unassigned redirect) was also posted
    assert any(parse_envelope(t) is not None for t in texts)


# ---------------------------------------------------------------------------
# reason="stalled"
# ---------------------------------------------------------------------------


def test_callback_stalled_fires(tmp_path: Path) -> None:  # CC-NEG-FAIL-STALL-1
    fired: list[HandoffFailure] = []
    _, transport, space = build_space(tmp_path, FakeCompleter([]), on_handoff_failed=fired.append)
    space.post_notice("vera", make_notice(recipient="vera"))
    assert len(fired) == 1
    f = fired[0]
    assert f.task_id == "rtw-402"
    assert f.initiator == "vera"
    assert f.counterparty is None
    assert f.reason == "stalled"
    assert isinstance(f.occurred_at, datetime)


def test_callback_stalled_fires_once(tmp_path: Path) -> None:  # CC-NEG-FAIL-STALL-2
    """mark_stalled prevents a second stall sweep → callback fires exactly once."""
    fired: list[HandoffFailure] = []
    _, transport, space = build_space(tmp_path, FakeCompleter([]), on_handoff_failed=fired.append)
    space.post_notice("vera", make_notice(recipient="vera"))
    # Re-drive the sweep by sending another message; stall is already marked
    space.owner_says("any message")
    assert len(fired) == 1  # still only once


# ---------------------------------------------------------------------------
# reason="declined"
# ---------------------------------------------------------------------------


def test_callback_declined_fires(tmp_path: Path) -> None:  # CC-NEG-FAIL-DEC-1
    """Bare decline (no redirect) → reason='declined', counterparty=milo."""
    fired: list[HandoffFailure] = []
    completer = FakeCompleter(
        [
            {
                "say": "can't help",
                "decisions": [
                    {"ask": HOLD_ASK, "decision": "decline"},  # bare decline
                    {"ask": LETTER_ASK, "decision": "defer"},
                ],
            }
        ]
    )
    _, transport, space = build_space(tmp_path, completer, on_handoff_failed=fired.append)
    space.post_notice("vera", make_notice())
    declined = [f for f in fired if f.reason == "declined"]
    assert len(declined) == 1
    assert declined[0].task_id == "rtw-402"
    assert declined[0].initiator == "vera"
    assert declined[0].counterparty == "milo"
    assert declined[0].summary == HOLD_ASK[:80]


def test_pending_failures_drained_without_callback(tmp_path: Path) -> None:  # CC-NEG-FAIL-DEC-3
    """With on_handoff_failed=None the ledger's pending-failure buffer is still
    drained each sweep, so it cannot grow unbounded for the space's lifetime."""
    completer = FakeCompleter(
        [
            {
                "say": "can't help",
                "decisions": [
                    {"ask": HOLD_ASK, "decision": "decline"},
                    {"ask": LETTER_ASK, "decision": "defer"},
                ],
            }
        ]
    )
    _, _, space = build_space(tmp_path, completer, on_handoff_failed=None)
    space.post_notice("vera", make_notice())
    # The declined ask produced a failure record, but the sweep drained it even
    # though no callback was registered — consume_failures returns nothing left.
    assert space.ledger.consume_failures() == []


def test_callback_declined_not_fired_for_redirect(tmp_path: Path) -> None:  # CC-NEG-FAIL-DEC-2
    """A decline WITH a valid redirect is a redirect, not a failure → no declined callback."""
    fired: list[HandoffFailure] = []
    completer = FakeCompleter(
        [
            {
                "say": "quill handles letters",
                "decisions": [
                    {"ask": HOLD_ASK, "decision": "accept"},
                    {"ask": LETTER_ASK, "decision": "decline", "redirect": "quill"},
                ],
            },
            # Quill receives the redirected ask and accepts it.
            {
                "say": "will write",
                "decisions": [{"ask": LETTER_ASK, "decision": "accept"}],
            },
        ]
    )
    _, transport, space = build_space(tmp_path, completer, on_handoff_failed=fired.append)
    space.post_notice("vera", make_notice())
    assert not any(f.reason == "declined" for f in fired)


# ---------------------------------------------------------------------------
# reason="parse_failed"
# ---------------------------------------------------------------------------


def test_callback_parse_failed_fires(tmp_path: Path) -> None:  # CC-NEG-FAIL-PARSE-1
    """A response envelope attributed to an open task but with origin≠author fires parse_failed."""
    fired: list[HandoffFailure] = []
    completer = FakeCompleter([])
    _, transport, space = build_space(tmp_path, completer, on_handoff_failed=fired.append)

    # Post the notice legitimately (vera posts to herself so nobody responds → no sweep stall yet)
    space.ledger.feed(agent_msg(render_envelope(make_notice()), "vera"))

    # Now simulate a response whose origin field says "milo" but the transport author is "quill"
    forged_response = HandoffEnvelope(
        kind="response",
        task_id="rtw-402",
        origin="milo",  # claimed origin
        recipient="vera",
        summary="re: rtw",
        decisions=(AskDecision(ask=HOLD_ASK, decision="accept"),),
    )
    # Feed directly into the ledger as if it arrived from "quill" (origin mismatch)
    space.ledger.feed(agent_msg(render_envelope(forged_response), "quill"))

    failures = space.ledger.consume_failures()
    assert len(failures) == 1
    assert failures[0].reason == "parse_failed"
    assert failures[0].task_id == "rtw-402"
    assert failures[0].initiator == "vera"
    assert failures[0].counterparty == "quill"


# ---------------------------------------------------------------------------
# reason="reflex_refused"
# ---------------------------------------------------------------------------


def _refused_reflex_kit(tmp_path: Path, handle: str) -> ReflexKit:
    def hold_matcher(env: HandoffEnvelope) -> str | None:
        for ask in env.asks:
            if "hold" in ask and "payroll" in ask:
                return ask
        return None

    bank = ReflexBank()
    bank.register(
        ReflexRule(
            capability_key="payroll.hold",
            description="hold a payroll run",
            matcher=hold_matcher,
            run=lambda proposal: False,  # always refuse
        )
    )
    log = ReflexLog(PersonaMemory(tmp_path, handle))
    return ReflexKit(bank=bank, policy=ReflexPolicy(bank.keys(), log), log=log)


def test_callback_reflex_refused_fires(tmp_path: Path) -> None:  # CC-NEG-FAIL-REFLEX-1
    """A reflex that matches but refuses (run()=False) → reason='reflex_refused'."""
    fired: list[HandoffFailure] = []
    # The model still needs to handle LETTER_ASK (HOLD_ASK is fired by the reflex but refused)
    completer = FakeCompleter(
        [
            {
                "say": "working on it",
                "decisions": [
                    {"ask": LETTER_ASK, "decision": "accept"},
                ],
            }
        ]
    )
    kit = _refused_reflex_kit(tmp_path, "milo")
    _, transport, space = build_space(
        tmp_path,
        completer,
        kits={"milo": kit},
        on_handoff_failed=fired.append,
    )
    space.post_notice("vera", make_notice())
    refused = [f for f in fired if f.reason == "reflex_refused"]
    assert len(refused) == 1
    assert refused[0].task_id == "rtw-402"
    assert refused[0].initiator == "vera"
    assert refused[0].counterparty == "milo"


# ---------------------------------------------------------------------------
# Raising callback is swallowed, ledger state unaffected
# ---------------------------------------------------------------------------


def test_raising_callback_is_swallowed(tmp_path: Path) -> None:  # CC-NEG-FAIL-ERR-1
    """A callback that raises must not propagate or corrupt ledger state."""

    def _boom(f: HandoffFailure) -> None:
        raise RuntimeError("observer exploded")

    _, transport, space = build_space(tmp_path, FakeCompleter([]), on_handoff_failed=_boom)
    # The stall path fires the callback; it must not surface
    space.post_notice("vera", make_notice(recipient="vera"))
    # Stall text was still posted despite the callback exploding
    texts = [text for _, text in transport.posted]
    assert any("unresolved handoff" in t for t in texts)
    # Ledger state: stall is marked (no double-stall)
    assert space.ledger.is_stalled("rtw-402")


# ---------------------------------------------------------------------------
# failure_to_signal bridge
# ---------------------------------------------------------------------------


class _FakeBlob:
    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self.name = name

    def upload_from_string(self, body: str, **kwargs) -> None:
        self._store[self.name] = body


class _FakeBucket:
    def __init__(self, store: dict) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)


class _FakeClient:
    def __init__(self) -> None:
        self._store: dict = {}

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)


def _make_failure(reason: str = "stalled", task_id: str = "rtw-402") -> HandoffFailure:
    return HandoffFailure(
        task_id=task_id,
        initiator="vera",
        counterparty=None,
        reason=reason,
        summary="1 ask(s) unresolved",
        occurred_at=datetime(2026, 6, 12, 9, 0, tzinfo=UTC),
    )


def test_bridge_emits_anomaly_detected(monkeypatch) -> None:  # CC-NEG-FAIL-BRIDGE-1
    monkeypatch.setenv("XHR_EMIT_SIGNALS", "1")
    client = _FakeClient()
    cb = failure_to_signal(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        bucket="test-bucket",
        storage_client_factory=lambda: client,
    )
    cb(_make_failure())
    archive_keys = [k for k in client._store if "/2026" in k and k.endswith(".jsonl")]
    assert len(archive_keys) == 1
    line = client._store[archive_keys[0]].strip()
    wire = json.loads(line)
    assert wire["kind"] == "anomaly.detected"
    assert wire["title"] == "Handoff failed"
    assert wire["worker"] == "xhr"
    assert wire["level"] == "error"
    assert wire["urgency"] == "due"


def test_bridge_source_id_equals_task_id(monkeypatch) -> None:  # CC-NEG-FAIL-BRIDGE-2
    """source_id=task_id is the stable dedup key per task."""
    monkeypatch.setenv("XHR_EMIT_SIGNALS", "1")
    client = _FakeClient()
    cb = failure_to_signal(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        bucket="test-bucket",
        storage_client_factory=lambda: client,
    )
    cb(_make_failure(task_id="rtw-999"))
    archive_keys = [k for k in client._store if "/2026" in k and k.endswith(".jsonl")]
    wire = json.loads(client._store[archive_keys[0]].strip())
    assert wire["source_id"] == "rtw-999"


def test_bridge_detail_contains_reason_and_summary(monkeypatch) -> None:  # CC-NEG-FAIL-BRIDGE-3
    monkeypatch.setenv("XHR_EMIT_SIGNALS", "1")
    client = _FakeClient()
    cb = failure_to_signal(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        bucket="test-bucket",
        storage_client_factory=lambda: client,
    )
    failure = _make_failure(reason="declined")
    cb(failure)
    archive_keys = [k for k in client._store if "/2026" in k and k.endswith(".jsonl")]
    wire = json.loads(client._store[archive_keys[0]].strip())
    assert "declined" in wire["detail"]
    assert failure.summary in wire["detail"]


def test_bridge_flag_off_does_not_emit(monkeypatch) -> None:  # CC-NEG-FAIL-BRIDGE-4
    """When the flag is off, failure_to_signal is a no-op."""
    monkeypatch.delenv("XHR_EMIT_SIGNALS", raising=False)
    client = _FakeClient()
    cb = failure_to_signal(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        bucket="test-bucket",
        storage_client_factory=lambda: client,
    )
    cb(_make_failure())
    assert client._store == {}


def test_bridge_dedup_key_stable_across_calls(monkeypatch) -> None:  # CC-NEG-FAIL-BRIDGE-5
    """Same task_id → same dedup_key on every call (stable per-task dedup)."""
    monkeypatch.setenv("XHR_EMIT_SIGNALS", "1")

    def _emit_once(task_id: str) -> str:
        client = _FakeClient()
        cb = failure_to_signal(
            worker_id="xhr",
            flag_env="XHR_EMIT_SIGNALS",
            bucket="test-bucket",
            storage_client_factory=lambda: client,
        )
        cb(_make_failure(task_id=task_id))
        keys = [k for k in client._store if "/2026" in k]
        return json.loads(client._store[keys[0]].strip())["dedup_key"]

    dk1 = _emit_once("rtw-402")
    dk2 = _emit_once("rtw-402")
    dk3 = _emit_once("rtw-999")  # different task
    assert dk1 == dk2
    assert dk1 != dk3
