"""Stage 1: splitting documents into the units that get embedded.

A stage is a carrier with its own knobs -- which is the reason the group construct exists
(architecture §5.3). The user expands the pipeline node, sees this stage under it, and
tunes the chunk size from here rather than from a settings file three directories away.
"""

from typing import Annotated

from bp import Param, editable, node


@node(id="rag.chunking", kind="rag.chunking", title="Chunking")
class Chunker:
    """Fixed-size chunks with an overlap. The two knobs every RAG pipeline has."""

    chunk_size: Annotated[int, Param(min=50, max=2000, step=50, label="Chunk size")] = 120
    chunk_overlap: Annotated[int, Param(min=0, max=200, step=10, label="Overlap")] = 20

    @editable(signature_locked=True)
    def split(self, document: str) -> list[str]:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        step = max(self.chunk_size - self.chunk_overlap, 1)
        return [
            document[start : start + self.chunk_size]
            for start in range(0, max(len(document), 1), step)
        ]
