# PyInstaller spec for the sidecar binary.
#
# Driven by scripts/build-sidecar.sh, which copies the result to
# src-tauri/binaries/aibuilder-core-<target-triple>.
#
# One file, no console window of its own: the process is spawned by Tauri and
# speaks NDJSON over its stdio.

from pathlib import Path

ROOT = Path(SPECPATH).parent  # packages/core

a = Analysis(
    [str(ROOT / "src" / "aibuilder_core" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    # The system prompt is data the core reads at runtime, not documentation, so it
    # travels with the binary -- under the package directory, which is where
    # `agent.prompt_path` looks from source as well. One file, one lookup.
    datas=[
        (
            str(ROOT / "src" / "aibuilder_core" / "prompts" / "system-prompt-claude-code.md"),
            "aibuilder_core/prompts",
        )
    ],
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
    name="aibuilder-core",
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
