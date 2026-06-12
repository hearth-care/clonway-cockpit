"""Framework-level fleet audit log.

This is an operational ledger for framework chokepoints, not a worker domain
audit trail, a metrics system, or a tamper-evident store. The event schema is a
structural privacy whitelist: there is no payload/detail/free-text field where
domain content can be represented.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from datetime import date as Date
from pathlib import Path
from typing import Any

from clonway_cockpit.obs import _BUCKET, _QUIET_ERROR_NAMES, resolve_run_id

AUDIT_SCHEMA = "audit/1"
EVENTS = frozenset(
    {
        "capability.launched",
        "gate.offered",
        "gate.applied",
        "gate.declined",
        "reflex.approved",
        "reflex.refused",
        "approval.routed",
        "approval.resolved",
    }
)
ACTORS = frozenset({"human", "agent", "reflex", "policy"})
_TRUTHY = {"1", "true", "yes", "on"}

AuditSink = Callable[["AuditEvent"], None]
StorageClientFactory = Callable[[], Any]


@dataclass(frozen=True)
class AuditEvent:
    ts: datetime
    worker: str
    run_id: str | None
    event: str
    capability_key: str | None
    actor: str
    dry_run: bool
    money_movement: bool
    outcome: str | None
    equivalent_cli: str | None
    focus: str | None
    ref: str | None

    def __post_init__(self) -> None:
        if self.event not in EVENTS:
            raise ValueError(f"unknown audit event {self.event!r}")
        if self.actor not in ACTORS:
            raise ValueError(f"unknown audit actor {self.actor!r}")
        if self.ts.tzinfo is None:
            object.__setattr__(self, "ts", self.ts.replace(tzinfo=UTC))
        else:
            object.__setattr__(self, "ts", self.ts.astimezone(UTC))

    def to_wire(self) -> dict[str, object]:
        wire = asdict(self)
        wire["schema"] = AUDIT_SCHEMA
        wire["ts"] = self.ts.isoformat()
        return wire

    @classmethod
    def from_wire(cls, wire: dict[str, object]) -> "AuditEvent":
        if wire.get("schema") != AUDIT_SCHEMA:
            raise ValueError(f"unknown audit schema {wire.get('schema')!r}")
        fields = dict(wire)
        fields.pop("schema", None)
        ts = fields.get("ts")
        if not isinstance(ts, str):
            raise ValueError("audit event requires string ts")
        fields["ts"] = datetime.fromisoformat(ts)
        return cls(**fields)  # type: ignore[arg-type]


def _gcs_enabled(worker_id: str) -> bool:
    names = (
        f"{worker_id.upper().replace('-', '_')}_AUDIT_GCS",
        "CLONWAY_AUDIT_GCS",
    )
    return any(os.environ.get(name, "").strip().lower() in _TRUTHY for name in names)


def _import_storage() -> Any:
    from google.cloud import storage

    return storage


def _default_factory() -> StorageClientFactory:
    def factory() -> Any:
        return _import_storage().Client()

    return factory


class _LocalJsonlAuditSink:
    def __init__(
        self,
        worker_id: str,
        *,
        base_dir: Path,
        bucket: str,
        gcs: bool,
        storage_client_factory: StorageClientFactory | None,
        flush_every: int,
        logger: logging.Logger,
    ) -> None:
        self.worker_id = worker_id
        self.base_dir = base_dir
        self.bucket = bucket
        self.gcs = gcs
        self.storage_client_factory = storage_client_factory or _default_factory()
        self.flush_every = flush_every
        self.log = logger
        self._by_path: dict[str, list[dict[str, object]]] = {}
        self._since_flush = 0
        atexit.register(self.flush)

    def __call__(self, event: AuditEvent) -> None:
        try:
            wire = event.to_wire()
            self._append_local(event, wire)
            if self.gcs:
                self._remember_for_gcs(event, wire)
        except Exception:  # noqa: BLE001 - audit must never break observed work
            self.log.exception("audit sink failed")

    def _append_local(self, event: AuditEvent, wire: dict[str, object]) -> None:
        path = self.base_dir / f"{event.ts.date().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(wire, separators=(",", ":")) + "\n")

    def _remember_for_gcs(self, event: AuditEvent, wire: dict[str, object]) -> None:
        rid = resolve_run_id(event.run_id) if event.run_id else uuid.uuid4().hex
        key = f"audit/{event.worker}/{event.ts.date().isoformat()}/{rid}.jsonl"
        self._by_path.setdefault(key, []).append(wire)
        self._since_flush += 1
        if self._since_flush >= self.flush_every:
            self.flush()

    def flush(self) -> bool:
        if not self.gcs or not self._by_path:
            return True
        try:
            bucket = self.storage_client_factory().bucket(self.bucket)
            for path, records in self._by_path.items():
                body = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in records)
                bucket.blob(path).upload_from_string(body, content_type="application/x-ndjson")
            self._since_flush = 0
            return True
        except Exception as exc:  # noqa: BLE001 - best-effort mirror
            if type(exc).__name__ in _QUIET_ERROR_NAMES:
                self.log.debug("audit GCS flush skipped (%s)", type(exc).__name__)
            else:
                self.log.exception("audit GCS flush failed")
            return False


def make_audit_sink(
    worker_id: str,
    *,
    base_dir: Path | None = None,
    bucket: str = _BUCKET,
    gcs: bool | None = None,
    storage_client_factory: StorageClientFactory | None = None,
    now: Callable[[], datetime] | None = None,
) -> AuditSink:
    """Return a never-raising append-only audit sink for one worker."""
    del now  # Reserved for future event-factory helpers; events carry their own timestamp today.
    return _LocalJsonlAuditSink(
        worker_id,
        base_dir=base_dir or Path(f".{worker_id}") / "audit",
        bucket=bucket,
        gcs=_gcs_enabled(worker_id) if gcs is None else gcs,
        storage_client_factory=storage_client_factory,
        flush_every=20,
        logger=logging.getLogger(f"{worker_id}.audit"),
    )


def read_events(base_dir: Path, *, since: Date | None = None) -> Iterator[AuditEvent]:
    """Read local audit JSONL files in date order."""
    for path in sorted(base_dir.glob("*.jsonl")):
        if since is not None and path.stem < since.isoformat():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield AuditEvent.from_wire(json.loads(line))
