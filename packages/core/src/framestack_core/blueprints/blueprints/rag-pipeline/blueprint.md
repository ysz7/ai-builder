# RAG pipeline

Retrieval-augmented generation as four stages a person can see and set: chunking, embedding,
retrieval, generation. It answers a question from a corpus, and it does it without calling a
model — the generator composes its answer from what retrieval found, so the pipeline runs and
proves itself on a machine with no API key.

## Architecture

A **group over the four stages**, not over a single pipeline object. The stages are equal:
none of them owns the others, and a group is the only construct that gives the pipeline a
node without pretending one of them does.

**The knobs live on the stages themselves.** `chunk_size` belongs to chunking and `top_k`
belongs to retrieval; a settings class collecting both would put every knob one level away
from the thing it changes, and the person setting `top_k` is looking at retrieval.

`build_index()` is the entry point that hands the pipeline its documents, and `answer()` is
the one that asks it a question. Both are part of the contract rather than conveniences:
the builder indexes through the first and talks to the node through the second.

## Contracts

- `Chunker.split(document: str) -> list[str]`
- `Embedder.index(chunks: list[str]) -> None`, `Embedder.embed(text: str) -> list[float]`
- `Retriever.search(question: str) -> list[str]`
- `Generator.compose(question: str, passages: list[str]) -> str`
- `build_index() -> object` — the store, whatever it is, after the documents went in
- `answer(question: str) -> str`

## Failure modes this shape avoids

- **A stage nobody can prove.** No stage can be proven by a call the toolchain invents —
  chunking needs a document, retrieval needs a question — so the tests are where the
  evidence comes from, and there is nowhere else it could honestly come from.
- **A pipeline that needs an account to run at all.** The generator stands in for a model.
  Replacing it with a real call is one file, and until somebody does, every stage is still
  provable.

## Done when

`pytest` passes, every stage is green because a test entered it, and `build_index()` returns
a store that answers `len`.
