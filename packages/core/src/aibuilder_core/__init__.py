"""aibuilder-core -- the Python core.

Everything with judgement in it lives here: the parser, the gates, the snapshot,
the libcst writer, the repair logic. The Tauri shell around it is transport only.

Right now the core answers exactly one method, `ping`, which is what this phase
set out to prove. See docs/roadmap.md for what lands next.
"""

__version__ = "0.1.0"
