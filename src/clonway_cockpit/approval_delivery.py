"""Transport-neutral approval request artifacts for guarded cockpit writes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ApprovalRequestError(ValueError):
    """A gate frame could not be converted into an approval request."""


def _non_empty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalRequestError(f"approval request requires non-empty {field}")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _meta_from_gate(gate: Mapping[str, object]) -> Mapping[str, object]:
    if gate.get("kind") == "walk.gate":
        meta = gate.get("meta")
        if not isinstance(meta, Mapping):
            raise ApprovalRequestError("walk.gate frame requires meta mapping")
        return meta
    if "kind" in gate:
        raise ApprovalRequestError("approval request requires a walk.gate frame")
    return gate


@dataclass(frozen=True)
class ApprovalRequest:
    token: str
    equivalent_cli: str
    proposal: Mapping[str, object]
    capability_key: str | None = None
    money_movement: bool | None = None
    worker: str | None = None
    intent: str | None = None
    title: str | None = None
    summary: str | None = None

    @classmethod
    def from_gate(cls, gate: Mapping[str, object]) -> ApprovalRequest:
        meta = _meta_from_gate(gate)
        if meta.get("gate") != "awaiting_apply":
            raise ApprovalRequestError("approval request requires gate='awaiting_apply'")
        token = _non_empty_str(meta.get("token"), "token")
        equivalent_cli = _non_empty_str(meta.get("equivalent_cli"), "equivalent_cli")
        money = meta.get("money_movement")
        if money is not None and not isinstance(money, bool):
            raise ApprovalRequestError("money_movement must be a bool when present")
        proposal = dict(meta)
        proposal["token"] = token
        proposal["equivalent_cli"] = equivalent_cli
        return cls(
            token=token,
            equivalent_cli=equivalent_cli,
            proposal=proposal,
            capability_key=_optional_str(meta.get("capability_key")),
            money_movement=money,
            worker=_optional_str(meta.get("worker")),
            intent=_optional_str(meta.get("intent")),
            title=_optional_str(meta.get("title")),
            summary=_optional_str(meta.get("summary")),
        )
