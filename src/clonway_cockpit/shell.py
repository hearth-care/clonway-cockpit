"""The cockpit shell loop — a full-screen TUI on the alternate screen, now a
framework-owned, parameterised ``run_cockpit``. Arrow keys move a highlight,
Enter opens it; number/letter hotkeys jump directly; each view redraws in place
(replacing the last) so it feels like a program, not a transcript. Raw keypresses
come from ``clonway_cockpit.keys`` (stdlib, no dep). The loop is unit-testable by
injecting ``read_key`` + a fake ``screen``.

A worker supplies its specifics through a :class:`Host` (a frozen bundle of
callbacks): how to capture its state snapshot, how to build a walk's
``WizardContext``, what a pulse-pill activation does, the doctor probe/fix
builders, the usage telemetry module, and an on-open hook (catalog registration /
signal emit). The generic machinery — navigation, filter, open-capability
chokepoint, the doctor loop, the animated-progress helper — lives here so every
worker inherits the whole interactive loop, not just the primitives.

This module imports only ``clonway_cockpit.{keys,render,walk,registry,usage}`` and
stdlib — never a worker package."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from rich.console import RenderableType

from clonway_cockpit import keys, render, walk
from clonway_cockpit import registry as _registry
from clonway_cockpit import render as r
from clonway_cockpit.registry import CapabilitySpec, WizardContext
from clonway_cockpit.state import CockpitState

# How long the cockpit sleeps between progress frames — ~8 redraws/second, fast
# enough that the spinner reads as motion, slow enough not to thrash the screen.
_PROGRESS_TICK = walk._PROGRESS_TICK


class Screen(Protocol):
    """Anything the loop draws onto: an object with an ``update(renderable)``
    method. The real cockpit passes ``console.screen()``'s alt-screen; tests pass
    a frame-recording fake."""

    def update(self, renderable: RenderableType) -> None: ...


class UsageModule(Protocol):
    """The slice of a worker's usage-telemetry module the loop reaches for. A
    worker passes its own module (e.g. ``xbook.cockpit.usage``, which defaults the
    state dir to ``.xbook``) so counts land in the worker's state dir and tests
    that monkeypatch the worker's ``usage.record`` see the loop's calls."""

    def record(self, key: str, action: str = ..., **kw: object) -> None: ...

    def load(self, **kw: object) -> dict: ...


@dataclass(frozen=True)
class Host:
    """The worker-specific bundle the cockpit loop is parameterised on.

    Each field is a callback (or the usage module) the generic loop calls at the
    points where behaviour is worker-specific. Passing callables (rather than, say,
    bound methods captured once) lets a worker resolve module-level functions at
    call time, so a test that monkeypatches the worker's ``usage`` / ``sync``
    indirections still sees the loop route through them."""

    # Capture the worker's state snapshot (pills + needs + header) — pure-read,
    # network-free. Re-called on every home redraw so freshness refreshes.
    capture_state: Callable[[], CockpitState]
    # Build a walk's WizardContext bound to the alt-screen (present=screen.update,
    # read_key=read_key), threading an optional focus. Worker-specific because it
    # carries the worker's console/client.
    build_walk_ctx: Callable[..., WizardContext]
    # ⏎ on a pulse pill — the worker's sync action (read-only, no-login routine
    # path; an explicit operator-confirmed re-auth for a lapsed bank session).
    activate_pill: Callable[[object, Screen, Callable[[], str]], None]
    # Doctor inputs: build the worker's status report (raises when unconfigured),
    # turn it into probes, list the named fixes, and render the unconfigured-hint
    # screen. Kept as callables so the doctor loop stays worker-agnostic.
    doctor_build_report: Callable[[], object]
    doctor_build_probes: Callable[[object], list]
    doctor_fixes_for: Callable[[list], list]
    doctor_unconfigured_renderable: Callable[[], RenderableType]
    # The worker's usage-telemetry module (its own state-dir default).
    usage: UsageModule
    # Fired once per cockpit open — catalog registration + best-effort signal
    # emit. Worker-specific; the loop just calls it before the first paint.
    on_open: Callable[[], None]
    # The worker's capability registry accessors. A worker may keep its own
    # registry dict (e.g. xbook does, so its tests can snapshot/restore it) rather
    # than share ``clonway_cockpit.registry``'s module global — so the loop reads
    # capabilities through the host, not a hard import. Default to the framework
    # registry for a worker that does share it.
    get_capabilities: Callable[[], list[CapabilitySpec]] = field(default=_registry.get_capabilities)
    get_capability: Callable[[str], CapabilitySpec | None] = field(default=_registry.get_capability)
    # The product name used in the Doctor screen header — "xbook doctor" for the
    # default worker; a fleet bridge passes its own label ("Clonway Office doctor").
    # Defaulted so existing Host constructions that don't set it are unchanged.
    app_label: str = "xbook"


def run_with_progress[T](
    screen: Screen,
    label: str,
    fn: Callable[[], T],
    *,
    tick: float = _PROGRESS_TICK,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run a blocking ``fn`` (a sync) in a worker thread while animating the
    screen, so a long pull is visibly alive (spinner + elapsed seconds) instead
    of a frozen panel. Returns ``fn``'s value; if ``fn`` raised, re-raises that
    exception after the loop so the caller's existing result/error screens still
    work. ``screen`` is anything with an ``update(renderable)`` method.

    Delegates to ``walk.animate_until_done`` (the shared thread/animation loop).
    ``clock``/``sleep`` are injectable so the loop is testable without real time."""
    return walk.animate_until_done(screen.update, label, fn, tick=tick, clock=clock, sleep=sleep)


def run_cockpit(host: Host, *, read_key: Callable[[], str] = keys.read_key, screen: Screen) -> None:
    """Drive the cockpit's home loop against ``screen`` with the worker ``host``.

    Fires ``host.on_open`` (catalog registration + signal emit) once, then runs
    the home loop. The alt-screen lifecycle and the ShellOut re-entry loop stay in
    the worker's thin wrapper (they need the worker's console + shell-out table);
    this entry point is the screen-bound core the tests drive directly."""
    host.on_open()
    _home(host, screen, read_key)


def selectables(state: CockpitState) -> list[tuple[str, object]]:
    """Ordered list of arrow-navigable rows, top-down as they're drawn: pulse
    pills first, then needs-you items, then the A–G shelves."""
    return (
        [("pill", i) for i in range(len(state.pills))]
        + [("need", i) for i in range(len(state.needs))]
        + [("shelf", letter) for letter in render.SHELVES]
    )


def default_sel(items: list[tuple[str, object]]) -> int:
    """Where the ❯ cursor lands on the first paint (H-1): the first actionable
    "needs you" row if any exist, else the first pulse pill, else 0 (the first
    shelf). Computed from ``selectables`` order so the index is always valid."""
    for kind in ("need", "pill"):
        for i, (k, _ref) in enumerate(items):
            if k == kind:
                return i
    return 0


def move_horizontal(items: list[tuple[str, object]], sel: int, key: str) -> int:
    """Map a LEFT/RIGHT press to a new selection index, jumping between the two
    columns of the regions that render as a 2-col grid (the pulse pills and the
    A–G toolkit shelves). Single-column regions (needs-you) are a no-op. Returns
    the new index, or ``sel`` unchanged when there's no column to jump to.

    The grids must match ``render``: the toolkit splits ``SHELVES`` at
    ``half = (len+1)//2`` into ``left = letters[:half]`` / ``right = letters[half:]``
    and draws them row-by-row (A↔E, B↔F, C↔G; D has no right pair); the pulse grid
    fills row-major two-per-row, so an even pill index is the left column and the
    next odd index is its right neighbour."""
    kind, ref = items[sel]
    want_right = key == keys.RIGHT

    if kind == "shelf" and isinstance(ref, str):
        letters = list(render.SHELVES)
        half = (len(letters) + 1) // 2
        left, right = letters[:half], letters[half:]
        if ref in left:
            row = left.index(ref)
            target = right[row] if want_right and row < len(right) else None
        else:  # ref in right
            row = right.index(ref)
            target = left[row] if not want_right else None
        if target is not None:
            return items.index(("shelf", target))
        return sel

    if kind == "pill" and isinstance(ref, int):
        n_pills = sum(1 for k, _ in items if k == "pill")
        # Even index = left column → RIGHT goes to ref+1 (if that pill exists);
        # odd index = right column → LEFT goes to ref-1.
        if want_right and ref % 2 == 0 and ref + 1 < n_pills:
            target_ref = ref + 1
        elif not want_right and ref % 2 == 1:
            target_ref = ref - 1
        else:
            return sel
        return items.index(("pill", target_ref))

    # needs-you is a single column — left/right do nothing.
    return sel


def _home(host: Host, screen: Screen, read_key: Callable[[], str]) -> None:
    sel: int | None = None  # set on the first paint to the first actionable row
    while True:
        state = host.capture_state()
        items = selectables(state)
        # First paint: land the cursor on the first actionable row (needs-you,
        # else a pill, else the first shelf) so the ❯ shows from frame one.
        # Thereafter keep a valid numeric selection in bounds after a refresh.
        if sel is None:
            sel = default_sel(items)
        else:
            sel %= len(items)
        selection = items[sel]
        screen.update(r.render_cockpit_screen(state, host.get_capabilities(), selection=selection))
        key = read_key()
        low = key.lower() if len(key) == 1 else key
        if low in ("q", keys.ESC):
            return
        if key == keys.UP:
            sel = (sel - 1) % len(items)
        elif key == keys.DOWN:
            sel = (sel + 1) % len(items)
        elif key in (keys.LEFT, keys.RIGHT):
            sel = move_horizontal(items, sel, key)
        elif key == keys.ENTER:
            _activate(host, items[sel], state, screen, read_key)
        elif low == "r":
            continue
        elif low == "?":
            _show(screen, r.render_help(), read_key)
        elif low == "/":
            _filter(host, screen, read_key)
        elif key.isdigit() and 1 <= int(key) <= len(state.needs):
            _activate(host, ("need", int(key) - 1), state, screen, read_key)
        elif low.isalpha() and low.upper() in render.SHELVES:
            _shelf(host, low.upper(), screen, read_key)
        # any other key: ignore — the highlight is the guide


def _activate(
    host: Host,
    item: tuple[str, object],
    state: CockpitState,
    screen: Screen,
    read_key: Callable[[], str],
) -> None:
    kind, ref = item
    if kind == "shelf" and isinstance(ref, str):
        _shelf(host, ref, screen, read_key)
        return
    if not isinstance(ref, int):
        return
    if kind == "pill":
        host.activate_pill(state.pills[ref], screen, read_key)
        return
    need = state.needs[ref]
    if need.capability_key and host.get_capability(need.capability_key):
        # A needs-you item can carry a focus (e.g. "Bills overdue" → "overdue"),
        # threaded into the walk's WizardContext so it opens scoped to that subset.
        _open_capability(host, need.capability_key, screen, read_key, focus=need.focus)
    else:
        _show(screen, r.render_note(need.title, need.detail), read_key)


def _shelf(host: Host, letter: str, screen: Screen, read_key: Callable[[], str]) -> None:
    specs = [s for s in host.get_capabilities() if s.shelf == letter]
    if not specs:
        return
    n = len(specs)  # navigable rows = the specs plus a trailing "Back"
    sel = 0
    # Load usage once per shelf render-loop and scale the inline notch against the
    # GLOBAL peak (the busiest tool across ALL shelves), so heights are comparable
    # shelf-to-shelf. Best-effort: an empty/failed load → no notch (today's look).
    usage_map = host.usage.load()
    peak = _usage_peak(usage_map)
    while True:
        options = [(str(i), s.title, s.summary) for i, s in enumerate(specs, 1)]
        opens = [_spec_opens(usage_map, s.key) for s in specs] if usage_map else None
        screen.update(
            r.render_menu(render.SHELVES[letter], options, selected=sel, opens=opens, peak=peak)
        )
        key = read_key()
        low = key.lower() if len(key) == 1 else key
        if low in ("q", keys.ESC):
            return
        if key == keys.UP:
            sel = (sel - 1) % (n + 1)
        elif key == keys.DOWN:
            sel = (sel + 1) % (n + 1)
        elif key == keys.ENTER:
            if sel == n:  # the Back row
                return
            _open_capability(host, specs[sel].key, screen, read_key)
            return
        elif key.isdigit() and 1 <= int(key) <= n:
            _open_capability(host, specs[int(key) - 1].key, screen, read_key)
            return


def _spec_opens(usage_map: dict, key: str) -> int:
    """The lifetime ``open`` count for ``key`` from a loaded usage map (0 if
    absent / malformed). Tolerant — never raises."""
    row = usage_map.get(key)
    if not isinstance(row, dict):
        return 0
    n = row.get("open")
    return n if isinstance(n, int) else 0


def _usage_peak(usage_map: dict) -> int:
    """The busiest tool's open count across the whole usage map — the denominator
    the inline notch scales against, so heights are comparable shelf-to-shelf.
    0 when there's no usage (the notch then renders nothing)."""
    return max((_spec_opens(usage_map, k) for k in usage_map), default=0)


def _open_capability(
    host: Host,
    key: str,
    screen: Screen,
    read_key: Callable[[], str],
    *,
    focus: str | None = None,
) -> None:
    spec = host.get_capability(key)
    if spec is None:
        return
    # The single chokepoint where any capability is opened (walks, reports, cards,
    # Doctor) — count the "open" here, best-effort, BEFORE running it. Never gates
    # the open: usage.record swallows all errors.
    host.usage.record(key, "open")
    if key == "doctor":
        _doctor(host, screen, read_key)
        return
    if spec.run is not None:
        spec.run(host.build_walk_ctx(screen, read_key, focus=focus))
        return
    # reference-only: no handler, just the equivalent-CLI card
    _show(screen, r.render_capability_card(spec), read_key)


def _doctor(host: Host, screen: Screen, read_key: Callable[[], str]) -> None:
    """The interactive Doctor — the only capability with a custom view (it doesn't
    fit the walk model). The probe table + verdict render as before, but the named
    fixes are a navigable list: ↑↓ moves over the RUNNABLE fixes, ⏎ runs the
    selected one (a state-changing fix asks one key first), and the screen
    re-builds afterwards so the probes reflect the change. Display-only fixes
    (browser auth, etc.) render dimmed and aren't selectable. Degrades to a
    setup hint, like the static view, if the worker isn't configured.

    Every runnable fix is READ-ONLY w.r.t. the worker's books and NO-LOGIN (the
    sync fixes reuse the existing token; the lock fix only unlinks a local file)."""
    sel = 0
    while True:
        try:
            report = host.doctor_build_report()
        except Exception:  # noqa: BLE001 — unconfigured/offline → setup hint, don't crash
            _show(screen, host.doctor_unconfigured_renderable(), read_key)
            return
        probes = host.doctor_build_probes(report)
        fixes = host.doctor_fixes_for(probes)
        runnable = [f for f in fixes if f.run is not None]
        if runnable:
            sel %= len(runnable)
        screen.update(
            r.render_doctor(
                probes,
                fixes,
                selected=sel if runnable else None,
                usage=host.usage.load(),  # best-effort; {} on any failure
                specs=host.get_capabilities(),
                app_label=host.app_label,
            )
        )
        key = read_key()
        low = key.lower() if len(key) == 1 else key
        if low in ("q", keys.ESC):
            return
        if not runnable:
            continue  # nothing to run — any non-quit key just refreshes
        if key == keys.UP:
            sel = (sel - 1) % len(runnable)
        elif key == keys.DOWN:
            sel = (sel + 1) % len(runnable)
        elif key.isdigit() and 1 <= int(key) <= len(runnable):
            _run_doctor_fix(host, runnable[int(key) - 1], screen, read_key)
        elif key == keys.ENTER:
            _run_doctor_fix(host, runnable[sel], screen, read_key)


def _run_doctor_fix(host: Host, fix, screen: Screen, read_key: Callable[[], str]) -> None:
    """Run one runnable Doctor fix, gating a state-changing one behind a single
    confirm key. The confirm grammar matches the walk gate (M-2 / N-5): ENTER or
    ``y``/``Y`` confirms; anything else fails closed (the fix does NOT run). The
    result waits for a key; the caller's loop then re-builds so the probes
    refresh."""
    if fix.confirm:
        screen.update(r.render_doctor_confirm(fix))
        if read_key() not in (keys.ENTER, "y", "Y"):
            return  # cancelled — the fix did NOT run
    host.usage.record("doctor:fix", "open")  # a Doctor fix was actually run
    try:
        # A "Sync now" fix is a blocking pull — run it under the animated progress
        # screen (FIX A) so it reads as alive. Other fixes (lock removal) are
        # instant, so the plain working screen is fine.
        if fix.title == "Sync now":
            msg = run_with_progress(screen, f"{fix.title}…", fix.run)
        else:
            screen.update(r.render_walk_progress(f"{fix.title}…"))
            msg = fix.run()
        ok = True
    except Exception as e:  # noqa: BLE001 — surface any failure as a clean result
        msg, ok = str(e), False
    screen.update(r.render_walk_result("Doctor", ok=ok, message=msg))
    read_key()


def _show(screen: Screen, renderable: RenderableType, read_key: Callable[[], str]) -> None:
    """Draw a leaf screen (card / doctor / note / help); any key returns."""
    screen.update(renderable)
    read_key()


def _filter(host: Host, screen: Screen, read_key: Callable[[], str]) -> None:
    """Type-to-filter the catalog by name; ↑↓ to move, Enter opens, Esc cancels."""
    term, sel = "", 0
    while True:
        matches = _matches(host, term)
        if matches:
            sel %= len(matches)
        screen.update(r.render_filter(term, matches, selected=(sel if matches else None)))
        key = read_key()
        if key == keys.ESC:
            return
        if key == keys.ENTER:
            if matches:
                _open_capability(host, matches[sel].key, screen, read_key)
            return
        if key == keys.UP and matches:
            sel = (sel - 1) % len(matches)
        elif key == keys.DOWN and matches:
            sel = (sel + 1) % len(matches)
        elif key == keys.BACKSPACE:
            term, sel = term[:-1], 0
        elif len(key) == 1 and key.isprintable():
            term, sel = term + key, 0


def _matches(host: Host, term: str) -> list[CapabilitySpec]:
    t = term.strip().lower()
    if not t:
        return []
    return [s for s in host.get_capabilities() if t in s.title.lower() or t in s.summary.lower()]
