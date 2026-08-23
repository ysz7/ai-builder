"""The service node.

Members are object references, never strings: a moved file still resolves, a renamed
string would not. This module is generated zone in its entirety -- it declares the node,
it does not run anything.
"""

from app.api.health import health
from app.api.users import users_router
from app.settings import ApiSettings
from bp import group_node

service = group_node(
    id="api",
    kind="fastapi.service",
    title="API Service",
    # The subsystem's direct children only. The users routes are not listed here because
    # the router declares them itself -- every node has exactly one parent, and the
    # nearest container is the one that claims it.
    members=[health, users_router, ApiSettings],
)
