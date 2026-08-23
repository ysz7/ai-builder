"""One project, read once: the Python the parser sees, and the artifacts it does not.

Two readers with nothing in common produce parts of the same graph -- `parser.py`, which
reads Python source and knows no library and no file format, and `artifacts.py`, which
knows paths and opens no Python. **Composition happens here and nowhere else**, so that "the
graph" means the same thing to the gate, the snapshot, the writer and the UI, and so that
neither reader has to learn what the other does (architecture §5.7).

`parse_project` keeps meaning exactly what it always meant -- Python source into IR -- and
everything that wants the whole project asks for it here.
"""

from __future__ import annotations

from pathlib import Path

from aibuilder_core.artifacts import read_artifacts
from aibuilder_core.ir import Graph
from aibuilder_core.parser import parse_project

__all__ = ["read_project"]


def read_project(project: Path | str) -> Graph:
    """The whole graph: nodes declared in Python, plus nodes carried by a file.

    Artifact nodes come last and never displace a declared one. An id collision means a
    project declared `@node(id="Dockerfile")`, which is a mistake worth a diagnostic rather
    than a silent overwrite -- so the declared node stays and the artifact is dropped, and
    the gate sees a top-level file with no node instead of a graph that quietly lost one.
    """
    root = Path(project)
    graph = parse_project(root)
    declared = {node.id for node in graph.nodes}

    artifacts = tuple(node for node in read_artifacts(root) if node.id not in declared)
    if not artifacts:
        return graph

    return Graph(
        root=graph.root,
        nodes=graph.nodes + artifacts,
        functions=graph.functions,
        edges=graph.edges,
        unparsed=graph.unparsed,
    )
