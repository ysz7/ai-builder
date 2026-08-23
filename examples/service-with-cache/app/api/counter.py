"""The counter route: cannot answer without the cache.

When the service the compose file declares is not running, the test that exercises this
route fails -- and that failure says nothing about this code. The node goes unproven with
the environment named, never red.
"""

from app.cache import command
from bp import editable, node


@node(id="counter", kind="fastapi.route", title="Visit counter")
@editable(signature_locked=True)
def counter() -> dict[str, int]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return {"visits": int(command("INCR", "visits"))}
