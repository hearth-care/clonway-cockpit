# tests/test_obs_package.py
"""CC-OBS-PKG-* — import-path compatibility after obs.py → obs/ package conversion.

Pins the re-export list so that any future removal of a public symbol from
``__init__`` is a CI failure, not a silent breakage in a worker shim.
"""

from __future__ import annotations

_EXPECTED_EXPORTS = {
    "FORCE_FLUSH_ENV",
    "RESERVED_LOGRECORD_KEYS",
    "SEVERITY_TO_LEVEL",
    "CloudLoggingSink",
    "EventBufferScope",
    "LoggerFactory",
    "StorageClientFactory",
    "atomic_append",
    "atomic_write_bytes",
    "event_buffer",
    "flush_buffer",
    "make_obs",
    "isolated_event_buffers",
    "resolve_run_id",
}


def test_package_import_paths():  # CC-OBS-PKG-1
    from clonway_cockpit import obs

    obs.make_obs(worker_id="xtest")


def test_dotted_import_path():  # CC-OBS-PKG-2
    from clonway_cockpit.obs import flush_buffer, make_obs, resolve_run_id

    assert callable(make_obs)
    assert callable(flush_buffer)
    assert callable(resolve_run_id)


def test_constants_accessible():  # CC-OBS-PKG-3
    from clonway_cockpit.obs import RESERVED_LOGRECORD_KEYS, SEVERITY_TO_LEVEL

    assert isinstance(SEVERITY_TO_LEVEL, dict)
    assert isinstance(RESERVED_LOGRECORD_KEYS, frozenset)


def test_re_export_list_pinned():  # CC-OBS-PKG-4
    import clonway_cockpit.obs as obs

    assert not hasattr(obs, "_RUN_BUFFERS")
    missing = _EXPECTED_EXPORTS - set(obs.__all__)
    assert not missing, f"Missing from __all__: {missing}"
    extra = set(obs.__all__) - _EXPECTED_EXPORTS
    assert not extra, f"Unexpected additions to __all__: {extra}"


def test_telemetry_submodule_importable():  # CC-OBS-PKG-5
    import clonway_cockpit.obs._telemetry as _tel

    assert hasattr(_tel, "make_obs")
    assert hasattr(_tel, "_import_storage")


def test_atomicio_exports_callable():  # CC-OBS-PKG-6
    from clonway_cockpit.obs import atomic_append, atomic_write_bytes

    assert callable(atomic_append)
    assert callable(atomic_write_bytes)
