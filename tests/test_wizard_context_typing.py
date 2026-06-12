import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_wizard_context_client_type_flows_to_handlers(tmp_path):
    snippet = tmp_path / "typed_worker.py"
    snippet.write_text(
        textwrap.dedent(
            """
            from collections.abc import Callable

            from clonway_cockpit.registry import AnyWizardContext, WizardContext


            class FakeClient:
                def ping(self) -> str:
                    return "pong"


            Handler = Callable[[WizardContext[FakeClient]], str]


            def handler(ctx: WizardContext[FakeClient]) -> str:
                assert ctx.client is not None
                return ctx.client.ping()


            typed_handler: Handler = handler


            def generic_handler(ctx: AnyWizardContext) -> None:
                ctx.client
            """
        )
    )

    env = {**os.environ, "MYPYPATH": "src", "PYTHONPATH": "src"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-incremental",
            "--python-version",
            "3.12",
            "--strict",
            str(snippet),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
