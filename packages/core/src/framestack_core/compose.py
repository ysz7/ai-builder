"""What may be connected to what, and the call that connects it (P21).

**This is where this project and the flow-document builders genuinely differ, and the difference
must not be blurred.** There an edge is data and the runtime interprets the wire. Here an edge
is a type crossing a boundary, read from signatures, and flow comes from a run (Q9). There is no
graph file to write a connection into, and there must never be one -- so connecting is a **code
generation**: dragging from one node to another writes the call, into the generated zone, which
is where assembly already lives.

**The arrow appears afterwards, and for the usual reasons.** Because a type now crosses a
boundary, or because a run drew a flow. It is never drawn because a gesture was made, and if
the write succeeded and no arrow appeared, that is information rather than a bug.

**It refuses more than it accepts.** A composition is described here or it does not exist:
two kinds whose composition this table does not name get a refusal naming both, never a best
guess at a call signature. That asymmetry is deliberate and is the whole safety of the
mechanism -- a wrong write into a generated zone is a broken project, and a refusal is a
sentence with the agent behind it, which has the whole project in front of it and can do
what a table cannot.

**What is describable here, and what is deliberately not.** A composition belongs in this
table when the call is a *statement about two named things* -- "mount this router on this
app", "add this node to this graph", "register this task on this queue". It does **not**
belong here when writing it would mean working out how a value threads through an assembly:
a RAG stage composed into `answer()` has to be handed what the stage before it returned, and
which of `split` / `index` / `find` / `answer` to call and what to pass is an inference about
somebody's pipeline. Inference is the thing this codebase does not do, and a table that
guessed would be wrong in the way that looks right. Those connections are refused and handed
to the agent, which is P21's own stated preference between the two.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Composition", "COMPOSITIONS", "composition_for", "targets_for"]


@dataclass(frozen=True)
class Composition:
    """One describable connection: from a kind, to a kind, as one line of assembly."""

    source: str
    target: str
    #: The generated function on the target's carrier that the call goes into. Named rather
    #: than searched for: "the only generated function" is a rule that holds until a carrier
    #: has two, and then it silently picks one.
    into: str
    #: The statement to write, with `{name}` for the source carrier's own name and `{id}`
    #: for the source node's id. A template rather than a builder, because what makes a
    #: composition describable at all is that it is one line about two named things.
    call: str
    #: `from <module> import <name>` for the source's carrier, when the target's file does
    #: not already have it. Always needed in practice; kept as a flag so a future
    #: composition between two things in one file does not have to fake an import.
    imports_source: bool = True
    #: What this connection means, in one line. Shown wherever a person is offered it.
    description: str = ""


def _composition(
    source: str, target: str, *, into: str, call: str, description: str
) -> Composition:
    return Composition(source=source, target=target, into=into, call=call, description=description)


#: Every connection this toolchain will write. Short on purpose.
#:
#: Each of these is a line that exists, verbatim in shape, in the annotated example the
#: parser is written against -- which is the standard for adding another: a composition goes
#: in this table when somebody has already written it by hand in real code and it turned out
#: to be one statement naming two things.
COMPOSITIONS: tuple[Composition, ...] = (
    _composition(
        "fastapi.router",
        "fastapi.service",
        into="create_app",
        call="app.include_router({name}())",
        description="Mount the router on the service.",
    ),
    _composition(
        "langgraph.node",
        "langgraph.agent",
        into="build_graph",
        call='builder.add_node("{id}", {name})',
        description="Add the step to the agent's graph.",
    ),
    _composition(
        "queue.task",
        "queue.app",
        into="register_tasks",
        call='app.task(name="{id}")({name})',
        description="Register the task on the queue.",
    ),
)


def composition_for(source_kind: str, target_kind: str) -> Composition | None:
    """The composition for this pair, or `None` -- which is a refusal, not a fallback."""
    return next(
        (one for one in COMPOSITIONS if one.source == source_kind and one.target == target_kind),
        None,
    )


def targets_for(source_kind: str) -> tuple[str, ...]:
    """The kinds this one may be connected *to*.

    So a canvas can say what a drag could land on before it is dropped, and can decline to
    offer one that would only be refused. It is the same table either way: there is no
    second list of what is connectable.
    """
    return tuple(one.target for one in COMPOSITIONS if one.source == source_kind)
