"""The pipeline's own tests, and therefore the run the graph observes.

Ordinary tests for a RAG pipeline: each stage on its own, then the assembled answer. No
stage can be proven by a call the toolchain invents -- chunking needs a document,
retrieval needs a question -- so this file is where the evidence for those nodes comes
from, and there is nowhere else it could honestly come from.
"""

from rag.chunking import Chunker
from rag.corpus import DOCUMENTS
from rag.embedding import Embedder
from rag.generation import STAND_IN_ANSWER, Generator
from rag.pipeline import answer, build_index
from rag.retrieval import Retriever


def test_chunking_splits_a_document_into_overlapping_pieces() -> None:
    chunker = Chunker()

    chunks = chunker.split(DOCUMENTS[0])

    assert len(chunks) > 1
    assert all(len(chunk) <= chunker.chunk_size for chunk in chunks)


def test_chunking_a_short_document_yields_one_chunk() -> None:
    assert Chunker().split("short") == ["short"]


def test_embedding_indexes_every_chunk() -> None:
    store = Embedder().index(["first chunk", "second chunk"])

    assert len(store.similarity_search("chunk", k=5)) == 2


def test_retrieval_returns_at_most_top_k() -> None:
    retriever = Retriever()
    store = Embedder().index([f"chunk number {index}" for index in range(10)])

    found = retriever.find(store, "chunk number 3")

    assert len(found) == retriever.top_k


def test_the_prompt_carries_the_retrieved_context() -> None:
    prompt = Generator().build_prompt("what is a node?", ["a node has a carrier"])

    assert "a node has a carrier" in prompt
    assert "what is a node?" in prompt


def test_the_prompt_honours_the_chunk_budget() -> None:
    generator = Generator()

    prompt = generator.build_prompt("q", [f"chunk {index}" for index in range(10)])

    assert "chunk 0" in prompt
    assert f"chunk {generator.max_context_chunks}" not in prompt


def test_generation_answers_through_the_model_it_was_given() -> None:
    assert Generator().answer("what is a node?", ["a node has a carrier"]) == STAND_IN_ANSWER


def test_the_assembled_pipeline_answers_a_question() -> None:
    assert answer("what makes a node green?") == STAND_IN_ANSWER


def test_the_index_holds_the_whole_corpus() -> None:
    store = build_index()

    assert store.similarity_search("blueprints", k=1)
