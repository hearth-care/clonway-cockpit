"""Agent ScreenModel twins for clonway-cockpit render primitives."""

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
from clonway_cockpit.model import Field as MField
from clonway_cockpit.model import Region as MRegion
from clonway_cockpit.model import Row as MRow
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import BlastRadius, CapabilitySpec
from clonway_cockpit.render_chrome import *
from clonway_cockpit.render_chrome import _PANEL_WIDTH, SHELVES, MenuItem, normalize_menu_items
from clonway_cockpit.render_panels import *
from clonway_cockpit.render_panels import _DEFAULT_HELP_LINES, _FilterRow
from clonway_cockpit.state import CockpitState, NeedsItem, Pill

if TYPE_CHECKING:
    from clonway_cockpit.doctor import Fix, Probe


def _selection_id(selection: tuple[str, object] | None) -> str | None:
    """Map the shell's ``(kind, ref)`` selection tuple to a stable Row id."""
    if not selection:
        return None
    kind, ref = selection
    return f"{kind}:{ref}"


def _home_actions(state: CockpitState) -> list[str]:
    """The keys the home loop honours — a deterministic, stable hint list."""
    letters = list(state.shelves) if state.shelves is not None else list(SHELVES)
    acts = ["up", "down", "left", "right", "enter", "/", "?", "r", "q", "backspace"]
    acts += [letter.lower() for letter in letters]
    acts += [str(i + 1) for i in range(min(9, len(state.needs)))]
    return acts


def model_cockpit_screen(
    state: CockpitState,
    specs: list[CapabilitySpec],
    *,
    selection: tuple[str, object] | None = None,
    extra_regions: list[RenderableType] | None = None,
    extra_model_regions: list[MRegion] | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_cockpit_screen`. Same inputs; structured out.

    Worker ``extra_regions`` are arbitrary Rich renderables (worker-owned), so they are
    not semanticised here — their count is recorded in ``meta``. A worker that wants
    those panels structured for an agent passes ``extra_model_regions`` instead: ready-made
    model ``Region``s, appended to ``regions`` after ``toolkit``."""
    present = {s.shelf for s in specs}
    shelf_map = state.shelves or SHELVES
    sel_id = _selection_id(selection)
    pulse_rows = [
        MRow(
            id=f"pill:{i}",
            label=p.label,
            fields=[
                # ``source`` is the stable sync-source key ("xero"/"lloyds") — exposed
                # so an agent keys on identity, not the positional ``pill:<i>`` order.
                MField("source", p.source or "", "id"),
                MField("status", p.status, "status"),
                MField("detail", p.detail),
                MField("level", p.level, "status"),
            ],
            selected=sel_id == f"pill:{i}",
        )
        for i, p in enumerate(state.pills)
    ]
    needs_rows = [
        MRow(
            id=f"need:{i}",
            label=n.title,
            fields=[
                MField("detail", n.detail),
                MField("level", n.level, "status"),
                # ``capability_key`` tells an agent whether ⏎ launches a walk (non-empty)
                # or just shows a note (empty); ``focus`` is the subset it opens scoped to.
                MField("capability_key", n.capability_key or "", "id"),
                MField("focus", n.focus or "", "id"),
            ],
            selected=sel_id == f"need:{i}",
        )
        for i, n in enumerate(state.needs)
    ]
    toolkit_rows = [
        MRow(
            id=f"shelf:{letter}",
            label=shelf_map[letter],
            enabled=letter in present,
            selected=sel_id == f"shelf:{letter}",
        )
        for letter in shelf_map
    ]
    meta: dict = {
        "app_label": state.app_label,
        "tenant_name": state.tenant_name,
        "date_label": state.date_label,
        "time_label": state.time_label,
        "extra_regions": len(extra_regions or []),
    }
    if state.breadcrumb:
        meta["breadcrumb"] = list(state.breadcrumb)
    regions = [
        MRegion("pulse", "pulse", rows=pulse_rows),
        MRegion("needs", "needs you", rows=needs_rows),
        MRegion("toolkit", state.toolkit_label, rows=toolkit_rows),
    ]
    regions.extend(extra_model_regions or [])
    return ScreenModel(
        kind="home",
        title=state.app_label,
        regions=regions,
        selection=sel_id,
        actions=_home_actions(state),
        meta=meta,
    )


def model_menu(
    title: str,
    options: Sequence[MenuItem | tuple[str, str, str]],
    *,
    label: str = "browse",
    selected: int | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_menu`. ``options`` is normalized the SAME
    way (see :func:`normalize_menu_items`) so the agent's advertised ``actions`` are
    exactly the shortcuts Rich renders — no `10`/`11`… fake multi-character tokens
    once a shelf passes nine items. A trailing ``back`` row mirrors the rendered
    Back option. ``selected`` indexes the normalized items, or ``len(items)`` for
    the Back row (matching the render). Row id stays the stable ``option:<ordinal>``
    even though the rendered/dispatched shortcut may differ from the ordinal
    (e.g. ordinal 10 → shortcut ``"a"``)."""
    items = normalize_menu_items(options)
    rows = [
        MRow(
            id=f"option:{item.ordinal}",
            label=item.title,
            fields=(
                [MField("summary", item.summary)]
                + ([MField("shortcut", item.shortcut)] if item.shortcut else [])
            ),
            selected=selected == i,
        )
        for i, item in enumerate(items)
    ]
    rows.append(MRow(id="back", label="Back", selected=selected == len(items)))
    sel_id: str | None = None
    if selected == len(items):
        sel_id = "back"
    elif selected is not None and 0 <= selected < len(items):
        sel_id = f"option:{items[selected].ordinal}"
    actions = ["up", "down", "enter", "q"] + [item.shortcut for item in items if item.shortcut]
    return ScreenModel(
        kind="shelf_menu",
        title=title,
        regions=[MRegion("menu", label, rows=rows)],
        selection=sel_id,
        actions=actions,
        meta={"label": label},
    )


def model_preflight(
    *,
    title: str,
    blast_radius: BlastRadius,
    preconditions: list,
    equivalent_cli: str,
    progress: str = "",
    ready: bool = True,
    remedy=None,
) -> ScreenModel:
    """The semantic twin of :func:`render_preflight`. Mirrors its keyword inputs.

    ``remedy`` is left unannotated (a ``walk.Remedy`` or None) to match
    ``render_preflight``'s signature exactly and keep the same mypy posture."""
    changes = [MRow(id=f"change:{i}", label=d) for i, d in enumerate(blast_radius.details)]
    precond_rows = [
        MRow(
            id=f"precond:{i}",
            label=p.label,
            fields=[MField("ok", str(p.ok), "status"), MField("detail", p.detail)],
            enabled=p.ok,
        )
        for i, p in enumerate(preconditions)
    ]
    if ready:
        actions = ["enter", "y", "n"]
    elif remedy is not None:
        actions = [remedy.key, "back"]
    else:
        actions = ["any"]
    meta: dict = {
        "equivalent_cli": equivalent_cli,
        "progress": progress,
        "ready": ready,
        "blast_radius_summary": blast_radius.summary,
        "reversible": blast_radius.reversible,
        "remedy": {"key": remedy.key, "label": remedy.label} if remedy is not None else None,
    }
    return ScreenModel(
        kind="walk.preflight",
        title=title,
        regions=[
            MRegion("what_this_does", "what this does", text=blast_radius.summary),
            MRegion("changes", "what changes", rows=changes, text=blast_radius.reversible or None),
            MRegion("preconditions", "preconditions", rows=precond_rows),
        ],
        actions=actions,
        meta=meta,
    )


def model_walk_result(
    title: str,
    *,
    ok: bool,
    message: str,
    links: list[tuple[str, str]] | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_walk_result`."""
    link_dicts = [{"label": lbl, "url": url} for lbl, url in (links or [])]
    return ScreenModel(
        kind="walk.result",
        title=title,
        regions=[MRegion("result", "", text=message)],
        actions=["any"],
        meta={"ok": ok, "message": message, "links": link_dicts},
    )


def model_note(title: str, detail: str) -> ScreenModel:
    """The semantic twin of :func:`render_note` — a titled prose leaf, any key returns."""
    return ScreenModel(
        kind="note",
        title=title,
        regions=[MRegion("prose", "", text=detail)],
        actions=["any"],
        meta={"detail": detail},
    )


def model_ledger(events: Sequence[AuditEvent]) -> ScreenModel:
    rows = [
        MRow(
            id=f"audit:{i}",
            label=event.ts.astimezone(UTC).strftime("%H:%M"),
            fields=[
                MField("worker", event.worker),
                MField("event", event.event),
                MField("capability", event.capability_key or ""),
                MField("actor", event.actor),
                MField("outcome", event.outcome or "", "status"),
            ],
        )
        for i, event in enumerate(events)
    ]
    return ScreenModel(
        kind="audit.ledger",
        title="fleet audit log",
        regions=[MRegion("ledger", "events", rows=rows)],
        actions=["any"],
        meta={"count": len(events)},
    )


def model_capability_card(spec: CapabilitySpec) -> ScreenModel:
    """The semantic twin of :func:`render_capability_card` — a reference-only
    capability (no walk yet): title, what-it-does prose, the equivalent-CLI."""
    return ScreenModel(
        kind="card",
        title=spec.title,
        regions=[MRegion("what_this_does", "what this does", text=spec.summary)],
        actions=["any"],
        meta={"equivalent_cli": spec.equivalent_cli, "summary": spec.summary},
    )


def model_help(
    help_lines: tuple[tuple[str, str], ...] | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_help`. ``help_lines`` (key, description)
    pairs override the default body, mirroring ``render_help``; the default is the
    shared ``_DEFAULT_HELP_LINES`` so the two can never drift."""
    rows_src = list(help_lines) if help_lines is not None else list(_DEFAULT_HELP_LINES)
    rows = [
        MRow(id=f"help:{i}", label=desc, fields=[MField("keys", k)])
        for i, (k, desc) in enumerate(rows_src)
    ]
    return ScreenModel(
        kind="help",
        title="Keys",
        regions=[MRegion("help", "Keys", rows=rows)],
        actions=["any"],
    )


def model_remedy_confirm(remedy) -> ScreenModel:  # noqa: ANN001 — mirrors render_remedy_confirm
    """The semantic twin of :func:`render_remedy_confirm` — the one-key gate before
    an inline pre-flight remedy runs. ``remedy`` is a ``walk.Remedy``."""
    label = remedy.label.capitalize()
    return ScreenModel(
        kind="confirm",
        title=label,
        regions=[MRegion("prose", "", text=f"{label}?")],
        actions=["enter", "y"],
        meta={"confirm_of": "remedy", "key": remedy.key, "label": remedy.label},
    )


def model_doctor_confirm(fix) -> ScreenModel:  # noqa: ANN001 — mirrors render_doctor_confirm
    """The semantic twin of :func:`render_doctor_confirm` — the one-key gate before a
    state-changing Doctor fix runs. ``fix`` is a ``doctor.Fix``."""
    return ScreenModel(
        kind="confirm",
        title=fix.title,
        regions=[MRegion("prose", "", text=f"{fix.title}?")],
        actions=["enter", "y"],
        meta={"confirm_of": "doctor_fix", "cmd": fix.cmd},
    )


def model_doctor(
    probes: list[Probe],
    fixes: list[Fix],
    *,
    selected: int | None = None,
    usage: dict | None = None,
    specs: list[CapabilitySpec] | None = None,
    app_label: str = "xbook",
) -> ScreenModel:
    """The semantic twin of :func:`render_doctor`. ``selected`` indexes the RUNNABLE
    fixes (those with a ``run``), matching the render. The read-only "what you reach
    for" usage block is telemetry display, not navigable structure, so it is not
    semanticised here (its presence is flagged in ``meta``)."""
    # Build the fixes first so we can give each probe a ``fix_id`` cross-reference —
    # the ``Probe.fix`` relationship the render shows by adjacency but the flat lists
    # would otherwise drop. Match by object identity (fixes_for returns the probes'
    # own Fix objects); a worker that rebuilds them simply gets no link (graceful).
    fix_rows: list[MRow] = []
    fix_id_by_obj: dict[int, str] = {}
    run_i = 0
    for i, f in enumerate(fixes):
        if f.run is not None:
            row_id = f"fix:{run_i}"
            fix_rows.append(
                MRow(
                    id=row_id,
                    label=f.title,
                    fields=[MField("cmd", f.cmd)],
                    selected=selected == run_i,
                    enabled=True,
                )
            )
            run_i += 1
        else:
            row_id = f"fix:display:{i}"
            fix_rows.append(
                MRow(
                    id=row_id,
                    label=f.title,
                    fields=[MField("cmd", f.cmd), MField("note", f.note)],
                    enabled=False,
                )
            )
        fix_id_by_obj[id(f)] = row_id

    def _probe_fields(p: Probe) -> list[MField]:
        fields = [MField("level", p.level, "status"), MField("detail", p.detail)]
        link = fix_id_by_obj.get(id(p.fix)) if p.fix is not None else None
        if link is not None:
            fields.append(MField("fix_id", link, "id"))
        return fields

    probe_rows = [
        MRow(id=f"probe:{i}", label=p.name, fields=_probe_fields(p)) for i, p in enumerate(probes)
    ]
    warns = sum(1 for p in probes if p.level == "warn")
    errs = sum(1 for p in probes if p.level == "error")
    if run_i > 0:
        actions = ["up", "down", "enter", "q"] + [str(n + 1) for n in range(run_i)]
        # Clamp to a runnable fix that exists (selected indexes RUNNABLE fixes).
        sel_id = f"fix:{selected}" if selected is not None and 0 <= selected < run_i else None
    else:
        actions = ["q"]
        sel_id = None
    meta: dict = {
        "app_label": app_label,
        "warnings": warns,
        "errors": errs,
        "ok": warns == 0 and errs == 0,
    }
    if usage:
        meta["usage_present"] = True
    return ScreenModel(
        kind="doctor",
        title=f"{app_label} doctor",
        regions=[
            MRegion("probes", "probes", rows=probe_rows),
            MRegion("fixes", "fixes", rows=fix_rows),
        ],
        selection=sel_id,
        actions=actions,
        meta=meta,
    )


def model_filter(
    term: str,
    matches: Sequence[_FilterRow],
    *,
    selected: int | None = None,
    title: str | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_filter`. Lists the (capped at 9) matches —
    capabilities and/or needs — each a row keyed ``match:<i>``; mirrors the rendered
    cap/back behaviour. ``selected`` indexes the shown matches."""
    shown = list(matches[:9])
    rows = [
        MRow(
            id=f"match:{i}",
            label=s.title,
            fields=[MField("summary", s.summary)],
            selected=selected == i,
        )
        for i, s in enumerate(shown)
    ]
    # Only point selection at a row that is actually shown — the render caps the list
    # at 9 and shows NO cursor for an off-screen ``selected``, so a model that minted
    # ``match:<selected>`` past the cap would be a phantom id (parity break).
    sel_id = f"match:{selected}" if selected is not None and 0 <= selected < len(shown) else None
    return ScreenModel(
        kind="filter",
        title=title or "Find a tool",
        regions=[MRegion("matches", "", rows=rows)],
        selection=sel_id,
        actions=["up", "down", "enter", "esc", "backspace"],
        meta={"term": term},
    )


def model_walk_progress(message: str, progress: str = "") -> ScreenModel:
    """The semantic twin of :func:`render_walk_progress` — a transient 'working…'
    leaf with no operator input."""
    return ScreenModel(
        kind="walk.progress",
        title="",
        regions=[MRegion("prose", "", text=message)],
        actions=[],
        meta={"message": message, "progress": progress},
    )


def model_sync_progress(
    label: str,
    *,
    latest: str = "",
    lines: tuple[str, ...] = (),
    elapsed: int = 0,
) -> ScreenModel:
    """The semantic twin of :func:`render_sync_progress`. The spinner ``frame`` is
    cosmetic and omitted; ``elapsed`` and the live-log ``lines`` carry the meaning."""
    rows = [MRow(id=f"log:{i}", label=ln) for i, ln in enumerate(lines)]
    return ScreenModel(
        kind="walk.progress",
        title="",
        regions=[MRegion("activity", label, rows=rows)],
        actions=[],
        meta={"label": label, "elapsed": elapsed, "latest": latest},
    )


def model_staged_progress(
    label: str,
    stages: Sequence,
    *,
    hint: str = "",
    elapsed: int = 0,
    controls: str = "",
) -> ScreenModel:
    """The semantic twin of :func:`render_staged_progress` — one row per stage with
    its status; ``controls`` (e.g. ``"q cancel"``) makes ``q`` an action."""
    rows = [
        MRow(
            id=f"stage:{st.key}",
            label=st.label,
            fields=[MField("status", st.status, "status"), MField("detail", st.detail)],
        )
        for st in stages
    ]
    return ScreenModel(
        kind="walk.progress",
        title="",
        regions=[MRegion("stages", label, rows=rows)],
        actions=["q"] if controls else [],
        meta={
            "label": label,
            "elapsed": elapsed,
            "hint": hint,
            "controls": controls,
            "stages": [
                {"key": s.key, "label": s.label, "status": s.status, "detail": s.detail}
                for s in stages
            ],
        },
    )


def model_unstructured(renderable: RenderableType, *, title: str = "") -> ScreenModel:
    """Fallback model for a screen not yet migrated to a ``model_*`` twin: capture the
    rendered text into a prose region and flag it explicitly as not-yet-semantic, so
    the driver still records a usable (if opaque) snapshot.

    ``file=io.StringIO()`` keeps ``con.print`` off the real process stdout — otherwise it
    would write the Rich panel straight into the agent's JSON channel under serve_stdio
    (it still records, so ``export_text`` is unaffected)."""
    con = Console(record=True, width=_PANEL_WIDTH, file=io.StringIO())
    con.print(renderable)
    return ScreenModel(
        kind="unstructured",
        title=title,
        regions=[MRegion("prose", "", text=con.export_text())],
        actions=["any"],
    )


__all__ = [name for name in globals() if not name.startswith("__")]
