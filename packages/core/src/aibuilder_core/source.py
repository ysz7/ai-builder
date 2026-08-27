"""The text behind a location.

The IR addresses code and deliberately does not carry it: `ir.Function` keeps a digest for a
generated body and **nothing at all** for an editable one, because a body kept in the graph is
a second copy of the code, and I-1 says there is only one. That is right for the graph and
leaves one question unanswered -- "show me this node's code" -- which is what this module is
for, and the only thing it is for.

It reads, it never writes, and it holds no opinion about what it read: a span of lines out of
a file the parser already located. Editing what comes back goes through `writer.set_body`,
addressed by node and function (I-6), never by handing this text back as a patch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .ir import Graph, Location, Node
from .project import read_project


@dataclass(frozen=True)
class FunctionSource:
    """One function of a node's carrier, with the text a person would edit."""

    path: str
    zone: str | None
    signature: str
    signature_locked: bool
    location: Location
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "zone": self.zone,
            "signature": self.signature,
            "signature_locked": self.signature_locked,
            "location": asdict(self.location),
            "source": self.source,
        }


@dataclass(frozen=True)
class NodeSource:
    """A node's carrier as text, and each function inside it."""

    node: str
    file: str
    source: str
    functions: tuple[FunctionSource, ...]
    refused: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "node": self.node,
            "file": self.file,
            "source": self.source,
            "functions": [item.as_dict() for item in self.functions],
            "refused": self.refused,
        }


def _refused(node_id: str, reason: str) -> NodeSource:
    return NodeSource(node=node_id, file="", source="", functions=(), refused=reason)


def _span(root: Path, location: Location) -> str:
    """The lines a location covers, as they are on disk.

    On disk rather than from a cache: the file is the source of truth, and a panel showing
    something else would be showing a state the person cannot edit.
    """
    path = root / location.file
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return ""
    start = max(location.start_line - 1, 0)
    return "".join(lines[start : location.end_line])


def _owned_by(function_path: str, carrier: str) -> bool:
    return function_path == carrier or function_path.startswith(f"{carrier}.")


def _closest(graph: Graph, function_path: str) -> Node | None:
    """Which node's panel this function belongs on.

    A module carrier owns everything defined inside it, including functions that are nodes of
    their own -- so ownership alone would put a route's body in its module's panel as well as
    its own. The most specific carrier wins, which is the one whose panel can actually say
    anything about it.
    """
    owners = [node for node in graph.nodes if _owned_by(function_path, node.carrier)]
    if not owners:
        return None
    return max(owners, key=lambda node: len(node.carrier))


def node_source(project: Path | str, node_id: str) -> NodeSource:
    """The code a node carries: the carrier's text, and each function inside it.

    A refusal is an ordinary answer, as it is for every write: a node that is not on the graph
    is a question with no answer, not a fault in the call.
    """
    root = Path(project).resolve()
    # **The whole graph, not only the Python one.** This asked `parse_project`, which knows
    # no file formats by design (§5.7) -- so a node carried by a file was not on the graph it
    # searched, and every `Dockerfile` and `compose.yaml` answered "no node on this graph"
    # while sitting on the canvas being clicked. The composition belongs here for the same
    # reason it belongs everywhere else: "the graph" has to mean one thing.
    graph = read_project(root)

    node = next((candidate for candidate in graph.nodes if candidate.id == node_id), None)
    if node is None:
        return _refused(node_id, f"no node {node_id!r} on this graph")

    # A file-carried node has no functions and cannot have any: `graph.functions` comes from
    # the parser, and the parser never opened this file. What it has is its text, which is
    # the whole of what a panel can offer -- there are no zones to edit through, because the
    # file *is* the source of truth and nothing here generated any part of it (Q10).
    functions = tuple(
        FunctionSource(
            path=function.path,
            zone=function.zone,
            signature=function.signature.render(),
            signature_locked=function.signature_locked,
            location=function.location,
            source=_span(root, function.location),
        )
        for function in graph.functions
        if _owned_by(function.path, node.carrier) and _closest(graph, function.path) is node
    )
    return NodeSource(
        node=node.id,
        file=node.location.file,
        source=_span(root, node.location),
        functions=functions,
    )
