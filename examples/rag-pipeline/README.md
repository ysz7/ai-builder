# Example: an annotated RAG pipeline

The topology that forced the group construct in the first place (architecture §5.3): four
equal stages — chunking, embedding, retrieval, generation — and no single carrier that
owns the others.

It is also where §5.4's promise first comes true: **each stage carries its own knobs**.
Expand the pipeline node, and the chunk size is on chunking, `top_k` is on retrieval, and
the context budget is on generation. There is deliberately no central settings class here;
collecting the knobs into one would take them away from the stage the user is looking at.

Everything runs locally and deterministically: a fake embedding model, an in-memory vector
store, and a stand-in chat model. The wiring around them — a prompt template carrying the
retrieved context — is the real thing, and swapping the stand-in for a real model is one
argument at the call site in `rag/generation.py`:

```python
Generator(model=ChatAnthropic(model="claude-sonnet-5"))
```

No stage can be proven by a call the toolchain invents — chunking takes a document,
retrieval takes a question — so `tests/` is the whole of the evidence for those nodes, and
there is nowhere else it could honestly come from.

```bash
uv run pytest examples/rag-pipeline/tests
uv run python -m aibuilder_core check examples/rag-pipeline --observe
```
