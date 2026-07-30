"""Behavioral contract for the stable worker-facing cockpit seams."""

from __future__ import annotations

import ast
import asyncio
import contextvars
import inspect
import logging
import textwrap
import threading
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import Any

import pytest

from clonway_cockpit import obs, render_panels, shell, walk
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import WizardContext
from clonway_cockpit.shell import (
    PROGRESS_TICK as SHELL_PROGRESS_TICK,
)
from clonway_cockpit.shell import (
    CallbackScreen,
    ShellSession,
    activate_item,
    activate_need,
    emit_model,
    open_capability,
    run_doctor,
    run_home,
    show_and_wait,
)
from clonway_cockpit.state import CockpitState, Pill


class _Screen:
    def __init__(self) -> None:
        self.frames: list[Any] = []

    def update(self, renderable: Any) -> None:
        self.frames.append(renderable)


def test_exact_public_import_surface() -> None:
    assert all(
        value is not None
        for value in (
            SHELL_PROGRESS_TICK,
            CallbackScreen,
            ShellSession,
            activate_item,
            activate_need,
            emit_model,
            open_capability,
            run_doctor,
            run_home,
            show_and_wait,
            walk.PROGRESS_TICK,
            walk.await_key,
            walk.emit,
            walk.first_blocked_remedy,
            walk.present,
            render_panels.DEFAULT_HELP_LINES,
            obs.EventBufferScope,
            obs.event_buffer,
            obs.isolated_event_buffers,
        )
    )


def _reader(keys: list[str], calls: list[str] | None = None):
    pending = list(keys)

    def read() -> str:
        if calls is not None:
            calls.append("read")
        return pending.pop(0) if pending else "q"

    return read


def _host(**changes: Any) -> shell.Host:
    usage = SimpleNamespace(record=lambda *args: None, load=lambda: {})
    host = shell.Host(
        capture_state=lambda: CockpitState(
            tenant_name="Clonway",
            pills=(Pill("Bank", "synced", "now", "ok", "bank"),),
        ),
        build_walk_ctx=lambda screen, read_key, **kwargs: WizardContext(
            state={},
            client=None,
            console=SimpleNamespace(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            **kwargs,
        ),
        activate_pill=lambda pill, screen, read_key: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda report: [],
        doctor_fixes_for=lambda probes: [],
        doctor_unconfigured_renderable=lambda: "unconfigured",
        usage=usage,
        on_open=lambda: None,
    )
    return replace(host, **changes)


def test_callback_screen_forwards_once_in_order_and_propagates() -> None:
    seen: list[Any] = []
    adapter = shell.CallbackScreen(seen.append)
    first, second = object(), object()

    assert adapter.update(first) is None
    assert adapter.update(second) is None
    assert seen == [first, second]

    expected = RuntimeError("render failed")

    def fail(renderable: Any) -> None:
        raise expected

    with pytest.raises(RuntimeError) as raised:
        shell.CallbackScreen(fail).update(first)
    assert raised.value is expected


def test_shell_session_methods_keep_exact_active_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    host, screen, read_key = _host(), _Screen(), _reader([])
    session = shell.ShellSession(host, screen, read_key)
    item, model, renderable = object(), object(), object()
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        shell,
        "open_capability",
        lambda *args, **kwargs: calls.append(("open", *args, kwargs)),
    )
    monkeypatch.setattr(shell, "activate_need", lambda *args: calls.append(("need", *args)))
    monkeypatch.setattr(shell, "emit_model", lambda *args: calls.append(("emit", *args)))
    monkeypatch.setattr(shell, "show_and_wait", lambda *args: calls.append(("show", *args)))

    session.open_capability("ledger", focus="overdue")
    session.activate_need(item)
    session.emit_model(model)  # type: ignore[arg-type]
    session.show_and_wait(renderable)

    assert calls == [
        ("open", host, "ledger", screen, read_key, {"focus": "overdue"}),
        ("need", host, item, screen, read_key),
        ("emit", host, model),
        ("show", screen, renderable, read_key),
    ]


def test_session_callback_wins_and_receives_active_session() -> None:
    legacy: list[Any] = []
    aware: list[Any] = []
    screen = _Screen()
    read_key = _reader(["z", "q"])
    host = _host(
        handle_extra_key=lambda *args: legacy.append(args) or True,
        handle_extra_key_with_session=lambda *args: aware.append(args) or True,
    )

    shell.run_home(host, screen, read_key)

    assert legacy == []
    assert len(aware) == 1
    state, selection, key, session = aware[0]
    assert key == "z"
    assert selection is not None
    assert isinstance(state, CockpitState)
    assert session.host is host
    assert session.screen is screen
    assert session.read_key is read_key


def test_legacy_extra_key_callback_is_unchanged_without_session_hook() -> None:
    calls: list[Any] = []
    screen = _Screen()
    read_key = _reader(["z", "q"])
    host = _host(handle_extra_key=lambda *args: calls.append(args) or True)

    shell.run_home(host, screen, read_key)

    assert len(calls) == 1
    assert calls[0][2:] == ("z", screen, read_key)


@pytest.mark.parametrize("agent_mode", [False, True])
def test_session_pill_callback_and_agent_refusal(agent_mode: bool) -> None:
    legacy: list[Any] = []
    aware: list[Any] = []
    models: list[ScreenModel] = []
    screen = _Screen()
    read_key = _reader([])
    host = _host(
        agent_mode=agent_mode,
        activate_pill=lambda *args: legacy.append(args),
        activate_pill_with_session=lambda *args: aware.append(args),
        on_screen=models.append,
    )
    state = host.capture_state()

    shell.activate_item(host, ("pill", 0), state, screen, read_key)

    assert legacy == []
    if agent_mode:
        assert aware == []
        assert len(models) == 1
        assert models[0].title == "Sync skipped"
    else:
        assert len(aware) == 1
        assert aware[0][0] is state.pills[0]
        assert aware[0][1] == shell.ShellSession(host, screen, read_key)
        assert models == []


def test_emit_model_is_best_effort_and_emits_once() -> None:
    model = object()
    seen: list[Any] = []
    shell.emit_model(_host(on_screen=seen.append), model)  # type: ignore[arg-type]
    assert seen == [model]

    def fail(value: Any) -> None:
        raise RuntimeError("observer failed")

    shell.emit_model(_host(on_screen=fail), model)  # type: ignore[arg-type]


def test_show_and_wait_updates_once_then_reads_once_and_propagates() -> None:
    screen = _Screen()
    reads: list[str] = []
    renderable = object()
    shell.show_and_wait(screen, renderable, _reader(["x"], reads))
    assert screen.frames == [renderable]
    assert reads == ["read"]

    expected = RuntimeError("key failed")

    def fail() -> str:
        raise expected

    with pytest.raises(RuntimeError) as raised:
        shell.show_and_wait(screen, renderable, fail)
    assert raised.value is expected


@pytest.mark.parametrize(
    ("public_name", "private_name", "args", "kwargs"),
    [
        ("emit_model", "_safe_emit", (object(), object()), {}),
        ("show_and_wait", "_show", (object(), object(), object()), {}),
        ("activate_need", "_activate_need", (object(), object(), object(), object()), {}),
        ("run_home", "_home", (object(), object(), object()), {}),
        ("activate_item", "_activate", (object(), object(), object(), object(), object()), {}),
        (
            "open_capability",
            "_open_capability",
            (object(), "key", object(), object()),
            {"focus": "today"},
        ),
        ("run_doctor", "_doctor", (object(), object(), object()), {}),
    ],
)
def test_shell_wrappers_resolve_private_owner_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
    public_name: str,
    private_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    seen: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(shell, private_name, lambda *a, **kw: seen.append((a, kw)))
    getattr(shell, public_name)(*args, **kwargs)
    assert seen == [(args, kwargs)]


@pytest.mark.parametrize(
    ("module", "public_name", "private_name"),
    [
        (shell, "emit_model", "_safe_emit"),
        (shell, "show_and_wait", "_show"),
        (shell, "activate_need", "_activate_need"),
        (shell, "run_home", "_home"),
        (shell, "activate_item", "_activate"),
        (shell, "open_capability", "_open_capability"),
        (shell, "run_doctor", "_doctor"),
        (walk, "present", "_present"),
        (walk, "emit", "_emit"),
        (walk, "await_key", "_await"),
        (walk, "first_blocked_remedy", "_first_blocked_remedy"),
    ],
)
def test_public_wrappers_are_one_call_and_keep_private_owner(
    module: Any, public_name: str, private_name: str
) -> None:
    assert hasattr(module, private_name)
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(module, public_name))))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert len(calls) == 1
    assert isinstance(calls[0].func, ast.Name)
    assert calls[0].func.id == private_name


def test_walk_public_constants_and_wrappers_delegate_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert walk.PROGRESS_TICK == walk._PROGRESS_TICK
    ctx, payload = object(), object()
    cases = [
        ("present", "_present", (ctx, payload)),
        ("emit", "_emit", (ctx, payload)),
        ("await_key", "_await", (ctx,)),
        ("first_blocked_remedy", "_first_blocked_remedy", ([],)),
    ]
    for public_name, private_name, args in cases:
        seen: list[tuple[Any, ...]] = []
        monkeypatch.setattr(walk, private_name, lambda *a, out=seen: out.append(a))
        getattr(walk, public_name)(*args)
        assert seen == [args]


def test_default_help_lines_is_canonical_immutable_tuple() -> None:
    assert isinstance(render_panels.DEFAULT_HELP_LINES, tuple)
    assert render_panels.DEFAULT_HELP_LINES is render_panels._DEFAULT_HELP_LINES


def test_event_buffer_scope_is_frozen() -> None:
    scope = obs.EventBufferScope([], True)
    with pytest.raises(FrozenInstanceError):
        scope.owner = False  # type: ignore[misc]


def test_event_buffer_owner_nested_and_cross_worker() -> None:
    with obs.isolated_event_buffers(), obs.event_buffer("alpha") as alpha:
        assert alpha.owner is True
        with obs.event_buffer("alpha") as nested:
            assert nested.owner is False
            assert nested.events is alpha.events
        with obs.event_buffer("beta") as beta:
            assert beta.owner is True
            assert beta.events is not alpha.events
            beta.events.append({"worker": "beta"})
        assert alpha.events == []


def test_make_obs_appends_exact_record_to_public_scope() -> None:
    event, _run_session = obs.make_obs(
        worker_id="alpha",
        logger_factory=lambda name: logging.getLogger("public-scope-test"),
    )
    with obs.isolated_event_buffers(), obs.event_buffer("alpha") as scope:
        event("custom.event", answer=42)
        assert len(scope.events) == 1
        record = scope.events[0]
        assert record["event"] == "custom.event"
        assert record["payload"] == {"severity": "INFO", "answer": 42}
        assert isinstance(record["ts"], str)


def test_nested_isolation_restores_exact_outer_scope() -> None:
    with obs.isolated_event_buffers(), obs.event_buffer("alpha") as outer:
        outer.events.append({"outer": True})
        with obs.isolated_event_buffers(), obs.event_buffer("alpha") as inner:
            assert inner.owner is True
            assert inner.events == []
        with obs.event_buffer("alpha") as restored:
            assert restored.owner is False
            assert restored.events is outer.events
            assert restored.events == [{"outer": True}]


def test_event_buffer_resets_on_async_cancellation_and_restores_outer_mapping() -> None:
    async def exercise() -> None:
        with obs.isolated_event_buffers(), obs.event_buffer("alpha") as outer:

            async def child() -> None:
                with obs.event_buffer("beta") as beta:
                    beta.events.append({"child": True})
                    await asyncio.Event().wait()

            task = asyncio.create_task(child())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            with obs.event_buffer("alpha") as restored:
                assert restored.events is outer.events
                assert restored.owner is False
            with obs.event_buffer("beta") as beta_after:
                assert beta_after.owner is True
                assert beta_after.events == []

    asyncio.run(exercise())


def test_copied_thread_context_reset_cannot_corrupt_parent_mapping() -> None:
    with obs.isolated_event_buffers(), obs.event_buffer("alpha") as outer:
        copied = contextvars.copy_context()
        errors: list[BaseException] = []

        def child() -> None:
            try:
                with obs.event_buffer("beta") as beta:
                    assert beta.owner is True
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=lambda: copied.run(child))
        thread.start()
        thread.join()

        assert errors == []
        with obs.event_buffer("alpha") as restored:
            assert restored.events is outer.events
            assert restored.owner is False
        with obs.event_buffer("beta") as beta_after:
            assert beta_after.owner is True


@pytest.mark.parametrize("worker_id", ["", " ", None, 7])
def test_event_buffer_rejects_invalid_worker_before_binding(worker_id: Any) -> None:
    with obs.isolated_event_buffers():
        with pytest.raises(ValueError), obs.event_buffer(worker_id):
            pytest.fail("invalid worker was bound")
        with obs.event_buffer("valid") as scope:
            assert scope.owner is True


@pytest.mark.parametrize(
    "error",
    [RuntimeError("boom"), KeyboardInterrupt(), SystemExit()],
)
def test_event_buffer_resets_after_base_exception(error: BaseException) -> None:
    with obs.isolated_event_buffers():
        with pytest.raises(type(error)), obs.event_buffer("alpha") as first:
            first.events.append({"first": True})
            raise error
        with obs.event_buffer("alpha") as second:
            assert second.owner is True
            assert second.events == []
