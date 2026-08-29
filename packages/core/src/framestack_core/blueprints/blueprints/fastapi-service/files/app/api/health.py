"""The health route.

A bare route function: the node's carrier is the function itself, and its body is the
editable zone. The signature is the contract the graph draws an edge from, so it is
locked -- the user may change what the check reports, not what it returns.
"""

from bp import editable, node


@node(id="health", kind="fastapi.route", title="Health")
@editable(signature_locked=True)
def health() -> dict[str, str]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return {"status": "ok"}
