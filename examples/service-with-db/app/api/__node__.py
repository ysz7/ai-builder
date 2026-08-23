"""The service node.

Its members are the routes, the settings, and the two nodes that own the service
connections: the database and the vector store. The container behind them is a node of its
own, carried by the compose file -- it is not a member of the application.
"""

from app.api.health import health
from app.api.notes import notes_router
from app.db import Database
from app.settings import ApiSettings
from app.vectors import VectorStore
from bp import group_node

service = group_node(
    id="api",
    kind="fastapi.service",
    title="Notes Service",
    members=[health, notes_router, ApiSettings, Database, VectorStore],
)
