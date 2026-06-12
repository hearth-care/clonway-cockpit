"""Permanent facade for the clonway-cockpit render API.

The implementation is split across render_chrome, render_panels, and render_models,
but worker imports from clonway_cockpit.render remain the stable public surface.
"""

# ruff: noqa: F401,F403
from __future__ import annotations

import io
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from rich import box
from rich.align import Align
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from clonway_cockpit.model import Field as MField
from clonway_cockpit.model import Region as MRegion
from clonway_cockpit.model import Row as MRow
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import BlastRadius, CapabilitySpec
from clonway_cockpit.render_chrome import *
from clonway_cockpit.render_chrome import (
    _APPLY_KEY_STYLE,
    _CRUMB_SEP,
    _CURSOR,
    _DIM_INFO,
    _DOT,
    _KEY_STYLE,
    _NOT_STYLE,
    _NOT_TOKENS,
    _PANEL_MAX_WIDTH,
    _PANEL_WIDTH,
    _PILL_GLYPH,
    ACCENT,
    BLUE,
    DIM,
    SHELVES,
    _apply_key,
    _breadcrumb_line,
    _highlight_not,
    _legend,
    _letters_cue,
    _marker_cell,
    _Page,
    _pill_text,
    chip,
    page,
    render_cockpit_screen,
    render_header,
    render_needs_you,
    render_pulse,
    render_toolkit,
    screen_header,
)
from clonway_cockpit.render_models import *
from clonway_cockpit.render_models import (
    _home_actions,
    _selection_id,
    model_capability_card,
    model_cockpit_screen,
    model_doctor,
    model_doctor_confirm,
    model_filter,
    model_help,
    model_ledger,
    model_menu,
    model_note,
    model_preflight,
    model_remedy_confirm,
    model_staged_progress,
    model_sync_progress,
    model_unstructured,
    model_walk_progress,
    model_walk_result,
)
from clonway_cockpit.render_panels import *
from clonway_cockpit.render_panels import (
    _COMPLETION_WALKS,
    _DEFAULT_HELP_LINES,
    _MAX_NEVER_USED,
    _NOTCH_GLYPHS,
    _STAGE_GLYPH,
    _STAGE_STYLE,
    SPINNER_FRAMES,
    _doctor_back_only_footer,
    _doctor_footer,
    _FilterRow,
    _opens,
    _relative_last,
    render_capability_card,
    render_doctor,
    render_doctor_confirm,
    render_filter,
    render_help,
    render_ledger,
    render_menu,
    render_note,
    render_preflight,
    render_remedy_confirm,
    render_staged_progress,
    render_sync_progress,
    render_usage_section,
    render_walk_progress,
    render_walk_result,
    usage_notch,
)
from clonway_cockpit.state import CockpitState, NeedsItem, Pill

__all__ = [name for name in globals() if not name.startswith("__")]
