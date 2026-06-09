"""S8/C6 — the worker-template generation smoke test.

Generates a stub worker from ``worker-template/`` (via ``copier``, reading the
CURRENT working tree so a template change is re-proved here) into a tmp dir, then
asserts the C6 acceptance criteria against the GENERATED output — so CI proves
the template still produces a worker that renders a cockpit, emits the C0 wire
shape flag-guarded, and ships a mandatory (initially empty) ``scan_horizon``.

The ACs are checked by importing the generated package directly into THIS test
process (clonway-cockpit is already installed in the test env), not by a nested
``uv sync`` — fast and network-free in CI. The generated worker's own
``uv run pytest`` / ``ruff`` are exercised separately by the documented
``make template-smoke`` target (a full install-and-run), kept out of the unit
suite so CI stays quick and offline.

Each test generates its own worker under a UNIQUE package name and tears the
import + ``sys.path`` entry down, so the generated modules never leak across
tests or collide with a real installed worker.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

copier = pytest.importorskip("copier", reason="copier is a dev dep; the smoke test needs it")

_REPO_ROOT = Path(__file__).resolve().parent.parent

_NOW = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)


def _generate(tmp_path: Path, *, worker_id: str, deploy_shape: str = "job") -> Path:
    """Generate a worker into ``tmp_path`` and return its repo root."""
    dst = tmp_path / worker_id
    copier.run_copy(
        str(_REPO_ROOT),
        dst,
        data={
            "worker_id": worker_id,
            "worker_title": f"Auto-{worker_id[1:].capitalize()}",
            "package_name": worker_id,
            "deploy_shape": deploy_shape,
            "clonway_rev": "main",
        },
        defaults=True,
        quiet=True,
        unsafe=True,  # template has computed values; we trust our own template
    )
    return dst


@contextmanager
def _importable(dst: Path, package_name: str) -> Iterator[None]:
    """Make the generated worker's ``src/`` importable, yielding while it is, then
    removing every imported ``<package>.*`` module + the path entry on exit so
    tests don't leak the generated package into each other."""
    src = str(dst / "src")
    sys.path.insert(0, src)
    try:
        yield
    finally:
        for name in [
            m for m in sys.modules if m == package_name or m.startswith(f"{package_name}.")
        ]:
            del sys.modules[name]
        if src in sys.path:
            sys.path.remove(src)


# --- generation surface ----------------------------------------------------


def test_template_generates_expected_layout(tmp_path: Path) -> None:
    dst = _generate(tmp_path, worker_id="xgenlayout")
    expected = {
        "pyproject.toml",
        "README.md",
        "CLAUDE.md",  # born carrying the agent-navigability convention
        "Dockerfile",  # job shape → Dockerfile present
        ".github/workflows/ci.yml",
        "src/xgenlayout/__init__.py",
        "src/xgenlayout/obs.py",
        "src/xgenlayout/cli/__init__.py",
        "src/xgenlayout/cli/cockpit.py",
        "src/xgenlayout/cli/signals.py",
        "src/xgenlayout/signals/build.py",
        "src/xgenlayout/signals/emit.py",
        "tests/test_signals_build.py",
        "tests/test_signals_emit.py",
        "tests/test_cockpit_render.py",
        "tests/test_cockpit_contract.py",  # the inherited agent-navigability gate
        "tests/test_safety.py",
    }
    present = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
    missing = expected - present
    assert not missing, f"template did not generate: {sorted(missing)}"


def test_local_shape_skips_dockerfile(tmp_path: Path) -> None:
    dst = _generate(tmp_path, worker_id="xgenlocal", deploy_shape="local")
    assert not (dst / "Dockerfile").exists()


# --- AC-C6-3 — mandatory scan_horizon, returns the (empty) Signal set ------


def test_ac_c6_3_scan_horizon_exists_and_returns_empty_signal_set(tmp_path: Path) -> None:
    dst = _generate(tmp_path, worker_id="xgenhorizon")
    with _importable(dst, "xgenhorizon"):
        from clonway_cockpit.signals.horizon import ScanHorizon, is_scan_horizon
        from clonway_cockpit.signals.model import Signal

        build = importlib.import_module("xgenhorizon.signals.build")

        scan = build.scan_xgenhorizon_horizon
        assert is_scan_horizon(scan), "@scan_horizon marker missing — not mandatory"
        assert isinstance(scan, ScanHorizon)

        out = build.build_xgenhorizon_signals(today=_NOW.date(), now=_NOW)
        assert out == ()  # the stub returns an empty Signal set
        assert all(isinstance(s, Signal) for s in out)


# --- AC-C6-1 — cockpit opens the three-region shell (headless render) -------


def test_ac_c6_1_cockpit_opens_three_region_shell(tmp_path: Path) -> None:
    from rich.console import Console

    dst = _generate(tmp_path, worker_id="xgencockpit")
    with _importable(dst, "xgencockpit"):
        cockpit = importlib.import_module("xgencockpit.cli.cockpit")

        frames: list[str] = []
        console = Console(width=120, record=True)

        class _Screen:
            def update(self, renderable: object) -> None:
                with console.capture() as cap:
                    console.print(renderable)
                frames.append(cap.get())

        cockpit.run_cockpit(read_key=lambda: "q", screen=_Screen())
        assert frames, "cockpit painted no frame"
        frame = frames[0]
        # The three-region grammar: pulse / needs you / toolkit.
        assert "pulse" in frame
        assert "needs you" in frame
        assert "toolkit" in frame
        assert "xgencockpit" in frame  # the worker's identity


# --- AC-C6-2 — emits the C0 wire shape, flag-guarded -----------------------


def test_ac_c6_2_emit_flag_guarded_writes_latest(tmp_path: Path, monkeypatch) -> None:
    dst = _generate(tmp_path, worker_id="xgenemit")
    with _importable(dst, "xgenemit"):
        from clonway_cockpit.signals import emit as shared_emit

        worker_emit = importlib.import_module("xgenemit.signals.emit")

        # Inject an in-memory fake for the shared helper's lazy GCS import.
        store: dict[str, str] = {}

        class _Blob:
            def __init__(self, path: str) -> None:
                self._path = path

            def upload_from_string(self, body: str, content_type: str = "") -> None:
                store[self._path] = body

        class _Bucket:
            def blob(self, path: str) -> _Blob:
                return _Blob(path)

        class _Client:
            def bucket(self, _name: str) -> _Bucket:
                return _Bucket()

        class _Storage:
            def Client(self, *a: object, **k: object) -> _Client:  # noqa: N802
                return _Client()

        monkeypatch.setattr(shared_emit, "_import_storage", lambda: _Storage())

        # Flag OFF → no-op, no GCS write.
        monkeypatch.delenv("XGENEMIT_EMIT_SIGNALS", raising=False)
        assert worker_emit.scan_and_emit(now=_NOW) == ()
        assert store == {}

        # Flag ON → writes signals/<worker>/latest.jsonl (empty body for the
        # empty stub set — the read-model snapshot is still flushed).
        monkeypatch.setenv("XGENEMIT_EMIT_SIGNALS", "1")
        assert worker_emit.scan_and_emit(now=_NOW) == ()
        assert "signals/xgenemit/latest.jsonl" in store
        assert store["signals/xgenemit/latest.jsonl"] == ""


# --- AC-C6-4 — the generated worker is born agent-navigable -----------------


def test_ac_c6_4_generated_worker_serves_agent_and_drives_clean(tmp_path: Path) -> None:
    from clonway_cockpit import contract

    dst = _generate(tmp_path, worker_id="xgenagent")
    with _importable(dst, "xgenagent"):
        cockpit = importlib.import_module("xgenagent.cli.cockpit")

        # serve_agent + an agent-mode-aware host exist out of the box.
        assert hasattr(cockpit, "serve_agent")
        host = cockpit._host(agent_mode=True)
        assert host.agent_mode is True

        # Parity holds for the scaffold, and the home screen drives clean (no unstructured).
        contract.assert_render_model_parity(cockpit)
        stream = contract.assert_drives_clean(host, ["q"])
        assert stream[0].kind == "home"


def test_ac_c6_4_generated_worker_cli_agent_stdio_subprocess_smoke(tmp_path: Path) -> None:
    from clonway_cockpit import agent, keys

    worker_id = "xgensubproc"
    dst = _generate(tmp_path, worker_id=worker_id)
    _install_generated_worker_against_local_checkout(dst)

    with agent.CockpitClient.spawn(
        ["uv", "run", worker_id, "--agent-stdio"],
        cwd=str(dst),
        timeout=10,
    ) as client:
        home = client.read_home()
        preflight = client.press("a")
        result = client.press(keys.ENTER)
        returned_home = client.press("x")
        extra = client.drain()

    frames = [home, preflight, result, returned_home, *extra]
    screen_frames = [frame for frame in frames if "kind" in frame]

    assert home["kind"] == "home"
    assert preflight["kind"] == "walk.preflight"
    assert result["kind"] == "walk.result"
    assert result["meta"]["ok"] is True
    assert result["meta"]["message"] == "Done."
    assert returned_home["kind"] == "home"
    assert screen_frames, frames
    assert all(frame["schema_version"] == "1.0" for frame in screen_frames)
    assert not any(frame["kind"] == "unstructured" for frame in screen_frames)
    assert client._proc is None or client._proc.poll() is not None


def test_ac_c6_4_cli_registers_agent_flags(tmp_path: Path) -> None:
    import inspect as _inspect

    dst = _generate(tmp_path, worker_id="xgenflags")
    with _importable(dst, "xgenflags"):
        cli = importlib.import_module("xgenflags.cli")
        # The Typer callback declares the agent-channel flags (source-text check is the
        # reliable cross-Typer-version assertion).
        src = _inspect.getsource(cli._root)
        assert "--agent-stdio" in src
        assert "--allow-apply" in src
