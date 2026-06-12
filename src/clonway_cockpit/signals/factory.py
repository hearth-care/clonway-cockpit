"""Sealed Signal construction for worker-owned emitters."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import date as Date
from typing import Any

from clonway_cockpit.signals.emit import emit_signals
from clonway_cockpit.signals.model import (
    _TITLE_KIND,
    SIGNAL_KINDS,
    Signal,
    _kind_for,
    dedup_key,
    urgency_from_due_at,
)
from clonway_cockpit.state import NeedsItem


class SignalIdentityError(ValueError):
    """Raised when a factory-bound emit path receives a different worker id."""


class UnknownSignalTitle(ValueError):
    """Raised in strict mode when a title has no registered kind mapping."""


_TRUTHY = {"1", "true", "yes", "on"}
_UNKNOWN_TITLES_SEEN: set[tuple[str, str]] = set()


def _strict_env_enabled() -> bool:
    return os.environ.get("CLONWAY_SIGNALS_STRICT_KINDS", "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class SignalFactory:
    worker_id: str
    flag_env: str
    title_kinds: Mapping[str, str] = field(default_factory=dict)
    strict_kinds: bool = False

    def make(
        self,
        *,
        title: str,
        detail: str,
        level: str,
        capability_key: str | None = None,
        focus: str | None = None,
        source_id: str | None = None,
        due_at: Date | None = None,
        now: datetime,
        kind: str | None = None,
        source_ref: str | None = None,
    ) -> Signal:
        resolved_kind = kind or self._kind_for(title)
        if resolved_kind not in SIGNAL_KINDS:
            raise ValueError(f"unknown signal kind: {resolved_kind!r}")
        return Signal(
            worker=self.worker_id,
            kind=resolved_kind,
            title=title,
            detail=detail,
            level=level,
            urgency=urgency_from_due_at(due_at, level, now),
            capability_key=capability_key,
            focus=focus,
            dedup_key=dedup_key(self.worker_id, title, capability_key, focus, source_id),
            emitted_at=now,
            due_at=due_at,
            source_ref=source_ref,
            source_id=source_id,
        )

    def from_needs(
        self,
        needs: tuple[NeedsItem, ...],
        *,
        now: datetime,
        source_ref: str | None = None,
    ) -> tuple[Signal, ...]:
        return tuple(
            self.make(
                title=n.title,
                detail=n.detail,
                level=n.level,
                capability_key=n.capability_key,
                focus=n.focus,
                source_id=n.source_id,
                due_at=n.due_at,
                now=now,
                source_ref=source_ref,
            )
            for n in needs
        )

    def _title_is_known(self, title: str) -> bool:
        return title in self.title_kinds or title in _TITLE_KIND

    def _kind_for(self, title: str) -> str:
        if title in self.title_kinds:
            return self.title_kinds[title]
        if title in _TITLE_KIND:
            return _kind_for(title)

        if self.strict_kinds or _strict_env_enabled():
            raise UnknownSignalTitle(f"unknown signal title: {title!r}")

        key = (self.worker_id, title)
        if key not in _UNKNOWN_TITLES_SEEN:
            _UNKNOWN_TITLES_SEEN.add(key)
            logging.getLogger(f"{self.worker_id}.signals").warning(
                "unknown signal title %r -> action.required", title
            )
        return "action.required"

    def emit(
        self,
        *,
        build: Callable[..., Sequence[Signal]],
        now: datetime | None = None,
        **kw: Any,
    ) -> tuple[Signal, ...]:
        def _build_checked(**build_kw: Any) -> tuple[Signal, ...]:
            signals = tuple(build(**build_kw))
            for signal in signals:
                if signal.worker != self.worker_id:
                    raise SignalIdentityError(
                        f"signal worker {signal.worker!r} does not match factory {self.worker_id!r}"
                    )
            return signals

        signals = emit_signals(
            worker_id=self.worker_id,
            flag_env=self.flag_env,
            build=_build_checked,
            now=now or datetime.now(UTC),
            **kw,
        )
        # Count signals that went through the fallback path (title unknown → action.required).
        # Signals with explicit kind= never add to _UNKNOWN_TITLES_SEEN, so they are excluded.
        unknown_title_kinds = sum(
            1 for signal in signals if (self.worker_id, signal.title) in _UNKNOWN_TITLES_SEEN
        )
        logging.getLogger(f"{self.worker_id}.signals").info(
            "signal emit complete unknown_title_kinds=%d", unknown_title_kinds
        )
        return signals
