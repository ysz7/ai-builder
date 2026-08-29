"""Stage 2: turning chunks into vectors, and the store they go into.

The embedding model is deterministic and local on purpose (see `corpus.py`). Swapping it
for a real one is a one-line change in this body, which is exactly the kind of change the
editable zone exists for.
"""

from typing import Annotated

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.vectorstores import InMemoryVectorStore

from bp import Param, editable, node


@node(id="rag.embedding", kind="rag.embedding", title="Embedding")
class Embedder:
    """Embeds chunks and holds the index they go into."""

    dimensions: Annotated[int, Param(min=16, max=1536, step=16, label="Vector size")] = 64

    @editable(signature_locked=True)
    def index(self, chunks: list[str]) -> InMemoryVectorStore:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        store = InMemoryVectorStore(DeterministicFakeEmbedding(size=self.dimensions))
        store.add_texts(chunks)
        return store
