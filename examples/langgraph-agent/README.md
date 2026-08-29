# Example: an annotated LangGraph agent

The second topology the toolchain is proven against, and the one that puts a **graph inside
the group**: the members are a state schema, three step functions and a router, none of
which an HTTP call could reach.

- the agent is a **group node** (`agent/__node__.py`), members by object reference;
- the **state is a node of its own** — it is the contract every step reads and writes, and
  its observable check is that the graph was actually built against it;
- each step is a `@node(kind="langgraph.node")` whose body is `@editable` with a locked
  signature — that signature is what LangGraph calls it by;
- the conditional edge is a `@node(kind="langgraph.router")`, proven by being wired into a
  branch, not by being named like one;
- graph assembly and the entry point are generated zone.

The corpus is three sentences in `agent/knowledge.py` and there is no model call anywhere:
an agent that could only be observed with an API key could not be observed in CI at all.

`tests/` is the agent's own suite, and it is **the run the graph observes** — every step
node is proven by a test that actually entered it.

```bash
uv run pytest examples/langgraph-agent/tests
uv run python -m framestack_core check examples/langgraph-agent --observe
```
