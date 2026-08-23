"""The health route: answers without touching the queue.

Its independence is the point. With the broker down this node keeps its evidence -- a test
that passed proves the node did its job, whatever else was absent.
"""

from bp import editable, node


@node(id="health", kind="fastapi.route", title="Health")
@editable(signature_locked=True)
def health() -> dict[str, str]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return {"status": "ok"}
