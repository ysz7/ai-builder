"""Stage 3: finding the chunks a question should be answered from."""

from typing import Annotated

from langchain_core.vectorstores import InMemoryVectorStore

from bp import Param, editable, node


@node(id="rag.retrieval", kind="rag.retrieval", title="Retrieval")
class Retriever:
    """Similarity search over the index, with the one knob that decides recall."""

    top_k: Annotated[int, Param(min=1, max=20, label="Chunks retrieved")] = 3
    search_type: Annotated[str, Param(widget="select", choices=("similarity", "mmr"))] = (
        "similarity"
    )

    @editable(signature_locked=True)
    def find(self, store: InMemoryVectorStore, question: str) -> list[str]:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        if self.search_type == "mmr":
            found = store.max_marginal_relevance_search(question, k=self.top_k)
        else:
            found = store.similarity_search(question, k=self.top_k)
        return [document.page_content for document in found]
