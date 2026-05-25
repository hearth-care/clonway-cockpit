"""The walk machine — the frozen contract every guided walk builds against.

A walk runs: explain -> preconditions -> review -> apply (gated) -> summarise.
Each screen draws ONE framed renderable and reads ONE key (the redraw-in-place
cockpit model): ``_present`` routes to ``screen.update`` when the context is
bound to the alternate screen, falling back to ``console.print`` for console
callers/tests. ``preflight()`` renders what-it-does / blast-radius /
preconditions / equivalent-CLI and blocks if any precondition fails.
``confirm_apply()`` is the ONLY write gate — a walk MUST route every irreversible
action through it (no silent --confirm). ``make_walk_handler()`` returns a
``CapabilitySpec.run`` callable so walks plug into the catalog without changing
``CapabilitySpec``."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from rich.console import RenderableType

from clonway_cockpit import keys, render
from clonway_cockpit.registry import BlastRadius, Handler, WizardContext

# How long the loop sleeps between progress frames — ~8 redraws/second, fast
# enough that the spinner reads as motion, slow enough not to thrash the screen.
_PROGRESS_TICK = 0.12


def animate_until_done[T](
    present: Callable[[RenderableType], None],
    label: str,
    fn: Callable[[], T],
    *,
    tick: float = _PROGRESS_TICK,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run a blocking ``fn`` (a sync) in a worker thread while animating the
    screen via ``present`` (``screen.update`` for the cockpit, ``ctx.present``
    for a walk step), so a long pull is visibly alive (spinner + elapsed
    seconds) instead of a frozen panel. Returns ``fn``'s value; if ``fn`` raised,
    re-raises that exception after the loop so the caller's existing
    result/error screens still work. ``clock``/``sleep`` are injectable so the
    loop is unit-testable without real time.

    Lives in ``walk`` (not ``app``) so the sync-all walk can reuse it without an
    ``app`` import cycle."""
    holder: dict[str, object] = {}

    def _worker() -> None:
        try:
            holder["value"] = fn()
        except BaseException as e:  # noqa: BLE001 — captured and re-raised on the main thread
            holder["error"] = e

    thread = threading.Thread(target=_worker, daemon=True)
    started = clock()
    thread.start()
    i = 0
    # Draw at least one animated frame before the first join so even an instant
    # fn shows the progress screen once (and a slow fn animates every tick).
    while True:
        frame = render.SPINNER_FRAMES[i % len(render.SPINNER_FRAMES)]
        elapsed = int(clock() - started)
        present(render.render_sync_progress(label, frame, elapsed))
        i += 1
        thread.join(timeout=tick)
        if not thread.is_alive():
            break
        sleep(tick)

    if "error" in holder:
        raise holder["error"]  # type: ignore[misc]
    return holder["value"]  # type: ignore[return-value]


@dataclass(frozen=True)
class StepResult:
    ok: bool
    message: str = ""
    data: dict = field(default_factory=dict)  # merged into the shared bag for later steps


@dataclass(frozen=True)
class Remedy:
    """An inline fix the pre-flight can offer for a BLOCKED precondition.

    ``key`` is the single keystroke that triggers it (e.g. ``"u"``); ``label``
    is the human verb shown in the footer ("clear the stale apply lock");
    ``action`` performs the fix and returns a result message. The pre-flight
    runs it behind a one-key confirm, then re-evaluates the preconditions so the
    operator sees the row clear and can continue — it never bypasses the write
    gate (the remedy fixes a precondition, it does not post to Xero)."""

    key: str
    label: str
    action: Callable[[], str]


@dataclass(frozen=True)
class Precondition:
    label: str
    ok: bool
    detail: str = ""
    remedy: Remedy | None = None


@dataclass(frozen=True)
class Step:
    label: str
    run: Callable[[WizardContext, dict], StepResult]


def _present(ctx: WizardContext, renderable: RenderableType) -> None:
    """Draw one full screen via the cockpit's ``screen.update`` when bound, else
    fall back to ``console.print`` (console-mode callers / tests)."""
    (ctx.present or ctx.console.print)(renderable)


def _await(ctx: WizardContext) -> None:
    """Let the operator read a terminal screen before returning (cockpit only)."""
    if ctx.read_key is not None:
        ctx.read_key()


def _first_blocked_remedy(preconditions: list[Precondition]) -> Remedy | None:
    """The remedy on the first blocked precondition that carries one, if any."""
    for p in preconditions:
        if not p.ok and p.remedy is not None:
            return p.remedy
    return None


def preflight(
    ctx: WizardContext,
    *,
    title: str,
    blast_radius: BlastRadius,
    preconditions: list[Precondition],
    equivalent_cli: str,
    progress: str = "",
    recheck: Callable[[], list[Precondition]] | None = None,
) -> bool:
    """explain -> blast-radius -> preconditions -> equivalent CLI. Returns True
    iff the operator continues; returns False immediately if any precondition
    is red AND no inline remedy is offered/taken.

    ``progress`` is an optional ``step N of M`` prefix for the header hint
    (e.g. ``"step 1 of 2"``). When set the hint reads ``step N of M · ‹esc› cancel``.

    ``recheck`` re-evaluates the preconditions after an inline remedy runs (the
    cockpit passes ``lambda: preconditions_fn(ctx)``). When a blocked precondition
    carries a ``Remedy``, the footer offers its one-key hint; pressing that key
    confirms (one key) → runs the remedy → re-checks → redraws, so the operator
    can fix a false-positive (e.g. a stale apply lock) and continue without
    leaving the screen. Any other key returns False (back to the cockpit), the
    pre-remedy behaviour. The remedy never posts to Xero — it only clears a
    precondition; the write gate is still the only place a walk mutates."""
    ready = all(p.ok for p in preconditions)
    remedy = None if ready else _first_blocked_remedy(preconditions)
    _present(
        ctx,
        render.render_preflight(
            title=title,
            blast_radius=blast_radius,
            preconditions=preconditions,
            equivalent_cli=equivalent_cli,
            progress=progress,
            ready=ready,
            remedy=remedy,
        ),
    )
    if not ready:
        if remedy is not None and ctx.read_key is not None:
            k = ctx.read_key()
            if k == remedy.key:
                # One-key confirm, then run the remedy and re-evaluate so the
                # operator sees the row clear and continues from the same screen.
                _present(ctx, render.render_remedy_confirm(remedy))
                if ctx.read_key() in (keys.ENTER, "y", "Y"):
                    remedy.action()
                    rechecked = recheck() if recheck is not None else preconditions
                    return preflight(
                        ctx,
                        title=title,
                        blast_radius=blast_radius,
                        preconditions=rechecked,
                        equivalent_cli=equivalent_cli,
                        progress=progress,
                        recheck=recheck,
                    )
            return False
        _await(ctx)
        return False
    if ctx.read_key is not None:
        k = ctx.read_key()
        return k in (keys.ENTER, "y", "Y")
    return ctx.confirm_fn("Continue? [Y]es / [n]o")


def confirm_apply(ctx: WizardContext, *, prompt: str = "", equivalent_cli: str) -> bool:
    """The single write gate. The chip is drawn inside the review screen, so this
    only reads the gate key. The ONLY place a walk may post to Xero.

    ``equivalent_cli`` is kept in the signature for API stability even though the
    review screen renders it."""
    if ctx.read_key is not None:
        k = ctx.read_key()
        return k in (keys.ENTER, "a", "A")
    return ctx.confirm_fn(prompt)


def run_walk(
    ctx: WizardContext,
    *,
    title: str,
    steps: list[Step],
    blast_radius: BlastRadius,
    preconditions: list[Precondition],
    equivalent_cli: str,
    total: int | None = None,
    recheck: Callable[[], list[Precondition]] | None = None,
) -> None:
    # pre-flight is step 1; the walk steps follow. ``total`` lets a walk number
    # its screens to match its design (e.g. schedule-bills shows "of 4" because
    # build + apply are real but non-interactive phases); else it's auto-counted.
    total = total or (len(steps) + 1)
    if not preflight(
        ctx,
        title=title,
        blast_radius=blast_radius,
        preconditions=preconditions,
        equivalent_cli=equivalent_cli,
        progress=f"step 1 of {total}",
        recheck=recheck,
    ):
        return
    bag: dict = {}
    for i, step in enumerate(steps, start=2):
        bag["progress"] = f"step {i} of {total}"
        result = step.run(ctx, bag)
        bag.update(result.data)
        if not result.ok:
            _present(ctx, render.render_walk_result(title, ok=False, message=result.message))
            _await(ctx)
            return
    _present(
        ctx,
        render.render_walk_result(
            title,
            ok=True,
            message=bag.get("summary") or "Done.",
            links=bag.get("result_links"),
        ),
    )
    _await(ctx)


def make_walk_handler(
    *,
    title: str,
    steps: list[Step],
    blast_radius: BlastRadius,
    preconditions_fn: Callable[[WizardContext], list[Precondition]],
    equivalent_cli: str,
    total: int | None = None,
) -> Handler:
    """Return a ``CapabilitySpec.run``. ``preconditions_fn(ctx)`` is evaluated at
    run time because freshness changes between cockpit opens. ``total`` overrides
    the screen count shown in the ``step N of M`` header (see ``run_walk``)."""

    def _run(ctx: WizardContext) -> None:
        run_walk(
            ctx,
            title=title,
            steps=steps,
            blast_radius=blast_radius,
            preconditions=preconditions_fn(ctx),
            equivalent_cli=equivalent_cli,
            total=total,
            # Re-evaluate after an inline remedy so a cleared precondition (e.g.
            # a stale apply lock) lets the operator continue without re-opening.
            recheck=lambda: preconditions_fn(ctx),
        )

    return _run
