"""The health route: answers without touching the database."""

from bp import editable, node


@node(id="health", kind="fastapi.route", title="Health")
@editable(signature_locked=True)
def health() -> dict[str, str]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return {"status": "ok"}
