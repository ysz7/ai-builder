"""framestack-core -- the Python core.

Everything with judgement in it lives here; the Tauri shell around it is transport only.

The rebuild emptied this package down to what the following phases build on: the wire
(`protocol`), the method table (`handlers`, `api`), the chat session, the terminal and the
layout a person arranges. The parser, the gate, the observer and the writer are rebuilt on
the convention -- a directory that exports what its kind requires -- rather than on markup.
"""

__version__ = "0.1.0"
