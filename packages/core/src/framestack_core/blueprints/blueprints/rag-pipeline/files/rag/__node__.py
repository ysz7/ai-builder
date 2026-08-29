"""The pipeline node.

Four equal carriers, one subsystem: the group is the only construct that gives the
pipeline a node without pretending one of its stages owns the others (§5.3). Expanding it
shows the four stages, each with the knobs that belong to it.
"""

from bp import group_node
from rag.chunking import Chunker
from rag.embedding import Embedder
from rag.generation import Generator
from rag.retrieval import Retriever

subsystem = group_node(
    id="rag",
    kind="rag.pipeline",
    title="RAG pipeline",
    members=[Chunker, Embedder, Retriever, Generator],
)
