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

echo "==> mypy (the other examples)"
# One at a time, for the same reason their suites are: three projects each declaring a `rag/`
# cannot be checked in one pass, because there is one module named `rag`.
for example in examples/rag examples/agent; do
    uv run mypy --strict "$example"
done

echo "==> pytest"
uv run pytest -q

echo "==> pytest (the other examples)"
# Their own suites, each in its own process. See the note in pyproject.toml: the convention
# names the directories, so every example has a `rag/` or an `agent/`, and one interpreter
# can hold one of each.
for example in examples/rag examples/agent; do
    uv run pytest -q "$example/tests"
done

echo "==> all checks passed"
