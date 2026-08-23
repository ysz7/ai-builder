"""The service node."""

from bp import group_node

from app.routes import boom, healthy

service = group_node(
    id="service",
    kind="fastapi.service",
    title="Broken service",
    members=[healthy, boom],
)
