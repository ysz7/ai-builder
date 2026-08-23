"""The database connection, and the node it is tuned from.

The module that owns the connection is what goes on the graph -- not the container it talks
to, which is the docker node beside it. Its observable check is the only one that means
anything here: the connection opens.
"""

from typing import Annotated

import psycopg

from app.settings import settings
from bp import Param, editable, generated, node

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    body TEXT NOT NULL,
    embedding vector(16)
);
"""


@node(id="db", kind="db.session", title="Database")
class Database:
    """One connection per call, opened against the knobs below."""

    connect_timeout_s: Annotated[int, Param(min=1, max=30, label="Connect timeout (s)")] = 3
    statement_timeout_ms: Annotated[int, Param(min=100, max=60000, step=100)] = 5000

    @editable(signature_locked=True)
    def connect(self) -> psycopg.Connection:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        connection = psycopg.connect(settings.dsn, connect_timeout=self.connect_timeout_s)
        with connection.cursor() as cursor:
            cursor.execute(f"SET statement_timeout = {self.statement_timeout_ms}")
        return connection

    @generated()
    def migrate(self) -> None:
        # GENERATED. Schema bootstrap; edited through the graph, not by hand.
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(SCHEMA)
            connection.commit()


database = Database()
