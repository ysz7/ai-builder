# PyInstaller spec for the sidecar binary.
#
# Driven by scripts/build-sidecar.sh, which copies the result to
# src-tauri/binaries/framestack-core-<target-triple>.
#
# One file, no console window of its own: the process is spawned by Tauri and
# speaks NDJSON over its stdio.

from pathlib import Path

ROOT = Path(SPECPATH).parent  # packages/core

a = Analysis(
    [str(ROOT / "src" / "framestack_core" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    # Nothing to carry yet. The system prompt, the probe and the bundled blueprint catalog
    # were all data this binary read at runtime, and the rebuild deleted the mechanisms they
    # belonged to. The prompts come back in Phase 4 and go here when they do -- a datas entry
    # for a file that is not there is a build that fails on somebody else's machine.
    datas=[],
    # libcst pulls its grammar and native parser in dynamically; without this the
    # frozen binary imports cleanly and then fails at first parse.
    hiddenimports=["libcst", "libcst.native"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc_data"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="framestack-core",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    # Ad-hoc signed so macOS lets the sidecar run locally. Distribution requires
    # the real identity -- see the signing section in the root README.
    codesign_identity=None,
    entitlements_file=None,
)
