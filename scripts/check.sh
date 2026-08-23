#!/bin/sh
# The full check suite: lint, types, tests, and the I-2 strip proof.
#
# This is the gate a phase must pass before it counts as done (roadmap P0). CI runs
# exactly this script, so a green run here means a green run there.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> ruff (lint)"
uv run ruff check .

echo "==> ruff (format)"
uv run ruff format --check .

echo "==> mypy"
uv run mypy

echo "==> pytest"
uv run pytest -q

echo "==> all checks passed"
