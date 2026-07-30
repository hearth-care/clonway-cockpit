"""Semantic screen model — the agent-facing contract for "what is on this screen".

A ScreenModel is a structured, JSON-serialisable description of one cockpit screen,
built in the framework from the same inputs the ``render_*`` functions consume. The
human cockpit renders Rich renderables exactly as before; an agent reads the
ScreenModel (via ``Host.on_screen`` / the ``CockpitDriver``) and asserts against its
structure instead of scraping rendered ANSI text.

``Row.id`` values are a SEMI-PUBLIC CONTRACT — agents assert on them; keep them
stable. The ids minted in M1:
  ``pill:<i>``  ``need:<i>``  ``shelf:<LETTER>``  ``option:<ordinal>``  ``back``
  ``change:<i>``  ``precond:<i>``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Wire-protocol version, stamped onto every ScreenModel.to_dict() frame so a driver /
# orchestrator can branch on it. Bumps ONLY on a breaking change (a removed/renamed key or a
# changed type); additive keys (a new optional meta field) do not bump it. The shape-pin test
# in tests/test_model.py fails on an accidental breaking change, forcing a deliberate bump.
SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Field:
    """One labelled datum within a row (e.g. a pill's status, a bill's amount)."""

    label: str
    value: str
    role: str = "text"  # text | number | currency | status | date | …


@dataclass(frozen=True)
class Row:
    """One navigable/selectable line. ``id`` is the stable semantic key agents key on."""

    id: str
    label: str
    fields: list[Field] = field(default_factory=list)
    selected: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class Region:
    """A titled group of rows (or a prose block via ``text``)."""

    role: str
    title: str = ""
    rows: list[Row] = field(default_factory=list)
    text: str | None = None


@dataclass(frozen=True)
class ScreenModel:
    """A structured description of one cockpit screen."""

    kind: str
    title: str = ""
    regions: list[Region] = field(default_factory=list)
    selection: str | None = None  # id of the currently-selected Row, if any
    actions: list[str] = field(default_factory=list)  # keys/verbs the screen honours
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """A plain JSON-serialisable dict (nested dataclasses expanded), tagged with the
        wire-protocol version so a driver/orchestrator can branch on it. Additive: a
        consumer that ignores unknown keys is unaffected."""
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return d
