from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from rich.console import Console

from clonway_cockpit import agent, keys, render, shell
from clonway_cockpit.doctor import DoctorRemedyReceipt, Fix, Probe, fixes_for
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, NeedsItem


class _Usage:
    def record(self, key: str, action: str = "open") -> None:
        pass

    def load(self) -> dict:
        return {}


def _ctx(screen, read_key, *, focus=None) -> WizardContext:  # noqa: ANN001
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


def _pipe_text():
    read_fd, write_fd = os.pipe()
    return os.fdopen(read_fd, "r"), os.fdopen(write_fd, "w", buffering=1)


def _wire(host: shell.Host):
    to_app_read, to_app_write = _pipe_text()
    to_agent_read, to_agent_write = _pipe_text()

    def run() -> None:
        agent.serve_stdio(host, stdin=to_app_read, stdout=to_agent_write)
        to_agent_write.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    client = agent.CockpitClient.over_streams(stdin=to_agent_read, stdout=to_app_write)
    return client, thread


def test_mixed_doctor_projection_carries_action_identity_and_focus() -> None:
    display = Fix("Explain", "worker explain", note="Read the runbook")
    callback = Fix(
        "Repair",
        "worker repair",
        run=lambda: "done",
        remedy_id="remedy.repair",
        probe_id="probe.repair",
        confirm=True,
    )
    capability = Fix(
        "Review",
        "worker review",
        remedy_id="remedy.review",
        probe_id="probe.review",
        capability_key="review",
        focus="row.7",
    )
    probes = [
        Probe("Display", "ok", "Documented", display),
        Probe("Repair", "warn", "Repair needed", callback, "probe.repair", "rev-1"),
        Probe("Review", "error", "Review needed", capability, "probe.review", "rev-2"),
    ]
    kwargs = {
        "probes": probes,
        "fixes": fixes_for(probes),
        "selected": 1,
        "focus_requested": "probe.review",
        "focus_matched": "probe.review",
    }

    model = render.model_doctor(**kwargs)
    console = Console(record=True, width=120)
    console.print(render.render_doctor(**kwargs))
    human = console.export_text()
    rows = next(region.rows for region in model.regions if region.role == "fixes")
    capability_fields = {field.label: field.value for field in rows[2].fields}

    assert [row.id for row in rows] == ["fix:display:0", "fix:0", "fix:1"]
    assert model.selection == "fix:1"
    assert capability_fields == {
        "cmd": "worker review",
        "remedy_id": "remedy.review",
        "probe_id": "probe.review",
        "action_kind": "open_capability",
        "capability_key": "review",
        "focus": "row.7",
        "confirm": "false",
    }
    assert model.meta["warnings"] == 1
    assert model.meta["errors"] == 1
    assert model.meta["focus_requested"] == "probe.review"
    assert model.meta["focus_matched"] == "probe.review"
    assert "Open Review" in human
    assert "worker review" in human
    assert "run in a terminal" in human


def test_cockpit_client_drives_focused_capability_and_one_receipt() -> None:
    clear_capabilities()
    receipts: list[DoctorRemedyReceipt] = []
    nested_focus = []
    try:

        def nested(ctx: WizardContext) -> None:
            nested_focus.append(ctx.focus)
            assert ctx.on_screen is not None
            ctx.on_screen(render.model_note("Nested review", "Structured capability"))

        register_capability(
            CapabilitySpec(
                "doctor",
                "G",
                "Doctor",
                "Health",
                "worker doctor",
            )
        )
        register_capability(
            CapabilitySpec(
                "review",
                "C",
                "Review",
                "Review",
                "worker review",
                run=nested,
            )
        )
        first = Probe(
            "First",
            "warn",
            "First",
            Fix(
                "First",
                "worker first",
                remedy_id="remedy.first",
                probe_id="probe.first",
                capability_key="review",
            ),
            "probe.first",
            "rev-1",
        )
        focused = Probe(
            "Focused",
            "error",
            "Focused",
            Fix(
                "Review",
                "worker review",
                remedy_id="remedy.focused",
                probe_id="probe.focused",
                capability_key="review",
                focus="row.focused",
            ),
            "probe.focused",
            "rev-1",
        )
        state = CockpitState(
            tenant_name="Clonway",
            needs=(
                NeedsItem(
                    "Focused",
                    "Review",
                    "error",
                    capability_key="doctor",
                    focus="probe.focused",
                ),
            ),
        )
        host = shell.Host(
            capture_state=lambda: state,
            build_walk_ctx=_ctx,
            activate_pill=lambda *args: None,
            doctor_build_report=lambda: object(),
            doctor_build_probes=lambda report: [first, focused],
            doctor_fixes_for=fixes_for,
            doctor_unconfigured_renderable=lambda: render.render_note("Doctor", "Unavailable"),
            usage=_Usage(),
            on_open=lambda: None,
            doctor_on_receipt=receipts.append,
        )
        client, thread = _wire(host)

        home = client.read_home()
        doctor = client.press(keys.ENTER)
        nested_frame = client.press(keys.ENTER)
        trailing = client.drain(idle=0.2)

        assert home["kind"] == "home"
        assert doctor["kind"] == "doctor"
        assert doctor["selection"] == "fix:1"
        assert doctor["meta"]["focus_matched"] == "probe.focused"
        assert doctor["schema_version"] == "1.0"
        assert nested_frame["kind"] == "note"
        assert nested_focus == ["row.focused"]
        assert trailing[-1]["kind"] == "doctor"
        assert len(receipts) == 1
        assert all(
            frame.get("kind") != "unstructured" for frame in [home, doctor, nested_frame, *trailing]
        )

        home_again = client.press("q")
        assert home_again["kind"] == "home"
        client.quit()
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        clear_capabilities()


def test_cockpit_client_redacts_throwing_doctor_capability_from_every_frame() -> None:
    clear_capabilities()
    receipts: list[DoctorRemedyReceipt] = []
    sentinel = "RAW-PROVIDER-CREDENTIAL-456"
    try:
        register_capability(CapabilitySpec("doctor", "G", "Doctor", "Health", "worker doctor"))

        def nested(ctx: WizardContext) -> None:
            raise RuntimeError(sentinel)

        register_capability(
            CapabilitySpec(
                "review",
                "C",
                "Review",
                "Review",
                "worker review",
                run=nested,
            )
        )
        fix = Fix(
            "Review",
            "worker review",
            remedy_id="remedy.review",
            probe_id="probe.review",
            capability_key="review",
        )
        probe = Probe("Review", "error", "Safe detail", fix, "probe.review", "rev-1")
        state = CockpitState(
            tenant_name="Clonway",
            needs=(NeedsItem("Review", "Open Doctor", "error", "doctor", "probe.review"),),
        )
        host = shell.Host(
            capture_state=lambda: state,
            build_walk_ctx=_ctx,
            activate_pill=lambda *args: None,
            doctor_build_report=lambda: object(),
            doctor_build_probes=lambda report: [probe],
            doctor_fixes_for=fixes_for,
            doctor_unconfigured_renderable=lambda: render.render_note("Doctor", "Unavailable"),
            usage=_Usage(),
            on_open=lambda: None,
            doctor_on_receipt=receipts.append,
        )
        client, thread = _wire(host)

        frames = [client.read_home(), client.press(keys.ENTER)]
        frames.append(client.press(keys.ENTER))
        frames.append(client.press("dismiss"))
        frames.extend(client.drain(idle=0.2))

        result = next(frame for frame in frames if frame.get("kind") == "walk.result")
        assert result["meta"]["ok"] is False
        assert result["meta"]["message"] == "Review hit an error (RuntimeError)."
        assert frames[-1]["kind"] == "doctor"
        assert len(receipts) == 1
        assert sentinel not in json.dumps(frames)
        assert sentinel not in repr(receipts[0])

        assert client.press("q")["kind"] == "home"
        client.quit()
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        clear_capabilities()


_LEGACY_CHILD = r"""
from rich.console import Console
from clonway_cockpit import agent, render, shell
from clonway_cockpit.doctor import fixes_for
from clonway_cockpit.registry import CapabilitySpec, WizardContext, register_capability
from clonway_cockpit.state import CockpitState, NeedsItem

class Usage:
    def record(self, key, action="open"): pass
    def load(self): return {}

def ctx(screen, read_key, *, focus=None):
    return WizardContext({}, None, Console(), lambda p, d: "", lambda p: False,
                         screen.update, read_key, focus)

register_capability(CapabilitySpec("doctor", "G", "Doctor", "Health", "worker doctor"))
state = CockpitState("Clonway", needs=(NeedsItem("Doctor", "Open", "error", "doctor"),))
host = shell.Host(
    capture_state=lambda: state,
    build_walk_ctx=ctx,
    activate_pill=lambda *args: None,
    doctor_build_report=lambda: (_ for _ in ()).throw(RuntimeError("legacy")),
    doctor_build_probes=lambda report: [],
    doctor_fixes_for=fixes_for,
    doctor_unconfigured_renderable=lambda: render.render_note("Doctor", "Legacy fallback"),
    usage=Usage(),
    on_open=lambda: None,
)
agent.serve_stdio(host)
"""


_OPT_IN_CHILD = r"""
import json
import os
from dataclasses import asdict
from pathlib import Path
from rich.console import Console
from clonway_cockpit import agent, render, shell
from clonway_cockpit.doctor import Fix, Probe, fixes_for
from clonway_cockpit.registry import CapabilitySpec, WizardContext, register_capability
from clonway_cockpit.state import CockpitState, NeedsItem

class Usage:
    def record(self, key, action="open"): pass
    def load(self): return {}

def ctx(screen, read_key, *, focus=None):
    return WizardContext({}, None, Console(), lambda p, d: "", lambda p: False,
                         screen.update, read_key, focus)

resolved = {"value": False}
def nested(ctx):
    resolved["value"] = True
    ctx.on_screen(render.model_note("Nested", "Structured capability"))

register_capability(CapabilitySpec("doctor", "G", "Doctor", "Health", "worker doctor"))
register_capability(CapabilitySpec("review", "C", "Review", "Review", "worker review", run=nested))
fix = Fix("Review", "worker review", remedy_id="remedy.focused", probe_id="probe.focused",
          capability_key="review", focus="row.focused")
probe = Probe("Focused", "error", "Review", fix, "probe.focused", "rev-1")
state = CockpitState(
    "Clonway",
    needs=(NeedsItem("Focused", "Review", "error", "doctor", "probe.focused"),),
)
def receipt(value):
    Path(os.environ["DOCTOR_RECEIPT_PATH"]).write_text(json.dumps(asdict(value)))

host = shell.Host(
    capture_state=lambda: state,
    build_walk_ctx=ctx,
    activate_pill=lambda *args: None,
    doctor_build_report=lambda: object(),
    doctor_build_probes=lambda report: [] if resolved["value"] else [probe],
    doctor_fixes_for=fixes_for,
    doctor_unconfigured_renderable=lambda: render.render_note("Doctor", "Unavailable"),
    usage=Usage(),
    on_open=lambda: None,
    doctor_on_receipt=receipt,
)
agent.serve_stdio(host)
"""


def test_subprocess_client_preserves_legacy_doctor_fallback() -> None:
    with agent.CockpitClient.spawn([sys.executable, "-c", _LEGACY_CHILD], timeout=10) as client:
        assert client.read_home()["kind"] == "home"
        fallback = client.press(keys.ENTER)
        assert fallback["kind"] == "unstructured"
        assert "Legacy fallback" in fallback["regions"][0]["text"]


def test_subprocess_client_drives_opt_in_remedy_and_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    environment = dict(os.environ)
    environment["DOCTOR_RECEIPT_PATH"] = str(receipt_path)

    with agent.CockpitClient.spawn(
        [sys.executable, "-c", _OPT_IN_CHILD],
        env=environment,
        timeout=10,
    ) as client:
        assert client.read_home()["kind"] == "home"
        doctor = client.press(keys.ENTER)
        assert doctor["kind"] == "doctor"
        assert doctor["selection"] == "fix:0"
        nested = client.press(keys.ENTER)
        assert nested["kind"] == "note"
        trailing = client.drain(idle=0.2)
        assert trailing[-1]["kind"] == "doctor"
        assert all(frame.get("kind") != "unstructured" for frame in [doctor, nested, *trailing])

    receipt = json.loads(receipt_path.read_text())
    assert receipt["remedy_id"] == "remedy.focused"
    assert receipt["action_result"] == "opened"
    assert receipt["closure"] == "resolved"
