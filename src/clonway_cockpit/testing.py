"""Pytest helpers for worker suites that consume :mod:`clonway_cockpit`.

Worker conftests can opt into the framework registry guard with:

``pytest_plugins = ["clonway_cockpit.testing"]``
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from clonway_cockpit import registry


@pytest.fixture(autouse=True)
def capability_registry_guard() -> Iterator[None]:
    """Restore the capability registry after each test.

    Snapshot/restore keeps module-import-time registrations intact while preventing
    per-test registrations from leaking into later tests.
    """

    saved = dict(registry._CAPABILITIES)
    yield
    registry._CAPABILITIES.clear()
    registry._CAPABILITIES.update(saved)
