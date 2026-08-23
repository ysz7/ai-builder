"""Stage 4: turning retrieved chunks and a question into an answer.

The chat model is injected, and the default is a deterministic fake -- for the same reason
the embeddings are (see `corpus.py`): this has to run in CI with no key and no network.
The wiring around it is the real thing: a prompt template carrying the retrieved context,
which is what the tests check. Swapping in a real model is one argument at the call site.
"""

from typing import Annotated

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.prompts import ChatPromptTemplate

from bp import Param, editable, generated, node

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "Answer only from the context. Tone: {tone}.\n\nContext:\n{context}"),
        ("human", "{question}"),
    ]
)

#: What the stand-in model says. A real model replaces the object, not this string.
STAND_IN_ANSWER = "Answered from the retrieved context."


@node(id="rag.generation", kind="rag.generation", title="Generation")
class Generator:
    """Prompt assembly and the model call."""

    max_context_chunks: Annotated[int, Param(min=1, max=10, label="Chunks in the prompt")] = 3
    tone: Annotated[str, Param(widget="select", choices=("plain", "formal", "terse"))] = "plain"

    @generated()
    def __init__(self, model: BaseChatModel | None = None) -> None:
        # GENERATED. Wiring; edited through the graph, not by hand.
        self.model = model or FakeListChatModel(responses=[STAND_IN_ANSWER])

    @editable(signature_locked=True)
    def build_prompt(self, question: str, chunks: list[str]) -> str:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        context = "\n\n".join(chunks[: self.max_context_chunks])
        rendered = PROMPT.format_messages(context=context, question=question, tone=self.tone)
        return "\n".join(str(message.content) for message in rendered)

    @editable(signature_locked=True)
    def answer(self, question: str, chunks: list[str]) -> str:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        return str(self.model.invoke(self.build_prompt(question, chunks)).content)
