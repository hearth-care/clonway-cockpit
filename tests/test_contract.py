"""Contract: every full-screen framework render primitive has a model_* twin.

A framework screen is a public ``render_*`` that frames a page via ``page()``. Each must
have a registered ``model_*`` builder, so an agent gets structure (not an ``unstructured``
fallback) from every framework screen. A new primitive that forgets its model fails here.
"""

from __future__ import annotations

import inspect

from clonway_cockpit import render

# render_* (page-framing) → its model_* twin. Sub-components (header/pulse/needs_you/
# toolkit/usage_section) and helpers don't frame a page, so they are not listed.
FRAMEWORK_SCREENS: dict[str, str] = {
    "render_cockpit_screen": "model_cockpit_screen",
    "render_menu": "model_menu",
    "render_capability_card": "model_capability_card",
    "render_preflight": "model_preflight",
    "render_remedy_confirm": "model_remedy_confirm",
    "render_walk_progress": "model_walk_progress",
    "render_sync_progress": "model_sync_progress",
    "render_staged_progress": "model_staged_progress",
    "render_walk_result": "model_walk_result",
    "render_note": "model_note",
    "render_help": "model_help",
    "render_doctor": "model_doctor",
    "render_doctor_confirm": "model_doctor_confirm",
    "render_filter": "model_filter",
}


def test_every_registered_screen_has_a_model():
    for render_fn, model_fn in FRAMEWORK_SCREENS.items():
        assert hasattr(render, render_fn), f"missing render fn {render_fn}"
        assert hasattr(render, model_fn), f"{render_fn} has no model builder {model_fn}"


def test_no_unregistered_page_framing_screen():
    """Any public render_* that frames a page() must be registered above, so a new
    framework primitive can't be added without a model twin."""
    page_screens: set[str] = set()
    for name, fn in inspect.getmembers(render, inspect.isfunction):
        if not name.startswith("render_"):
            continue
        try:
            src = inspect.getsource(fn)
        except OSError:  # pragma: no cover - source always available in-tree
            continue
        if "page(" in src:
            page_screens.add(name)
    missing = page_screens - set(FRAMEWORK_SCREENS)
    assert not missing, f"page-framing framework screens with no registered model: {missing}"


def test_unstructured_is_explicitly_flagged():
    m = render.model_unstructured(render.render_note("x", "y"))
    assert m.kind == "unstructured"
