"""Tests for clonway_cockpit.contract — the shippable agent-navigability gate."""

from __future__ import annotations

import types

import pytest

from clonway_cockpit import contract, render


def test_page_framing_renders_finds_screens_not_subcomponents():
    found = contract.page_framing_renders(render)
    assert "render_cockpit_screen" in found  # frames a page()
    assert "render_help" in found
    # sub-components / helpers that don't call page() are excluded
    assert "render_header" not in found
    assert "render_pulse" not in found


def test_model_twin_naming():
    assert contract.model_twin("render_help") == "model_help"
    assert contract.model_twin("render_cockpit_screen") == "model_cockpit_screen"


def test_parity_passes_for_the_framework_render_module():
    # The framework co-locates render_* and model_*; all page-framers are twinned.
    contract.assert_render_model_parity(render)


def _orphan_ns() -> types.ModuleType:
    ns = types.ModuleType("fake")

    def render_orphan():
        page("x")  # noqa: F821 — only the source text matters to the heuristic

    ns.render_orphan = render_orphan
    return ns


def test_parity_fails_on_an_orphan_render():
    with pytest.raises(AssertionError, match="render_orphan -> model_orphan"):
        contract.assert_render_model_parity(_orphan_ns())


def test_parity_allow_unmodeled_escape_hatch():
    contract.assert_render_model_parity(_orphan_ns(), allow_unmodeled={"render_orphan"})


# --- dynamic drive-it conformance ------------------------------------------


def test_assert_drives_clean_passes_on_a_clean_home_walk(make_stub_host):
    host = make_stub_host()
    # Home → quit: only the cockpit home screen is emitted, no unstructured.
    stream = contract.assert_drives_clean(host, ["q"])
    assert stream
    assert all(m.kind != "unstructured" for m in stream)
    assert stream[0].kind == "home"


def test_assert_drives_clean_flags_unstructured(make_stub_host):
    host = make_stub_host()
    # Driving into Doctor (shelf G) on the unconfigured stub emits model_unstructured,
    # so the gate must trip with the default allow_unstructured=False.
    with pytest.raises(AssertionError, match="unstructured"):
        contract.assert_drives_clean(host, ["g", "q"])


def test_assert_drives_clean_allow_unstructured_opt_out(make_stub_host):
    host = make_stub_host()
    stream = contract.assert_drives_clean(host, ["g", "q"], allow_unstructured=True)
    assert any(m.kind == "unstructured" for m in stream)  # Doctor setup hint present
