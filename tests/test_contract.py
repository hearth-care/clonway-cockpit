"""Contract: every full-screen framework render primitive has a model_* twin.

Dogfoods clonway_cockpit.contract — the SHIPPABLE gate consumers import. Expressing the
framework's own check through the public helper makes the framework's CI the canary for the
helper itself: if assert_render_model_parity regresses, this fails first. The old hand-rolled
FRAMEWORK_SCREENS dict is subsumed by assert_render_model_parity, which finds ALL page-framers
(not just a listed subset), so a new primitive can't be added without a model twin.
"""

from __future__ import annotations

from clonway_cockpit import contract, render


def test_every_page_framing_render_has_a_model_twin():
    contract.assert_render_model_parity(render)


def test_split_render_modules_keep_parity_discovery():
    from clonway_cockpit import render_chrome, render_models, render_panels

    renders = contract.page_framing_renders((render_chrome, render_panels))
    assert len(renders) == 14
    contract.assert_render_model_parity((render_chrome, render_panels), render_models)


def test_unstructured_is_explicitly_flagged():
    m = render.model_unstructured(render.render_note("x", "y"))
    assert m.kind == "unstructured"
