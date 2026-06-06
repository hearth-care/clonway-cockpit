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

from collections.abc import Iterable
from dataclasses import replace

from rich.console import RenderableType

from clonway_cockpit import shell
from clonway_cockpit.model import ScreenModel


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
