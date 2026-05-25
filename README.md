# clonway-cockpit

The shared **interactive-cockpit framework spine** for the Clonway worker family,
extracted from xbook's cockpit (C1). It carries the framework, not any domain
logic: the walk machine and its single write gate (`confirm_apply`), the
capability registry (`CapabilitySpec` / `WizardContext` / `BlastRadius`), the
render primitives that define the cockpit's locked visual language
(header / pulse / needs-you / toolkit / walk / doctor / usage chrome), the raw
single-keypress reader, local usage telemetry, the shell-out mechanism, and the
forward-looking `Signal` model.

Workers (xbook, and future siblings) depend on this package and supply their own
capabilities, probes, and domain screens. The only runtime dependency is
[`rich`](https://github.com/Textualize/rich); the package never imports any
worker — it is the substrate they build on, not the other way round.

## Layout

```
src/clonway_cockpit/
  keys.py        prompts.py     registry.py    state.py
  doctor.py      render.py      walk.py        usage.py    shellout.py
  signals/model.py
```

## Develop

```sh
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
