"""The words a care-home owner sees on screen must not be developer words.

The model twins carry ids and region names that agents parse, so those stay
unchanged; only the drawn text is checked here, which has no structured twin."""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render
from clonway_cockpit.registry import BlastRadius
from clonway_cockpit.state import CockpitState, NeedsItem, Pill
from clonway_cockpit.walk import Precondition

BANNED = ("pulse", "equivalent CLI", "preconditions", "toolkit shelves", "walk")


def _text(renderable) -> str:
    con = Console(record=True, width=120)
    con.print(renderable)
    return con.export_text()


def _state(pills: bool = True) -> CockpitState:
    return CockpitState(
        tenant_name="Clonway Care",
        date_label="Fri 23 May 2026",
        time_label="06:45",
        tenant_id="9b40…",
        pills=(Pill("Xero", "synced", "06:45", "ok", "xero"),) if pills else (),
        needs=(NeedsItem("Bills overdue", "3", "error", "schedule-bills", "overdue"),),
    )


def _assert_plain(out: str) -> None:
    low = out.lower()
    for word in BANNED:
        assert word.lower() not in low, f"{word!r} is drawn on screen:\n{out}"


def _preflight(ready: bool, remedy=None) -> str:
    return _text(
        render.render_preflight(
            title="Schedule bills",
            blast_radius=BlastRadius(summary="Posts bills", details=("x",), reversible="y"),
            preconditions=[Precondition("Xero connected", False, "lock held")],
            equivalent_cli="xbook bills schedule",
            ready=ready,
            remedy=remedy,
        )
    )


def test_home_screen_has_no_developer_words():
    _assert_plain(_text(render.render_cockpit_screen(_state(), [])))
    _assert_plain(_text(render.render_cockpit_screen(_state(pills=False), [])))


def test_help_has_no_developer_words():
    _assert_plain(_text(render.render_help()))


def test_preflight_has_no_developer_words():
    _assert_plain(_preflight(ready=True))
    _assert_plain(_preflight(ready=False))
