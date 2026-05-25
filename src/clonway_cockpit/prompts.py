"""Injectable prompt helpers for the cockpit framework.

``InputFn``/``ConfirmFn`` are injected so domains and pickers are unit-testable
with scripted answers. The default impls wrap Typer/Rich for real interactive
use; Typer is imported lazily inside those defaults so importing this module
needs only ``rich`` (the framework's sole hard runtime dependency) — a worker
that actually calls a default fn must have ``typer`` installed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as Date
from decimal import Decimal, InvalidOperation

from rich.console import Console

InputFn = Callable[[str, str], str]
ConfirmFn = Callable[[str], bool]


def default_input_fn() -> InputFn:
    import typer

    def _ask(prompt_text: str, default: str = "") -> str:
        return typer.prompt(prompt_text, default=default)

    return _ask


def make_clean_input_fn() -> InputFn:
    """Prompt fn for the cockpit: renders the prompt text verbatim — no ``": "``
    suffix and no default echo — so a bare ``"▸ "`` cursor matches the design."""
    import typer

    def _ask(prompt_text: str, default: str = "") -> str:
        return typer.prompt(prompt_text, default=default, show_default=False, prompt_suffix="")

    return _ask


def default_confirm_fn() -> ConfirmFn:
    import typer

    def _confirm(prompt_text: str) -> bool:
        return typer.confirm(prompt_text)

    return _confirm


def ask_required(input_fn: InputFn, prompt_text: str) -> str:
    """Re-prompt until the answer is non-blank."""
    while True:
        value = (input_fn(prompt_text, "") or "").strip()
        if value:
            return value


def ask_decimal(input_fn: InputFn, prompt_text: str) -> Decimal:
    """Re-prompt until the answer parses as a Decimal."""
    while True:
        raw = (input_fn(prompt_text, "") or "").strip()
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            continue


def ask_int(input_fn: InputFn, prompt_text: str, *, default: int) -> int:
    """Blank accepts ``default``; otherwise re-prompt until it parses as int."""
    while True:
        raw = (input_fn(prompt_text, str(default)) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            continue


def ask_optional_decimal(input_fn: InputFn, prompt_text: str) -> Decimal | None:
    """Blank → None; otherwise re-prompt until it parses as a Decimal."""
    while True:
        raw = (input_fn(prompt_text, "") or "").strip()
        if not raw:
            return None
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            continue


def ask_optional_date(input_fn: InputFn, prompt_text: str) -> Date | None:
    """Blank → None; otherwise re-prompt until it parses as YYYY-MM-DD."""
    while True:
        raw = (input_fn(prompt_text, "") or "").strip()
        if not raw:
            return None
        try:
            return Date.fromisoformat(raw)
        except ValueError:
            continue


def choose(input_fn: InputFn, title: str, options: list[tuple[str, str]]) -> str:
    """Render a numbered menu of (key, label); return the chosen key.

    Accepts a 1-based index or the raw key string; re-prompts until valid.
    """
    keys = {key for key, _ in options}
    lines = "\n".join(f"  {i}. {label}" for i, (_key, label) in enumerate(options, 1))
    while True:
        raw = (input_fn(f"{title}\n{lines}\nChoice", "") or "").strip()
        # Accept direct key match (e.g. "q" for quit).
        if raw in keys:
            return raw
        try:
            idx = int(raw)
        except ValueError:
            continue
        if 1 <= idx <= len(options):
            return options[idx - 1][0]


def make_console_input_fn(console: Console) -> InputFn:
    """Rich-backed input fn (kept for callers that already hold a Console)."""
    from rich.prompt import Prompt

    def _ask(prompt_text: str, default: str = "") -> str:
        return Prompt.ask(prompt_text, default=default, console=console)

    return _ask
