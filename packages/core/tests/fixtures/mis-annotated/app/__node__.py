"""The service group. Claims one member that does not exist."""

from bp import group_node

from app.routes import first, invented, router, second, shared
from app.settings import Settings

service = group_node(
    id="api",
    kind="fastapi.service",
    title="Broken service",
    # DEFECT: `ghost` resolves to nothing. DEFECT: `shared` is also claimed by `router`.
    members=[first, second, shared, router, invented, Settings, ghost],  # noqa: F821
)
