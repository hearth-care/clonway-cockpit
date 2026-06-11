"""Shared config loading for Clonway workers.

Secrets convention: config values store the *name* of an environment variable,
never the secret value itself. Use ``SecretEnvName`` on model fields that follow
that convention; ``load_config`` warns when the referenced env var is unset.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, TypeVar, get_args, get_origin

import yaml
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class ConfigError(Exception):
    """Aggregated config problems found in one pass."""

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


class _SecretEnvName:
    pass


_SECRET_ENV_NAME = _SecretEnvName()
SecretEnvName = Annotated[str, _SECRET_ENV_NAME]


def load_config(
    model: type[ModelT],
    *,
    worker_id: str,
    paths: Sequence[Path] | None = None,
    env_prefix: str | None = None,
    require_file: bool = False,
) -> ModelT:
    prefix = env_prefix or worker_id.upper()
    candidate_paths = _candidate_paths(worker_id, prefix, paths)
    data, file_path, problems = _load_file(candidate_paths, require_file=require_file)
    provenance: dict[tuple[str, ...], str] = {}
    if file_path is not None:
        _record_file_provenance(data, file_path, provenance)

    for var, value in sorted(os.environ.items()):
        env_key = f"{prefix}__"
        if not var.startswith(env_key):
            continue
        parts = tuple(part.lower() for part in var[len(env_key) :].split("__") if part)
        if not parts:
            continue
        _set_nested(data, parts, value)
        provenance[parts] = f"env {var}"

    if problems:
        raise ConfigError(problems)

    try:
        cfg = model.model_validate(data, strict=False)
    except ValidationError as exc:
        validation_problems = [
            _format_validation_error(error, provenance, file_path) for error in exc.errors()
        ]
        validation_problems.extend(_secret_env_problems(model, data, provenance))
        raise ConfigError(validation_problems) from None

    secret_warnings = _secret_env_problems(model, cfg.model_dump(), provenance)
    for problem in secret_warnings:
        field, env_name = _secret_problem_parts(problem)
        warnings.warn(
            f"{field} references unset secret env var {env_name}",
            UserWarning,
            stacklevel=2,
        )
    return cfg


def _candidate_paths(
    worker_id: str, env_prefix: str, paths: Sequence[Path] | None
) -> list[Path]:
    if paths is not None:
        return [Path(path) for path in paths]
    env_path = os.environ.get(f"{env_prefix}_CONFIG")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path(f"./{worker_id}.yaml"),
            Path.home() / ".config" / "clonway" / f"{worker_id}.yaml",
        ]
    )
    return candidates


def _load_file(paths: Sequence[Path], *, require_file: bool) -> tuple[dict[str, Any], Path | None, list[str]]:
    problems: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return {}, path, [f"file {path}: {exc}"]
        if loaded is None:
            return {}, path, []
        if not isinstance(loaded, Mapping):
            return {}, path, [f"file {path}: config must be a mapping"]
        return dict(loaded), path, []
    if require_file:
        if len(paths) == 1:
            problems.append(f"file {paths[0]}: not found")
        else:
            problems.append("file: no config file found")
    return {}, None, problems


def _record_file_provenance(
    value: Mapping[str, Any], file_path: Path, provenance: dict[tuple[str, ...], str]
) -> None:
    def walk(current: Any, path: tuple[str, ...]) -> None:
        if isinstance(current, Mapping):
            for key, child in current.items():
                walk(child, (*path, str(key)))
            return
        provenance[path] = f"file {file_path}"

    walk(value, ())


def _set_nested(data: dict[str, Any], parts: tuple[str, ...], value: str) -> None:
    current = data
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _format_validation_error(
    error: dict[str, Any], provenance: Mapping[tuple[str, ...], str], file_path: Path | None
) -> str:
    loc = tuple(str(part) for part in error["loc"])
    source = _source_for(loc, provenance, file_path)
    return f"{source}: {'.'.join(loc)}: {error['msg']}"


def _source_for(
    loc: tuple[str, ...], provenance: Mapping[tuple[str, ...], str], file_path: Path | None
) -> str:
    for end in range(len(loc), 0, -1):
        source = provenance.get(loc[:end])
        if source:
            return source
    if file_path is not None:
        return f"file {file_path}"
    return "field"


def _secret_env_problems(
    model: type[BaseModel], data: Mapping[str, Any], provenance: Mapping[tuple[str, ...], str]
) -> list[str]:
    problems: list[str] = []
    for loc in _secret_field_locs(model):
        value = _get_nested(data, loc)
        if isinstance(value, str) and value and os.environ.get(value) is None:
            field = ".".join(loc)
            source = provenance.get(loc, f"field {field}")
            problems.append(f"env {value}: {field} references an unset secret env var")
            if source.startswith("env "):
                problems[-1] = f"env {value}: {field} references an unset secret env var"
    return problems


def _secret_field_locs(model: type[BaseModel], prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    locs: list[tuple[str, ...]] = []
    for name, field in model.model_fields.items():
        loc = (*prefix, name)
        annotation = field.annotation
        if _is_secret_annotation(annotation) or _has_secret_metadata(field.metadata):
            locs.append(loc)
            continue
        nested = _base_model_type(annotation)
        if nested is not None:
            locs.extend(_secret_field_locs(nested, loc))
    return locs


def _is_secret_annotation(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _has_secret_metadata(get_args(annotation)[1:])
    return any(_is_secret_annotation(arg) for arg in get_args(annotation))


def _has_secret_metadata(metadata: Sequence[Any]) -> bool:
    return any(isinstance(item, _SecretEnvName) for item in metadata)


def _base_model_type(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation):
        nested = _base_model_type(arg)
        if nested is not None:
            return nested
    return None


def _get_nested(data: Mapping[str, Any], loc: tuple[str, ...]) -> Any:
    current: Any = data
    for part in loc:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _secret_problem_parts(problem: str) -> tuple[str, str]:
    env_name = problem.removeprefix("env ").split(":", maxsplit=1)[0]
    field = problem.split(": ", maxsplit=1)[1].split(" references", maxsplit=1)[0]
    return field, env_name
