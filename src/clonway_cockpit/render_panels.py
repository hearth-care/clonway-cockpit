"""Flow, Doctor, filter, and progress render panels for clonway-cockpit."""

# ruff: noqa: F401,F403,F405
from __future__ import annotations

import io
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from rich import box
from rich.align import Align
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from clonway_cockpit.audit_log import AuditEvent
from clonway_cockpit.doctor import DoctorActionKind, DoctorFocusState, Fix, Probe, action_kind
from clonway_cockpit.model import Field as MField
from clonway_cockpit.model import Region as MRegion
from clonway_cockpit.model import Row as MRow
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import BlastRadius, CapabilitySpec
from clonway_cockpit.render_chrome import *
from clonway_cockpit.render_chrome import (
    _DIM_INFO,
    _DOT,
    _KEY_STYLE,
    ACCENT,
    DIM,
    MenuItem,
    _highlight_not,
    _marker_cell,
    chip,
    normalize_menu_items,
    page,
    screen_header,
)
from clonway_cockpit.state import CockpitState, NeedsItem, Pill


def render_menu(
    title: str,
    options: Sequence[MenuItem | tuple[str, str, str]],
    *,
    label: str = "browse",
    selected: int | None = None,
    opens: list[int] | None = None,
    peak: int = 0,
) -> RenderableType:
    """A shelf/filter picker in the cockpit's language: amber ❯-marked shortcuts,
    cream titles, dim summaries. ``options`` is a list of ``MenuItem`` (or a
    legacy ``(key, title, summary)`` tuple, normalized once at this boundary —
    see :func:`normalize_menu_items`), so the shortcut cell renders EXACTLY the
    token the shell's dispatch map honours. A row with no shortcut (shelf-
    capacity overflow) renders a blank marker cell — never a fake multi-
    character token — and stays reachable by arrow + Enter.

    ``opens`` (optional, parallel to ``options``) carries each capability's
    lifetime open count; ``peak`` is the global max across ALL capabilities, so the
    inline usage notch — a single dim block glyph trailing the summary — scales
    relative to the busiest tool. A zero-open row renders NO glyph (blank), so
    "never used" reads as absence; the notch is a single trailing char that never
    pushes or wraps the title/summary. ``opens=None`` → no notch (today's look)."""
    items = normalize_menu_items(options)
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(style=DIM)
    # The notch sits in its own trailing column so it can never push or wrap the
    # title/summary — Rich allots it one cell; a blank string takes none.
    show_notch = opens is not None and peak > 0
    if show_notch:
        table.add_column(no_wrap=True, justify="right", style=_DIM_INFO)
    for i, item in enumerate(items):
        is_sel = selected == i
        marker = f"{item.shortcut}." if item.shortcut else ""
        cells: list[RenderableType] = [
            _marker_cell(marker, selected=is_sel),
            Text(item.title, style="bold" if is_sel else ""),
            item.summary,
        ]
        if show_notch:
            n = opens[i] if opens is not None and i < len(opens) else 0
            cells.append(Text(usage_notch(n, peak), style=_DIM_INFO))
        table.add_row(*cells)
    back_sel = selected == len(items)
    table.add_row(
        _marker_cell("q.", selected=back_sel),
        Text("Back", style="bold" if back_sel else DIM),
        "",
    )
    return page(Group(screen_header(label, title, "↑↓ move · ⏎ select · q back"), Text(""), table))


def render_capability_card(spec: CapabilitySpec) -> RenderableType:
    """A reference-only capability shown in the walk pre-flight language — header
    bar, `what this does`, the equivalent-CLI chip — clearly marked not-yet-a-walk."""
    return page(
        Group(
            screen_header("▸", spec.title, "any key to return"),
            Text(""),
            Text("what this does", style=DIM),
            Text(f"  {spec.summary}"),
            Text(""),
            chip(spec.equivalent_cli),
            Text(""),
            Text(
                "  not yet a guided walk — run the command above (Wave 2 wires this up)", style=DIM
            ),
        )
    )


def render_preflight(
    *,
    title: str,
    blast_radius: BlastRadius,
    preconditions: list,
    equivalent_cli: str,
    progress: str = "",
    ready: bool = True,
    remedy=None,
) -> RenderableType:
    """Screen 02 — what-this-does / blast-radius (NOT highlighted amber) /
    preconditions (✓/✗) / equivalent-CLI chip / footer. Framed via page().

    When not ``ready`` and a blocked precondition carries a ``walk.Remedy``,
    the footer offers its one-key hint (e.g. ``press [u] to clear the stale
    apply lock``) so the dead-end becomes actionable; otherwise it shows the
    plain "fix the above first · press any key" message."""
    hint = f"{progress} · ‹esc› cancel" if progress else "‹esc› cancel"
    parts: list[RenderableType] = [
        screen_header("walk", title, hint),
        Text(""),
        Text("what this does", style=DIM),
        Text(f"  {blast_radius.summary}"),
        Text(""),
        Text("what changes", style=DIM),
    ]
    for d in blast_radius.details:
        parts.append(Text("  ") + _highlight_not(d))
    if blast_radius.reversible:
        parts.append(Text(f"  {blast_radius.reversible}", style=DIM))
    parts.append(Text(""))
    parts.append(Text("preconditions", style=DIM))
    for p in preconditions:
        row = Text("  ")
        row.append("✓ " if p.ok else "✗ ", style="#7faa7f" if p.ok else "#e06c6c")
        row.append(f"{p.label:<22}")
        if p.detail:
            row.append(p.detail, style=DIM)
        parts.append(row)
    parts.append(Text(""))
    parts.append(chip(equivalent_cli))
    parts.append(Text(""))
    if ready:
        footer = Text("  ")
        footer.append("▸ ", style=ACCENT)
        footer.append("Continue?  ", style=DIM)
        footer.append("[Y]es", style=_KEY_STYLE)
        footer.append(" · ", style=DIM)
        footer.append("[n]o", style=_KEY_STYLE)
        parts.append(footer)
    elif remedy is not None:
        footer = Text("  ")
        footer.append("▸ ", style=ACCENT)
        footer.append("preconditions not met — press ", style="#e06c6c")
        footer.append(f"[{remedy.key}]", style=_KEY_STYLE)
        footer.append(f" to {remedy.label}", style="#e06c6c")
        footer.append(" · any other key to go back", style=DIM)
        parts.append(footer)
    else:
        footer = Text("  ")
        footer.append("▸ ", style=ACCENT)
        footer.append("preconditions not met — fix the above first", style="#e06c6c")
        footer.append(" · press any key", style=DIM)
        parts.append(footer)
    return page(Group(*parts))


def render_remedy_confirm(remedy) -> RenderableType:
    """A one-key confirm screen for an inline pre-flight remedy — the same gate
    grammar Doctor uses (``render_doctor_confirm``), surfaced before the remedy
    runs. ``remedy`` is a ``walk.Remedy``."""
    body = Text("  ")
    body.append("▸ ", style=ACCENT)
    body.append(f"{remedy.label.capitalize()}?  ", style=DIM)
    body.append("[y]es", style=_KEY_STYLE)
    body.append(" / ", style=DIM)
    body.append("⏎", style=_KEY_STYLE)
    body.append(" · ", style=DIM)
    body.append("any other key cancels", style=DIM)
    return page(
        Group(
            screen_header("walk", remedy.label.capitalize(), "confirm"),
            Text(""),
            body,
        )
    )


def render_walk_progress(message: str, progress: str = "") -> RenderableType:
    """Transient 'working…' screen while a non-interactive beat runs (build /
    apply). Framed. ``progress`` is an optional ``step N of M`` line in the same
    dim look as the screen-header hint, so the walk's step count stays continuous
    even on the screens with no operator stop (M-1 / N-1)."""
    parts: list[RenderableType] = [Text(""), Text(f"  {message}", style=DIM)]
    if progress:
        parts.append(Text(f"  {progress}", style=DIM))
    parts.append(Text(""))
    return page(Group(*parts))


# A no-emoji braille spinner (BMP — not an emoji) cycled while a blocking sync
# runs, so "Syncing…" visibly animates instead of reading as frozen.
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def render_sync_progress(
    label: str,
    frame: str = SPINNER_FRAMES[0],
    elapsed: int = 0,
    latest: str = "",
    lines: tuple[str, ...] = (),
) -> RenderableType:
    """Animated 'working…' screen for a blocking sync — a spinner ``frame`` +
    the ``label`` + ``elapsed`` seconds on one line, then a dim activity region
    below, then a calm reassurance so a long pull never reads as hung. Framed
    via ``page()``; the cockpit loop redraws it in place with a fresh
    ``frame``/``elapsed`` ~8×/second.

    ``lines`` is a snapshot of the live-log ring buffer: when non-empty each
    entry is rendered as a dim row beneath the spinner head, replacing the calm
    reassurance (the buffer's activity IS the reassurance). ``latest`` is kept
    for backwards compat with callers that haven't migrated to the buffer yet;
    when both ``latest`` and ``lines`` are given, ``lines`` takes precedence."""
    head = Text("  ")
    head.append(f"{frame} ", style=ACCENT)
    head.append(label)
    head.append(f"   {elapsed}s", style=DIM)
    parts: list[RenderableType] = [Text(""), head]
    if lines:
        for line in lines:
            parts.append(Text(f"  {line}", style=DIM))
    elif latest:
        parts.append(Text(f"  {latest}", style=DIM))
    else:
        parts.append(Text("  this can take up to a minute", style=DIM))
    parts.append(Text(""))
    return page(Group(*parts))


_STAGE_GLYPH = {"done": "✓", "pending": "·", "skipped": "⚠"}
_STAGE_STYLE = {"done": _DOT["ok"], "active": ACCENT, "pending": DIM, "skipped": ACCENT}


def render_staged_progress(
    label: str,
    stages: Sequence,
    frame: str = SPINNER_FRAMES[0],
    elapsed: int = 0,
    *,
    hint: str = "",
    hint_after_s: int = 60,
    controls: str = "",
) -> RenderableType:
    """Staged 'working…' screen: a spinner ``frame`` + ``label`` + ``elapsed`` on
    the head line, then one row per stage — ``✓`` done / the live ``frame`` active /
    ``·`` pending / ``⚠`` skipped, label + dim detail. Shows ``hint`` once
    ``elapsed >= hint_after_s`` so a long sync never reads as hung. Reuses the
    sync-progress head + the preflight ✓-row style; no new glyph/colour. Framed
    via ``page()``; the loop redraws with a fresh ``frame``/``elapsed``.

    When ``controls`` is set (e.g. ``"q cancel"``), it is appended dim to the
    head line so the operator knows how to abort."""
    head = Text("  ")
    head.append(f"{frame} ", style=ACCENT)
    head.append(label)
    head.append(f"   {elapsed}s", style=DIM)
    if controls:
        head.append(f"   {controls}", style=DIM)
    parts: list[RenderableType] = [Text(""), head]
    for i, st in enumerate(stages):
        glyph = frame if st.status == "active" else _STAGE_GLYPH.get(st.status, "·")
        # Tree connector so the stages read as children of the spinner head, not
        # as a flat sibling list — └─ on the last row, ├─ above it.
        connector = "└─ " if i == len(stages) - 1 else "├─ "
        row = Text("  ")
        row.append(connector, style=DIM)
        row.append(f"{glyph} ", style=_STAGE_STYLE.get(st.status, DIM))
        row.append(f"{st.label:<22}")
        if st.detail:
            row.append(st.detail, style=DIM)
        parts.append(row)
    if hint and elapsed >= hint_after_s:
        parts.append(Text(""))
        parts.append(Text(f"  {hint}", style=DIM))
    parts.append(Text(""))
    return page(Group(*parts))


def render_walk_result(
    title: str, *, ok: bool, message: str, links: list[tuple[str, str]] | None = None
) -> RenderableType:
    """Final walk screen — a ✓/✗ + outcome lines + 'press any key to return'. Framed.

    ``links`` is an optional list of ``(label, url)`` pairs for the entities a
    confirmed post created — rendered as a "view in Xero" section of amber,
    underlined OSC-8 hyperlinks (clickable in modern terminals; plain text
    elsewhere). ``None``/empty leaves the screen unchanged."""
    lines = message.split("\n")
    first = lines[0] if lines else ""
    head = Text("  ")
    head.append("✓ " if ok else "✗ ", style="#7faa7f" if ok else "#e06c6c")
    head.append(first)
    parts: list[RenderableType] = [
        screen_header("walk", title, "done"),
        Text(""),
        head,
    ]
    for extra in lines[1:]:
        parts.append(Text(f"  {extra}", style=DIM))
    if links:
        parts.append(Text(""))
        parts.append(Text("  view in Xero", style=DIM))
        for label, url in links:
            row = Text("  ")
            # Rich's ``link <url>`` style emits an OSC-8 hyperlink — clickable in
            # modern terminals; the alt-screen preserves it.
            row.append(label, style=f"{ACCENT} underline link {url}")
            parts.append(row)
    parts.append(Text(""))
    parts.append(Text("  press any key to return", style=DIM))
    return page(Group(*parts))


def render_note(title: str, detail: str) -> RenderableType:
    return page(
        Group(
            screen_header("▸", title, "any key to return"), Text(""), Text(f"  {detail}", style=DIM)
        )
    )


def render_ledger(events: Sequence[AuditEvent]) -> RenderableType:
    table = Table(show_header=True, box=None, padding=(0, 2), pad_edge=False)
    table.add_column("time", style=DIM)
    table.add_column("worker")
    table.add_column("event")
    table.add_column("capability")
    table.add_column("actor")
    table.add_column("outcome")
    for event in events:
        table.add_row(
            event.ts.astimezone(UTC).strftime("%H:%M"),
            event.worker,
            event.event,
            event.capability_key or "",
            event.actor,
            event.outcome or "",
        )
    return page(Group(screen_header("audit", "fleet audit log", "metadata only"), Text(""), table))


# The default home help body (key, description) — shared by render_help and
# model_help so the rendered help and its semantic twin can never drift.
DEFAULT_HELP_LINES: tuple[tuple[str, str], ...] = (
    ("↑ ↓", "move the highlight"),
    ("← →", "jump between the two columns (pulse pills · toolkit shelves)"),
    ("⏎", "open the item · sync the selected pulse pill"),
    ("1–9", "jump to a needs-you item"),
    ("A–G", "open a toolkit shelf"),
    ("/", "filter capabilities by name"),
    ("r", "refresh the cockpit"),
    ("q / esc", "back · quit"),
)
# Compatibility spelling for workers pinned before the public facade. Keep both
# names bound to the exact same immutable tuple.
_DEFAULT_HELP_LINES = DEFAULT_HELP_LINES


def render_help(
    help_lines: tuple[tuple[str, str], ...] | None = None,
) -> RenderableType:
    """The help screen. ``help_lines`` (key, description) pairs override the body so
    a worker (the Fleet Cockpit) can describe its own keys — workers, not shelves;
    no dead "sync"; the real letter set. ``None`` → xbook's verbatim help, so the
    extracting worker is byte-identical. The chrome (title + border + return hint) is
    the same either way."""
    rows = list(help_lines) if help_lines is not None else list(_DEFAULT_HELP_LINES)
    body = Text()
    for k, d in rows:
        body.append(f"  {k:<9}", style=_KEY_STYLE)
        body.append(f"{d}\n", style=DIM)
    return page(Group(screen_header("help", "Keys", "any key to return"), Text(""), body))


_FOCUS_VERDICTS = {
    DoctorFocusState.MATCHED: ("✓ ", "green", "{identity} matched"),
    DoctorFocusState.PRESENT: ("⚠ ", ACCENT, "{identity} present — no runnable remedy"),
    DoctorFocusState.AMBIGUOUS: ("⚠ ", ACCENT, "{identity} ambiguous — review selection"),
    DoctorFocusState.UNKNOWN: ("⚠ ", ACCENT, "{identity} not found — review selection"),
}


def _focus_line(
    focus_requested: str,
    focus_matched: str | None,
    focus_state: str | None,
    focus_row_label: str | None = None,
) -> Text:
    """The human projection of the focus verdict — the same facts the model reports
    in ``meta.focus_state``/``meta.focus_row``/``meta.focus_matched``, so neither
    projection can claim a target is absent while the other shows it on screen, nor
    claim a match for a row the cursor has left.

    ``focus_state`` is the RESOLUTION verdict; ``focus_matched`` additionally says
    the cursor is on the resolved row. A resolved focus the operator has navigated
    away from renders as "matched — cursor on <row>" rather than a bare ✓, because a
    bare ✓ next to a cursor on somebody else's state-changing remedy is the same lie
    the model contract forbids.

    ``focus_state=None`` is the legacy two-valued call (matched / not): derive the
    verdict from ``focus_matched`` so an older caller renders exactly as before."""
    state = focus_state or (
        DoctorFocusState.MATCHED if focus_matched is not None else DoctorFocusState.UNKNOWN
    )
    glyph, glyph_style, template = _FOCUS_VERDICTS.get(
        DoctorFocusState(state), _FOCUS_VERDICTS[DoctorFocusState.UNKNOWN]
    )
    resolved = state == DoctorFocusState.MATCHED
    on_focus = resolved and focus_matched is not None
    line = Text("focus     ", style="bold")
    if on_focus:
        line.append(glyph, style=glyph_style)
    else:
        line.append("⚠ ", style=ACCENT)
    line.append(
        template.format(identity=focus_matched if on_focus else focus_requested),
        style=DIM if on_focus else ACCENT,
    )
    if resolved and not on_focus:
        line.append(
            f" — cursor on {focus_row_label}" if focus_row_label else " — cursor moved",
            style=ACCENT,
        )
    return line


def render_doctor(
    probes: list[Probe],
    fixes: list[Fix],
    *,
    selected: int | None = None,
    usage: dict | None = None,
    specs: list[CapabilitySpec] | None = None,
    app_label: str = "xbook",
    focus_requested: str | None = None,
    focus_matched: str | None = None,
    focus_state: str | None = None,
    focus_row: int | None = None,
) -> RenderableType:
    """The Doctor screen — the same probe table + verdict as the static view, but
    the fixes become a navigable list. ``selected`` indexes the RUNNABLE fixes
    (those with a ``run``); a runnable fix gets an amber ❯-markable row, while a
    display-only fix (``run is None`` — e.g. browser auth) renders dimmed with a
    "(run in a terminal)" tag and no cursor. ``selected=None`` paints the
    non-interactive view (the QA shot + ``doctor_renderable`` use this).

    When ``usage`` is provided, a calm read-only "what you reach for" section is
    appended BELOW the fixes (most-used / never-used / completion) — secondary to
    the health probes. ``usage=None`` omits it entirely (today's behaviour).

    ``app_label`` controls the screen title (e.g. "xbook doctor" vs "Clonway Office
    doctor"); defaults to "xbook" so existing callers are unchanged."""
    head = Text(f"{app_label} doctor ", style="bold")
    head.append(f"deep health check · {len(probes)} probes", style=DIM)

    probe_body = Text()
    for p in probes:
        probe_body.append("● ", style=_DOT[p.level])
        probe_body.append(f"{p.name:<22}")  # uniform weight — severity is the dot + colour
        probe_body.append(f"{p.level:<6}", style=_DOT[p.level])
        probe_body.append(f"{p.detail}\n", style="" if p.level == "error" else DIM)

    warns = sum(1 for p in probes if p.level == "warn")
    errs = sum(1 for p in probes if p.level == "error")
    glyph = "⚠" if (warns or errs) else "✓"
    vline = Text("verdict   ", style="bold")
    vline.append(
        f"{glyph} {warns} warning(s) · {errs} error(s)",
        style=ACCENT if (warns or errs) else "green",
    )

    parts: list[RenderableType] = [head, Rule(style=DIM), probe_body, Rule(style=DIM), vline]

    if focus_requested is not None:
        parts.append(
            _focus_line(
                focus_requested,
                focus_matched,
                focus_state,
                f"row {focus_row + 1}" if focus_row is not None else None,
            )
        )

    if fixes:
        parts.append(Text(""))
        ftable = Table(show_header=False, box=None, padding=(0, 2))
        ftable.add_column(no_wrap=True)  # ❯ + index
        ftable.add_column(no_wrap=True)  # title
        ftable.add_column(overflow="fold")  # chip / tag
        run_i = 0
        for f in fixes:
            kind = action_kind(f)
            if kind is not DoctorActionKind.DISPLAY_ONLY:
                is_sel = selected == run_i
                run_i += 1
                title = f"Open {f.title}" if kind is DoctorActionKind.OPEN_CAPABILITY else f.title
                ftable.add_row(
                    _marker_cell(f"{run_i}.", selected=is_sel),
                    Text(title, style="bold" if is_sel else ""),
                    chip(f.cmd),
                )
            else:
                # Display-only fix: the title, the terminal-only tag and the note
                # all carry information, so they sit at the readable _DIM_INFO
                # floor (P-2); only the non-selectable "-" marker stays decoration.
                cells: list[RenderableType] = [chip(f.cmd)]
                cells.append(Text("  (run in a terminal)", style=_DIM_INFO))
                if f.note:
                    cells.append(Text(f"  {f.note}", style=_DIM_INFO))
                ftable.add_row(
                    Text("  -", style="grey30"),
                    Text(f.title, style=_DIM_INFO),
                    Group(*cells),
                )
        parts.append(ftable)
        parts.append(Text(""))
        # Show the full move/run footer only when at least one fix is runnable.
        # Display-only fixes (run=None) make ↑↓ and ⏎ no-ops, so advertising them
        # misleads the operator — fall back to the back-only footer in that case.
        if any(action_kind(f) is not DoctorActionKind.DISPLAY_ONLY for f in fixes):
            parts.append(_doctor_footer())
        else:
            parts.append(_doctor_back_only_footer())
    else:
        # A read-only Doctor (no runnable fixes — e.g. the Fleet Doctor) still needs
        # an exit cue, or the screen is a cul-de-sac. Show only "q back" — there's no
        # "⏎ run" / "↑↓ move" because nothing is runnable.
        parts.append(Text(""))
        parts.append(_doctor_back_only_footer())

    # "What you reach for" — appended BELOW the fixes, dim/secondary so it doesn't
    # compete with the health probes. Only when usage telemetry is supplied.
    if usage is not None:
        parts.append(Text(""))
        parts.append(Rule(style=DIM))
        parts.append(render_usage_section(usage, specs or []))

    return page(Group(*parts))


def _doctor_footer() -> Text:
    footer = Text("  ")
    footer.append("↑↓", style=_KEY_STYLE)
    footer.append(" move · ", style=DIM)
    footer.append("⏎", style=_KEY_STYLE)
    footer.append(" run · ", style=DIM)
    footer.append("q", style=_KEY_STYLE)
    footer.append(" back", style=DIM)
    return footer


def _doctor_back_only_footer() -> Text:
    """The read-only Doctor footer (D2): just "q back" — no move/run keys, since a
    Doctor with no runnable fixes has nothing to navigate or execute."""
    footer = Text("  ")
    footer.append("q", style=_KEY_STYLE)
    footer.append(" back", style=DIM)
    return footer


# --- Usage telemetry ("What you reach for") ----------------------------------
# The inline-notch heat bar: a 7-step block ramp (more used = taller), rendered
# in _DIM_INFO so it recedes. Zero use renders NOTHING (blank), so "never used"
# reads as absence, not a stunted bar.
_NOTCH_GLYPHS = "▁▂▃▄▅▆▇"
# The three posting walks whose completion rate (applied/open) the Doctor section
# reports — keyed by capability key → display title.
_COMPLETION_WALKS: tuple[tuple[str, str], ...] = (
    ("schedule-bills", "Schedule bills"),
    ("payroll-clear", "Clear payroll"),
    ("apply-remittance", "Apply remittance"),
)
# Cap the never-used list so a fresh install (everything unused) can't flood the
# Doctor screen; the remainder folds into a "+K more" line.
_MAX_NEVER_USED = 8


def usage_notch(opens: int, peak: int) -> str:
    """A single block glyph whose height scales ``opens`` against the global
    ``peak`` (the most-used capability's open count). Zero opens → "" (blank), so
    a never-used row reads as absence; the busiest tool (opens == peak) gets the
    tallest glyph; a lightly-used tool gets the shortest. Floor-scaled so a small
    count against a big peak reads as the smallest bar, not a mid one."""
    if opens <= 0 or peak <= 0:
        return ""
    if opens >= peak:
        return _NOTCH_GLYPHS[-1]
    idx = int((opens / peak) * (len(_NOTCH_GLYPHS) - 1))
    return _NOTCH_GLYPHS[idx]


def _relative_last(iso: str | None) -> str:
    """A calm 'last touched' label — 'today' / 'yesterday' / 'Nd ago', falling
    back to the date for older / unparseable values. Best-effort: a bad value
    degrades to the raw string's date portion or '—'."""
    if not iso:
        return "—"
    try:
        when = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso[:10] or "—"
    now = datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    days = (now.date() - when.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days}d ago"
    return when.date().isoformat()


def _opens(usage: dict, key: str) -> int:
    """The integer ``open`` count for ``key`` (0 if absent / malformed)."""
    row = usage.get(key)
    if not isinstance(row, dict):
        return 0
    n = row.get("open")
    return n if isinstance(n, int) else 0


def render_usage_section(usage: dict, specs: list[CapabilitySpec]) -> RenderableType:
    """The Doctor "What you reach for" block — a calm, read-only, dim/secondary
    summary that recedes behind the health probes + fixes. Three parts:

    * **Most used** — top ~5 capabilities by ``open`` (title · N opens · last …).
    * **Never used** — capabilities in ``specs`` with no ``open`` record (the
      diagnostic the operator wants: undiscovered vs useless), capped + "+K more".
    * **Completion** — for the three posting walks only: opened · applied · P%.

    Degrades to a single dim "no usage recorded yet" line when ``usage`` is empty.
    Pure render — non-interactive text, drawn below the fixes."""
    head = Text("what you reach for ", style="bold")
    head.append("local · this machine only", style=_DIM_INFO)

    if not usage:
        return Group(
            head,
            Text(""),
            Text("  no usage recorded yet — open a few tools and check back", style=_DIM_INFO),
        )

    spec_by_key = {s.key: s for s in specs}

    def _title(key: str) -> str:
        spec = spec_by_key.get(key)
        if spec is not None:
            return spec.title
        if key.startswith("pulse:"):
            return f"Sync {key.split(':', 1)[1].title()} (pulse)"
        return key

    parts: list[RenderableType] = [head, Text("")]

    # Most used — top 5 by open count (skip zero-open rows, e.g. a row that only
    # ever recorded a cancelled outcome).
    ranked = sorted(
        ((k, _opens(usage, k)) for k in usage),
        key=lambda kv: kv[1],
        reverse=True,
    )
    ranked = [(k, n) for k, n in ranked if n > 0]
    if ranked:
        parts.append(Text("  most used", style=DIM))
        for key, n in ranked[:5]:
            row = Text("    ")
            row.append(f"{_title(key):<26}", style="")
            row.append(f"{n} open{'s' if n != 1 else ''}", style=DIM)
            last = usage.get(key, {}).get("last") if isinstance(usage.get(key), dict) else None
            row.append(f" · last {_relative_last(last)}", style=_DIM_INFO)
            parts.append(row)

    # Never used — specs with no open record (cap + "+K more").
    never = [s for s in specs if _opens(usage, s.key) == 0]
    if never:
        parts.append(Text(""))
        parts.append(Text("  never used", style=DIM))
        shown = never[:_MAX_NEVER_USED]
        titles = ", ".join(s.title for s in shown)
        line = Text("    ")
        line.append(titles, style=_DIM_INFO)
        if len(never) > _MAX_NEVER_USED:
            line.append(f"  +{len(never) - _MAX_NEVER_USED} more", style=_DIM_INFO)
        parts.append(line)

    # Completion — the three posting walks (applied / open), skipping 0-open walks.
    comp_rows: list[Text] = []
    for key, title in _COMPLETION_WALKS:
        crow = usage.get(key)
        if not isinstance(crow, dict):
            continue
        opened = _opens(usage, key)
        applied_val = crow.get("applied")
        applied = applied_val if isinstance(applied_val, int) else 0
        if opened <= 0:
            continue
        # Telemetry can record an apply without a matching open (re-entry, a reset
        # between sessions), making applied > opened — which would render an
        # incoherent "5 opened · 26 applied". Clamp the displayed applied to opened
        # so the line reads sensibly (the pct is then naturally ≤ 100).
        applied = min(applied, opened)
        pct = min(100, round((applied / opened) * 100))
        line = Text("    ")
        line.append(f"{title:<26}", style="")
        line.append(f"{opened} opened · {applied} applied · {pct}%", style=DIM)
        comp_rows.append(line)
    if comp_rows:
        parts.append(Text(""))
        parts.append(Text("  completion  (posting walks)", style=DIM))
        parts.extend(comp_rows)

    return Group(*parts)


def render_doctor_confirm(fix: Fix) -> RenderableType:
    """A one-key confirm screen for a state-changing Doctor fix — the same gate
    pattern the walks use, surfaced before an irreversible keypress."""
    body = Text("  ")
    body.append("▸ ", style=ACCENT)
    body.append(f"{fix.title}?  ", style=DIM)
    body.append("[y]es", style=_KEY_STYLE)
    body.append(" / ", style=DIM)
    body.append("⏎", style=_KEY_STYLE)
    body.append(" · ", style=DIM)
    body.append("any other key cancels", style=DIM)
    return page(
        Group(
            screen_header("doctor", fix.title, "confirm"),
            Text(""),
            chip(fix.cmd),
            Text(""),
            body,
        )
    )


class _FilterRow(Protocol):
    """The shape ``render_filter`` reads from each match — a title + a summary. Both
    a ``CapabilitySpec`` and the shell's needs-aware filter match satisfy it, so the
    filter can list capabilities AND needs-you items (F1) without this primitive
    importing the shell's match type."""

    @property
    def title(self) -> str: ...

    @property
    def summary(self) -> str: ...


def render_filter(
    term: str,
    matches: Sequence[_FilterRow],
    *,
    selected: int | None = None,
    title: str | None = None,
) -> RenderableType:
    # The header title defaults to xbook's single-worker "Find a tool"; a worker
    # whose filter finds more than tools (the Fleet Cockpit finds workers AND needs)
    # passes its own title so the header names what's actually being searched.
    typed = Text()
    typed.append("  filter  ", style=DIM)
    typed.append(term or "type to filter…", style="bold" if term else DIM)
    parts: list[RenderableType] = [
        screen_header("filter", title or "Find a tool", "⏎ open · esc back"),
        Text(""),
        typed,
        Text(""),
    ]
    if term and not matches:
        parts.append(Text(f"  no match for {term!r}", style=DIM))
    else:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(style=DIM)
        for i, s in enumerate(matches[:9]):
            is_sel = selected == i
            table.add_row(
                _marker_cell(f"{i + 1}.", selected=is_sel),
                Text(s.title, style="bold" if is_sel else ""),
                s.summary,
            )
        parts.append(table)
    return page(Group(*parts))


__all__ = [name for name in globals() if not name.startswith("__")]
