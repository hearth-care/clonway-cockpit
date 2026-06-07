"""The conversational operator — a framework-owned, fleet-wide layer for driving any worker by
message. A verified operator DMs ("draft this week's bills"); the conversation routes the
command to the right worker and drives it over the agent channel (``CockpitClient``). Every
worker inherits this; the safety + session model is defined ONCE here, not per worker.

**THE TRUST BOUNDARY (first-class).** A message carries a ``source``: ``OPERATOR`` (a command
from the verified operator) or ``QUOTED`` (content forwarded/quoted from someone else — DATA).
**Only an operator message is ever a command; quoted content can never trigger an action.**
This is the confused-deputy / payroll-fraud guard at the conversation boundary — the reason
this lives at the platform level.

**Model-agnostic by construction.** The framework provides the session, the trust enforcement,
the execution (drive the worker, route the write gate to the approver, narrate). The LLM
(``Router``), the worker launcher (``Launcher``), and the write-gate decision (``ApprovalPolicy``)
are INJECTED — kept out of the framework core.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from clonway_cockpit.agent import CockpitClient, CockpitClosed
from clonway_cockpit.approval import deny_all

OPERATOR = "operator"  # a command from the verified operator
QUOTED = "quoted"  # content quoted/forwarded from someone else — DATA, never a command


@dataclass(frozen=True)
class Message:
    """One inbound message. ``source`` is the trust label. It defaults to ``QUOTED`` — the
    FAIL-SAFE default: a transport must EXPLICITLY mark a message ``source=OPERATOR`` for it to
    be treated as a command. Anything left unmarked (forwarded/excerpted content) is data and is
    never executed — a transport that forgets to classify can only *under*-trust, never
    over-trust."""

    text: str
    source: str = QUOTED


@dataclass(frozen=True)
class Plan:
    """A router's decision: drive ``worker`` (a roster codename) with ``script`` (a key
    sequence). ``intent`` is a short human label for the narration."""

    worker: str
    script: tuple[str, ...] = ()
    intent: str = ""


@dataclass
class Reply:
    text: str
    acted: bool
    frames: list = field(default_factory=list)


# A Router maps an operator Message → a Plan (or None for 'no actionable command'). The LLM
# lives here, injected — the framework stays model-agnostic.
Router = Callable[[Message], "Plan | None"]
# A Launcher maps a worker codename → its --agent-stdio argv (or None if not drivable).
Launcher = Callable[[str], "list[str] | None"]


def _drive_argv(argv, script, *, approve) -> list:  # noqa: ANN001
    """The platform's default driver: spawn the worker over the agent channel and play
    ``script``, routing any ``walk.gate{awaiting_apply}`` to ``approve`` (the human-sign-off /
    autonomous policy). Robust like ``xops.drive.drive_argv`` — guards a worker that fails to
    start and a tokenless gate — but framework-owned + worker-agnostic."""
    frames: list = []
    with CockpitClient.spawn(list(argv)) as c:
        try:
            frames.append(c.read_home())
        except CockpitClosed:
            return frames
        for key in script:
            try:
                frame = c.press(key)
            except CockpitClosed:
                break
            frames.append(frame)
            meta = frame.get("meta") or {}
            if frame.get("kind") == "walk.gate" and meta.get("gate") == "awaiting_apply":
                token = meta.get("token")
                if token is not None:
                    try:
                        frames.append(c.apply(token, approve=approve, proposal=meta))
                    except CockpitClosed:
                        break
            frames.extend(c.drain())
    return frames


class Conversation:
    """Route an operator's message to a worker and drive it. Construct with the injected seams;
    call :meth:`handle` per inbound message."""

    def __init__(
        self,
        *,
        router: Router,
        launch: Launcher,
        approve=deny_all,  # noqa: ANN001 — ApprovalPolicy
        drive: Callable[..., list] | None = None,
    ) -> None:
        self._router = router
        self._launch = launch
        self._approve = approve
        self._drive = drive or _drive_argv

    def handle(self, message: Message) -> Reply:
        # TRUST BOUNDARY — only an operator message is a command. Quoted/observed content is data
        # and is NEVER routed to an action (the confused-deputy / fraud guard).
        if message.source != OPERATOR:
            return Reply(
                "Ignored — quoted/observed content is never run as a command.", acted=False
            )
        plan = self._router(message)
        if plan is None:
            return Reply("No actionable command found.", acted=False)
        argv = self._launch(plan.worker)
        if argv is None:
            return Reply(f"Worker {plan.worker!r} is not drivable.", acted=False)
        try:
            frames = self._drive(argv, plan.script, approve=self._approve)
        except CockpitClosed as e:  # pragma: no cover — driver guards this; belt-and-braces
            return Reply(f"Drive of {plan.worker} ended early: {e}", acted=False)
        if not frames:
            # The worker never painted a frame (failed to start / died at EOF). Driving it was a
            # no-op — report that honestly rather than claiming we drove it.
            return Reply(f"Could not reach {plan.worker} — it did not start.", acted=False)
        return Reply(self._narrate(plan, frames), acted=True, frames=frames)

    @staticmethod
    def _narrate(plan: Plan, frames: list) -> str:
        def _status(s: str) -> int:
            return sum(
                1
                for f in frames
                if isinstance(f, Mapping)
                and f.get("kind") == "walk.gate"
                and f.get("meta", {}).get("status") == s
            )

        last = frames[-1] if frames else {}
        bits = [f"Drove {plan.worker}" + (f" — {plan.intent}" if plan.intent else "") + "."]
        if _status("applied"):
            bits.append(f"Applied {_status('applied')} change(s).")
        if _status("declined"):
            bits.append(f"Declined {_status('declined')} (not authorized).")
        if isinstance(last, Mapping) and last.get("kind"):
            bits.append(f"Now on: {last.get('kind')}.")
        return " ".join(bits)


__all__ = ["OPERATOR", "QUOTED", "Message", "Plan", "Reply", "Router", "Launcher", "Conversation"]
