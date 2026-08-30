"""Stage 2: turning chunks into vectors, and the store they go into.

The embeddings model is injected and the default is deterministic and local (see
`corpus.py`), for the same reason the chat model in `generation.py` is: this has to run in
CI with no key and no network.

**Which model, and where it lives, are knobs** -- the same three as the generation stage,
because a person choosing a local embeddings model is making exactly the choice a person
choosing a local chat model is, and two different answers to one question is how a graph
stops being predictable. They are separate knobs on a separate node on purpose: the stage
that answers and the stage that indexes can reach different providers, and usually should
-- embeddings are cheap, local and must stay fixed for the life of an index, and an answer
is neither.
"""

import os
from typing import Annotated

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from bp import Param, editable, generated, node


@node(id="rag.embedding", kind="rag.embedding", title="Embedding")
class Embedder:
    """Embeds chunks and holds the index they go into."""

    #: The stand-in's vector size. A real model decides its own, and this stops applying --
    #: which is why it is not the place to choose a model from.
    dimensions: Annotated[int, Param(min=16, max=1536, step=16, label="Vector size")] = 64
    model: Annotated[str, Param(label="Model")] = "text-embedding-3-small"
    #: Empty means the client's own default. A local server or a gateway is a different
    #: value here and nothing else changes.
    base_url: Annotated[str, Param(label="Base URL", help="Empty for the provider default")] = ""
    #: The variable's **name**, never its value. A local model needs no key, so empty is an
    #: ordinary state rather than a misconfiguration.
    api_key_env: Annotated[str, Param(label="API key env var")] = "OPENAI_API_KEY"

    @generated()
    def __init__(self, embeddings: Embeddings | None = None) -> None:
        # GENERATED. Wiring; edited through the graph, not by hand.
        #
        # The stand-in is the default and stays the default: the evidence these nodes get is
        # the project's own tests (Q7), and a suite that needed somebody's credential would
        # prove nothing in CI. A caller with a real model passes one.
        self.embeddings = embeddings or DeterministicFakeEmbedding(size=self.dimensions)

    @editable(signature_locked=True)
    def describe_model(self) -> str:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        #
        # What the knobs point at, said rather than connected to. Reading the key would put
        # it in a return value; this reports only whether the named variable is set.
        where = self.base_url or "the provider default"
        key = self.api_key_env
        held = "set" if key and os.environ.get(key) else "not set"
        return f"{self.model} via {where} (key {key or 'none'}: {held})"

    @editable(signature_locked=True)
    def index(self, chunks: list[str]) -> InMemoryVectorStore:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        store = InMemoryVectorStore(self.embeddings)
        store.add_texts(chunks)
        return store
