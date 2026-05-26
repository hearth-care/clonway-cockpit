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
    # Optional in-cockpit ack / snooze on a SELECTED needs-you item — the Fleet
    # bridge wires these to its real Firestore-backed lifecycle store; each takes the
    # selected NeedsItem and returns a short confirmation line (or None). The host
    # callback owns everything domain-specific (snooze DURATION, the write, what
    # "ack" means) — the shell only routes the keypress and shows the returned
    # confirmation. Defaulted None so xbook's single-worker cockpit (which supplies
    # neither) is byte-identical: with both None, 'a'/'s' stay the shelf-letter
    # hotkeys on every selectable, including a selected need.
    ack: Callable[[object], str | None] | None = None
    snooze: Callable[[object], str | None] | None = None
    # Worker-contributed rows + regions + key handlers — the extension points that
    # let a worker bolt an extra panel onto the cockpit home screen (e.g. xbook's
    # statutory heads-up card) WITHOUT monkey-patching the framework. Three
    # callbacks, each defaulted to a no-op so a worker that doesn't supply them is
    # byte-identical:
    #
    # * ``extra_selectables(state)`` — additional arrow-navigable rows the worker
    #   contributes (each a ``(tag, value)`` tuple under the worker's own tag).
    #   Spliced into ``selectables`` AFTER needs-you and BEFORE shelves so the
    #   visual ordering the worker controls (e.g. a statutory region sits above
    #   the toolkit) matches the arrow-key navigation order.
    # * ``extra_regions(state)`` — additional Rich renderables drawn between the
    #   needs-you region and the toolkit by ``render_cockpit_screen``. Lets the
    #   worker insert its own panel without re-implementing the screen composition.
    # * ``handle_extra_key(state, selection, key)`` — first refusal on every
    #   keypress in ``_home``. The worker inspects the current ``selection`` (which
    #   may be one of its ``extra_selectables`` tuples) and dispatches the key.
    #   Returning ``True`` tells the shell "I handled it — don't fall through to
    #   the default dispatch". ``False`` lets the shell's existing logic fire.
    extra_selectables: Callable[[CockpitState], list[tuple[str, object]]] = field(
        default=lambda state: []
    )
    extra_regions: Callable[[CockpitState], list[RenderableType]] = field(default=lambda state: [])
    handle_extra_key: Callable[[CockpitState, tuple[str, object] | None, str], bool] = field(
        default=lambda state, sel, key: False
    )


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


def _shelf_letters(state: CockpitState) -> list[str]:
    """The shelf letters the shell navigates — the letters it actually DRAWS. When
    a worker supplies ``state.shelves`` (the Fleet Cockpit's roster), navigate
    exactly those; otherwise fall back to xbook's canonical A–G ``render.SHELVES``.

    This is the single source of truth for the navigable letter set, so the
    arrow-down selectables, the ←/→ grid math, and the letter-hotkey handler all
    agree with ``render_toolkit`` (which lays out ``state.shelves or SHELVES``)."""
    return list(state.shelves) if state.shelves is not None else list(render.SHELVES)


def _shelf_label(state: CockpitState, letter: str) -> str:
    """The display name for a shelf letter — the worker's tagline from
    ``state.shelves`` (the Fleet Cockpit's roster) when present, else xbook's
    canonical taxonomy. Drives the shelf sub-menu title so it names the worker,
    not xbook's "Money in"/"Daily rhythm" shelf names."""
    if state.shelves is not None:
        return state.shelves[letter]
    return render.SHELVES[letter]


def selectables(state: CockpitState, host: Host | None = None) -> list[tuple[str, object]]:
    """Ordered list of arrow-navigable rows, top-down as they're drawn: pulse
    pills first, then needs-you items, then any worker-supplied extra rows
    (``host.extra_selectables``), then the shelves actually drawn (the fleet's
    ``state.shelves`` letters, or xbook's A–G when unset).

    Extras land between needs-you and shelves so the cursor walks them in the
    visual order the worker controls (an extra panel sits above the toolkit on
    screen, so its rows are reachable by ↓ after the needs-you items). ``host``
    is optional — callers that don't supply one (xbook tests pre-extension)
    get the legacy three-tier list, byte-identical."""
    extras = host.extra_selectables(state) if host is not None else []
    return (
        [("pill", i) for i in range(len(state.pills))]
        + [("need", i) for i in range(len(state.needs))]
        + list(extras)
        + [("shelf", letter) for letter in _shelf_letters(state)]
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

    The grids must match ``render``: the toolkit splits the DRAWN letters at
    ``half = (len+1)//2`` into ``left = letters[:half]`` / ``right = letters[half:]``
    and draws them row-by-row; the pulse grid fills row-major two-per-row, so an
    even pill index is the left column and the next odd index is its right
    neighbour. The shelf letters come from ``items`` (the same set ``selectables``
    drew), so the jump matches the fleet's roster, not xbook's hardcoded A–G."""
    kind, ref = items[sel]
    want_right = key == keys.RIGHT

    if kind == "shelf" and isinstance(ref, str):
        letters = [r for k, r in items if k == "shelf" and isinstance(r, str)]
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
        items = selectables(state, host)
        # First paint: land the cursor on the first actionable row (needs-you,
        # else a pill, else the first shelf) so the ❯ shows from frame one.
        # Thereafter keep a valid numeric selection in bounds after a refresh.
        if sel is None:
            sel = default_sel(items)
        else:
            sel %= len(items)
        selection = items[sel]
        screen.update(
            r.render_cockpit_screen(
                state,
                host.get_capabilities(),
                selection=selection,
                extra_regions=host.extra_regions(state),
            )
        )
        key = read_key()
        low = key.lower() if len(key) == 1 else key
        if low in ("q", keys.ESC):
            return
        # Worker first refusal — let the host's ``handle_extra_key`` claim any
        # key on a selection it owns (e.g. ⏎/y/p/c on an xbook statutory row)
        # BEFORE the default dispatch fires. Returning True means "I handled
        # it; skip the framework's branches below". This is the extension point
        # that lets a worker bolt on key dispatch for its own extra_selectables.
        if host.handle_extra_key(state, selection, key):
            continue
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
            _show(screen, r.render_help(state.help_lines), read_key)
        elif low == "/":
            _filter(host, screen, read_key)
        elif key.isdigit() and 1 <= int(key) <= len(state.needs):
            _activate(host, ("need", int(key) - 1), state, screen, read_key)
        elif isinstance(selection[1], int) and _ack_snooze_cb(host, selection, low) is not None:
            # Context-sensitive ack/snooze: ONLY when a needs-you item is selected
            # AND the host wired the matching callback. This branch sits BEFORE the
            # shelf-letter handler so 'a'/'s' act on the need first — but only in
            # that exact case. With no callback (xbook) _ack_snooze_cb returns None
            # and we fall through to the shelf-letter handler below, so 'a' stays
            # the shelf-A hotkey, byte-identical.
            _ack_snooze_need(host, state.needs[selection[1]], low, screen, read_key)
        elif low.isalpha() and low.upper() in _shelf_letters(state):
            _shelf(host, low.upper(), screen, read_key, title=_shelf_label(state, low.upper()))
        # any other key: ignore — the highlight is the guide


def _ack_snooze_cb(
    host: Host, selection: tuple[str, object], low: str
) -> Callable[[object], str | None] | None:
    """The host callback a key would fire on the CURRENT selection, or ``None`` when
    the keypress is not a context-sensitive ack/snooze.

    Returns ``host.ack`` for 'a' / ``host.snooze`` for 's' — but ONLY when the
    selected row is a needs-you item AND the host wired that callback. In every
    other case (a different key, a pill/shelf selected, or the callback absent) it
    returns ``None`` so the caller falls through to the unchanged shelf-letter
    handler. This single predicate is what keeps the new keybind from ever shadowing
    xbook's 'a'=shelf-A hotkey: with ``host.ack`` None it returns None for 'a'."""
    if selection[0] != "need":
        return None
    if low == "a":
        return host.ack
    if low == "s":
        return host.snooze
    return None


def _ack_snooze_need(
    host: Host,
    need: object,
    low: str,
    screen: Screen,
    read_key: Callable[[], str],
) -> None:
    """Fire the ack ('a') / snooze ('s') callback for ``need``, then show its
    confirmation. The host callback owns the action (and, for snooze, the duration);
    the shell only renders the short message it returns and waits for a key, after
    which ``_home``'s loop re-captures state on its next pass so the acked/snoozed
    item drops from the redraw. A ``None`` / empty return falls back to a neutral
    confirmation so the operator always gets feedback that the key landed."""
    cb = host.ack if low == "a" else host.snooze
    assert cb is not None  # guarded by _ack_snooze_cb before we get here
    verb = "Acknowledged" if low == "a" else "Snoozed"
    message = cb(need) or verb
    _show(screen, r.render_note(verb, message), read_key)


def _activate(
    host: Host,
    item: tuple[str, object],
    state: CockpitState,
    screen: Screen,
    read_key: Callable[[], str],
) -> None:
    kind, ref = item
    if kind == "shelf" and isinstance(ref, str):
        _shelf(host, ref, screen, read_key, title=_shelf_label(state, ref))
        return
    if not isinstance(ref, int):
        return
    if kind == "pill":
        host.activate_pill(state.pills[ref], screen, read_key)
        return
    _activate_need(host, state.needs[ref], screen, read_key)


def _activate_need(host: Host, need, screen: Screen, read_key: Callable[[], str]) -> None:
    """Drill a needs-you item — the single activation path shared by a needs-you ⏎
    (``_activate``) and a filtered-need ⏎ (``_filter``), so a need found through the
    filter opens identically to one selected on the home screen."""
    if need.capability_key and host.get_capability(need.capability_key):
        # A needs-you item can carry a focus (e.g. "Bills overdue" → "overdue"),
        # threaded into the walk's WizardContext so it opens scoped to that subset.
        _open_capability(host, need.capability_key, screen, read_key, focus=need.focus)
    else:
        _show(screen, r.render_note(need.title, need.detail), read_key)


def _shelf(
    host: Host,
    letter: str,
    screen: Screen,
    read_key: Callable[[], str],
    *,
    title: str | None = None,
) -> None:
    specs = [s for s in host.get_capabilities() if s.shelf == letter]
    if not specs:
        return
    # A shelf with exactly one spec has no real choice to make — open it directly
    # instead of forcing a second ⏎ through a one-row "browse" menu. For the fleet,
    # every worker-shelf is single-spec, so this removes a detour on every drill;
    # xbook's multi-spec shelves still get the menu (the branch below).
    if len(specs) == 1:
        _open_capability(host, specs[0].key, screen, read_key)
        return
    # The menu title names the worker (fleet roster) or xbook's shelf taxonomy.
    # Default to the canonical SHELVES name so callers that don't pass one (xbook)
    # are unchanged.
    menu_title = title if title is not None else render.SHELVES[letter]
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
        screen.update(r.render_menu(menu_title, options, selected=sel, opens=opens, peak=peak))
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


@dataclass(frozen=True)
class _FilterMatch:
    """One filter hit — a capability OR a needs-you item — carrying its display
    title/summary (so ``render_filter`` reads it like a CapabilitySpec) plus the
    drill it triggers on ⏎. A need's ``activate`` routes through ``_activate_need``,
    the same path a needs-you ⏎ takes, so a filtered need opens identically."""

    title: str
    summary: str
    activate: Callable[[Screen, Callable[[], str]], None]


def _filter(host: Host, screen: Screen, read_key: Callable[[], str]) -> None:
    """Type-to-filter the things on screen — capabilities AND needs-you items — by
    name; ↑↓ moves, Enter drills, Esc always cancels. ``q`` also cancels when the
    term is empty (consistency with every other screen); once a term is typed, ``q``
    is a normal search char so a term containing 'q' stays searchable."""
    state = host.capture_state()
    term, sel = "", 0
    while True:
        matches = _matches(host, state, term)
        if matches:
            sel %= len(matches)
        screen.update(
            r.render_filter(
                term,
                matches,
                selected=(sel if matches else None),
                title=state.filter_title,
            )
        )
        key = read_key()
        if key == keys.ESC:
            return
        # q quits the filter only with an empty term — once the operator has typed
        # something, q is a normal search char (so "bq" etc. stay searchable).
        if key == "q" and not term:
            return
        if key == keys.ENTER:
            if matches:
                matches[sel].activate(screen, read_key)
            return
        if key == keys.UP and matches:
            sel = (sel - 1) % len(matches)
        elif key == keys.DOWN and matches:
            sel = (sel + 1) % len(matches)
        elif key == keys.BACKSPACE:
            term, sel = term[:-1], 0
        elif len(key) == 1 and key.isprintable():
            term, sel = term + key, 0


def _matches(host: Host, state: CockpitState, term: str) -> list[_FilterMatch]:
    """The filter's candidate set: capabilities (title/summary) PLUS the rendered
    needs-you items (title/detail). A need that isn't a capability — the bridge's
    cross-worker alerts — is otherwise invisible to the filter; matching it here and
    routing ⏎ to ``_activate_need`` makes the filter find what's actually on screen.
    With no needs (xbook's typical use) this reduces to the capability-only match."""
    t = term.strip().lower()
    if not t:
        return []
    # Needs come first: the match list is capped at 9 downstream, and a need (the
    # cross-worker thing the operator most wants to find) must survive truncation
    # ahead of a common-substring flood of capability matches. Order WITHIN each
    # group is left stable (R4). With no needs (xbook's typical use) this reduces to
    # the capability-only list, unchanged.
    out: list[_FilterMatch] = []
    for need in state.needs:
        if t in need.title.lower() or t in need.detail.lower():
            out.append(_FilterMatch(need.title, need.detail, _need_activation(host, need)))
    for s in host.get_capabilities():
        if t in s.title.lower() or t in s.summary.lower():
            out.append(_FilterMatch(s.title, s.summary, _capability_activation(host, s.key)))
    return out


def _capability_activation(host: Host, key: str) -> Callable[[Screen, Callable[[], str]], None]:
    """The drill a filtered capability fires on ⏎ — the open-capability chokepoint,
    bound to ``key``."""
    return lambda scr, rk: _open_capability(host, key, scr, rk)


def _need_activation(host: Host, need) -> Callable[[Screen, Callable[[], str]], None]:
    """The drill a filtered need fires on ⏎ — ``_activate_need``, the SAME path a
    needs-you ⏎ takes, bound to this ``need`` (so its focus/note carry through)."""
    return lambda scr, rk: _activate_need(host, need, scr, rk)
