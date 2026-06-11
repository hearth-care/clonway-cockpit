# Release Policy

clonway-cockpit is the shared framework under the Clonway worker fleet. Releases are git tags
created from `pyproject.toml` versions, and workers pin those tags through their `uv` git source
configuration.

## Version Source

- `pyproject.toml` is the source of truth for `project.version`.
- `CHANGELOG.md` must contain a matching `## [x.y.z]` heading for the current version.
- `CHANGELOG.md` must keep an `## [Unreleased]` section. Every PR that changes `src/` adds a
  user-facing line there unless the change is strictly internal and has no worker-visible effect.
- A release PR moves the accumulated `Unreleased` notes into a dated version section and bumps
  `pyproject.toml` in the same commit.

## Contract Surface

Breaking-change severity is judged by the highest-precedence surface touched:

| Surface | Breaking change examples | Bump |
|---|---|---|
| Wire shapes: `Signal.to_wire()`, obs run-log JSONL, `ScreenModel.to_dict()` and `schema_version`, handoff payloads | Field removed, renamed, retyped, or given different semantics | Major after 1.0; minor with a loud changelog callout before 1.0 |
| Public Python API: documented modules including `shell`, `walk`, `registry`, `render`, `keys`, `signals.*`, `gateway.*`, and persona modules | Signature change, removal, or behaviour change a worker test would catch | Major after 1.0; minor with a loud changelog callout before 1.0 |
| Underscore-prefixed names, tests, and worker-template internals | Any implementation-only change | Patch |

## Pre-1.0 Rules

The project is currently pre-1.0.

- Minor releases may contain breaking changes, but the changelog must call them out explicitly.
- Patch releases must not intentionally break worker-visible behaviour.
- Wire-shape changes should update the relevant schema/version marker where one exists.
- Fleet skew is managed by docs/pin-sync.md; consumers update before emitters when a wire shape
  changes.

## Deprecations

When a public name is replaced, keep the old name available for at least one minor release and
emit `DeprecationWarning`. The warning should point to the replacement and the earliest version
where removal is planned.

## Release Flow

1. Edit `CHANGELOG.md` and `pyproject.toml` together in a PR.
2. Merge the PR to `main`.
3. The release workflow creates tag `v<project.version>` and a GitHub Release from that
   changelog section if the tag does not already exist.
4. Worker repos then update their `[tool.uv.sources]` pin to the supported tag.
