"""``page()`` frames a centred window that grows with the terminal up to a cap.

Sizing is via the Rich console protocol, so it tracks the RENDERING console's
width — deterministic here, wide on a real terminal. We measure the rounded
panel's top border (``╭ … ╮``) to recover the actual window width."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from clonway_cockpit import render


def _panel_width(console_width: int) -> int:
    con = Console(width=console_width)
    with con.capture() as cap:
        con.print(render.page(Text("x")))
    for line in cap.get().splitlines():
        if "╭" in line and "╮" in line:
            return line.index("╮") - line.index("╭") + 1
    raise AssertionError("no rounded-panel border found in output")


def test_page_grows_with_terminal_up_to_cap():
    # Narrow terminal → window tracks it.
    assert _panel_width(60) == 60
    # Reference width unchanged (keeps existing screens/tests stable).
    assert _panel_width(96) == 96
    # Wide terminal → grows, but capped (uses the real estate without a
    # wall-of-text line length).
    assert _panel_width(200) == render._PANEL_MAX_WIDTH
    assert render._PANEL_MAX_WIDTH == 140
