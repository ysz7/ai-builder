"""The agent's own tool.

A **local tool** is the opposite case from a remote one and stays a node: it has a carrier,
an editable body and a signature that is a contract. The carrier stays a plain function --
the langchain tool object is built for it in a generated zone below -- because a function
wrapped in a decorator is no longer the function the graph named, and a run through it
could not be seen.
"""

from langchain_core.tools import BaseTool, StructuredTool

from bp import editable, generated, node


@node(id="agent.shout", kind="langgraph.tool", title="Shout")
@editable(signature_locked=True)
def shout(text: str) -> str:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return text.upper()


@generated()
def build_tools() -> list[BaseTool]:
    # GENERATED. Tool binding; edited through the graph, not by hand.
    return [
        StructuredTool.from_function(
            shout, name="shout", description="Return the text in capitals."
        )
    ]
