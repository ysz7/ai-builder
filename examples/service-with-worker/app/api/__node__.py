"""The service node.

Its members are the routes and the settings. The queue is **not** a member: it is a
subsystem of its own, with its own group and its own process to run.
"""

from app.api.health import health
from app.api.reports import reports_router
from app.settings import ApiSettings
from bp import group_node

service = group_node(
    id="api",
    kind="fastapi.service",
    title="Reports Service",
    members=[health, reports_router, ApiSettings],
)
