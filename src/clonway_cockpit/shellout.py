"""Cockpit shell-out — leave the alt-screen to run an interactive CLI command
(browser OAuth / a setup wizard) on the real terminal, then return.

The cockpit runs inside ``console.screen()``. An interactive child can't share
that alt-screen, so a shell-out capability's ``run`` raises ``ShellOut`` carrying
the command to run; ``run_cockpit`` catches it OUTSIDE the screen context, runs
the child against the real tty (inherited stdio) via ``run_shellout``, waits for
a keypress, and re-enters the cockpit.

The argv table is worker-owned: a worker builds the ``ShellOut`` with the argv
(and a human label) for the command it wants to drop out to. The framework only
provides the exception shape + the run mechanism."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class ShellOut(Exception):
    """Signal raised by a shell-out capability's ``run`` to leave the alt-screen.

    ``key`` is a stable identifier for the command (telemetry / dispatch).
    ``argv`` is the full command to execute; ``label`` is the human verb shown
    while it runs. A worker constructs this with the command it wants to run."""

    key: str
    argv: Sequence[str] = field(default_factory=tuple)
    label: str = ""


def run_shellout(shellout: ShellOut) -> None:
    """Run a shell-out command against the real terminal (inherited stdio), then
    wait for a keypress so the operator can read its output before the cockpit
    re-enters. The argv + label come from the ``ShellOut`` the worker raised."""
    label = shellout.label or shellout.key
    argv = list(shellout.argv)
    print(f"\n— {label}: running `{' '.join(argv)}` —\n", flush=True)
    subprocess.run(argv, check=False)
    input("\nDone — press Enter to return to the cockpit… ")
