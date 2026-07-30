"""Worker-declared Home action facts (menu-input-parity Task 4): a worker's
``handle_extra_key`` extension (e.g. xbook's park/wake 'z') is live for a human
but was invisible to an agent — ``_home_actions()`` only knew the framework's
own keys, and Needs rows carried no action field. ``NeedsItem.actions`` and
``CockpitState.home_actions`` are additive, backward-compatible state fields;
``model_cockpit_screen`` merges/normalizes them from the same snapshot already
rendered — no worker imports, no callbacks, no I/O."""

from __future__ import annotations

from clonway_cockpit import render
from clonway_cockpit.state import CockpitState, NeedsItem

# --- legacy construction stays byte-compatible ---------------------------------


def test_needs_item_legacy_positional_constructor_still_works():
    n = NeedsItem("Bills overdue", "2 bills", "warn", "schedule-bills")
    assert n.actions == ()


def test_needs_item_all_positional_fields_preserved_with_actions_appended_last():
    n = NeedsItem("T", "D", "warn", "cap", "focus-x", None, "src-1", ("z",))
    assert (n.title, n.detail, n.level, n.capability_key) == ("T", "D", "warn", "cap")
    assert (n.focus, n.due_at, n.source_id) == ("focus-x", None, "src-1")
    assert n.actions == ("z",)


def test_cockpit_state_legacy_constructor_still_works():
    state = CockpitState(tenant_name="Clonway")
    assert state.home_actions == ()


def test_worker_with_no_declarations_is_model_shape_compatible():
    """A worker that supplies neither NeedsItem.actions nor CockpitState.home_actions
    gets byte-identical Home model output to before this feature existed: no
    'actions' field on any Needs row, and the global actions list unaffected."""
    needs = (NeedsItem("Just a note", "fyi", "warn", ""),)
    state = CockpitState(tenant_name="Clonway", needs=needs)
    m = render.model_cockpit_screen(state, [], selection=None)
    need_row = next(r for reg in m.regions if reg.role == "needs" for r in reg.rows)
    assert not any(f.label == "actions" for f in need_row.fields)


# --- global home_actions: merge + dedupe ---------------------------------------


def test_home_actions_merge_worker_declared_action_into_global_actions():
    state = CockpitState(tenant_name="Clonway", home_actions=("z",))
    m = render.model_cockpit_screen(state, [], selection=None)
    assert "z" in m.actions


def test_home_actions_base_wins_ordering_worker_extra_appended():
    state = CockpitState(tenant_name="Clonway", home_actions=("z",))
    m = render.model_cockpit_screen(state, [], selection=None)
    # base framework actions ("up", "down", ... "q", "backspace", shelf letters)
    # all precede the worker-declared extra.
    assert m.actions.index("z") > m.actions.index("q")


def test_home_actions_already_in_base_is_not_duplicated():
    """A worker declaring an action the framework already exposes (e.g. 'q')
    must never shadow/duplicate it — base wins, worker extra appends ONLY when
    absent."""
    state = CockpitState(tenant_name="Clonway", home_actions=("q", "z"))
    m = render.model_cockpit_screen(state, [], selection=None)
    assert m.actions.count("q") == 1
    assert "z" in m.actions


def test_home_actions_duplicates_deduped_first_seen_order():
    state = CockpitState(tenant_name="Clonway", home_actions=("z", "z", "y", "z"))
    m = render.model_cockpit_screen(state, [], selection=None)
    tail = [a for a in m.actions if a in ("z", "y")]
    assert tail == ["z", "y"]


def test_home_actions_malformed_values_normalized_safely_never_crash():
    """Whitespace/control-only or non-string declarations must never crash Home
    or corrupt the frame — they're silently dropped."""
    state = CockpitState(tenant_name="Clonway", home_actions=("  ", "\x01", "", "  z  "))
    m = render.model_cockpit_screen(state, [], selection=None)
    assert "z" in m.actions  # the surrounding whitespace was trimmed
    assert "\x01" not in m.actions
    assert "" not in m.actions
    assert "  " not in m.actions


def test_home_actions_invalid_worker_hint_does_not_remove_framework_actions():
    state = CockpitState(tenant_name="Clonway", home_actions=("\x01",))
    m = render.model_cockpit_screen(state, [], selection=None)
    assert "q" in m.actions and "up" in m.actions and "enter" in m.actions


# --- per-Needs-row actions field ------------------------------------------------


def test_needs_row_actions_field_present_only_when_declared():
    needs = (
        NeedsItem("Park me", "deferred", "warn", "", actions=("enter", "z")),
        NeedsItem("Plain note", "fyi", "warn", ""),
    )
    state = CockpitState(tenant_name="Clonway", needs=needs)
    m = render.model_cockpit_screen(state, [], selection=None)
    need_rows = [r for reg in m.regions if reg.role == "needs" for r in reg.rows]
    declared = next(f for f in need_rows[0].fields if f.label == "actions")
    assert "enter" in declared.value and "z" in declared.value
    assert not any(f.label == "actions" for f in need_rows[1].fields)


def test_needs_row_actions_normalized_deduped_and_malformed_dropped():
    needs = (NeedsItem("Park me", "deferred", "warn", "", actions=("z", "z", "\x01", "enter")),)
    state = CockpitState(tenant_name="Clonway", needs=needs)
    m = render.model_cockpit_screen(state, [], selection=None)
    need_row = next(r for reg in m.regions if reg.role == "needs" for r in reg.rows)
    actions_field = next(f for f in need_row.fields if f.label == "actions")
    tokens = actions_field.value.split(",")
    assert tokens.count("z") == 1
    assert "\x01" not in tokens


def test_needs_row_actions_do_not_disturb_other_fields():
    needs = (
        NeedsItem(
            "Bills overdue", "2 bills", "warn", "schedule-bills", focus="overdue", actions=("z",)
        ),
    )
    state = CockpitState(tenant_name="Clonway", needs=needs)
    m = render.model_cockpit_screen(state, [], selection=None)
    need_row = next(r for reg in m.regions if reg.role == "needs" for r in reg.rows)
    assert any(f.label == "capability_key" and f.value == "schedule-bills" for f in need_row.fields)
    assert any(f.label == "focus" and f.value == "overdue" for f in need_row.fields)
    assert any(f.label == "actions" and f.value == "z" for f in need_row.fields)
