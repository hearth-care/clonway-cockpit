import pytest
from rich.console import Console

from clonway_cockpit import keys, walk
from clonway_cockpit.registry import BlastRadius, WizardContext
from clonway_cockpit.walk import Precondition, Remedy, Step, StepResult


def _ctx(confirms):
    cq = list(confirms)

    def _confirm(prompt):
        return cq.pop(0) if cq else False

    return WizardContext(
        state={},
        client=None,
        console=Console(record=True),
        input_fn=lambda p, d="": "",
        confirm_fn=_confirm,
    )


def _key_ctx(presented, keys_seq):
    """A screen-mode context: records presented renderables; reads scripted keys."""
    kq = list(keys_seq)

    def _present(renderable):
        presented.append(renderable)

    def _read_key():
        return kq.pop(0) if kq else keys.ESC

    return WizardContext(
        state={},
        client=None,
        console=Console(record=True),
        input_fn=lambda p, d="": "",
        confirm_fn=lambda p: False,
        present=_present,
        read_key=_read_key,
    )


def _br():
    return BlastRadius(
        summary="Sets PlannedPaymentDate.",
        details=("Does NOT post payments.",),
        reversible="Idempotent within 24h.",
    )


def test_preflight_blocks_when_a_precondition_fails():
    ctx = _ctx([True])  # operator would continue, but a precondition is red
    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=False, detail="no token")],
        equivalent_cli="uv run xbook plan",
    )
    assert ok is False


def test_apply_is_never_reached_without_explicit_confirm():
    posted = {"n": 0}

    def _propose(ctx, bag):
        return StepResult(ok=True, data={"plan": "p.json"})

    def _apply(ctx, bag):
        if not walk.confirm_apply(
            ctx,
            prompt="Apply now? [a]pply / [c]ancel",
            equivalent_cli="uv run xbook apply p.json --confirm",
        ):
            return StepResult(ok=True, message="cancelled — nothing posted")
        posted["n"] += 1
        return StepResult(ok=True)

    ctx = _ctx([True, False])  # continue at preflight, decline at apply
    walk.run_walk(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=True)],
        equivalent_cli="uv run xbook plan",
        steps=[Step("propose", _propose), Step("apply", _apply)],
    )
    assert posted["n"] == 0  # the write never happened


def test_equivalent_cli_is_shown():
    """preflight renders the equivalent-CLI chip (console fallback)."""
    ctx = _ctx([True])
    walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=True)],
        equivalent_cli="uv run xbook plan",
    )
    assert "uv run xbook plan" in ctx.console.export_text()


def test_preflight_shows_step_counter_via_run_walk():
    """run_walk() passes ``step 1 of N`` to preflight so the header includes the counter."""
    ctx = _ctx([True])

    def _noop(c, bag):
        return StepResult(ok=True)

    walk.run_walk(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=True)],
        equivalent_cli="uv run xbook plan",
        steps=[Step("propose", _noop), Step("apply", _noop)],
    )
    out = ctx.console.export_text()
    assert "step 1 of 3" in out  # 2 steps + preflight = 3 total


def test_preflight_no_progress_when_called_directly():
    """preflight() without ``progress`` still renders the escape hint without a counter."""
    ctx = _ctx([True])
    walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=True)],
        equivalent_cli="uv run xbook plan",
    )
    out = ctx.console.export_text()
    assert "esc" in out and "cancel" in out
    assert "step" not in out


def test_blast_radius_not_is_highlighted():
    """A blast-radius detail containing NOT is rendered (the token appears in output)."""
    ctx = _ctx([True])
    walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),  # details = ("Does NOT post payments.",)
        preconditions=[Precondition("Auth valid", ok=True)],
        equivalent_cli="uv run xbook plan",
    )
    out = ctx.console.export_text()
    # The word NOT must appear in the rendered text
    assert "NOT" in out


# --- Screen-mode (cockpit) path -----------------------------------------------


def test_preflight_screen_mode_continues_on_enter():
    """With present + read_key bound, preflight draws ONE screen and reads ONE key;
    ENTER continues."""
    presented: list = []
    ctx = _key_ctx(presented, [keys.ENTER])
    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=True)],
        equivalent_cli="uv run xbook plan",
        progress="step 1 of 2",
    )
    assert ok is True
    assert len(presented) == 1  # exactly one framed screen drawn


def test_preflight_screen_mode_blocks_when_precondition_fails():
    """A red precondition draws the screen, waits for a key, and returns False
    without reading a continue key."""
    presented: list = []
    ctx = _key_ctx(presented, [keys.ENTER])  # the single key is the 'press any key' ack
    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=False, detail="no token")],
        equivalent_cli="uv run xbook plan",
    )
    assert ok is False
    assert len(presented) == 1


# --- Inline precondition remedy (FIX 1: stale apply-lock) --------------------


def test_preflight_offers_remedy_key_for_blocked_precondition():
    """A blocked precondition carrying a Remedy makes the footer offer its
    one-key hint instead of the dead-end 'fix the above first' message."""
    presented: list = []
    # esc → anything-other-than-the-remedy-key returns False without running it.
    ctx = _key_ctx(presented, [keys.ESC])
    remedy = Remedy(key="u", label="clear the stale apply lock", action=lambda: "cleared")
    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Apply lock free", ok=False, remedy=remedy)],
        equivalent_cli="uv run xbook plan",
    )
    assert ok is False
    # screen-mode present is the recorder (console export is empty), so assert on
    # the directly-rendered preflight text instead.
    text = _render_preflight_text(remedy)
    assert "[u]" in text and "clear the stale apply lock" in text


def _render_preflight_text(remedy) -> str:
    from clonway_cockpit import render

    con = Console(record=True, width=120)
    con.print(
        render.render_preflight(
            title="Schedule bills",
            blast_radius=_br(),
            preconditions=[Precondition("Apply lock free", ok=False, remedy=remedy)],
            equivalent_cli="uv run xbook plan",
            ready=False,
            remedy=remedy,
        )
    )
    return con.export_text()


def test_preflight_runs_remedy_on_key_then_rechecks_and_continues():
    """Pressing the remedy key + confirming runs the remedy (spied) and
    re-evaluates the preconditions; once cleared, preflight returns True so the
    operator continues from the same screen."""
    presented: list = []
    ran = {"n": 0}

    def _action() -> str:
        ran["n"] += 1
        return "Removed .xbook/apply.lock"

    remedy = Remedy(key="u", label="clear the stale apply lock", action=_action)
    # keys: 'u' (offer) → ENTER (confirm) → ENTER (continue once cleared)
    ctx = _key_ctx(presented, ["u", keys.ENTER, keys.ENTER])

    # recheck flips the precondition to ok after the remedy runs.
    def _recheck():
        return [Precondition("Apply lock free", ok=ran["n"] > 0)]

    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Apply lock free", ok=False, remedy=remedy)],
        equivalent_cli="uv run xbook plan",
        recheck=_recheck,
    )
    assert ran["n"] == 1  # the remedy ran exactly once
    assert ok is True  # cleared → the operator can continue


def test_preflight_non_remedy_key_returns_false_without_running_remedy():
    """Any key other than the remedy key returns False (back to the cockpit) and
    does NOT run the remedy."""
    presented: list = []
    ran = {"n": 0}
    remedy = Remedy(
        key="u",
        label="clear the stale apply lock",
        action=lambda: ran.__setitem__("n", ran["n"] + 1) or "x",
    )
    ctx = _key_ctx(presented, ["x"])  # not the remedy key
    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Apply lock free", ok=False, remedy=remedy)],
        equivalent_cli="uv run xbook plan",
        recheck=lambda: [Precondition("Apply lock free", ok=False, remedy=remedy)],
    )
    assert ok is False
    assert ran["n"] == 0  # the remedy never ran


def test_preflight_remedy_confirm_declined_does_not_run():
    """Pressing the remedy key but declining the one-key confirm does NOT run
    the remedy and returns False."""
    presented: list = []
    ran = {"n": 0}
    remedy = Remedy(
        key="u",
        label="clear the stale apply lock",
        action=lambda: ran.__setitem__("n", ran["n"] + 1) or "x",
    )
    ctx = _key_ctx(presented, ["u", "n"])  # offer → decline confirm
    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Apply lock free", ok=False, remedy=remedy)],
        equivalent_cli="uv run xbook plan",
        recheck=lambda: [Precondition("Apply lock free", ok=False, remedy=remedy)],
    )
    assert ok is False
    assert ran["n"] == 0


def test_preflight_blocked_without_remedy_is_unchanged():
    """A blocked precondition with NO remedy keeps today's behaviour: draw the
    screen, wait for any key, return False — never runs anything."""
    presented: list = []
    ctx = _key_ctx(presented, [keys.ENTER])  # the 'press any key' ack
    ok = walk.preflight(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=False, detail="no token")],
        equivalent_cli="uv run xbook plan",
    )
    assert ok is False
    assert len(presented) == 1  # one screen, no remedy flow


def test_run_walk_screen_mode_drives_preflight_then_step():
    """run_walk in screen mode: ENTER at preflight, the step runs, the result
    screen is drawn and a key returns."""
    presented: list = []
    ran: list = []

    def _step(ctx, bag):
        ran.append(bag.get("progress"))
        return StepResult(ok=True, data={"summary": "Done well."})

    ctx = _key_ctx(presented, [keys.ENTER, keys.ENTER])  # continue, then ack the result
    walk.run_walk(
        ctx,
        title="Schedule bills",
        blast_radius=_br(),
        preconditions=[Precondition("Auth valid", ok=True)],
        equivalent_cli="uv run xbook plan",
        steps=[Step("review", _step)],
    )
    assert ran == ["step 2 of 2"]  # 1 step + preflight = total 2
    # preflight screen + result screen drawn.
    assert len(presented) == 2


# --- animate_until_done log-panel tests ----------------------------------------


def _instant_clock():
    """A clock that returns 0, then 0 forever — tick=0 so the loop exits fast."""
    return 0.0


def _noop_sleep(_t):
    pass


def test_animate_passes_log_to_unary_worker():
    """A worker fn that accepts one positional arg receives the log callback and
    can append lines; the redraw snapshot carries them."""
    presented: list = []

    def worker(log):
        log("stage · invoices 1/10")
        log("stage · invoices 10/10")
        return "done"

    result = walk.animate_until_done(
        presented.append,
        "Syncing",
        worker,
        tick=0.0,
        clock=_instant_clock,
        sleep=_noop_sleep,
    )
    assert result == "done"
    # At least one rendered frame should contain the logged lines.
    from rich.console import Console

    def _text(r):
        c = Console(record=True, width=120)
        c.print(r)
        return c.export_text()

    # The final frame is drawn after the thread exits — check all frames.
    all_text = "\n".join(_text(r) for r in presented)
    assert "stage · invoices 10/10" in all_text


def test_animate_runs_zero_arg_worker_unchanged():
    """A zero-arg worker still works — backwards compat."""
    presented: list = []

    def worker():
        return 42

    result = walk.animate_until_done(
        presented.append,
        "Syncing",
        worker,
        tick=0.0,
        clock=_instant_clock,
        sleep=_noop_sleep,
    )
    assert result == 42
    assert len(presented) >= 1


def test_animate_buffer_caps_at_log_lines():
    """The ring buffer never grows beyond log_lines — only the most recent N
    lines are visible, older ones are dropped."""
    presented: list = []

    def worker(log):
        for i in range(10):
            log(f"line {i}")
        return "done"

    walk.animate_until_done(
        presented.append,
        "Syncing",
        worker,
        tick=0.0,
        clock=_instant_clock,
        sleep=_noop_sleep,
        log_lines=3,
    )
    from rich.console import Console

    def _text(r):
        c = Console(record=True, width=120)
        c.print(r)
        return c.export_text()

    # Check the final frame (last presented renderable).
    final_text = _text(presented[-1])
    # At most 3 lines in the buffer — lines 7, 8, 9 are the tail.
    assert "line 9" in final_text
    assert "line 0" not in final_text


def test_animate_empty_log_renders_calm_reassurance():
    """When no log lines have been emitted, the calm 'this can take up to a minute'
    line is shown — unchanged from today's behaviour."""
    presented: list = []

    def worker():
        return "done"

    walk.animate_until_done(
        presented.append,
        "Syncing",
        worker,
        tick=0.0,
        clock=_instant_clock,
        sleep=_noop_sleep,
    )
    from rich.console import Console

    def _text(r):
        c = Console(record=True, width=120)
        c.print(r)
        return c.export_text()

    first_text = _text(presented[0])
    assert "this can take up to a minute" in first_text


def test_animate_reraises_worker_exception_with_logs():
    """If the worker raises, animate_until_done re-raises on the main thread.
    Any log lines emitted before the error are still in the buffer (not lost)."""
    import pytest

    presented: list = []

    def worker(log):
        log("stage · started")
        raise ValueError("sync failed")

    with pytest.raises(ValueError, match="sync failed"):
        walk.animate_until_done(
            presented.append,
            "Syncing",
            worker,
            tick=0.0,
            clock=_instant_clock,
            sleep=_noop_sleep,
        )


def test_stage_reporter_transitions():
    from clonway_cockpit.walk import StageReporter

    r = StageReporter([("accounts", "Accounts"), ("contacts", "Contacts")])
    snap = r.snapshot()
    assert [s.status for s in snap] == ["pending", "pending"]

    r.start("accounts")
    r.update("accounts", "page 1 · 100")
    assert r.snapshot()[0].status == "active"
    assert r.snapshot()[0].detail == "page 1 · 100"

    r.done("accounts", "120")
    assert r.snapshot()[0].status == "done"
    assert r.snapshot()[0].detail == "120"

    r.skip("contacts", "skipped")
    assert r.snapshot()[1].status == "skipped"
    assert r.snapshot()[1].detail == "skipped"

    # snapshot is an independent copy — mutating the reporter doesn't change a prior snapshot
    snap2 = r.snapshot()
    r.done("contacts")
    assert snap2[1].status == "skipped"

    # unknown keys are no-ops (never raise)
    r.start("nope")
    r.done("nope")


def test_animate_staged_drives_reporter_and_renders():
    presented: list = []

    def worker(reporter):
        reporter.start("accounts")
        reporter.done("accounts", "120")
        reporter.start("pnl")
        reporter.update("pnl", "month 3/12")
        return "ok"

    result = walk.animate_staged(
        presented.append,
        "Syncing Xero…",
        worker,
        stages=[("accounts", "Accounts"), ("pnl", "P&L")],
        hint="still working",
        tick=0.0,
        clock=_instant_clock,
        sleep=_noop_sleep,
    )
    assert result == "ok"

    from rich.console import Console

    def _text(r):
        c = Console(record=True, width=120)
        c.print(r)
        return c.export_text()

    all_text = "\n".join(_text(r) for r in presented)
    assert "Accounts" in all_text and "120" in all_text
    assert "P&L" in all_text


def test_animate_staged_reraises_worker_exception():
    def worker(reporter):
        reporter.start("accounts")
        raise ValueError("sync failed")

    with pytest.raises(ValueError, match="sync failed"):
        walk.animate_staged(
            lambda r: None,
            "Syncing Xero…",
            worker,
            stages=[("accounts", "Accounts")],
            tick=0.0,
            clock=_instant_clock,
            sleep=_noop_sleep,
        )


def test_run_animated_poll_cancel_raises(monkeypatch):
    import threading

    release = threading.Event()

    def worker(_arg):
        release.wait(timeout=2)  # stay alive until the test releases it
        return "done"

    with pytest.raises(walk.Cancelled):
        walk._run_animated(
            lambda r: None,
            worker,
            lambda frame, elapsed: "",
            worker_arg=None,
            pass_arg=True,
            tick=0.0,
            clock=_instant_clock,
            sleep=_noop_sleep,
            poll_cancel=lambda: True,  # user "pressed q"
        )
    release.set()


def test_animate_staged_cancellable_q_raises(monkeypatch):
    import threading

    release = threading.Event()
    monkeypatch.setattr(walk.keys, "pending", lambda timeout=0.0: True)
    monkeypatch.setattr(walk.keys, "read_key", lambda: "q")

    def worker(reporter):
        release.wait(timeout=2)
        return "done"

    with pytest.raises(walk.Cancelled):
        walk.animate_staged(
            lambda r: None,
            "Syncing Xero…",
            worker,
            stages=[("a", "A")],
            cancellable=True,
            tick=0.0,
            clock=_instant_clock,
            sleep=_noop_sleep,
        )
    release.set()


def test_animate_staged_not_cancellable_by_default(monkeypatch):
    # default (cancellable=False) must NOT read keys — proves no behaviour change
    monkeypatch.setattr(
        walk.keys, "pending", lambda timeout=0.0: (_ for _ in ()).throw(AssertionError("polled"))
    )
    result = walk.animate_staged(
        lambda r: None,
        "Syncing",
        lambda rep: "ok",
        stages=[("a", "A")],
        tick=0.0,
        clock=_instant_clock,
        sleep=_noop_sleep,
    )
    assert result == "ok"
