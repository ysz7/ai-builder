#!/bin/sh
# Freeze the Python core into a single-file binary and install it where Tauri
# expects the sidecar: src-tauri/binaries/framestack-core-<target-triple>.
#
# Only needed for `npm run build`. Dev mode uses the shim at that same path.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BINARIES="$ROOT/apps/desktop/src-tauri/binaries"

# Tauri resolves the sidecar by the Rust host triple, so ask rustc when it exists
# and fall back to uname only when it does not.
if command -v rustc >/dev/null 2>&1; then
    TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
else
    case "$(uname -sm)" in
        "Darwin arm64")  TRIPLE="aarch64-apple-darwin" ;;
        "Darwin x86_64") TRIPLE="x86_64-apple-darwin" ;;
        *) echo "[build-sidecar] install rustup so the host triple can be resolved" >&2; exit 1 ;;
    esac
fi

echo "[build-sidecar] target triple: $TRIPLE"

uv run --project "$ROOT" --extra package pyinstaller \
    --clean --noconfirm \
    --distpath "$ROOT/packages/core/dist" \
    --workpath "$ROOT/packages/core/build" \
    "$ROOT/packages/core/packaging/core.spec"

mkdir -p "$BINARIES"
cp "$ROOT/packages/core/dist/framestack-core" "$BINARIES/framestack-core-$TRIPLE"
chmod +x "$BINARIES/framestack-core-$TRIPLE"

echo "[build-sidecar] installed $BINARIES/framestack-core-$TRIPLE"
echo "[build-sidecar] note: this overwrote the dev shim; 'git checkout -- $BINARIES' restores it"
