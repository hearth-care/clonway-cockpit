#!/usr/bin/env bash
# Full install-and-run smoke for the worker-template (S8/C6).
#
# Generates a throwaway worker from worker-template/ (reading the CURRENT working
# tree), installs it against THIS clonway-cockpit checkout (a local path source,
# so the smoke proves the template against the code under test, not a published
# rev), and runs the generated worker's own gates: pytest, ruff, mypy.
#
# The lightweight, network-free version of these assertions runs in CI via
# tests/test_worker_template.py (imports the generated package directly). This
# script is the heavier, operator-run validation that the generated worker also
# `uv sync`s + passes its own toolchain end-to-end.
#
# Usage:  ./scripts/template_smoke.sh [worker_id] [deploy_shape]
set -euo pipefail

WORKER_ID="${1:-xsmoke}"
DEPLOY_SHAPE="${2:-job}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
DST="${WORK_DIR}/${WORKER_ID}"

cleanup() { rm -rf "${WORK_DIR}"; }
trap cleanup EXIT

echo "==> Generating ${WORKER_ID} (${DEPLOY_SHAPE}) into ${DST}"
uv run copier copy --trust --vcs-ref=HEAD \
  --data "worker_id=${WORKER_ID}" \
  --data "worker_title=Auto-Smoke" \
  --data "package_name=${WORKER_ID}" \
  --data "deploy_shape=${DEPLOY_SHAPE}" \
  --data "clonway_rev=main" \
  --defaults \
  "${REPO_ROOT}" "${DST}"

cd "${DST}"

echo "==> Pinning clonway-cockpit to the local checkout under test"
uv add "clonway-cockpit @ file://${REPO_ROOT}" >/dev/null

echo "==> pytest"
uv run pytest -q

echo "==> ruff check"
uv run ruff check .

echo "==> ruff format --check"
uv run ruff format --check .

echo "==> mypy"
uv run mypy src

FLAG="$(echo "${WORKER_ID}" | tr '[:lower:]' '[:upper:]')_EMIT_SIGNALS"

echo "==> CLI: signals scan (flag off)"
uv run "${WORKER_ID}" signals scan

echo "==> CLI: signals scan (flag on)"
env "${FLAG}=1" uv run "${WORKER_ID}" signals scan

echo "==> template-smoke PASSED for ${WORKER_ID} (${DEPLOY_SHAPE})"
