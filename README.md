# clonway-cockpit

The shared **interactive-cockpit framework spine** for the Clonway worker family,
extracted from xbook's cockpit (C1). It carries the framework, not any domain
logic: the walk machine and its single write gate (`confirm_apply`), the
capability registry (`CapabilitySpec` / `WizardContext` / `BlastRadius`), the
render primitives that define the cockpit's locked visual language
(header / pulse / needs-you / toolkit / walk / doctor / usage chrome), the raw
single-keypress reader, local usage telemetry, the shell-out mechanism, the
forward-looking `Signal` model, and the shared best-effort Signal emitter.

Workers (xbook, and future siblings) depend on this package and supply their own
capabilities, probes, and domain screens. The only runtime dependency is
[`rich`](https://github.com/Textualize/rich); the package never imports any
worker — it is the substrate they build on, not the other way round.

## Layout

```
src/clonway_cockpit/
  keys.py        prompts.py     registry.py    state.py
  doctor.py      render.py      walk.py        usage.py    shellout.py
  signals/model.py   signals/rank.py   signals/emit.py
```

Adding a new worker to the Fleet Signal layer? See
[docs/onboarding-a-worker.md](docs/onboarding-a-worker.md).

## Scaffold a new worker (the template)

`worker-template/` + `copier.yml` are a [copier](https://copier.readthedocs.io/)
template that generates a new fleet worker born with a working cockpit, a
flag-guarded Signal emit path, a **mandatory** `@scan_horizon` stub, telemetry,
CI, and the single write-gate + draft-never-send safety posture — out of the
box (S8/C6). The template lives in this repo (no repo proliferation); copier
copies fine from this local path or the Git URL.

```sh
copier copy gh:hearth-care/clonway-cockpit ../xadmit   # or a local checkout path
# answer worker_id / worker_title / package_name / deploy_shape, then:
cd ../xadmit && uv sync && uv run pytest -q
```

The generated worker runs, emits, and opens a cockpit immediately; its
`@scan_horizon` stub returns `()` behind a strict-`xfail` test until you fill in
real domain signals (proactive by construction). `make template-smoke` runs a
full generate-install-and-test of the template against this checkout; the fast,
network-free version of those assertions runs in CI
([tests/test_worker_template.py](tests/test_worker_template.py)).

## Develop

```sh
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
