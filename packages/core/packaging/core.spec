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
    # The agent's entire contract: the shared base and one file per command, loaded at
    # dispatch (`chat.py`). They are carried rather than compiled in so they stay readable
    # and reviewable -- and they must be *here*, because a prompt that exists only in the
    # repository is one the shipped application does not have, and it would fail as an agent
    # given no instructions rather than as a missing file.
    datas=[(str(ROOT / "prompts"), "prompts")],
    # libcst pulls its grammar and native parser in dynamically; coverage's data layer is
    # imported inside a function; ruamel picks its parser plugins by name at load time. None
    # of the three is found by following imports from `__main__`.
    hiddenimports=[
        "libcst",
        "libcst.native",
        "coverage",
        "coverage.sqldata",
        "ruamel.yaml",
    ],
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
