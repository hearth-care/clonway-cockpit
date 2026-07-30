"""Menu input parity: the normalized MenuItem shape, the deterministic shortcut
alphabet, Rich/model parity, and the shell's one dispatch map + legacy
multi-digit agent alias — for shelves of every size. Root Backspace (the other
half of this plan) is covered in tests/test_shell.py and tests/test_serve_stdio.py."""

from __future__ import annotations

import pytest
from rich.console import Console

from clonway_cockpit import keys, render, shell
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.render_chrome import (
    MENU_SHORTCUT_ALPHABET,
    MenuItem,
    assign_menu_shortcuts,
    normalize_menu_items,
)
from clonway_cockpit.state import CockpitState


def _text(frame) -> str:
    con = Console(record=True, width=160)
    con.print(frame)
    return con.export_text()


def _keys(seq):
    """A scripted key reader: returns each token, then 'q' forever (so any
    nested loop still terminates if the script runs out)."""
    buf = list(seq)

    def _next():
        return buf.pop(0) if buf else "q"

    return _next


class _Screen:
    def __init__(self):
        self.frames = []

    def update(self, renderable):
        self.frames.append(renderable)


class _NullUsage:
    """A usage stand-in that never touches disk — load()/record() are no-ops."""

    def load(self) -> dict:
        return {}

    def record(self, key: str, action: str = "open") -> None:
        return None


class _CountingUsage:
    """Records each ``record(key, "open")`` call so a test can assert an exact
    open count (usage/audit launch counts must remain one per press)."""

    def __init__(self) -> None:
        self.opens: dict[str, int] = {}

    def load(self) -> dict:
        return {}

    def record(self, key: str, action: str = "open") -> None:
        if action == "open":
            self.opens[key] = self.opens.get(key, 0) + 1


def _walk_ctx(screen, read_key, *, focus=None):
    return WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda prompt, default: "",
        confirm_fn=lambda prompt: False,
        present=screen.update,
        read_key=read_key,
        focus=focus,
    )


def _host(state: CockpitState | None = None, **over) -> shell.Host:
    base = dict(
        capture_state=lambda: state or CockpitState(tenant_name="Clonway"),
        build_walk_ctx=_walk_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=_NullUsage(),
        on_open=lambda: None,
    )
    base.update(over)
    return shell.Host(**base)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_capabilities()
    yield
    clear_capabilities()


def _register_shelf(n: int, shelf: str = "B") -> dict[str, list]:
    """Register ``n`` reference-only-turned-run capabilities on ``shelf``; each
    key's run appends True to its own list in the returned dict, so a test can
    assert exactly which capability opened."""
    ran: dict[str, list] = {}
    for i in range(1, n + 1):
        key = f"cap-{i}"
        marks: list = []
        ran[key] = marks
        register_capability(
            CapabilitySpec(
                key=key,
                shelf=shelf,
                title=f"Cap {i}",
                summary=f"summary {i}",
                equivalent_cli="x",
                run=lambda ctx, marks=marks: marks.append(True),
            )
        )
    return ran


# --- MenuItem validation + legacy tuple normalization --------------------------


def test_menu_item_rejects_nonpositive_ordinal():
    with pytest.raises(ValueError):
        MenuItem(ordinal=0, title="x", summary="s")


@pytest.mark.parametrize("bad", ["q", "Q", "10", "enter", "", "-", "AB"])
def test_menu_item_rejects_invalid_shortcut(bad):
    with pytest.raises(ValueError):
        MenuItem(ordinal=1, title="x", summary="s", shortcut=bad)


def test_menu_item_accepts_none_and_valid_shortcuts():
    assert MenuItem(ordinal=1, title="x", summary="s", shortcut=None).shortcut is None
    assert MenuItem(ordinal=1, title="x", summary="s", shortcut="a").shortcut == "a"
    assert MenuItem(ordinal=1, title="x", summary="s", shortcut="1").shortcut == "1"


def test_normalize_menu_items_legacy_tuple_keeps_ordinal_and_shortcut():
    items = normalize_menu_items([("1", "Loans", "term loans"), ("2", "Insurance", "policies")])
    assert [(i.ordinal, i.shortcut) for i in items] == [(1, "1"), (2, "2")]


def test_normalize_menu_items_rejects_duplicate_shortcuts():
    with pytest.raises(ValueError):
        normalize_menu_items([MenuItem(1, "A", "s", "a"), MenuItem(2, "B", "s", "a")])


def test_normalize_menu_items_rejects_duplicate_ordinals():
    with pytest.raises(ValueError):
        normalize_menu_items([MenuItem(1, "A", "s", "a"), MenuItem(1, "B", "s", "b")])


# --- deterministic alphabet + exact token matrix (2/9/10/16/capacity/+1) -------


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (2, ["1", "2"]),
        (9, [str(i) for i in range(1, 10)]),
        (10, [*(str(i) for i in range(1, 10)), "a"]),
        (16, [*(str(i) for i in range(1, 10)), "a", "b", "c", "d", "e", "f", "g"]),
    ],
)
def test_assign_menu_shortcuts_exact_sequence(n, expected):
    assert assign_menu_shortcuts(n) == expected


def test_menu_shortcut_alphabet_excludes_q_and_has_34_unique_slots():
    assert "q" not in MENU_SHORTCUT_ALPHABET
    assert len(MENU_SHORTCUT_ALPHABET) == 34
    assert len(set(MENU_SHORTCUT_ALPHABET)) == 34


def test_assign_menu_shortcuts_at_capacity_and_overflow():
    capacity = len(MENU_SHORTCUT_ALPHABET)
    at_capacity = assign_menu_shortcuts(capacity)
    assert all(s is not None for s in at_capacity)
    assert at_capacity[-1] == MENU_SHORTCUT_ALPHABET[-1]
    overflow = assign_menu_shortcuts(capacity + 1)
    assert overflow[:-1] == at_capacity
    assert overflow[-1] is None  # beyond capacity: no fake token, ever


# --- Rich / model parity: same non-None tokens, one char, unique, no q --------


def _items_for(n: int) -> list[MenuItem]:
    shortcuts = assign_menu_shortcuts(n)
    return [
        MenuItem(ordinal=i + 1, title=f"T{i}", summary="s", shortcut=shortcuts[i]) for i in range(n)
    ]


@pytest.mark.parametrize("n", [2, 9, 10, 16, 34, 35])
def test_rich_and_model_advertise_the_same_tokens(n):
    items = _items_for(n)
    txt = _text(render.render_menu("Shelf", items))
    m = render.model_menu("Shelf", items)
    model_tokens = [a for a in m.actions if a not in ("up", "down", "enter", "q")]
    non_none = [it.shortcut for it in items if it.shortcut is not None]
    assert model_tokens == non_none
    assert len(model_tokens) == len(set(model_tokens))
    assert all(len(t) == 1 for t in model_tokens)
    assert "q" not in model_tokens
    for token in non_none:
        assert f"{token}." in txt
    # Row ids stay the stable ordinal identity, never the shortcut.
    assert [row.id for row in m.regions[0].rows[:-1]] == [f"option:{it.ordinal}" for it in items]


def test_overflow_row_has_no_fake_token_but_is_selectable():
    n = len(MENU_SHORTCUT_ALPHABET) + 1
    items = _items_for(n)
    txt = _text(render.render_menu("Shelf", items, selected=n - 1))
    m = render.model_menu("Shelf", items, selected=n - 1)  # select the overflow row
    assert m.selection == f"option:{n}"
    overflow_row = m.regions[0].rows[n - 1]
    assert not any(f.label == "shortcut" for f in overflow_row.fields)
    assert "10" not in m.actions  # no raw two-digit ordinal ever advertised
    assert f"T{n - 1}" in txt  # still rendered/selectable, just no shortcut cell


def test_option_10_no_longer_advertises_the_raw_ordinal_string():
    """RED-documenting regression: before this PR, a 10-item shelf advertised the
    literal (unenterable-by-a-human) two-character '10' as its shortcut/action."""
    items = _items_for(10)
    m = render.model_menu("Shelf", items)
    assert "10" not in m.actions
    assert "a" in m.actions


# --- shell: one dispatch map + legacy multi-digit agent alias ------------------


def test_shelf_ten_items_shortcut_a_opens_item_ten():
    ran = _register_shelf(10)
    host = _host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "a", "q"]), screen=scr)
    assert ran["cap-10"] == [True]
    assert all(v == [] for key, v in ran.items() if key != "cap-10")


def test_shelf_sixteen_items_shortcut_g_opens_item_sixteen():
    ran = _register_shelf(16)
    host = _host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "g", "q"]), screen=scr)
    assert ran["cap-16"] == [True]
    assert all(v == [] for key, v in ran.items() if key != "cap-16")


def test_uppercase_shortcut_normalizes_and_dispatches():
    ran = _register_shelf(10)
    host = _host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "A", "q"]), screen=scr)
    assert ran["cap-10"] == [True]


def test_legacy_multichar_ordinal_alias_still_opens_item_ten():
    """An agent that cached the old advertised (impossible-for-a-human) '10'
    still gets compatibility — it opens item 10 once, but the token is never
    rendered/advertised (proved in test_option_10_no_longer_advertises_the...)."""
    ran = _register_shelf(10)
    host = _host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "10", "q"]), screen=scr)
    assert ran["cap-10"] == [True]


def test_human_shaped_1_then_0_cannot_combine_into_item_ten():
    """Two SEPARATE single-key presses "1" then "0" must never retroactively
    combine — "1" opens item 1 immediately; the later "0" is a distinct input."""
    ran = _register_shelf(10)
    host = _host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "1", "0", "q"]), screen=scr)
    assert ran["cap-1"] == [True]
    assert ran["cap-10"] == []


def test_unknown_and_malformed_inputs_are_inert_in_shelf_menu():
    ran = _register_shelf(10)
    host = _host()
    scr = _Screen()
    # 'z' has no shortcut on a 10-item shelf (only 1-9,a exist); "xx" is a
    # multi-character non-digit — neither a real shortcut nor the legacy alias.
    shell.run_cockpit(host, read_key=_keys(["b", "z", "xx", "q"]), screen=scr)
    assert all(v == [] for v in ran.values())


def test_direct_token_opens_exact_capability_once():
    ran = _register_shelf(10)
    cu = _CountingUsage()
    host = _host(usage=cu)
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "a", "q"]), screen=scr)
    assert ran["cap-10"] == [True]
    assert cu.opens.get("cap-10") == 1
    assert "cap-1" not in cu.opens


def test_overflow_row_beyond_capacity_reachable_by_arrow_and_enter():
    capacity = len(MENU_SHORTCUT_ALPHABET)
    n = capacity + 1
    ran = _register_shelf(n)
    host = _host()
    scr = _Screen()
    # From the first row, UP wraps to Back, then UP again lands on the LAST real
    # row — the overflow item with no direct-action shortcut — proving it stays
    # arrow/Enter reachable regardless of n.
    shell.run_cockpit(host, read_key=_keys(["b", keys.UP, keys.UP, keys.ENTER, "q"]), screen=scr)
    assert ran[f"cap-{n}"] == [True]


def test_single_spec_shelf_direct_open_unchanged():
    """A shelf with exactly one capability still bypasses the menu entirely —
    the normalization must not force a one-row menu detour."""
    ran = _register_shelf(1)
    host = _host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "q"]), screen=scr)
    assert ran["cap-1"] == [True]
