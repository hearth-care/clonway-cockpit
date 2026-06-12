.PHONY: test lint format typecheck docs check template-smoke

test:
	uv run pytest -q

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

typecheck:
	uv run mypy src

docs:
	uv run pdoc clonway_cockpit -o build/docs

# All the gates CI runs, in one shot.
check: lint format typecheck test

# Heavy, operator-run worker-template validation: generate a throwaway worker
# from worker-template/, install it against THIS checkout, and run its own
# pytest/ruff/mypy + CLI end-to-end. The fast, network-free version of these
# assertions runs in the unit suite (tests/test_worker_template.py).
#   make template-smoke                  # job shape, worker_id=xsmoke
#   make template-smoke ARGS="xcqc local"
template-smoke:
	bash scripts/template_smoke.sh $(ARGS)
