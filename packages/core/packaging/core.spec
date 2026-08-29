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
    # The system prompt is data the core reads at runtime, not documentation, so it
    # travels with the binary -- under the package directory, which is where
    # `agent.prompt_path` looks from source as well. One file, one lookup.
    datas=[
        (
            str(ROOT / "src" / "framestack_core" / "prompts" / "system-prompt-claude-code.md"),
            "framestack_core/prompts",
        ),
        # The probe is handed to the *project's* interpreter as a plain file (P11), so it
        # has to exist on disk -- a module frozen into the archive cannot be run by anyone
        # but this binary.
        (str(ROOT / "src" / "framestack_core" / "probe.py"), "framestack_core"),
        # The bundled blueprint catalog (P20). It is package data for the reason the system
        # prompt is: the core reads it at runtime and a frozen sidecar has no repository
        # around it to look in. It is also the whole of Q28's first source -- the catalog
        # shipped *with the application*, whose trust decision was made at install -- so a
        # build that dropped it would leave only the named one, which most people have not
        # got.
        (
            str(ROOT / "src" / "framestack_core" / "blueprints"),
            "framestack_core/blueprints",
        ),
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
