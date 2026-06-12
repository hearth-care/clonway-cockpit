"""clonway_cockpit.obs — shared run/stage telemetry emitter package.

Re-exports the full public surface of ``_telemetry`` so all existing imports
continue working after the module→package conversion:

    from clonway_cockpit.obs import make_obs, flush_buffer, resolve_run_id
    from clonway_cockpit import obs; obs.make_obs(...)
    import clonway_cockpit.obs as obs_mod; obs_mod.flush_buffer(...)

Sub-modules available after explicit import:
    clonway_cockpit.obs.runlog   — per-worker JSONL run log
    clonway_cockpit.obs.logsetup — root-logger setup for entrypoints/servers
"""

from __future__ import annotations

from clonway_cockpit.obs._telemetry import (
    FORCE_FLUSH_ENV,
    RESERVED_LOGRECORD_KEYS,
    SEVERITY_TO_LEVEL,
    CloudLoggingSink,
    LoggerFactory,
    StorageClientFactory,
    flush_buffer,
    make_obs,
    resolve_run_id,
)

__all__ = [
    "FORCE_FLUSH_ENV",
    "RESERVED_LOGRECORD_KEYS",
    "SEVERITY_TO_LEVEL",
    "CloudLoggingSink",
    "LoggerFactory",
    "StorageClientFactory",
    "flush_buffer",
    "make_obs",
    "resolve_run_id",
]
