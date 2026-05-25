"""Pure render functions for the cockpit — the locked visual style contract
(warm charcoal terminal, cream text, amber accent, blue toolkit label, two-tier
severity dots, no emoji). All functions return Rich renderables; the caller
draws them onto the alternate screen. A `selection`/`selected` argument marks
the highlighted row so the operator can arrow through the cockpit.

This module holds the FRAMEWORK render primitives + visual language — the
palette/glyphs/styles, the window frame, the home screen (header/pulse/
needs-you/toolkit), the walk/doctor/filter/usage chrome — shared by every
domain screen. The domain screens themselves are supplied by each worker."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rich import box
from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from clonway_cockpit.registry import BlastRadius, CapabilitySpec
from clonway_cockpit.state import CockpitState, NeedsItem, Pill

if TYPE_CHECKING:
    from clonway_cockpit.doctor import Fix, Probe


ACCENT = "#d18d54"  # warm amber — dates, needs-you numbers, the badge, warn, the ❯ cursor
BLUE = "#7a9cc6"  # muted blue — the toolkit label
DIM = "grey50"  # secondary text — timestamps, detail, the toolkit body
# Informative-but-de-emphasised text (a not-clearable row's £ amount, the
# terminal-only Doctor tag) sits at grey42 — above the contrast floor so it stays
# readable for low vision (P-2). The very dimmest grey30 is reserved for pure
# decoration (a not-present shelf letter).
_DIM_INFO = "grey42"
_KEY_STYLE = "bold white"  # legend hotkeys — bright so they pop off the dim line
# The single irreversible keystroke (apply) gets the amber-badge inverse — the
# same escalation as the needs-you count — so the money-moving key reads as
# different IN KIND from save/cancel/not-now (which stay _KEY_STYLE).
_APPLY_KEY_STYLE = f"bold black on {ACCENT}"
_DOT = {"ok": "#7faa7f", "warn": ACCENT, "error": "#e06c6c"}
# Severity travels in the GLYPH as well as the hue, so it survives monochrome and
# red-green colourblindness (BMP geometric/symbol chars, not emoji).
_PILL_GLYPH = {"ok": "●", "warn": "◐", "error": "✗"}
_CURSOR = "❯"  # highlighted-row marker (U+276F — not an emoji)
_NOT_STYLE = "#d18d54"  # amber — the no-fabrication rule made visible


# The negation tokens that carry the no-fabrication emphasis (amber). Includes the
# plain-English forms (Doesn't / Don't / Won't) now that the copy leads with plain
# words rather than the shouty all-caps "NOT" — the emphasis stays on the negation.
_NOT_TOKENS = ("NOT", "Doesn't", "doesn't", "Don't", "don't", "Won't", "won't")


def _highlight_not(line: str) -> Text:
    """Return a Rich Text that renders a negation token (NOT / Doesn't / Don't /
    Won't) in amber — the no-fabrication rule made visible, kept emphasised even
    after the copy moved from all-caps NOT to plain English."""
    t = Text()
    pattern = "|".join(re.escape(tok) for tok in _NOT_TOKENS)
    parts = re.split(rf"\b({pattern})\b", line)
    for part in parts:
        if part in _NOT_TOKENS:
            t.append(part, style=_NOT_STYLE)
        else:
            t.append(part)
    return t


# Shelf taxonomy (display names) lives here — the lowest-dependency cockpit
# module — so a catalog can re-export it without a render->catalog import cycle.
SHELVES: dict[str, str] = {
    "A": "Daily rhythm",
    "B": "Money in",
    "C": "Money out",
    "D": "Cash flow & forecasting",
    "E": "People & payroll",
    "F": "Compliance & reports",
    "G": "Diagnostics & setup",
}


_PANEL_WIDTH = 96  # a fixed, comfortable window width so the cockpit keeps the
# reference's proportions instead of floating, left-anchored, in a huge terminal


def page(body: RenderableType) -> RenderableType:
    """Frame a screen as a fixed-width window centred in the terminal — so it
    reads as a contained app (reference proportions), not bare text lost in a
    sea of black on a maximised terminal."""
    window = Panel(
        body,
        box=box.ROUNDED,
        border_style=DIM,
        width=_PANEL_WIDTH,
        padding=(1, 3),
    )
    return Align(window, align="center", vertical="middle")


def render_header(state: CockpitState) -> RenderableType:
    t = Text()
    t.append(state.app_label, style="bold")
    t.append(" · ", style=DIM)
    t.append(state.date_label, style=ACCENT)
    t.append(" · ", style=DIM)
    t.append(state.time_label, style=ACCENT)
    t.append(" · ", style=DIM)
    t.append(state.tenant_name)
    if state.tenant_id:
        t.append(f" (tenant {state.tenant_id})", style=DIM)
    return t


def _pill_text(p: Pill, *, selected: bool = False) -> Text:
    # The ❯ cursor (amber) prefixes the selected pill so the operator can see
    # which source ⏎ will sync; an unselected pill keeps a leading space so the
    # dots stay column-aligned across the grid.
    t = Text(f"{_CURSOR} " if selected else "  ", style=ACCENT)
    t.append(f"{_PILL_GLYPH[p.level]} ", style=_DOT[p.level])
    t.append(f"{p.label:<9}", style="bold" if selected else "")
    t.append(f"{p.status:<7}", style=DIM)
    if p.detail:
        t.append(p.detail, style=DIM)
    return t


def render_pulse(state: CockpitState, *, selected: int | None = None) -> RenderableType:
    if not state.pills:
        return Text("pulse   no feed data yet — run a sync", style=DIM)
    grid = Table(show_header=False, box=None, padding=(0, 3), pad_edge=False)
    grid.add_column(style=DIM)
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)
    pills = list(state.pills)
    # The gutter carries a one-word verb cue (H-2) so the three home grammars read
    # distinctly: pulse rows ⏎ to sync. The cue rides the second gutter row when
    # there is one; a single-row pulse keeps just the label.
    n_rows = (len(pills) + 1) // 2
    gutter = ["pulse"] + [""] * (n_rows - 1)
    if n_rows > 1:
        gutter[1] = "⏎ sync"
    for r, i in enumerate(range(0, len(pills), 2)):
        left = _pill_text(pills[i], selected=selected == i)
        right = (
            _pill_text(pills[i + 1], selected=selected == i + 1) if i + 1 < len(pills) else Text("")
        )
        grid.add_row(gutter[r], left, right)
    return grid


def _marker_cell(text: str, *, selected: bool) -> Text:
    """An amber number/key cell, prefixed with the ❯ cursor when selected."""
    return Text(f"{_CURSOR if selected else ' '} {text}", style=ACCENT)


def render_needs_you(
    needs: tuple[NeedsItem, ...], *, selected: int | None = None
) -> RenderableType:
    head = Text("needs you  ", style=DIM)
    if not needs:
        head.append("nothing pending — all caught up", style=DIM)
        return head
    head.append(f" {len(needs)} ", style=f"bold black on {ACCENT}")
    head.append(" item" if len(needs) == 1 else " items", style=DIM)
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(no_wrap=True)  # ❯ + number
    table.add_column(no_wrap=True)  # title
    table.add_column(style=DIM)  # detail
    for i, item in enumerate(needs):
        is_sel = selected == i
        table.add_row(
            _marker_cell(f"{i + 1}.", selected=is_sel),
            Text(item.title, style="bold" if is_sel else ""),
            item.detail,
        )
    return Group(head, Text(""), table)


def render_toolkit(specs: list[CapabilitySpec], *, selected: str | None = None) -> RenderableType:
    present = {s.shelf for s in specs}

    def _cell(letter: str | None) -> Text:
        if letter is None:
            return Text("")
        is_sel = letter == selected
        body_style = "bold" if is_sel else (DIM if letter in present else "grey30")
        t = Text(f"{_CURSOR if is_sel else ' '} ", style=ACCENT)
        t.append(f"{letter}. {SHELVES[letter]}", style=body_style)
        return t

    letters = list(SHELVES)
    half = (len(letters) + 1) // 2
    left, right = letters[:half], letters[half:]
    table = Table(show_header=False, box=None, padding=(0, 3), pad_edge=False)
    table.add_column(style=BLUE)
    table.add_column()
    table.add_column()
    # The gutter carries a one-word verb cue (H-2): toolkit shelves open with the
    # A–G letters. The cue rides the second gutter row when there is one.
    gutter: list[str | Text] = ["toolkit", *([""] * (half - 1))]
    if half > 1:
        gutter[1] = Text("A–G", style=DIM)
    for i in range(half):
        table.add_row(gutter[i], _cell(left[i]), _cell(right[i] if i < len(right) else None))
    return table


def chip(cli: str) -> Text:
    """The inset `equivalent CLI` command chip (P2) — shared by walks + cards."""
    t = Text("equivalent CLI  ", style=DIM)
    t.append(f" {cli.strip()} ", style="bold white on grey23")
    return t


def _apply_key() -> Text:
    """The escalated ``[a]pply`` token — amber-inverse, padded so the badge has
    breathing room — so the one irreversible key reads as different in kind from
    the save/cancel/not-now keys (which stay ``_KEY_STYLE``). Shared by the three
    review footers (H-3)."""
    return Text(" [a]pply ", style=_APPLY_KEY_STYLE)


def screen_header(label: str, title: str, hint: str = "") -> RenderableType:
    """The consistent top bar for every sub-screen: a rule, an amber label + bold
    title on the left with an optional dim hint right-aligned, then a rule."""
    row = Table(show_header=False, box=None, padding=0, expand=True)
    row.add_column(justify="left")
    row.add_column(justify="right", style=DIM)
    left = Text()
    left.append(f"{label}  ", style=ACCENT)
    left.append(title, style="bold")
    row.add_row(left, hint)
    return Group(row, Rule(style=DIM))


def render_menu(
    title: str,
    options: list[tuple[str, str, str]],
    *,
    label: str = "browse",
    selected: int | None = None,
    opens: list[int] | None = None,
    peak: int = 0,
) -> RenderableType:
    """A shelf/filter picker in the cockpit's language: amber ❯-marked numbers,
    cream titles, dim summaries. ``options`` is a list of (key, title, summary).

    ``opens`` (optional, parallel to ``options``) carries each capability's
    lifetime open count; ``peak`` is the global max across ALL capabilities, so the
    inline usage notch — a single dim block glyph trailing the summary — scales
    relative to the busiest tool. A zero-open row renders NO glyph (blank), so
    "never used" reads as absence; the notch is a single trailing char that never
    pushes or wraps the title/summary. ``opens=None`` → no notch (today's look)."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(style=DIM)
    # The notch sits in its own trailing column so it can never push or wrap the
    # title/summary — Rich allots it one cell; a blank string takes none.
    show_notch = opens is not None and peak > 0
    if show_notch:
        table.add_column(no_wrap=True, justify="right", style=_DIM_INFO)
    for i, (key, otitle, summary) in enumerate(options):
        is_sel = selected == i
        cells: list[RenderableType] = [
            _marker_cell(f"{key}.", selected=is_sel),
            Text(otitle, style="bold" if is_sel else ""),
            summary,
        ]
        if show_notch:
            n = opens[i] if opens is not None and i < len(opens) else 0
            cells.append(Text(usage_notch(n, peak), style=_DIM_INFO))
        table.add_row(*cells)
    back_sel = selected == len(options)
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
    label: str, frame: str = SPINNER_FRAMES[0], elapsed: int = 0, latest: str = ""
) -> RenderableType:
    """Animated 'working…' screen for a blocking sync — a spinner ``frame`` +
    the ``label`` + ``elapsed`` seconds on one line, an optional dim
    latest-activity line below (e.g. the current stage), then a calm reassurance
    so a long pull never reads as hung. Framed via ``page()``; the cockpit loop
    redraws it in place with a fresh ``frame``/``elapsed`` ~8×/second."""
    head = Text("  ")
    head.append(f"{frame} ", style=ACCENT)
    head.append(label)
    head.append(f"   {elapsed}s", style=DIM)
    parts: list[RenderableType] = [Text(""), head]
    if latest:
        parts.append(Text(f"  {latest}", style=DIM))
    else:
        parts.append(Text("  this can take up to a minute", style=DIM))
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


def render_help() -> RenderableType:
    rows = [
        ("↑ ↓", "move the highlight"),
        ("← →", "jump between the two columns (pulse pills · toolkit shelves)"),
        ("⏎", "open the item · sync the selected pulse pill"),
        ("1–9", "jump to a needs-you item"),
        ("A–G", "open a toolkit shelf"),
        ("/", "filter capabilities by name"),
        ("r", "refresh the cockpit"),
        ("q / esc", "back · quit"),
    ]
    body = Text()
    for k, d in rows:
        body.append(f"  {k:<9}", style=_KEY_STYLE)
        body.append(f"{d}\n", style=DIM)
    return page(Group(screen_header("help", "Keys", "any key to return"), Text(""), body))


def render_doctor(
    probes: list[Probe],
    fixes: list[Fix],
    *,
    selected: int | None = None,
    usage: dict | None = None,
    specs: list[CapabilitySpec] | None = None,
    app_label: str = "xbook",
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

    if fixes:
        parts.append(Text(""))
        ftable = Table(show_header=False, box=None, padding=(0, 2))
        ftable.add_column(no_wrap=True)  # ❯ + index
        ftable.add_column(no_wrap=True)  # title
        ftable.add_column(overflow="fold")  # chip / tag
        run_i = 0
        for f in fixes:
            if f.run is not None:
                is_sel = selected == run_i
                run_i += 1
                ftable.add_row(
                    _marker_cell(f"{run_i}.", selected=is_sel),
                    Text(f.title, style="bold" if is_sel else ""),
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
        parts.append(_doctor_footer())

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
        pct = round((applied / opened) * 100)
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


def render_filter(
    term: str, matches: list[CapabilitySpec], *, selected: int | None = None
) -> RenderableType:
    typed = Text()
    typed.append("  filter  ", style=DIM)
    typed.append(term or "type to filter…", style="bold" if term else DIM)
    parts: list[RenderableType] = [
        screen_header("filter", "Find a tool", "⏎ open · esc back"),
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


def _legend() -> Text:
    # Plain-English voice (reference) trimmed to one line for the 96-col window.
    # Number hotkeys (1–9) still work; they live in the ? help screen rather than
    # crowding the legend.
    legend = Text("▸ Press ", style=DIM)
    legend.append("↑↓←→", style=_KEY_STYLE)
    legend.append(" to move · ", style=DIM)
    legend.append("⏎", style=_KEY_STYLE)
    legend.append(" to open / sync · ", style=DIM)
    legend.append("A–G", style=_KEY_STYLE)
    legend.append(" to browse · ", style=DIM)
    legend.append("/", style=_KEY_STYLE)
    legend.append(" to filter · ", style=DIM)
    legend.append("?", style=_KEY_STYLE)
    legend.append(" for help · ", style=DIM)
    legend.append("q", style=_KEY_STYLE)
    legend.append(" to quit", style=DIM)
    return legend


def render_cockpit_screen(
    state: CockpitState,
    specs: list[CapabilitySpec],
    *,
    selection: tuple[str, object] | None = None,
) -> RenderableType:
    sel_pill = selection[1] if selection and selection[0] == "pill" else None
    sel_need = selection[1] if selection and selection[0] == "need" else None
    sel_shelf = selection[1] if selection and selection[0] == "shelf" else None
    return page(
        Group(
            render_header(state),
            Rule(style=DIM),
            Text(""),
            render_pulse(state, selected=sel_pill),  # type: ignore[arg-type]
            # "needs you" gets a touch more vertical breathing room than pulse /
            # toolkit (H-2) so it reads as the primary "do this now" zone.
            Text(""),
            Text(""),
            render_needs_you(state.needs, selected=sel_need),  # type: ignore[arg-type]
            Text(""),
            Text(""),
            render_toolkit(specs, selected=sel_shelf),  # type: ignore[arg-type]
            Text(""),
            Rule(style=DIM),
            _legend(),
        )
    )
