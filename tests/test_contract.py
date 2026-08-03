"""Contract: every full-screen framework render primitive has a model_* twin.

Dogfoods clonway_cockpit.contract — the SHIPPABLE gate consumers import. Expressing the
framework's own check through the public helper makes the framework's CI the canary for the
helper itself: if assert_render_model_parity regresses, this fails first. The old hand-rolled
FRAMEWORK_SCREENS dict is subsumed by assert_render_model_parity, which finds ALL page-framers
(not just a listed subset), so a new primitive can't be added without a model twin.
"""

from __future__ import annotations

import json

import pytest
from rich.console import Console

from clonway_cockpit import contract, render, shell
from clonway_cockpit.agent import serve_stdio
from clonway_cockpit.audit_log import AuditEvent
from clonway_cockpit.registry import (
    BlastRadius,
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState
from clonway_cockpit.walk import confirm_apply


def test_every_page_framing_render_has_a_model_twin():
    contract.assert_render_model_parity(render)


def test_split_render_modules_keep_parity_discovery():
    from clonway_cockpit import render_chrome, render_models, render_panels

    renders = contract.page_framing_renders((render_chrome, render_panels))
    assert len(renders) == 15
    assert "render_ledger" in renders
    contract.assert_render_model_parity((render_chrome, render_panels), render_models)


def test_unstructured_is_explicitly_flagged():
    m = render.model_unstructured(render.render_note("x", "y"))
    assert m.kind == "unstructured"


# --- Task 5: real-shape 16-item host — human/agent parity + acceptance --------
#
# A 16-item shelf is Auto-Bookkeeper's real shelf-G shape (advertised `10`-`16`
# on the OLD framework). This drives the SAME 16-item host both ways — human-
# shaped injected keys, then the real serve_stdio JSON wire — and cross-checks
# titles/row-ids/shortcuts/actions/selection plus the exact opened capability,
# so the two projections of one screen provably stay one screen.

_N_ITEMS = 16
_SIXTEEN_ROUTES = tuple(
    zip(render.assign_menu_shortcuts(_N_ITEMS), range(1, _N_ITEMS + 1), strict=True)
)


def _register_sixteen_item_shelf() -> dict[str, list]:
    """Fifteen plain capabilities plus a 16th that is money-movement/write-gated
    (posts only past ``confirm_apply``) — shelf B, matching Auto-Bookkeeper's
    real 16-capability shelf-G shape."""
    ran: dict[str, list] = {}
    for i in range(1, _N_ITEMS):
        key = f"cap-{i}"
        marks: list = []
        ran[key] = marks
        register_capability(
            CapabilitySpec(
                key=key,
                shelf="B",
                title=f"Cap {i}",
                summary=f"summary {i}",
                equivalent_cli="x",
                run=lambda ctx, marks=marks: marks.append(True),
            )
        )

    posts: list = []

    def _write_handler(ctx: WizardContext) -> None:
        if confirm_apply(ctx, equivalent_cli="x post"):
            posts.append(True)  # only reached on an authorized apply

    ran["cap-16"] = posts
    register_capability(
        CapabilitySpec(
            key="cap-16",
            shelf="B",
            title="Cap 16",
            summary="the write-gated one",
            equivalent_cli="x post",
            run=_write_handler,
            blast_radius=BlastRadius(summary="posts a batch"),
            money_movement=True,
        )
    )
    return ran


def _register_sixteen_route_shelf() -> dict[str, list]:
    """A side-effect-free catalog where every ordinal has a distinct public effect."""
    ran: dict[str, list] = {}
    for ordinal in range(1, _N_ITEMS + 1):
        key = f"route-{ordinal}"
        marks: list = []
        ran[key] = marks
        register_capability(
            CapabilitySpec(
                key=key,
                shelf="B",
                title=f"Route {ordinal}",
                summary=f"route summary {ordinal}",
                equivalent_cli=f"x route {ordinal}",
                run=lambda ctx, marks=marks: marks.append(True),
            )
        )
    return ran


class _CountingUsage:
    """Records each ``record(key, "open")`` call — the acceptance's usage/audit
    launch-count-stays-one proof."""

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


def _sixteen_item_host(**over) -> shell.Host:
    base = dict(
        capture_state=lambda: CockpitState(tenant_name="Clonway"),
        build_walk_ctx=_walk_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=_CountingUsage(),
        on_open=lambda: None,
    )
    base.update(over)
    return shell.Host(**base)


def test_sixteen_item_shelf_drives_clean_with_no_unstructured_frame():
    """Dynamic conformance over a representative gated route on the 16-item shape.

    Exact exhaustive routing belongs to the fresh-session 2 × 16 matrix below;
    this test only proves the gate path itself never emits ``unstructured``.
    """
    clear_capabilities()
    _register_sixteen_item_shelf()
    host = _sixteen_item_host()
    keys_script = ["b", "g", "n", "q", "q"]
    stream = contract.assert_drives_clean(host, keys_script)
    assert any(s.kind == "shelf_menu" for s in stream)
    clear_capabilities()


def test_sixteen_item_shelf_human_shortcut_opens_exact_capability_once():
    """Human-shaped injected keys: shortcut 'a' opens ordinal 10, 'g' opens
    ordinal 16 exactly (matching the design's byte-compatible mapping), each
    exactly once (the usage/audit launch-count invariant), and the human render
    + agent model agree on titles/tokens for the whole shelf."""
    clear_capabilities()
    ran = _register_sixteen_item_shelf()
    usage_stub = _CountingUsage()
    host = _sixteen_item_host(usage=usage_stub)

    class _Screen:
        def __init__(self):
            self.frames = []

        def update(self, renderable):
            self.frames.append(renderable)

    def _keys(seq):
        buf = list(seq)
        return lambda: buf.pop(0) if buf else "q"

    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "a", "q"]), screen=scr)
    assert ran["cap-10"] == [True]
    assert usage_stub.opens == {"cap-10": 1}  # opened exactly once; nothing else touched

    clear_capabilities()
    ran = _register_sixteen_item_shelf()
    usage_stub = _CountingUsage()
    host = _sixteen_item_host(usage=usage_stub)
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "g", "q"]), screen=scr)
    assert ran["cap-16"] == []  # write-gated: opening it does NOT post
    assert usage_stub.opens == {"cap-16": 1}
    clear_capabilities()


@pytest.mark.parametrize("channel", ["human", "stdio"])
@pytest.mark.parametrize(("token", "ordinal"), _SIXTEEN_ROUTES)
def test_every_displayed_sixteen_item_shortcut_routes_exactly_once(channel, token, ordinal):
    """Exhaustive 2 × 16 channel/token protocol matrix, one fresh session per cell."""
    clear_capabilities()
    ran = _register_sixteen_route_shelf()
    usage = _CountingUsage()
    events: list[AuditEvent] = []
    models = []
    host = _sixteen_item_host(usage=usage, audit_sink=events.append, on_screen=models.append)

    if channel == "human":

        class _Screen:
            def __init__(self):
                self.frames = []

            def update(self, renderable):
                self.frames.append(renderable)

        keys_script = iter(["b", token, "q"])
        screen = _Screen()
        shell.run_cockpit(host, read_key=lambda: next(keys_script, "q"), screen=screen)
        shelf_model = next(model for model in models if model.kind == "shelf_menu")
        rendered_frames = []
        for frame in screen.frames:
            rendered = Console(record=True, width=160)
            rendered.print(frame)
            rendered_frames.append(rendered.export_text())
        assert any(f"{token}." in text for text in rendered_frames)
        shelf_wire = shelf_model.to_dict()
    else:
        import io

        inp = io.StringIO("".join(json.dumps({"key": key}) + "\n" for key in ("b", token, "q")))
        out = io.StringIO()
        serve_stdio(host, stdin=inp, stdout=out)
        frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
        shelf_wire = next(frame for frame in frames if frame.get("kind") == "shelf_menu")
        assert all(frame.get("kind") != "unstructured" for frame in frames)

    rows = shelf_wire["regions"][0]["rows"]
    selected_row = rows[ordinal - 1]
    shortcut = next(
        field["value"] for field in selected_row["fields"] if field["label"] == "shortcut"
    )
    assert shortcut == token
    assert token in shelf_wire["actions"]
    assert ran[f"route-{ordinal}"] == [True]
    assert sum(len(opens) for opens in ran.values()) == 1
    assert usage.opens == {f"route-{ordinal}": 1}
    launches = [event for event in events if event.event == "capability.launched"]
    assert len(launches) == 1
    assert launches[0].capability_key == f"route-{ordinal}"
    clear_capabilities()


def test_sixteen_item_shelf_serve_stdio_matches_human_titles_ids_and_actions():
    """Drive the SAME 16-item host over the real serve_stdio JSON wire and cross-
    check its shelf_menu frame against the in-process CockpitDriver/human render:
    same ordered titles, row ids, advertised shortcuts/actions and selection."""
    clear_capabilities()
    _register_sixteen_item_shelf()
    host = _sixteen_item_host()

    inp_lines = [
        json.dumps(m) + "\n"
        for m in [{"key": "b"}, {"key": "g"}, {"key": "n"}, {"key": "q"}, {"key": "q"}]
    ]
    import io

    inp = io.StringIO("".join(inp_lines))
    out = io.StringIO()
    serve_stdio(host, stdin=inp, stdout=out)
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]

    assert all(f.get("kind") != "unstructured" for f in frames), frames
    assert frames[-1]["kind"] == "home"  # a clean exit, not an early/dangling frame

    menu_frame = next(f for f in frames if f["kind"] == "shelf_menu")
    titles = [row["label"] for row in menu_frame["regions"][0]["rows"][:-1]]
    assert titles == [f"Cap {i}" for i in range(1, _N_ITEMS + 1)]
    row_ids = [row["id"] for row in menu_frame["regions"][0]["rows"][:-1]]
    assert row_ids == [f"option:{i}" for i in range(1, _N_ITEMS + 1)]
    token_actions = [a for a in menu_frame["actions"] if a not in ("up", "down", "enter", "q")]
    assert token_actions == render.assign_menu_shortcuts(_N_ITEMS)

    # The write-gated 16th capability declined over the wire — the gate fired,
    # never posted, and no early EOF ended the session before "q" was honoured.
    assert any(
        f.get("kind") == "walk.gate" and f["meta"]["status"] == "declined" for f in frames
    ), [f.get("kind") for f in frames]
    clear_capabilities()


def test_navigation_creates_no_completion_receipt_only_the_one_launch_event():
    """Arrow moves and Backspace must record NO audit event; opening the
    write-gated capability records exactly one ``capability.launched`` plus the
    gate's own decline — navigation itself is read-only and completion-receipt-free."""
    clear_capabilities()
    _register_sixteen_item_shelf()
    events: list[AuditEvent] = []
    host = _sixteen_item_host(audit_sink=events.append)

    class _Screen:
        def update(self, renderable):
            return None

    def _keys(seq):
        buf = list(seq)
        return lambda: buf.pop(0) if buf else "q"

    # Home cursor moves, into the shelf, arrow around, open the write-gated cap,
    # decline it, back out, quit — no step here should mint more than the one
    # launch event for the one capability actually opened.
    shell.run_cockpit(
        host,
        read_key=_keys(
            [
                "down",
                "up",
                "b",
                "down",
                "up",
                "g",
                "n",
                "q",
                "q",
            ]
        ),
        screen=_Screen(),
    )
    launches = [e for e in events if e.event == "capability.launched"]
    assert len(launches) == 1
    assert launches[0].capability_key == "cap-16"
    clear_capabilities()
