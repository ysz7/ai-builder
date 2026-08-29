#!/bin/sh
# Dev-mode sidecar: run the Python core straight from source, no PyInstaller step.
#
# Tauri spawns whatever file sits at src-tauri/binaries/<name>-<target-triple>.
# In dev that file is a shim which execs this script, so the sidecar plumbing is
# exercised for real while the core stays editable and reloadable.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "[dev-sidecar] uv not found on PATH; install it or run scripts/build-sidecar.sh" >&2
    exit 127
fi

exec uv run --project "$ROOT" python -m framestack_core "$@"
