"""In-process headless driver for the cockpit.

``CockpitDriver`` runs the real shell loop (``shell.run_cockpit``) with a scripted
key sequence and a no-op screen, installing the ``on_screen`` observer so it records
the ``ScreenModel`` stream the loop emits. It is the non-brittle test harness and the
in-process core the subprocess ``--agent`` protocol (M2) is built on top of.

Driving is scripted (a fixed key list) rather than interactive ``send()`` stepping;
interactive stepping arrives with the M2 stdio protocol, which needs a thread/queue
pump. For verification — drive a known path, assert on the recorded models — scripted
keys match the existing framework test harness exactly.
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import replace

from rich.console import RenderableType

from clonway_cockpit import shell, shellout
from clonway_cockpit.model import Region, ScreenModel

_log = logging.getLogger(__name__)

# Cap a single stdin message so a hostile/buggy peer can't force unbounded buffering.
_MAX_MSG_BYTES = 1_000_000


class _NullScreen:
    """A screen sink that renders nothing — the driver reads models, not pixels."""

    def update(self, renderable: RenderableType) -> None:
        return None


class CockpitDriver:
    """Drive the cockpit headlessly and record the ScreenModel stream it emits."""

    def __init__(self, host: shell.Host, keys: Iterable[str] | None = None) -> None:
        self._stream: list[ScreenModel] = []
        self._host = replace(host, on_screen=self._stream.append)
        self._keys: list[str] = list(keys or [])

    def _read_key(self) -> str:
        # Out of scripted keys → 'q' so every nested loop terminates (matches the
        # framework test harness's _keys helper).
        return self._keys.pop(0) if self._keys else "q"

    def run(self) -> list[ScreenModel]:
        """Run the full home loop with the scripted keys; return the recorded stream."""
        shell.run_cockpit(self._host, read_key=self._read_key, screen=_NullScreen())
        return self._stream

    @property
    def stream(self) -> list[ScreenModel]:
        return self._stream

    @property
    def last(self) -> ScreenModel:
        return self._stream[-1]


def serve_stdio(
    host: shell.Host,
    *,
    stdin=sys.stdin,  # noqa: ANN001
    stdout=sys.stdout,  # noqa: ANN001
    allow_apply: bool = False,
    on_apply: Callable[[dict], None] | None = None,
) -> None:
    """Drive the real cockpit over line-delimited JSON on stdin/stdout — the
    subprocess transport an external agent process uses to launch + drive the
    cockpit. A thin pump over ``shell.run_cockpit``: each draw writes the screen's
    ``ScreenModel.to_dict()`` as a JSON line to stdout; each loop ``read_key`` blocks
    reading one JSON message from stdin. Runs in agent mode (``Host.agent_mode``), so
    every walk's write gate is dry-run — the agent can drive any flow but never posts.

    Protocol (one JSON object per line):
      agent -> app : {"key": "<k>"} | {"cmd": "snapshot"} | {"cmd": "quit"}
      app -> agent : <ScreenModel.to_dict()>  |  {"error": "<reason>"}
    Stdin EOF unwinds the cockpit (treated as quit). A capability that shells out
    (``ShellOut``) surfaces as a note frame rather than exec'ing a child — agents
    don't get an interactive child shell.

    ``allow_apply`` (M4, default False) opts into the guarded-apply handshake: at a
    write gate the app emits ``walk.gate{gate:"awaiting_apply",token,…}`` and the next
    message must be exactly ``{"apply":true,"token":<token>}`` to post — anything else
    declines. With it False (the default) the gate stays pure dry-run and NEVER posts."""
    last: list[ScreenModel | None] = [None]

    def _write(obj: dict) -> None:
        # Best-effort: a broken downstream pipe must unwind cleanly (EOF on the next
        # read), never raise out of the pump.
        with contextlib.suppress(Exception):
            stdout.write(json.dumps(obj) + "\n")
            stdout.flush()

    def on_screen(model: ScreenModel) -> None:
        last[0] = model
        _write(model.to_dict())

    def read_key() -> str:
        while True:
            # Cap the line so a hostile/buggy peer can't force unbounded buffering;
            # an over-long line just fails to parse and is reported.
            raw = stdin.readline(_MAX_MSG_BYTES)
            if raw == "":  # EOF → unwind the cockpit
                return "q"
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except (ValueError, TypeError, RecursionError):
                # RecursionError: deeply-nested JSON. Caught so a malformed message
                # degrades to an error reply instead of crashing the session.
                _write({"error": "invalid json"})
                continue
            if not isinstance(msg, dict):
                _write({"error": "expected a JSON object"})
                continue
            if "key" in msg:
                key = msg["key"]
                if not isinstance(key, str):
                    _write({"error": "key must be a string"})
                    continue
                return key
            cmd = msg.get("cmd")
            if cmd == "snapshot":
                if last[0] is not None:
                    _write(last[0].to_dict())
                continue
            if cmd == "quit":
                return "q"
            _write({"error": f"unknown message: {msg}"})

    def authorize_apply(proposal: dict) -> bool:
        # Read ONE message and authorize iff it is exactly {"apply":true,"token":<the
        # gate's token>}. Anything else (wrong/missing token, a different message, bad
        # JSON, EOF) declines — fail-safe. The per-gate token defeats stale/replayed
        # applies. The human-sign-off policy is the agent's; this only enforces the
        # explicit, gate-matched handshake.
        raw = stdin.readline(_MAX_MSG_BYTES)
        if raw == "":  # EOF → decline
            return False
        line = raw.strip()
        if not line:
            return False
        try:
            msg = json.loads(line)
        except (ValueError, TypeError, RecursionError):
            _write({"error": "invalid json"})
            return False
        if not isinstance(msg, dict):
            _write({"error": "expected a JSON object"})
            return False
        authorized = msg.get("apply") is True and msg.get("token") == proposal["token"]
        if authorized and on_apply is not None:
            # Authoritative audit hook: fire on an AUTHORIZED apply (before the post),
            # so a worker can log the applied gate via its own obs. Best-effort — a
            # logging failure must never block or crash the post.
            with contextlib.suppress(Exception):
                on_apply(proposal)
        return authorized

    agent_host = replace(
        host,
        on_screen=on_screen,
        agent_mode=True,
        authorize_apply=authorize_apply if allow_apply else None,
    )
    try:
        shell.run_cockpit(agent_host, read_key=read_key, screen=_NullScreen())
    except shellout.ShellOut as so:
        # serve_stdio drives run_cockpit directly (no worker alt-screen wrapper to
        # catch ShellOut), so surface it as a note frame instead of crashing. Agents
        # don't get an interactive child shell; the session ends after the note.
        _write(
            ScreenModel(
                kind="note",
                title="shell-out",
                regions=[Region("prose", "", text=str(so) or "capability shelled out")],
                actions=["any"],
                meta={"shellout": True},
            ).to_dict()
        )


def serve_agent_stdio(
    host: shell.Host,
    *,
    allow_apply: bool = False,
    stdin=sys.stdin,  # noqa: ANN001
    stdout=sys.stdout,  # noqa: ANN001
) -> None:
    """The worker-side one-liner a CLI ``--agent-stdio`` callback calls: serve the agent
    protocol over stdin/stdout. Thin over :func:`serve_stdio` (which already forces
    ``agent_mode=True`` and wires the guarded-apply handshake when ``allow_apply``).

    Promoted into the framework so every consumer stops hand-rolling its own ``serve_agent``;
    the worker-template generates a call to this. NOTE the host-rebuild recipe: if a worker's
    ``_host()`` is re-invoked inside its own callbacks, build it agent-mode-aware (see
    docs/agent-screen-model.md → 'Wiring a worker to the agent channel')."""
    serve_stdio(host, stdin=stdin, stdout=stdout, allow_apply=allow_apply)


class CockpitClosed(Exception):
    """The cockpit stream closed (worker exited / EOF) when a frame was expected."""


_EOF = object()  # sentinel the reader thread enqueues on stream close


class CockpitClient:
    """Drive a worker's cockpit over the ``--agent-stdio`` protocol — the framework-owned
    PEER of :func:`serve_stdio`. The orchestrator, a CLI session, and an autonomous agent all
    drive through this one class, so 'human operating' and 'agent operating' are the same path.

    The protocol is emit-driven (every draw writes a frame), so a background reader thread
    pumps frames onto a queue and the request methods read from it. Two constructors:
    :meth:`spawn` launches ``<worker> --agent-stdio`` as a subprocess (production);
    :meth:`over_streams` wraps an existing reader/writer pair (tests, or any owned transport)."""

    def __init__(self, *, stdin, stdout, proc=None, timeout: float = 30.0) -> None:  # noqa: ANN001
        # stdin = the stream WE READ frames from (the app's stdout);
        # stdout = the stream WE WRITE messages to (the app's stdin).
        # timeout = how long a single read waits for a frame before treating the cockpit as
        # closed. Default 30s is generous on purpose: a cold-starting worker (the fleet bridge
        # can take ~15s to paint its first frame) must not trip a spurious close.
        self._in = stdin
        self._out = stdout
        self._proc = proc
        self._timeout = timeout
        self._q: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    @classmethod
    def over_streams(cls, *, stdin, stdout, timeout: float = 30.0) -> CockpitClient:  # noqa: ANN001
        return cls(stdin=stdin, stdout=stdout, timeout=timeout)

    @classmethod
    def spawn(
        cls,
        argv: list[str],
        *,
        cwd: str | None = None,
        env: dict | None = None,
        timeout: float = 30.0,
    ) -> CockpitClient:
        proc = subprocess.Popen(  # noqa: S603 — argv is caller-controlled, not a shell string
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return cls(stdin=proc.stdout, stdout=proc.stdin, proc=proc, timeout=timeout)

    def _read_loop(self) -> None:
        try:
            while True:
                line = self._in.readline(_MAX_MSG_BYTES)
                if line == "":  # EOF
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    self._q.put(json.loads(line))
                except (ValueError, TypeError):
                    continue  # skip a malformed line rather than killing the reader
        finally:
            self._q.put(_EOF)

    def _send(self, obj: dict) -> None:
        try:
            self._out.write(json.dumps(obj) + "\n")
            self._out.flush()
        except OSError as e:
            # The peer's stdin pipe broke (worker exited) — surface as a clean close so
            # callers (e.g. xops.drive.drive_argv) that handle CockpitClosed don't take a raw
            # BrokenPipeError to the face.
            _log.warning("cockpit driver: input stream broke on send (%s) — closing", e)
            raise CockpitClosed("cockpit input stream closed") from e

    def _next(self, timeout: float | None = None) -> dict:
        t = self._timeout if timeout is None else timeout
        try:
            frame = self._q.get(timeout=t)
        except queue.Empty as e:
            _log.warning("cockpit driver: no frame within %.1fs — treating as closed", t)
            raise CockpitClosed(f"timed out waiting for a frame after {t:.1f}s") from e
        if frame is _EOF:
            _log.warning("cockpit driver: stream closed (worker exited / EOF)")
            raise CockpitClosed("cockpit stream closed")
        return frame

    def read_home(self) -> dict:
        """Read the first frame the cockpit paints on open."""
        return self._next()

    def press(self, key: str) -> dict:
        """Send a keypress; return the next frame the cockpit emits."""
        self._send({"key": key})
        return self._next()

    def snapshot(self) -> dict:
        """Ask for the current screen again (no state change)."""
        self._send({"cmd": "snapshot"})
        return self._next()

    def apply(self, token: str, *, approve, proposal=None) -> dict:  # noqa: ANN001
        """Complete the guarded-apply handshake at a ``walk.gate{awaiting_apply}`` frame.
        ``approve(proposal) -> bool`` is the authorization-policy seam (see
        ``clonway_cockpit.approval``): called with the proposal; only a True result sends
        ``{"apply":true,"token":token}``. Any other result sends ``{"apply":false}`` so the
        app declines. Returns the next frame (applied/declined). Never auto-approves — the
        policy is the caller's.

        ``proposal`` is what the policy is shown. Pass the gate frame's ``meta`` (so the policy
        sees ``equivalent_cli`` + the apply identity, not just the token); when omitted it
        defaults to ``{"token": token}`` (back-compatible)."""
        prop = dict(proposal) if proposal is not None else {"token": token}
        prop.setdefault("token", token)
        if approve(prop):
            self._send({"apply": True, "token": token})
        else:
            self._send({"apply": False})
        return self._next()

    def drain(self, *, idle: float = 0.1) -> list[dict]:
        """Collect any further frames already in flight (an action can emit several before
        the app blocks for input — e.g. applied + the home redraw), until none arrive within
        ``idle``. Use to resync after a multi-frame action; the last entry is the current
        screen."""
        out: list[dict] = []
        while True:
            try:
                frame = self._q.get(timeout=idle)
            except queue.Empty:
                break
            if frame is _EOF:
                self._q.put(
                    _EOF
                )  # keep the sentinel so a later _next() reports closed, not a timeout
                break
            out.append(frame)
        return out

    def quit(self) -> None:
        """End the session: send ``quit``, then ensure a spawned child actually exits. A child
        that ignores ``quit``/EOF is escalated terminate → kill so it is never orphaned (FBA
        hardening — previously a stuck worker survived the 5s ``wait`` with no signal sent)."""
        with contextlib.suppress(Exception):
            self._send({"cmd": "quit"})
        if self._proc is None:
            return
        try:
            self._proc.wait(timeout=5)
            return
        except Exception:  # noqa: BLE001 — timeout or already-dead; escalate to a signal
            pass
        for signal_fn in (self._proc.terminate, self._proc.kill):
            with contextlib.suppress(Exception):
                signal_fn()
                self._proc.wait(timeout=5)
                if self._proc.poll() is not None:
                    return

    def __enter__(self) -> CockpitClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.quit()
