from __future__ import annotations

from clonway_cockpit.model import SCHEMA_VERSION, Field, Region, Row, ScreenModel


def test_screenmodel_to_dict_is_json_shaped():
    m = ScreenModel(
        kind="home",
        title="xbook",
        regions=[
            Region(
                role="toolkit",
                title="toolkit",
                rows=[Row(id="shelf:C", label="Money out", selected=True)],
            )
        ],
        selection="shelf:C",
        actions=["up", "down", "enter"],
        meta={"app_label": "xbook"},
    )
    d = m.to_dict()
    assert d["kind"] == "home"
    assert d["selection"] == "shelf:C"
    assert d["regions"][0]["rows"][0]["id"] == "shelf:C"
    assert d["regions"][0]["rows"][0]["selected"] is True
    assert d["regions"][0]["rows"][0]["fields"] == []  # default empty list, not missing
    assert d["meta"] == {"app_label": "xbook"}


def test_field_defaults_to_text_role():
    assert Field(label="amount", value="£10").role == "text"


def test_to_dict_carries_schema_version():
    d = ScreenModel(kind="note", title="t").to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    # The full top-level shape is pinned so an accidental breaking change to the wire
    # contract fails here and forces a deliberate SCHEMA_VERSION bump + doc update.
    assert set(d) == {
        "kind",
        "title",
        "regions",
        "selection",
        "actions",
        "meta",
        "schema_version",
    }
