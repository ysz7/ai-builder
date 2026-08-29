"""Pipeline assembly.

Generated zone: constructing the stages, running a document through them, answering a
question with what came back. The order of the stages is the pipeline, and it is edited
through the graph rather than here.
"""

from bp import generated
from rag.chunking import Chunker
from rag.corpus import DOCUMENTS
from rag.embedding import Embedder
from rag.generation import Generator
from rag.retrieval import Retriever


@generated()
def build_index() -> object:
    # GENERATED. Stage wiring; edited through the graph, not by hand.
    chunker = Chunker()
    chunks = [chunk for document in DOCUMENTS for chunk in chunker.split(document)]
    return Embedder().index(chunks)


@generated()
def answer(question: str) -> str:
    # GENERATED. Stage wiring; edited through the graph, not by hand.
    chunks = Retriever().find(build_index(), question)
    return Generator().answer(question, chunks)
