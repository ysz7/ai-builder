# LangGraph agent

An agent as a state machine: a shared state, the steps that change it, and the routers that
decide where it goes next. It runs and proves itself without a model call.

## Architecture

A **group over the state, the steps and the routers**. The topology is a graph, and the
state is what every part of it shares — so the state is a node rather than a detail of the
assembly, and each step is a node because each step is a carrier somebody can open.

`agent/graph.py` compiles the graph. That assembly is a **generated zone**. The flow arrows
the canvas draws come from the compiled graph the framework exposes and from a real run —
never from parsing the assembly code, and never from markup.

## Contracts

- the state is a `TypedDict` (or dataclass) every step takes and returns
- a step is `def step(state: State) -> State` — state in, the part of it that changed out
- a router is `def route(state: State) -> str` — a conditional edge, decided at runtime
- `agent/graph.py` exposes the compiled graph and an `ask()` entry point

## Failure modes this shape avoids

- **A step that only exists inside the assembly.** Every step is a named function with a
  node, so a run can be seen to enter it; a lambda in the builder call cannot be.
- **Flow that is a diagram rather than a fact.** The order is read from a run, so a graph
  with no run has no arrows — and that emptiness is a measurement.

## Done when

`pytest` passes, every step is green because a test entered it, and the compiled graph holds
every node the markup declares.
