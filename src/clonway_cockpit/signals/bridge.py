"""Handoff-failure → Signal bridge.

:func:`failure_to_signal` is the reference :attr:`NegotiatedSpace.on_handoff_failed`
callback. It converts a :class:`~clonway_cockpit.negotiation.HandoffFailure` into
an ``anomaly.detected`` Signal and emits it via the fleet's shared GCS sink, putting
the failure on the bus so any subscriber (the briefing today, a retry loop tomorrow)
can react programmatically.

The emitted signal carries ``source_id=task_id`` for stable per-task dedup across
restarts: the same failure is delivered at-most-once per consumer cursor window.

The bridge is a *soft* dependency on ``emit_signals`` — it never imports the
signal-hardening factory (if that plan is not yet merged, it builds the Signal
directly and calls ``emit_signals`` with ``build=lambda **_: (signal,)``).

``google-cloud-storage`` is NOT imported by default: the same lazy idiom as
``emit.py`` applies. Pass ``storage_client_factory`` in tests.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from clonway_cockpit.signals.emit import _BUCKET, emit_signals
from clonway_cockpit.signals.model import Signal, dedup_key

if TYPE_CHECKING:
    from clonway_cockpit.negotiation import HandoffFailure


def failure_to_signal(
    *,
    worker_id: str,
    flag_env: str,
    bucket: str = _BUCKET,
    storage_client_factory: Callable[[], Any] | None = None,
) -> Callable[[HandoffFailure], None]:
    """Return an ``on_handoff_failed`` callback that emits an ``anomaly.detected`` Signal.

    Wire it up once on the :class:`~clonway_cockpit.negotiation.NegotiatedSpace`::

        space = NegotiatedSpace(
            ...
            on_handoff_failed=failure_to_signal(
                worker_id=WORKER_ID,
                flag_env=EMIT_FLAG,
            ),
        )

    The emitted signal:

    - ``kind="anomaly.detected"``
    - ``title="Handoff failed"``
    - ``detail="{reason}: {summary}"``
    - ``source_id=task_id`` — stable per-task dedup key across restarts
    - ``urgency="due"`` — handoff failures need attention now
    - ``level="error"``

    The callback never raises; failures in ``emit_signals`` are swallowed by its
    own best-effort idiom (same as any other signal flush).
    """

    def _callback(failure: HandoffFailure) -> None:
        now = datetime.now(UTC)
        signal = Signal(
            worker=worker_id,
            kind="anomaly.detected",
            title="Handoff failed",
            detail=f"{failure.reason}: {failure.summary}",
            level="error",
            urgency="due",
            capability_key=None,
            focus=None,
            dedup_key=dedup_key(worker_id, "Handoff failed", None, None, failure.task_id),
            emitted_at=now,
            source_id=failure.task_id,
        )

        def _build(**_: Any) -> tuple[Signal, ...]:
            return (signal,)

        emit_signals(
            worker_id=worker_id,
            flag_env=flag_env,
            build=_build,
            bucket=bucket,
            now=now,
            storage_client_factory=storage_client_factory,
        )

    return _callback
