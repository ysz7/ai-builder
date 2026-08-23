"""The vector index: what goes into it, and how it is searched.

The embedding is deterministic and local -- a hash spread over a small vector -- for the
same reason every other example avoids a model: this has to run in CI with no key. The
storage and the search are the real thing, in Postgres with pgvector.
"""

import hashlib
from typing import Annotated

from app.db import database
from bp import Param, editable, node


@node(id="vectors", kind="vector.store", title="Vector store")
class VectorStore:
    """Embedding and similarity search over the notes table."""

    dimensions: Annotated[int, Param(min=8, max=2048, step=8, label="Vector size")] = 16
    top_k: Annotated[int, Param(min=1, max=20, label="Neighbours returned")] = 3

    @editable(signature_locked=True)
    def embed(self, text: str) -> list[float]:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[index % len(digest)] / 255 for index in range(self.dimensions)]

    @editable(signature_locked=True)
    def add(self, body: str) -> int:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        with database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO notes (body, embedding) VALUES (%s, %s) RETURNING id",
                (body, str(self.embed(body))),
            )
            row = cursor.fetchone()
            connection.commit()
        return int(row[0]) if row else 0

    @editable(signature_locked=True)
    def search(self, query: str) -> list[str]:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        with database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT body FROM notes ORDER BY embedding <-> %s LIMIT %s",
                (str(self.embed(query)), self.top_k),
            )
            return [row[0] for row in cursor.fetchall()]


vectors = VectorStore()
