"""The service node."""

from app.api.counter import counter
from app.api.health import health
from app.settings import ApiSettings
from bp import group_node

service = group_node(
    id="api",
    kind="fastapi.service",
    title="Cached Service",
    members=[health, counter, ApiSettings],
)
