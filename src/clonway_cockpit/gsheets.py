"""Thin Google Sheets v4 helpers with injected service construction."""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable, Sequence
from typing import Any

_SHEET_ID_PATTERNS = (
    re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]{20,})"),
    re.compile(r"/d/([a-zA-Z0-9_-]{20,})"),
)


def extract_sheet_id(value: str) -> str:
    """Return a Sheets file ID from a URL, or the bare ID if already one."""
    candidate = value.strip()
    if not candidate:
        raise ValueError("empty Sheets ID / URL")
    if "://" not in candidate and "/" not in candidate:
        return candidate
    for pattern in _SHEET_ID_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(1)
    raise ValueError(f"could not extract a Sheets file ID from {value!r}")


def col_letter(n: int) -> str:
    """Convert a 1-based column number to an A1 column letter."""
    if n < 1:
        raise ValueError("column number must be >= 1")
    letter = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letter = chr(65 + remainder) + letter
    return letter


def a1(
    tab: str,
    *,
    row: int | None = None,
    col: int | None = None,
    end_row: int | None = None,
    end_col: int | None = None,
) -> str:
    """Build a quoted A1 tab/cell/range reference."""
    quoted_tab = "'" + tab.replace("'", "''") + "'"
    if row is None and col is None:
        return quoted_tab
    if row is None or col is None:
        raise ValueError("row and col must be provided together")
    start = f"{col_letter(col)}{row}"
    if end_row is None and end_col is None:
        return f"{quoted_tab}!{start}"
    if end_row is None or end_col is None:
        raise ValueError("end_row and end_col must be provided together")
    return f"{quoted_tab}!{start}:{col_letter(end_col)}{end_row}"


class SheetsClient:
    def __init__(
        self,
        service: Any,
        spreadsheet_id: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        self._service = service
        self._spreadsheet_id = spreadsheet_id
        self._sleep = sleep
        self._jitter = jitter or (lambda delay: random.uniform(0, delay * 0.1))

    def list_tabs(self) -> list[str]:
        response = self._execute(
            lambda: self._service.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id,
                fields="sheets(properties(title))",
            )
        )
        return [sheet["properties"]["title"] for sheet in response.get("sheets", [])]

    def batch_get(self, ranges: Sequence[str]) -> dict[str, list[list[str]]]:
        response = self._execute(
            lambda: (
                self._service.spreadsheets()
                .values()
                .batchGet(spreadsheetId=self._spreadsheet_id, ranges=list(ranges))
            )
        )
        return {
            item["range"]: item.get("values", []) or [] for item in response.get("valueRanges", [])
        }

    def get_records(self, tab: str, *, header_row: int = 1) -> list[dict[str, str]]:
        range_ = tab if header_row == 1 else f"{a1(tab)}!{header_row}:"
        response = self._execute(
            lambda: (
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=self._spreadsheet_id, range=range_)
            )
        )
        rows = response.get("values", []) or []
        if not rows:
            return []
        header = [str(value) for value in rows[0]]
        records: list[dict[str, str]] = []
        for row in rows[1:]:
            padded = [str(value) for value in row[: len(header)]]
            padded.extend([""] * (len(header) - len(padded)))
            records.append(dict(zip(header, padded, strict=False)))
        return records

    def append_rows(
        self,
        tab: str,
        rows: Sequence[Sequence[object]],
        *,
        value_input: str = "RAW",
    ) -> None:
        self._execute(
            lambda: (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=tab,
                    valueInputOption=value_input,
                    insertDataOption="INSERT_ROWS",
                    body={"values": [list(row) for row in rows]},
                )
            )
        )

    def update_range(
        self,
        range_: str,
        values: Sequence[Sequence[object]],
        *,
        value_input: str = "RAW",
    ) -> None:
        self._execute(
            lambda: (
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self._spreadsheet_id,
                    range=range_,
                    valueInputOption=value_input,
                    body={"values": [list(row) for row in values]},
                )
            )
        )

    def batch_format(self, requests: Sequence[dict]) -> None:
        self._execute(
            lambda: self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": list(requests)},
            )
        )

    def _execute(self, request_factory: Callable[[], Any]) -> dict[str, Any]:
        delay = 1.0
        for attempt in range(5):
            try:
                return request_factory().execute()
            except Exception as exc:
                if attempt == 4 or not _is_retryable(exc):
                    raise
                self._sleep(delay + self._jitter(delay))
                delay *= 2
        raise RuntimeError("unreachable")


def _is_retryable(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    return status == 429 or (isinstance(status, int) and 500 <= status <= 599)
