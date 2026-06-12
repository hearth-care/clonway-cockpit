"""Page chrome and home-screen render primitives for clonway-cockpit."""

# ruff: noqa: F401
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

from clonway_cockpit.model import Field as MField
from clonway_cockpit.model import Region as MRegion
from clonway_cockpit.model import Row as MRow
from clonway_cockpit.model import ScreenModel
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


_PANEL_WIDTH = 96  # floor/reference width — the cockpit's minimum comfortable window
_PANEL_MAX_WIDTH = 140  # cap — grow into a wide terminal up to here, then stay centred
# (beyond ~140 cols a monospace wall of text gets hard to scan; the window stays
# centred so it still reads as a contained app, not text floating in a sea of black)


class _Page:
    """Frame a screen as a centred window that grows with the terminal up to
    ``_PANEL_MAX_WIDTH``, so the cockpit uses the available real estate without
    becoming an unreadably-wide wall of text. Sizes to the RENDERING console's
    width via the Rich console protocol — deterministic under a fixed-width test
    console, wide on a real terminal."""

    def __init__(self, body: RenderableType) -> None:
        self.body = body

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = min(options.max_width, _PANEL_MAX_WIDTH)
        window = Panel(
            self.body,
            box=box.ROUNDED,
            border_style=DIM,
            width=width,
            padding=(1, 3),
        )
        yield Align(window, align="center", vertical="middle")


def page(body: RenderableType) -> RenderableType:
    """Frame a screen as a centred, terminal-adaptive window — see :class:`_Page`."""
    return _Page(body)


_CRUMB_SEP = " ▸ "  # the cross-deck breadcrumb separator (U+25B8 — not an emoji)


def _breadcrumb_line(trail: tuple[str, ...]) -> Text:
    """The persistent 'A ▸ B ▸ C' mode-line under the header (Fleet-Cockpit §4.3).
    The crumb labels sit at the dim secondary weight; the ▸ joints carry the amber
    accent so the trail reads as navigation chrome, not body text. A lone crumb
    renders just itself — no dangling joint."""
    t = Text()
    for i, crumb in enumerate(trail):
        if i:
            t.append(_CRUMB_SEP, style=ACCENT)
        t.append(crumb, style=DIM)
    return t


def render_header(state: CockpitState) -> RenderableType:
    t = Text()
    t.append(state.app_label, style="bold")
    t.append(" · ", style=DIM)
    t.append(state.date_label, style=ACCENT)
    t.append(" · ", style=DIM)
    t.append(state.time_label, style=ACCENT)
    # The fleet bridge has no single tenant, so it leaves tenant_name empty — skip
    # the "· {tenant}" segment entirely rather than render a dangling "08:00 · ".
    if state.tenant_name:
        t.append(" · ", style=DIM)
        t.append(state.tenant_name)
        if state.tenant_id:
            t.append(f" (tenant {state.tenant_id})", style=DIM)
    # An optional persistent breadcrumb mode-line below the identity row. The xops
    # bridge supplies 'Fleet ▸ <worker> ▸ <walk>' so "where am I" survives the
    # shell-out boundary; the framework just renders the supplied trail. No crumb
    # (None or empty) → the bare identity Text, byte-identical to today, so the
    # extracting worker (xbook) is unchanged.
    if not state.breadcrumb:
        return t
    return Group(t, _breadcrumb_line(state.breadcrumb))


def _pill_text(p: Pill, *, selected: bool = False) -> Text:
    # The ❯ cursor (amber) prefixes the selected pill so the operator can see
    # which source ⏎ will sync; an unselected pill keeps a leading space so the
    # dots stay column-aligned across the grid.
    t = Text(f"{_CURSOR} " if selected else "  ", style=ACCENT)
    t.append(f"{_PILL_GLYPH[p.level]} ", style=_DOT[p.level])
    t.append(f"{p.label:<9}", style="bold" if selected else "")
    # Padded to <10 so a long status (the fleet bridge emits the 9-char "in-flight")
    # keeps a space before the detail instead of running together ("in-flight07:30");
    # xbook's short statuses (ran/idle/stale/synced ≤ 6) are unaffected — widening the
    # pad only adds trailing space, never removes the existing gap.
    t.append(f"{p.status:<10}", style=DIM)
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
        # The ⏎ cue defaults to "⏎ sync" (xbook syncs the selected pill); a worker
        # whose pills are read-only (the Fleet Cockpit) passes pulse_hint, e.g.
        # "⏎ open", so the gutter advertises the action it actually has.
        gutter[1] = state.pulse_hint if state.pulse_hint is not None else "⏎ sync"
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


def _letters_cue(letters: list[str]) -> str:
    """The second-gutter range cue for the toolkit — "A–G" style — derived from
    the actual letters laid out. Contiguous runs collapse to "first–last"; a gap
    splits into separate runs joined with ", " so the cue never asserts a phantom
    letter. So a contiguous [A..G] stays "A–G", the fleet's gapped [A,B,C,D,E,G]
    (no F) reads "A–E, G" — matching the legend instead of implying a live F — and
    a lone letter renders just itself."""
    if not letters:
        return ""
    runs: list[list[str]] = [[letters[0]]]
    for letter in letters[1:]:
        # Adjacency by code point: 'F' follows 'E', so a missing 'F' breaks the run.
        if ord(letter) == ord(runs[-1][-1]) + 1:
            runs[-1].append(letter)
        else:
            runs.append([letter])
    return ", ".join(run[0] if len(run) == 1 else f"{run[0]}–{run[-1]}" for run in runs)


def render_toolkit(
    specs: list[CapabilitySpec],
    *,
    selected: str | None = None,
    shelves: dict[str, str] | None = None,
    label: str = "toolkit",
) -> RenderableType:
    """The bottom home region — a 2-column letter grid of shelf rows.

    ``shelves`` (letter→display-name) overrides the default per-domain ``SHELVES``
    taxonomy: a worker (the Fleet Cockpit) passes its own map (the WORKERS roster)
    so the region reads its workers, not xbook's shelves. ``label`` is the dim
    gutter cue ("toolkit" for shelves, "workers" for the roster). Both default so
    the extracting worker (xbook) is unchanged. When a custom ``shelves`` is given,
    exactly those letters are laid out; the second-gutter range cue is derived from
    them, gap-aware (e.g. "A–E" for five workers, "A–E, G" for the bridge's gapped
    roster — never a phantom "A–G"), while the default keeps the canonical "A–G"."""
    shelf_map = shelves or SHELVES
    present = {s.shelf for s in specs}

    def _cell(letter: str | None) -> Text:
        if letter is None:
            return Text("")
        is_sel = letter == selected
        body_style = "bold" if is_sel else (DIM if letter in present else "grey30")
        t = Text(f"{_CURSOR if is_sel else ' '} ", style=ACCENT)
        t.append(f"{letter}. {shelf_map[letter]}", style=body_style)
        return t

    letters = list(shelf_map)
    half = (len(letters) + 1) // 2
    left, right = letters[:half], letters[half:]
    table = Table(show_header=False, box=None, padding=(0, 3), pad_edge=False)
    table.add_column(style=BLUE)
    table.add_column()
    table.add_column()
    # The gutter carries a one-word verb cue (H-2): the first row names the region
    # ("toolkit"/"workers"), the second carries the letter-range cue. For the
    # default taxonomy this stays the canonical "A–G"; a custom shelf map derives
    # the cue from its own letters so it never lies about the rows present.
    cue = "A–G" if shelves is None else _letters_cue(letters)
    gutter: list[str | Text] = [label, *([""] * (half - 1))]
    if half > 1:
        gutter[1] = Text(cue, style=DIM)
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


def _legend(state: CockpitState) -> Text:
    # Plain-English voice (reference) trimmed to one line for the 96-col window.
    # Number hotkeys (1–9) still work; they live in the ? help screen rather than
    # crowding the legend.
    #
    # Two app-aware bits keep the legend from lying about a different product:
    #  * the ⏎ cue — "open / sync" for xbook; a worker with no sync action (the
    #    Fleet Cockpit's read-only pills) passes state.legend_hint (e.g. "open
    #    worker") so the dead "sync" key isn't advertised.
    #  * the shelf segment — by default the letter-range cue ("A–E" for a
    #    five-worker roster, derived from state.shelves' actual letters; gap-aware,
    #    so the Fleet Cockpit's A,B,C,D,E,G shelves render "A–E, G", never a phantom
    #    "A–G") plus the verb "browse"; the default (shelves=None) stays the canonical
    #    "A–G to browse". A worker that wants its own verb — the Fleet Cockpit says a
    #    letter "open a worker", not "browse" — passes state.shelf_hint to render the
    #    whole segment verbatim instead (e.g. "A–E, G open a worker").
    enter_cue = state.legend_hint if state.legend_hint is not None else "open / sync"
    letters = list(state.shelves) if state.shelves is not None else list(SHELVES)
    range_cue = _letters_cue(letters) if state.shelves is not None else "A–G"
    legend = Text("▸ Press ", style=DIM)
    legend.append("↑↓←→", style=_KEY_STYLE)
    legend.append(" to move · ", style=DIM)
    legend.append("⏎", style=_KEY_STYLE)
    legend.append(f" to {enter_cue} · ", style=DIM)
    if state.shelf_hint is not None:
        legend.append(state.shelf_hint, style=_KEY_STYLE)
        legend.append(" · ", style=DIM)
    else:
        legend.append(range_cue, style=_KEY_STYLE)
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
    extra_regions: list[RenderableType] | None = None,
) -> RenderableType:
    """Compose the home screen. ``extra_regions`` (when supplied by a worker via
    ``Host.extra_regions``) is a list of additional Rich renderables inserted
    BETWEEN the needs-you region and the toolkit, so a worker can bolt on its
    own panel (e.g. xbook's statutory heads-up card) without monkey-patching
    this composition. Defaulted to None → no extras, byte-identical."""
    sel_pill = selection[1] if selection and selection[0] == "pill" else None
    sel_need = selection[1] if selection and selection[0] == "need" else None
    sel_shelf = selection[1] if selection and selection[0] == "shelf" else None
    extras: list[RenderableType] = []
    for region in extra_regions or []:
        extras.extend([Text(""), region])
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
            *extras,
            Text(""),
            Text(""),
            render_toolkit(
                specs,
                selected=sel_shelf,  # type: ignore[arg-type]
                shelves=state.shelves,
                label=state.toolkit_label,
            ),
            Text(""),
            Rule(style=DIM),
            _legend(state),
        )
    )


__all__ = [name for name in globals() if not name.startswith("__")]
