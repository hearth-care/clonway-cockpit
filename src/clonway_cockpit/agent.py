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
import sys
from collections.abc import Iterable
from dataclasses import replace

from rich.console import RenderableType

from clonway_cockpit import shell, shellout
from clonway_cockpit.model import Region, ScreenModel

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


def serve_stdio(host: shell.Host, *, stdin=sys.stdin, stdout=sys.stdout) -> None:  # noqa: ANN001
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
    don't get an interactive child shell."""
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

    agent_host = replace(host, on_screen=on_screen, agent_mode=True)
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
