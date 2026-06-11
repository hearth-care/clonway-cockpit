from __future__ import annotations

from typing import Any

import pytest

from clonway_cockpit.gsheets import SheetsClient, a1, col_letter, extract_sheet_id


class FakeHttpError(Exception):
    def __init__(self, status: int):
        self.resp = type("Resp", (), {"status": status})()
        super().__init__(f"HTTP {status}")


class FakeRequest:
    def __init__(self, service: FakeSheetsService, response: dict[str, Any]):
        self._service = service
        self._response = response

    def execute(self) -> dict[str, Any]:
        if self._service.failures:
            raise FakeHttpError(self._service.failures.pop(0))
        return self._response


class FakeValuesResource:
    def __init__(self, service: FakeSheetsService):
        self._service = service

    def get(self, **kwargs: Any) -> FakeRequest:
        self._service.calls.append(("values.get", kwargs))
        return FakeRequest(self._service, self._service.values_get_response)

    def batchGet(self, **kwargs: Any) -> FakeRequest:  # noqa: N802 - Google API surface
        self._service.calls.append(("values.batchGet", kwargs))
        return FakeRequest(self._service, self._service.batch_get_response)

    def append(self, **kwargs: Any) -> FakeRequest:
        self._service.calls.append(("values.append", kwargs))
        return FakeRequest(self._service, {"updates": {"updatedRange": "register!A2:B2"}})

    def update(self, **kwargs: Any) -> FakeRequest:
        self._service.calls.append(("values.update", kwargs))
        return FakeRequest(self._service, {"updatedCells": 2})


class FakeSpreadsheetsResource:
    def __init__(self, service: FakeSheetsService):
        self._service = service

    def values(self) -> FakeValuesResource:
        return FakeValuesResource(self._service)

    def get(self, **kwargs: Any) -> FakeRequest:
        self._service.calls.append(("spreadsheets.get", kwargs))
        return FakeRequest(self._service, self._service.metadata_response)

    def batchUpdate(self, **kwargs: Any) -> FakeRequest:  # noqa: N802 - Google API surface
        self._service.calls.append(("spreadsheets.batchUpdate", kwargs))
        return FakeRequest(self._service, {"replies": []})


class FakeSheetsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failures: list[int] = []
        self.metadata_response = {
            "sheets": [
                {"properties": {"title": "register"}},
                {"properties": {"title": "archive"}},
            ]
        }
        self.values_get_response: dict[str, Any] = {"values": []}
        self.batch_get_response: dict[str, Any] = {"valueRanges": []}

    def spreadsheets(self) -> FakeSpreadsheetsResource:
        return FakeSpreadsheetsResource(self)


def test_extract_sheet_id_accepts_bare_ids_and_sheets_urls():
    assert extract_sheet_id("abcDEF_1234567890-abcdefghijkl") == "abcDEF_1234567890-abcdefghijkl"
    assert (
        extract_sheet_id(
            "https://docs.google.com/spreadsheets/d/abcDEF_1234567890-abcdefghijkl/edit#gid=0"
        )
        == "abcDEF_1234567890-abcdefghijkl"
    )

    with pytest.raises(ValueError, match="could not extract"):
        extract_sheet_id("https://example.com/not-a-sheet")


@pytest.mark.parametrize(
    ("number", "letter"),
    [(1, "A"), (26, "Z"), (27, "AA"), (52, "AZ"), (703, "AAA")],
)
def test_col_letter_round_trips(number: int, letter: str):
    assert col_letter(number) == letter


def test_a1_quotes_tabs_and_builds_cell_or_range():
    assert a1("Register", row=2, col=3) == "'Register'!C2"
    assert a1("DBS Register", row=2, col=1, end_row=4, end_col=3) == "'DBS Register'!A2:C4"
    assert a1("Owner's Tab", row=1, col=1) == "'Owner''s Tab'!A1"
    assert a1("Register") == "'Register'"


def test_list_tabs_uses_metadata_shape_from_bookkeeper_copy():
    service = FakeSheetsService()
    client = SheetsClient(service, "sheet123")

    assert client.list_tabs() == ["register", "archive"]
    assert service.calls == [
        (
            "spreadsheets.get",
            {"spreadsheetId": "sheet123", "fields": "sheets(properties(title))"},
        )
    ]


def test_batch_get_returns_range_keyed_values():
    service = FakeSheetsService()
    service.batch_get_response = {
        "valueRanges": [
            {"range": "register!A1:B2", "values": [["name", "status"], ["Ada", "clear"]]},
            {"range": "archive!A1:A1"},
        ]
    }
    client = SheetsClient(service, "sheet123")

    assert client.batch_get(["register!A1:B2", "archive!A1:A1"]) == {
        "register!A1:B2": [["name", "status"], ["Ada", "clear"]],
        "archive!A1:A1": [],
    }
    assert service.calls == [
        (
            "values.batchGet",
            {"spreadsheetId": "sheet123", "ranges": ["register!A1:B2", "archive!A1:A1"]},
        )
    ]


def test_get_records_pads_ragged_rows_to_header_width():
    service = FakeSheetsService()
    service.values_get_response = {
        "values": [
            ["dbs_id", "name", "status"],
            ["DBS-1", "Ada"],
            ["DBS-2", "Grace", "clear", "ignored"],
        ]
    }
    client = SheetsClient(service, "sheet123")

    assert client.get_records("register") == [
        {"dbs_id": "DBS-1", "name": "Ada", "status": ""},
        {"dbs_id": "DBS-2", "name": "Grace", "status": "clear"},
    ]
    assert service.calls == [("values.get", {"spreadsheetId": "sheet123", "range": "register"})]


def test_get_records_with_non_default_header_row_fetches_data_rows():
    service = FakeSheetsService()
    service.values_get_response = {
        "values": [
            ["dbs_id", "name", "status"],
            ["DBS-1", "Ada", "clear"],
            ["DBS-2", "Grace"],
        ]
    }
    client = SheetsClient(service, "sheet123")

    assert client.get_records("Register", header_row=2) == [
        {"dbs_id": "DBS-1", "name": "Ada", "status": "clear"},
        {"dbs_id": "DBS-2", "name": "Grace", "status": ""},
    ]
    assert service.calls == [
        ("values.get", {"spreadsheetId": "sheet123", "range": "'Register'!2:"})
    ]


def test_retries_429s_with_injected_sleep_then_succeeds():
    service = FakeSheetsService()
    service.failures = [429, 429, 429, 429]
    sleeps: list[float] = []
    client = SheetsClient(service, "sheet123", sleep=sleeps.append, jitter=lambda _delay: 0)

    assert client.list_tabs() == ["register", "archive"]
    assert sleeps == [1, 2, 4, 8]
    assert [name for name, _kwargs in service.calls] == ["spreadsheets.get"] * 5


def test_gives_up_after_fifth_retryable_error():
    service = FakeSheetsService()
    service.failures = [500, 500, 500, 500, 500]
    sleeps: list[float] = []
    client = SheetsClient(service, "sheet123", sleep=sleeps.append, jitter=lambda _delay: 0)

    with pytest.raises(FakeHttpError, match="HTTP 500"):
        client.list_tabs()

    assert sleeps == [1, 2, 4, 8]
    assert [name for name, _kwargs in service.calls] == ["spreadsheets.get"] * 5


def test_append_update_and_format_payloads_match_existing_worker_shapes():
    service = FakeSheetsService()
    client = SheetsClient(service, "sheet123")

    client.append_rows("register", [["DBS-1", "Ada"]])
    client.update_range("register!A2:B2", [["DBS-1", "clear"]])
    client.batch_format([{"repeatCell": {"range": {"sheetId": 0}}}])

    assert service.calls == [
        (
            "values.append",
            {
                "spreadsheetId": "sheet123",
                "range": "register",
                "valueInputOption": "RAW",
                "insertDataOption": "INSERT_ROWS",
                "body": {"values": [["DBS-1", "Ada"]]},
            },
        ),
        (
            "values.update",
            {
                "spreadsheetId": "sheet123",
                "range": "register!A2:B2",
                "valueInputOption": "RAW",
                "body": {"values": [["DBS-1", "clear"]]},
            },
        ),
        (
            "spreadsheets.batchUpdate",
            {
                "spreadsheetId": "sheet123",
                "body": {"requests": [{"repeatCell": {"range": {"sheetId": 0}}}]},
            },
        ),
    ]
