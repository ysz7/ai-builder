"""Stage 4: turning retrieved chunks and a question into an answer.

The chat model is injected, and the default is a deterministic fake -- for the same reason
the embeddings are (see `corpus.py`): this has to run in CI with no key and no network.
The wiring around it is the real thing: a prompt template carrying the retrieved context,
which is what the tests check. Swapping in a real model is one argument at the call site.

**Which model, and where it lives, are knobs** -- and that is the whole point of the three
of them below. Moving from a hosted API to a model on your own machine is `base_url` and a
model name, edited on the node; a stage that named its provider in an import would make
that a rewrite, and a graph you cannot change anything from is decoration. `api_key_env`
holds the **name** of a variable and never a key, because the graph writes knobs into the
repository and the first write would put somebody's credential on its way to git.
"""

import os
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
    model: Annotated[str, Param(label="Model")] = "gpt-4o-mini"
    #: Empty means the client's own default, which is what a first-party API wants. A local
    #: server or a gateway is a different value here and nothing else changes: this one knob
    #: is what makes OpenAI, OpenRouter, Ollama and LM Studio the same code.
    base_url: Annotated[str, Param(label="Base URL", help="Empty for the provider default")] = ""
    #: The variable's **name**, never its value. A local model needs no key, so empty is an
    #: ordinary state rather than a misconfiguration.
    api_key_env: Annotated[str, Param(label="API key env var")] = "OPENAI_API_KEY"

    @generated()
    def __init__(self, client: BaseChatModel | None = None) -> None:
        # GENERATED. Wiring; edited through the graph, not by hand.
        #
        # `client`, not `model`: the knob above is the model's *name*, and one attribute
        # holding both a string and a chat client is how the two quietly become one bug.
        #
        # The stand-in is the default and stays the default: the evidence these nodes get is
        # the project's own tests (Q7), and a suite that needed somebody's credential would
        # prove nothing in CI. A caller with a real model passes one; `describe_model` says
        # what the knobs above would reach, without reaching it.
        self.client = client or FakeListChatModel(responses=[STAND_IN_ANSWER])

    @editable(signature_locked=True)
    def describe_model(self) -> str:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        #
        # What the knobs point at, said rather than connected to. Reading the key would put
        # it in a return value; this reports only whether the named variable is set, which
        # is the question a person actually has when nothing answers.
        where = self.base_url or "the provider default"
        key = self.api_key_env
        held = "set" if key and os.environ.get(key) else "not set"
        return f"{self.model} via {where} (key {key or 'none'}: {held})"

    @editable(signature_locked=True)
    def build_prompt(self, question: str, chunks: list[str]) -> str:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        context = "\n\n".join(chunks[: self.max_context_chunks])
        rendered = PROMPT.format_messages(context=context, question=question, tone=self.tone)
        return "\n".join(str(message.content) for message in rendered)

    @editable(signature_locked=True)
    def answer(self, question: str, chunks: list[str]) -> str:
        # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
        return str(self.client.invoke(self.build_prompt(question, chunks)).content)
