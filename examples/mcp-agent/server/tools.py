"""The tools this project offers to whoever connects to its server.

Each one is a node, because each one has a carrier we own: an editable body, a locked
signature, and a name the graph can address. That is the whole of the Q12 line -- a tool
written *here* is a node; a tool belonging to somebody else's server is contents of that
server's node, because there is nothing of ours for a node to hang on.

The carrier stays a **plain function** and the exposing is a generated zone, the same split
the routes and the tasks follow. A function wrapped in the SDK's decorator would no longer
be the function the graph named, and a run through it could not be seen.
"""

from bp import editable, generated, node
from server.app import mcp_server


@node(id="tools.summarize", kind="mcp.tool", title="Summarize")
@editable(signature_locked=True)
def summarize(text: str, sentences: int = 1) -> str:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    parts = [part.strip() for part in text.split(".") if part.strip()]
    return ". ".join(parts[:sentences]) + "." if parts else ""


@node(id="tools.word_count", kind="mcp.tool", title="Count words")
@editable(signature_locked=True)
def word_count(text: str) -> int:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return len(text.split())


@generated()
def expose_tools(server: object) -> None:
    # GENERATED. Tool registration; edited through the graph, not by hand.
    server.add_tool(summarize, name="summarize", description="Shorten text to its first sentences.")  # type: ignore[attr-defined]
    server.add_tool(word_count, name="word_count", description="Count the words in a text.")  # type: ignore[attr-defined]


expose_tools(mcp_server)
