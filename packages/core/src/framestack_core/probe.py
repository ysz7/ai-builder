"""The observable checks, executed inside the user's project.

This is the **only** module that imports the project it is looking at. Everywhere else
reading is deliberately static (see `parser.py`), because drawing a picture of code should
never run it. Here the opposite is the point: acceptance condition 2 asks whether the node
actually works, and nothing but running it can answer that.

Which is why this file is never imported by the toolchain. It is spawned as a separate
process (`observe.py` does the spawning), so a project that crashes on import, hangs, or
installs a signal handler takes down a process nobody depends on. It reads a plan on
stdin, writes results on stdout, and treats every failure as data rather than as an
exception -- a check that blew up is a red node with a reason, not a dead runner.

**A check that cannot run reports `skipped`, never `passed`.** A skipped check leaves the
node unproven, which is the honest state; a check that quietly passed because it could not
find anything to test would be the exact failure I-5 exists to prevent.

There are two sources of evidence here, and exactly one rule for choosing between them
(Q7):

1. **The project's own tests**, run with the carriers instrumented. This is the primary
   source. It is a real run with real input, authored by whoever knows the domain, and it
   is the only thing that can prove a node the toolchain cannot call at all -- `POST
   /users` has no valid body we are entitled to invent.
2. **The direct calls** built in P4, for the nodes no test reached. Cheap, and they need
   nothing made up: an app serves its schema, a router's routes are mounted, a GET with no
   parameters answers.

Test evidence outranks a direct call wherever both exist. A node neither exercised nor
callable is `skipped` -- which is the "no evidence" state Unreal shows as a dark node, and
it is a measurement, not a failure.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from types import CodeType, FrameType
from typing import Any

__all__ = [
    "TestRun",
    "build_pipeline_index",
    "converse",
    "environment_note",
    "locate_application",
    "call_server_tool",
    "inspect_server",
    "locate_queue",
    "main",
    "ping_queue",
    "observe_tests",
    "observed_flow",
    "run_plan",
    "run_plan_with_flow",
    "version_note",
    "wired_flow",
]

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class Context:
    """What the checks share: the imported project, and whatever was found in it."""

    modules: dict[str, Any] = field(default_factory=dict)
    import_errors: dict[str, str] = field(default_factory=dict)
    _app: Any = None
    _app_searched: bool = False

    def resolve(self, dotted: str) -> Any:
        """The object a carrier path names, or None if it is not there any more."""
        module_name, _, attribute = dotted.rpartition(".")
        module = self.modules.get(module_name)
        if module is None:
            return None
        return getattr(module, attribute, None)

    def application(self) -> Any:
        """The ASGI application, found by looking for one among the imported modules.

        Discovery rather than convention: the graph knows which modules take part, and a
        service has exactly one app object, so searching those modules is more robust than
        guessing `main:app` and more honest than requiring the project to announce itself
        in a place the runtime would never read.
        """
        if self._app_searched:
            return self._app
        self._app_searched = True

        try:
            from fastapi import FastAPI
        except ImportError:
            return None

        found = [
            value
            for module in self.modules.values()
            for value in vars(module).values()
            if isinstance(value, FastAPI)
        ]
        # Identity, not equality: two names for one app must not read as two apps.
        unique = {id(app): app for app in found}
        self._app = next(iter(unique.values())) if len(unique) == 1 else None
        return self._app


@dataclass
class Result:
    node: str
    check: str
    status: str
    detail: str
    #: What produced this result, as an identifier rather than as prose -- a test id, where
    #: a test is what proved the node. The detail already says so in a sentence, but a
    #: sentence is written to be read and a chip on a node card has to be *rendered*, and a
    #: front end pulling a test id back out of "exercised by 3 passing test(s), e.g. ..."
    #: would be a second opinion about a format one floor down (architecture 5.8) that
    #: breaks the first time the wording improves. Empty where the evidence has no name of
    #: its own beyond `check`.
    by: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "node": self.node,
            "check": self.check,
            "status": self.status,
            "detail": self.detail,
            "by": self.by,
        }


def _client(app: Any) -> Any:
    from fastapi.testclient import TestClient

    # Server exceptions must come back as a 500 response, not be re-raised into the
    # runner: "the route raises" is a finding about the node, not a crash of the checker.
    return TestClient(app, raise_server_exceptions=False)


def _iter_routes(container: Any) -> Any:
    """Every route reachable from an app or router, however it is nested.

    `app.routes` is not flat. Current FastAPI keeps an included router as a wrapper object
    holding the original, older versions copied the routes up, and a mounted sub-app nests
    again. Walking the tree works for all three; reading `app.routes` directly works only
    for whichever shape happened to be current when the code was written.
    """
    for route in getattr(container, "routes", []) or []:
        nested = getattr(route, "original_router", None) or getattr(route, "app", None)
        if nested is not None and hasattr(nested, "routes"):
            yield from _iter_routes(nested)
        else:
            yield route


def _route_for(app: Any, carrier: Any) -> Any:
    """The mounted route whose handler *is* this carrier -- identity, not name."""
    return next(
        (route for route in _iter_routes(app) if getattr(route, "endpoint", None) is carrier),
        None,
    )


# -- the checks ------------------------------------------------------------------


def app_serves(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    app = context.application()
    if app is None:
        return FAILED, "no single ASGI application was found among the project's modules"

    response = _client(app).get("/openapi.json")
    if response.status_code != 200:
        return FAILED, f"the application did not serve its schema (HTTP {response.status_code})"
    return PASSED, "the application starts and serves"


def route_answers(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    app = context.application()
    if app is None:
        return FAILED, "no single ASGI application was found among the project's modules"

    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    route = _route_for(app, carrier)
    if route is None:
        return FAILED, "the route is declared but not mounted on the application"

    methods = set(getattr(route, "methods", set()) or set())
    callable_methods = methods & {"GET", "HEAD"}
    if not callable_methods:
        return SKIPPED, f"{'/'.join(sorted(methods)) or 'the route'} needs a request body to call"
    if "{" in route.path:
        return SKIPPED, "the path takes parameters, and inventing values would prove nothing"
    if getattr(route, "body_field", None) is not None:
        return SKIPPED, "the route takes a request body, and inventing one would prove nothing"

    response = _client(app).get(route.path)
    if response.status_code >= 500:
        return FAILED, f"{route.path} answered HTTP {response.status_code}"
    if response.status_code == 422:
        # The framework rejecting the call for want of input is not the node working. It is
        # the same lie a synthesized request body would be, arriving by a different door
        # (Q7): what a 422 proves is that validation runs.
        return SKIPPED, f"{route.path} needs input this check is not entitled to invent"
    return PASSED, f"{route.path} answered HTTP {response.status_code}"


def router_mounts(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    app = context.application()
    if app is None:
        return FAILED, "no single ASGI application was found among the project's modules"

    members = node.get("member_carriers") or []
    if not members:
        return SKIPPED, "the router declares no routes, so there is nothing to mount"

    missing = [
        dotted
        for dotted in members
        if (carrier := context.resolve(dotted)) is None or _route_for(app, carrier) is None
    ]
    if missing:
        return FAILED, f"not mounted on the application: {', '.join(sorted(missing))}"
    return PASSED, f"all {len(members)} route(s) are mounted"


def settings_load(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    instance = carrier()
    return PASSED, f"{type(instance).__name__} loads with its declared defaults"


def dependency_resolves(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    import inspect

    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    required = [
        parameter
        for parameter in inspect.signature(carrier).parameters.values()
        if parameter.default is inspect.Parameter.empty
    ]
    if required:
        return SKIPPED, "the provider takes arguments, so it cannot be resolved on its own"

    carrier()
    return PASSED, "the provider resolves"


# -- LangGraph -------------------------------------------------------------------
#
# The registration checks below ask an identity question -- "is *this* function the one
# the graph actually calls?" -- and answer it through attributes LangGraph does not
# promise. When a version stops exposing them the answer is `skipped`, never `failed`: a
# library that moved an attribute has not broken the user's node, and the node's real
# evidence comes from the project's own tests either way (Q7).


def _compiled_graph(context: Context) -> Any:
    """The one compiled LangGraph in the project, found the way the app is found."""
    try:
        from langgraph.graph.state import CompiledStateGraph
    except ImportError:
        return None

    found = [
        value
        for module in context.modules.values()
        for value in vars(module).values()
        if isinstance(value, CompiledStateGraph)
    ]
    unique = {id(graph): graph for graph in found}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _underlying(runnable: Any) -> Any:
    """The user's own function inside whatever LangGraph wrapped it in."""
    import functools

    for attribute in ("func", "afunc", "bound"):
        candidate = getattr(runnable, attribute, None)
        if isinstance(candidate, functools.partial):
            candidate = next((arg for arg in candidate.args if callable(arg)), None)
        if candidate is not None:
            return candidate
    return None


def graph_compiles(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    graph = _compiled_graph(context)
    if graph is None:
        return FAILED, "no single compiled LangGraph was found among the project's modules"

    names = [name for name in getattr(graph, "nodes", {}) if not name.startswith("__")]
    if not names:
        return FAILED, "the graph compiled with no nodes in it"
    return PASSED, f"the graph compiles with {len(names)} node(s)"


def graph_state_schema(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    graph = _compiled_graph(context)
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"
    if graph is None:
        return FAILED, "no single compiled LangGraph was found among the project's modules"

    builder = getattr(graph, "builder", None)
    schema = next(
        (
            candidate
            for attribute in ("state_schema", "schema", "input_schema")
            if (candidate := getattr(builder, attribute, None)) is not None
        ),
        None,
    )
    if schema is None:
        return SKIPPED, "this LangGraph version does not expose the graph's state schema"
    if schema is not carrier:
        return FAILED, f"the graph was built against {getattr(schema, '__name__', schema)!r}"
    return PASSED, "the graph is built against this state"


def graph_node_registered(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    graph = _compiled_graph(context)
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"
    if graph is None:
        return FAILED, "no single compiled LangGraph was found among the project's modules"

    specs = getattr(getattr(graph, "builder", None), "nodes", None)
    if not specs:
        return SKIPPED, "this LangGraph version does not expose the graph's nodes"

    resolved = {name: _underlying(getattr(spec, "runnable", None)) for name, spec in specs.items()}
    for name, underlying in resolved.items():
        if underlying is carrier:
            return PASSED, f"registered as the node {name!r}"
    # Nothing at all could be unwrapped: that is a version whose shape we cannot read, not
    # a node the user failed to register. Saying "never registered" there would be a red
    # badge invented by a library upgrade.
    if not any(resolved.values()):
        return SKIPPED, "this LangGraph version does not expose the callable behind a node"
    return FAILED, "the function is declared a node but the graph never registered it"


def graph_branch_registered(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    graph = _compiled_graph(context)
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"
    if graph is None:
        return FAILED, "no single compiled LangGraph was found among the project's modules"

    branches = getattr(getattr(graph, "builder", None), "branches", None)
    if branches is None:
        return SKIPPED, "this LangGraph version does not expose the graph's branches"

    resolved = {
        source: [_underlying(getattr(spec, "path", None)) for spec in named.values()]
        for source, named in branches.items()
    }
    for source, paths in resolved.items():
        if any(path is carrier for path in paths):
            return PASSED, f"decides the edges leaving {source!r}"
    if branches and not any(path for paths in resolved.values() for path in paths):
        return SKIPPED, "this LangGraph version does not expose the callable behind a branch"
    return FAILED, "the function is declared a router but no conditional edge uses it"


# -- Persistence and vectors -----------------------------------------------------


def db_connection_opens(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """Open the connection this node owns, and close it again.

    The one claim worth making about a database node without inventing anything: the
    settings it holds reach something that answers. The carrier exposes `connect()` taking
    no arguments -- a convention the system prompt fixes, the way the settings kind's
    convention is fixed -- and a node that exposes no such method is skipped rather than
    guessed at.
    """
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    instance = carrier() if isinstance(carrier, type) else carrier
    connect = getattr(instance, "connect", None)
    if not callable(connect):
        return SKIPPED, "this node exposes no connect() to call"

    connection = connect()
    close = getattr(connection, "close", None)
    if callable(close):
        close()
    return PASSED, "the connection opens"


def vector_store_opens(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """The store constructs and is ready to be used.

    Searching needs a query and adding needs a document, and neither is ours to invent, so
    the proof of what this node *does* comes from the project's own tests (Q7). What can be
    said here without inventing anything is that the store loads at all.
    """
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    instance = carrier() if isinstance(carrier, type) else carrier
    operations = [
        name
        for name in ("add", "search", "embed", "index", "query")
        if callable(getattr(instance, name, None))
    ]
    if not operations:
        return FAILED, "the store loads but exposes nothing to add to or search"
    return SKIPPED, "the store loads; proving what it does needs real input"


# -- Background work -------------------------------------------------------------
#
# Two claims live here and they are deliberately not the same one: **the task works** and
# **the queue delivers**. A task is proven by a run that entered it -- the project's own
# tests, which may well run it in-process; the queue is proven by the broker answering.
# Letting either stand in for the other is how a green graph would come to mean "the code
# is fine" while nothing was ever actually delivered.
#
# Everything below asks celery. Nothing reads a task out of the assembly code: the registry
# is the queue's own account of what it knows, and the identity question -- "is *this*
# function the one registered?" -- is answered by code object, never by a matching name.


def _queue(context: Context) -> Any:
    """The one celery application in the project, found the way the app is found."""
    try:
        # celery ships no type information; nothing here needs any, since what comes back
        # is the project's own object and every question asked of it is asked defensively.
        from celery import Celery  # type: ignore[import-untyped]
    except ImportError:
        return None

    found = [
        value
        for module in context.modules.values()
        for value in vars(module).values()
        if isinstance(value, Celery)
    ]
    unique = {id(app): app for app in found}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _registered_as(app: Any, carrier: Any) -> list[str]:
    """The names this exact function is registered under. Identity, never a name match."""
    code = getattr(carrier, "__code__", None)
    if code is None:
        return []

    names = []
    for name, task in dict(getattr(app, "tasks", {})).items():
        run = getattr(task, "run", None)
        if getattr(run, "__code__", None) is code:
            names.append(name)
    return sorted(names)


def queue_broker_answers(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """Does the broker this queue is configured against answer?

    A broker that is down leaves this **skipped**, not failed, and for the same reason a
    stopped container does (P11): the queue's configuration is not wrong because nothing is
    listening yet, and the reason names the button that would prove it.
    """
    if context.resolve(node["carrier"]) is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    app = _queue(context)
    if app is None:
        return FAILED, "no single task queue was found among the project's modules"

    try:
        with app.connection() as connection:
            connection.ensure_connection(max_retries=0, timeout=2)
            where = connection.as_uri()
    except Exception as exc:
        return SKIPPED, (
            f"the broker does not answer ({type(exc).__name__})"
            " -- start it from the compose file's node"
        )
    return PASSED, f"the broker answers at {where}"


def queue_task_registered(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """Is this function on the queue -- and therefore something a worker could ever run?

    The wiring question, the same one a route's mounting asks. It is not the question of
    whether the task *works*: that one is answered by a run that entered it, and that
    evidence outranks this check wherever both exist.
    """
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    app = _queue(context)
    if app is None:
        return FAILED, "no single task queue was found among the project's modules"

    names = _registered_as(app, carrier)
    if not names:
        return FAILED, "this function is declared a task but nothing registers it with the queue"
    return PASSED, f"registered as {names[0]}"


def queue_schedule_entries(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """Every timed entry names a task the queue knows.

    An entry pointing at a name nothing registered is a job that will fire and fail forever,
    silently, at three in the morning. It is exactly the kind of thing a graph is for.
    """
    if context.resolve(node["carrier"]) is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    app = _queue(context)
    if app is None:
        return FAILED, "no single task queue was found among the project's modules"

    schedule = dict(getattr(app.conf, "beat_schedule", None) or {})
    if not schedule:
        return FAILED, "the queue has no scheduled entries, so this node schedules nothing"

    unknown = sorted(
        f"{name} -> {_entry_task(entry)}"
        for name, entry in schedule.items()
        if _entry_task(entry) not in app.tasks
    )
    if unknown:
        return FAILED, f"scheduled entries name tasks the queue does not know: {', '.join(unknown)}"
    return PASSED, f"{len(schedule)} scheduled entry(s), all naming registered tasks"


def _entry_task(entry: Any) -> Any:
    """The task name inside a schedule entry, whichever shape celery accepted for it."""
    if isinstance(entry, dict):
        return entry.get("task")
    return getattr(entry, "task", None)


def queue_assembles(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """The subsystem as a whole: a queue exists and it knows about work of its own."""
    app = _queue(context)
    if app is None:
        return FAILED, "no single task queue was found among the project's modules"

    # Celery registers its own housekeeping tasks in every application; they are not this
    # project's work, and counting them would make an empty queue look assembled.
    own = sorted(name for name in app.tasks if not name.startswith("celery."))
    if not own:
        return FAILED, "the queue has no tasks registered, so no worker would have anything to do"
    return PASSED, f"{len(own)} task(s) registered on the {app.main!r} queue"


# -- MCP and tools (P15) ---------------------------------------------------------
#
# Three roles, three questions, and they are not interchangeable. What this project
# *exposes* is its own code, so the identity question -- "is this exact function the one on
# the server?" -- is answered by code object, the way a task's registration is. What this
# project *consumes* is a foreign program, so nothing here connects to it: a connection is
# an action a person takes (P11), never a side effect of drawing a graph, and the check
# says which button would prove the node instead.


def _mcp_server(context: Context) -> Any:
    """The one MCP server this project exposes, found the way the app is found."""
    try:
        # The SDK ships types, but nothing here needs them: what comes back is asked
        # defensively, and a release that moves an attribute must cost a skip, not a crash.
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        return None

    found = [
        value
        for module in context.modules.values()
        for value in vars(module).values()
        if isinstance(value, MCPServer)
    ]
    unique = {id(server): server for server in found}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _exposed_tools(server: Any) -> list[Any]:
    """The tools the server is holding, with the function behind each one still attached.

    `list_tools()` is the protocol answer and it has no functions in it -- it is what a
    client sees. Identity needs the object the server kept, which is why this goes through
    the SDK's tool manager and why `mcp` has an entry in `kinds.TECHNOLOGIES`.
    """
    manager = getattr(server, "_tool_manager", None)
    lister = getattr(manager, "list_tools", None)
    if lister is None:
        return []
    try:
        return list(lister())
    except Exception:
        return []


def _exposed_as(server: Any, carrier: Any) -> list[str]:
    """The names this exact function is exposed under. Identity, never a name match."""
    code = getattr(carrier, "__code__", None)
    if code is None:
        return []
    return sorted(
        str(getattr(tool, "name", ""))
        for tool in _exposed_tools(server)
        if getattr(getattr(tool, "fn", None), "__code__", None) is code
    )


def mcp_service_serves(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """The server this project exposes, with tools actually on it.

    The wiring question for the whole subsystem, and the same one `queue.assembles` asks:
    an empty server is a program a client can connect to and get nothing from.
    """
    server = _mcp_server(context)
    if server is None:
        return FAILED, "no single MCP server was found among the project's modules"

    tools = _exposed_tools(server)
    if not tools:
        return FAILED, "the server exposes no tools, so a client would connect to nothing"
    return PASSED, f"the {getattr(server, 'name', '?')!r} server offers {len(tools)} tool(s)"


def mcp_tool_exposed(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """Is this function on our server -- and therefore something a client could call?

    The wiring question again, and not the question of whether the tool *works*: that one
    is answered by a run that entered it, and that evidence outranks this check.
    """
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    server = _mcp_server(context)
    if server is None:
        return FAILED, "no single MCP server was found among the project's modules"

    names = _exposed_as(server, carrier)
    if not names:
        return FAILED, "this function is declared a tool but nothing exposes it on the server"
    return PASSED, f"exposed as {names[0]}"


def _declaration(context: Context, node: dict[str, Any]) -> tuple[Any, str | None]:
    """The consumed server's declaration, ready to be asked something.

    A class is constructed, a module is itself. Constructing is not connecting: the
    declaration holds a command, a URL and an environment variable's *name*, and building
    it reaches nobody.
    """
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return None, f"{node['carrier']} does not exist at runtime"
    if isinstance(carrier, type):
        try:
            return carrier(), None
        except Exception as exc:
            return None, f"the declaration does not construct: {type(exc).__name__}: {exc}"
    return carrier, None


def mcp_server_reachable(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """Never connects, on purpose (P11).

    A stdio server is a third party's process and a URL is somebody else's machine.
    Starting or reaching either while a graph is being drawn is the side effect P11 exists
    to forbid -- so this check stops at what can be known without a connection, and names
    the button that would answer the rest. `mcp.inspect` is that button, and it is where
    the three verdicts of this node actually get decided.

    Structural rather than conditional: there is no flag that makes this connect. A read
    cannot reach a foreign program by any path through here.
    """
    declaration, problem = _declaration(context, node)
    if problem is not None:
        return FAILED, problem

    if not callable(getattr(declaration, "connect", None)):
        return FAILED, "the declaration exposes no connect(), so nothing can reach the server"

    # The knob holds the *name* of the variable, never the token -- a knob is a syntax node
    # in this project's source, and a write of a secret into one lands in git.
    variable = str(getattr(declaration, "token_env", "") or "")
    if variable and not os.environ.get(variable):
        return SKIPPED, f"{variable} is not set, so this server could not be reached anyway"
    return SKIPPED, "not connected -- connect from this node (mcp.inspect)"


def graph_tool_bound(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    """Is this function bound to the agent as a tool it may call?

    Asked of the compiled graph, the way every other LangGraph fact is (§5.8). Identity by
    code object, because the tool object the agent holds is a wrapper the framework built
    around the carrier, and matching by name would call a different `search` this one.
    """
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"
    graph = _compiled_graph(context)
    if graph is None:
        return FAILED, "no single compiled LangGraph was found among the project's modules"

    bound = _bound_tools(graph)
    if not bound:
        return SKIPPED, "this agent binds no tools in a way the graph exposes"

    code = getattr(carrier, "__code__", None)
    for name, function in bound.items():
        same = code is not None and getattr(function, "__code__", None) is code
        if function is carrier or same:
            return PASSED, f"bound to the agent as the tool {name!r}"
    return FAILED, "the function is declared a tool but the agent never bound it"


def _bound_tools(graph: Any) -> dict[str, Any]:
    """name -> the function behind each tool the compiled graph holds."""
    bound: dict[str, Any] = {}
    specs = getattr(getattr(graph, "builder", None), "nodes", None) or {}
    for spec in specs.values():
        runnable = getattr(spec, "runnable", None)
        for holder in (runnable, _underlying(runnable)):
            for name, tool in dict(getattr(holder, "tools_by_name", {}) or {}).items():
                function = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
                if function is not None:
                    bound[str(name)] = function
    return bound


# -- RAG -------------------------------------------------------------------------
#
# A stage takes a document, a query or a set of chunks. None of those can be invented --
# a made-up question proves that the pipeline does not crash, not that it retrieves the
# right thing -- so the direct checks here stop at what needs no input: the stage exists,
# it constructs, and it is callable. Everything beyond that is the project's own tests,
# which is exactly the split Q7 settled.


def _stage(context: Context, carrier: Any) -> tuple[Any, str | None]:
    """A stage ready to be used: the class constructed, or the function itself."""
    if isinstance(carrier, type):
        try:
            return carrier(), None
        except Exception as exc:
            return None, f"the stage does not construct: {type(exc).__name__}: {exc}"
    if callable(carrier):
        return carrier, None
    return None, "the stage is neither a class nor a callable"


def rag_stage_ready(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    carrier = context.resolve(node["carrier"])
    if carrier is None:
        return FAILED, f"{node['carrier']} does not exist at runtime"

    stage, problem = _stage(context, carrier)
    if problem is not None:
        return FAILED, problem

    if isinstance(carrier, type) and not any(
        callable(getattr(stage, name, None)) for name in vars(carrier) if not name.startswith("_")
    ):
        return FAILED, "the stage constructs but exposes nothing to call"
    return SKIPPED, "the stage loads; proving what it does needs real input"


def rag_stages_load(context: Context, node: dict[str, Any]) -> tuple[str, str]:
    members = node.get("member_carriers") or []
    if not members:
        return SKIPPED, "the pipeline declares no stages, so there is nothing to load"

    broken: list[str] = []
    for dotted in members:
        carrier = context.resolve(dotted)
        if carrier is None:
            broken.append(f"{dotted} (missing)")
            continue
        _, problem = _stage(context, carrier)
        if problem is not None:
            broken.append(f"{dotted} ({problem})")

    if broken:
        return FAILED, f"the pipeline does not assemble: {'; '.join(sorted(broken))}"
    return PASSED, f"all {len(members)} stage(s) load"


CHECKS = {
    "http.app_serves": app_serves,
    "http.route_answers": route_answers,
    "http.router_mounts": router_mounts,
    "http.dependency_resolves": dependency_resolves,
    "settings.load": settings_load,
    "graph.compiles": graph_compiles,
    "graph.state_schema": graph_state_schema,
    "graph.node_registered": graph_node_registered,
    "graph.branch_registered": graph_branch_registered,
    "db.connection_opens": db_connection_opens,
    "vector.store_opens": vector_store_opens,
    "rag.stages_load": rag_stages_load,
    "rag.stage_ready": rag_stage_ready,
    "queue.assembles": queue_assembles,
    "queue.broker_answers": queue_broker_answers,
    "queue.task_registered": queue_task_registered,
    "queue.schedule_entries": queue_schedule_entries,
    "mcp.service_serves": mcp_service_serves,
    "mcp.tool_exposed": mcp_tool_exposed,
    "mcp.server_reachable": mcp_server_reachable,
    "graph.tool_bound": graph_tool_bound,
}


# -- the observed run: the project's own tests, with the carriers instrumented ----


@dataclass
class TestRun:
    """What the project's tests proved about each node, and nothing beyond that."""

    #: node id -> the tests that actually entered its carrier.
    fired: dict[str, set[str]] = field(default_factory=dict)
    #: test id -> the nodes it entered, in the order it first entered each of them. This is
    #: where the flow relation comes from (Q9): not parsed out of assembly code, not
    #: declared in markup, but the order a real run went in.
    sequence: dict[str, list[str]] = field(default_factory=dict)
    #: test id -> "passed" / "failed" / "skipped", as pytest reported it.
    outcomes: dict[str, str] = field(default_factory=dict)
    ran: bool = False
    #: Why the suite did not run, when it did not. Never an absence of information.
    detail: str = ""

    def evidence(self, node: str) -> tuple[str, str, str] | None:
        """The verdict this run supports for one node, or `None` if it reached it not.

        A node is proven by a test that entered it **and passed**. A node entered only by
        failing tests is not proven -- and it is not merely unproven either, because
        something did run it and something did go wrong in that run.

        The third element is the test's id **as data**, beside the sentence and never
        instead of it: the prose is what a person reads, and the id is what a chip on a
        node card is drawn from without anybody parsing the prose.
        """
        tests = self.fired.get(node)
        if not tests:
            return None

        passing = sorted(test for test in tests if self.outcomes.get(test) == "passed")
        if passing:
            return (
                PASSED,
                f"exercised by {len(passing)} passing test(s), e.g. {passing[0]}",
                passing[0],
            )

        failing = sorted(test for test in tests if self.outcomes.get(test) == "failed")
        if failing:
            return (
                FAILED,
                f"every test that exercised this node failed, e.g. {failing[0]}",
                failing[0],
            )
        return None  # only skipped tests touched it: a run, but not a verdict


class _Recorder:
    """A pytest plugin and a trace hook, recording which carrier ran inside which test.

    Tracing rather than wrapping. A wrapper would have to be installed on the carrier
    object, and FastAPI captured its own reference to the endpoint when the route was
    added -- so the wrapper would sit on a name nothing calls. Code objects are what the
    interpreter actually enters, whichever reference got there first, and watching them
    changes no object the application holds. The markup layer is inert, and so is this.
    """

    def __init__(self, codes: dict[CodeType, str]):
        self.codes = codes
        self.fired: dict[str, set[str]] = {}
        self.sequence: dict[str, list[str]] = {}
        self.outcomes: dict[str, str] = {}
        self.current: str | None = None

    # the trace hook
    def trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if event == "call" and self.current is not None:
            node = self.codes.get(frame.f_code)
            if node is not None:
                self.fired.setdefault(node, set()).add(self.current)
                order = self.sequence.setdefault(self.current, [])
                if node not in order:
                    order.append(node)
        # No local trace function: entering the frame is the whole observation, and
        # tracing every line of a stranger's test suite would cost far more than it says.
        return None

    # the pytest hooks
    def pytest_runtest_logstart(self, nodeid: str, location: Any) -> None:
        self.current = nodeid

    def pytest_runtest_logfinish(self, nodeid: str, location: Any) -> None:
        self.current = None

    def pytest_runtest_logreport(self, report: Any) -> None:
        # A failure in setup or teardown is a failed test as far as evidence goes: the
        # node was not proven by it, whatever phase the error was reported in.
        if report.when == "call" or report.failed:
            previous = self.outcomes.get(report.nodeid)
            if previous != "failed":
                self.outcomes[report.nodeid] = report.outcome


def carrier_codes(context: Context, nodes: list[dict[str, Any]]) -> dict[CodeType, str]:
    """The code objects that mean "this node ran".

    A function carrier is its own code object. A class carrier contributes the functions
    defined in its body -- a class with no methods of its own (a Pydantic settings model,
    typically) contributes nothing, and is proven by its direct check instead. A group has
    no code at all, by definition: it is a declaration over other carriers.
    """
    codes: dict[CodeType, str] = {}
    for node in nodes:
        carrier = context.resolve(node["carrier"])
        if carrier is None:
            continue
        for code in _codes_of(carrier):
            codes[code] = node["id"]
    return codes


def _codes_of(carrier: Any) -> list[CodeType]:
    code = getattr(carrier, "__code__", None)
    if isinstance(code, CodeType):
        return [code]
    if isinstance(carrier, type):
        return [
            value.__code__
            for value in vars(carrier).values()
            if isinstance(getattr(value, "__code__", None), CodeType)
        ]
    return []


def observe_tests(plan: dict[str, Any], codes: dict[CodeType, str]) -> TestRun:
    """Run the project's test suite with the carriers instrumented.

    Everything that can go wrong here -- no suite, no pytest, a suite that will not even
    collect -- comes back as `ran=False` with a reason, and the nodes fall back to their
    direct checks. A broken suite must not read as a broken node, and it must not read as
    a passing one either.
    """
    tests = plan.get("tests")
    if not tests:
        return TestRun(detail="the project has no test suite to observe")
    if not codes:
        return TestRun(detail="no node carrier has code a run could enter")

    try:
        import pytest
    except ImportError:  # pragma: no cover -- pytest is a dependency of the core
        return TestRun(detail="pytest is not available to run the project's tests")

    recorder = _Recorder(codes)
    previous = sys.gettrace()
    sys.settrace(recorder.trace)
    # The application runs its request in a worker thread (the TestClient's portal), and
    # a trace hook set on this thread would never see it.
    threading.settrace(recorder.trace)
    project = plan["project"]
    working_directory = os.getcwd()
    try:
        # Run the suite from inside the project, the way its author runs it: a test that
        # opens a fixture file by relative path is an ordinary test, not a broken one.
        os.chdir(project)
        # pytest writes its report to stdout, and stdout here is the wire back to the
        # runner. Onto stderr with it, where every other log line in this system goes.
        with contextlib.redirect_stdout(sys.stderr):
            status = pytest.main(
                [str(tests), "-q", "-p", "no:cacheprovider", f"--rootdir={project}"],
                plugins=[recorder],
            )
    finally:
        os.chdir(working_directory)
        sys.settrace(previous)
        threading.settrace(None)

    code = int(getattr(status, "value", status))
    if code >= 2:
        return TestRun(detail=f"the project's tests could not be run (pytest exit {code})")
    if not recorder.outcomes:
        return TestRun(detail="the project's test suite collected nothing")

    return TestRun(
        fired=recorder.fired,
        sequence=recorder.sequence,
        outcomes=recorder.outcomes,
        ran=True,
    )


# -- completeness: if it is not on the graph, it is not in the code (Q12) --------
#
# I-3 says every node has a carrier. Nothing said every carrier has a node, so an
# undeclared client or an unmarked tool was simply invisible -- a graph lying by silence,
# which looks exactly like a clean graph. This is the other half of the rule, and it is
# **asked, never parsed** (§5.8): the project is imported and the library is asked what it
# is holding. Anything the library holds that the graph does not declare is reported with
# an address.
#
# Two costs, both deliberate. The claim needs a run, so it carries `proven` / `unproven`
# rather than being assumed -- claiming a complete graph from a static read would be the
# I-5 failure one level up. And **every** module is imported, not only the annotated ones:
# the file with no markup in it is exactly the file this rule exists for.


def _address(project: str, function: Any) -> dict[str, Any] | None:
    """Where a function lives, project-relative. `None` when it has no source at all."""
    code = getattr(function, "__code__", None)
    if code is None:
        return None
    file = getattr(code, "co_filename", "")
    return {
        "file": _relative(project, file),
        "line": int(getattr(code, "co_firstlineno", 1) or 1),
        "object": str(getattr(function, "__qualname__", getattr(function, "__name__", "?"))),
    }


def _relative(project: str, file: str) -> str:
    if not file:
        return "?"
    prefix = project.rstrip(os.sep) + os.sep
    return file[len(prefix) :] if file.startswith(prefix) else file


def _values_in(context: Context) -> list[tuple[str, str, Any]]:
    """Every module-level name in the project, as (module, attribute, value)."""
    return [
        (name, attribute, value)
        for name, module in context.modules.items()
        for attribute, value in vars(module).items()
        if not attribute.startswith("__")
    ]


def complete_mcp_tools(
    context: Context, declared: set[CodeType], project: str
) -> list[dict[str, Any]]:
    """Every tool on our own server has a node -- asked of the server, not of the source."""
    server = _mcp_server(context)
    if server is None:
        return []

    surplus = []
    for tool in _exposed_tools(server):
        function = getattr(tool, "fn", None)
        code = getattr(function, "__code__", None)
        if code is None or code in declared:
            continue
        address = _address(project, function)
        if address is not None:
            surplus.append({"what": f"the tool {getattr(tool, 'name', '?')!r}", **address})
    return surplus


def complete_mcp_clients(
    context: Context, declared: set[CodeType], project: str, objects: set[int]
) -> list[dict[str, Any]]:
    """Every connection to somebody else's server has a node.

    The library's own types are what identifies one: a `Client` or the parameters that
    start a server is a connection whatever the project called the variable. A declaration
    the graph *does* carry is skipped by identity -- the node's carrier, or its type.
    """
    try:
        from mcp import Client, StdioServerParameters
    except ImportError:
        return []

    surplus = []
    for module, attribute, value in _values_in(context):
        if not isinstance(value, Client | StdioServerParameters):
            continue
        if id(value) in objects or id(type(value)) in objects:
            continue
        file = getattr(context.modules[module], "__file__", "") or ""
        surplus.append(
            {
                "what": f"a connection to an MCP server held in {attribute}",
                "file": _relative(project, file),
                "line": 1,
                "object": f"{module}.{attribute}",
            }
        )
    return surplus


def complete_graph_tools(
    context: Context, declared: set[CodeType], project: str
) -> list[dict[str, Any]]:
    """Every tool the agent is bound to has a node -- asked of the compiled graph."""
    graph = _compiled_graph(context)
    if graph is None:
        return []

    surplus = []
    for name, function in _bound_tools(graph).items():
        code = getattr(function, "__code__", None)
        if code is None or code in declared:
            continue
        address = _address(project, function)
        if address is not None:
            surplus.append({"what": f"the tool {name!r} bound to the agent", **address})
    return surplus


def check_completeness(
    plan: dict[str, Any], context: Context, nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    """What the libraries hold that the graph does not declare, and whether we could ask.

    The probes named in the plan are the kinds that opted in through the registry, so a kind
    joins this rule by naming one and nothing here changes when the next one does.
    """
    probes = list(plan.get("completeness", []))
    if not probes:
        return {"state": "unproven", "detail": "no kind claims completeness", "undeclared": []}

    unimported = _import_the_rest(plan, context)

    declared: set[CodeType] = set()
    objects: set[int] = set()
    for node in nodes:
        carrier = context.resolve(node["carrier"])
        if carrier is None:
            continue
        objects.add(id(carrier))
        declared.update(_codes_of(carrier))

    project = plan["project"]
    undeclared: list[dict[str, Any]] = []
    for probe in probes:
        try:
            if probe == "mcp.tools":
                undeclared += complete_mcp_tools(context, declared, project)
            elif probe == "mcp.clients":
                undeclared += complete_mcp_clients(context, declared, project, objects)
            elif probe == "graph.tools":
                undeclared += complete_graph_tools(context, declared, project)
        except Exception as exc:
            # A probe that blew up asked nothing, so the claim is unproven rather than
            # clean. Reporting "complete" here would be the whole point of the rule lost.
            return {
                "state": "unproven",
                "detail": f"{probe} could not ask: {type(exc).__name__}: {exc}",
                "undeclared": undeclared,
            }

    if unimported:
        # A module that did not import is a module nothing was asked about, and the file
        # with no markup in it is exactly the one this rule is for. Unproven, with names.
        return {
            "state": "unproven",
            "detail": f"these modules did not import: {'; '.join(unimported)}",
            "undeclared": undeclared,
        }
    return {
        "state": "proven",
        "detail": f"{len(probes)} kind(s) asked their library what it holds",
        "undeclared": undeclared,
    }


def _import_the_rest(plan: dict[str, Any], context: Context) -> list[str]:
    """Import the project's unannotated modules too, and say which would not.

    Leniently, unlike the annotated ones: a module the graph knows nothing about must not
    be able to redden every node in the project. It costs the completeness claim instead,
    which is the thing it actually has a bearing on.
    """
    failures = []
    for name in plan.get("all_modules", []):
        if name in context.modules:
            continue
        try:
            context.modules[name] = importlib.import_module(name)
        except Exception as exc:
            failures.append(f"{name} ({type(exc).__name__})")
    return sorted(failures)


# -- the runner ------------------------------------------------------------------


def run_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    """Import what the plan names, run every check, and report one result per node."""
    return run_plan_with_flow(plan)[0]


def run_plan_with_flow(
    plan: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """The same run, plus the flow it revealed (Q9) and what the graph left out (Q12).

    Flow and evidence come out of one execution because they are one execution: the order a
    test went in is a fact about the same run that proved the nodes. Completeness joins them
    for the same reason -- it is a question about the same imported project.
    """
    sys.path.insert(0, plan["project"])

    context = Context()
    for name in plan.get("modules", []):
        try:
            context.modules[name] = importlib.import_module(name)
        except Exception as exc:  # importing is the check; a failure here is a finding
            context.import_errors[name] = f"{type(exc).__name__}: {exc}"

    nodes = plan.get("nodes", [])

    if context.import_errors:
        # A project that does not import cannot be proven in any part. Running the checks
        # anyway would report symptoms -- "no application was found" -- instead of the
        # cause, and send a repair after the wrong thing.
        failed = "; ".join(f"{name} ({error})" for name, error in context.import_errors.items())
        detail = f"the project did not import: {failed}"
        return (
            [Result(node["id"], node["check"], FAILED, detail).as_dict() for node in nodes],
            [],
            {"state": "unproven", "detail": detail, "undeclared": []},
        )

    # The suite runs after the imports, deliberately: "exercised" means a test entered
    # the carrier, and a carrier that merely ran at import time was not tested.
    run = observe_tests(plan, carrier_codes(context, nodes))

    results: list[Result] = []
    for node in nodes:
        evidence = run.evidence(node["id"])
        if evidence is not None:
            status, detail, by = evidence
            # A failure in an environment that is missing what the project asked for is
            # **unattributable**, and the asymmetry is deliberate: a test that passed proves
            # the node did its job, whatever else was absent, while a test that failed could
            # have failed because a database was not there. Calling that node broken would
            # be blaming code for the environment it was denied.
            if status == FAILED and (note := environment_note(plan)):
                status = SKIPPED
                detail = f"{detail}{note} -- a failure cannot be attributed to the node"
            results.append(Result(node["id"], "tests.exercised", status, detail, by))
            continue

        # Below the tests and above the direct checks (Q19). A conversation is a real run
        # with real input a person chose, so it proves more than a call this toolchain could
        # invent -- and less than a suite somebody wrote knowing the domain. The ranking is
        # here, in this loop, because there is exactly one place it is allowed to be.
        spoken = _conversation(node, plan)
        if spoken is not None:
            results.append(spoken)
            continue

        results.append(_direct(context, node, run, plan))

    flow = observed_flow(run) + wired_flow(context, nodes)
    # Last, and after everything else has been asked: it widens the imports to the
    # project's unannotated code, and nothing above it should be affected by that.
    completeness = check_completeness(plan, context, nodes)
    return [result.as_dict() for result in results], flow, completeness


def environment_note(plan: dict[str, Any]) -> str:
    """ "the services this project declares are not running" -- when that is the case.

    Attached to results that are not a pass, like the version note, and for the same
    reason: it is context the reader would otherwise have to go and find.
    """
    incomplete = plan.get("environment", {}).get("incomplete")
    return f"; {incomplete}" if incomplete else ""


def version_note(plan: dict[str, Any], kind: str) -> str:
    """ "The checks were written against X, you have Y" -- when, and only when, X != Y.

    Attached to results that are **not** a pass, and to nothing else. A node proven by a
    real run needs no footnote about library versions, and a note on a green node would be
    a warning about a problem that demonstrably is not there.

    It is context, never a cause: the mismatch is stated, and no claim is made that it is
    what went wrong. Anything stronger would be a guess about a release we have not run.
    """
    import importlib.metadata

    technology = plan.get("technologies", {}).get(kind.partition(".")[0])
    if not technology:
        return ""

    try:
        installed = importlib.metadata.version(technology["distribution"])
    except Exception:
        return ""

    if installed == technology["verified"]:
        return ""
    return (
        f"; these checks were written against {technology['distribution']} "
        f"{technology['verified']}, and {installed} is installed"
    )


def observed_flow(run: TestRun) -> list[dict[str, str]]:
    """What ran, and in what order. One arrow per pair of consecutive nodes in a test.

    Only from tests that **passed**: an order a failing run went in is not a description of
    how the system works, it is a description of how it broke that time.
    """
    seen: list[dict[str, str]] = []
    for test, order in run.sequence.items():
        if run.outcomes.get(test) != "passed":
            continue
        for source, target in zip(order, order[1:], strict=False):
            edge = {"source": source, "target": target, "origin": "observed"}
            if edge not in seen:
                seen.append(edge)
    return seen


def wired_flow(context: Context, nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The edges the framework itself holds, asked of the compiled object (§5.8).

    A LangGraph agent knows its own wiring, so we ask it rather than reading `add_edge`
    calls out of the assembly code -- which would teach the parser one library's API, and
    then the next one's. Edges that no run took are still real edges, and they are marked as
    wiring rather than as something that happened.
    """
    graph = _compiled_graph(context)
    builder = getattr(graph, "builder", None)
    edges = getattr(builder, "edges", None)
    if not edges:
        return []

    by_name: dict[str, str] = {}
    specs = getattr(builder, "nodes", {}) or {}
    for name, spec in specs.items():
        carrier = _underlying(getattr(spec, "runnable", None))
        for node in nodes:
            if carrier is not None and context.resolve(node["carrier"]) is carrier:
                by_name[name] = node["id"]

    flow: list[dict[str, str]] = []
    for edge in edges:
        try:
            source, target = edge
        except (TypeError, ValueError):
            continue
        if source in by_name and target in by_name:
            flow.append({"source": by_name[source], "target": by_name[target], "origin": "wiring"})
    return flow


def _conversation(node: dict[str, Any], plan: dict[str, Any]) -> Result | None:
    """What talking to this node proved, or `None` when nobody has talked to it (P17.4).

    Nothing is invented and nothing is remembered: the plan carries only the conversations
    that are open right now, so a node nobody asked anything stays unproven rather than
    keeping a claim from a dialogue that is over.
    """
    held = plan.get("conversations") or {}
    said = held.get(node["id"]) if isinstance(held, dict) else None
    if not isinstance(said, dict) or not said.get("status"):
        return None

    status = str(said["status"])
    detail = str(said.get("detail", ""))
    # The same attribution rule the tests and the direct checks follow: a node that broke
    # while the services it needs were down did not necessarily break.
    if status == FAILED and (note := environment_note(plan)):
        return Result(
            node["id"],
            "talk.answered",
            SKIPPED,
            f"{detail}{note} -- a failure cannot be attributed to the node",
        )
    return Result(node["id"], "talk.answered", status, detail)


def _direct(context: Context, node: dict[str, Any], run: TestRun, plan: dict[str, Any]) -> Result:
    """The fallback check: what the toolchain can call without inventing anything.

    Whatever it answers, the reason the tests did not answer first travels with it. A node
    that stays unproven has to say which run did not reach it, or "unproven" degrades into
    a shrug.
    """
    check = CHECKS.get(node["check"])
    if check is None:
        return Result(node["id"], node["check"], SKIPPED, "no runner for this check yet")

    try:
        status, detail = check(context, node)
    except Exception:
        # The traceback is the diagnosis. Truncated because a node badge is not a
        # place to read a stack, and the tail is the part that names the cause.
        trace = traceback.format_exc().strip().splitlines()
        status, detail = FAILED, f"the check raised: {trace[-1]}"

    if status == SKIPPED:
        unreached = "no test exercised this node" if run.ran else run.detail
        detail = f"{detail}; {unreached}"
    if status != PASSED:
        detail = f"{detail}{environment_note(plan)}{version_note(plan, node['kind'])}"
    # The same rule the test evidence follows, and for the same reason: a check that failed
    # because the service it needed was not there says nothing about this node.
    if status == FAILED and environment_note(plan):
        status = SKIPPED
        detail = f"{detail} -- a failure cannot be attributed to the node"
    return Result(node["id"], node["check"], status, detail)


def locate_application(plan: dict[str, Any]) -> dict[str, Any]:
    """Where the ASGI application is, as `module:attribute`.

    Asked of the project rather than guessed from a convention (§5.8): the runner has to
    name something to `uvicorn`, and "main:app" is a guess that is wrong the moment a
    project is laid out differently. This is the only question the runner needs the
    project imported to answer, and it is answered in the same process that imports
    everything else -- never in the one the UI is talking to.
    """
    context, failure = _import_all(plan)
    if failure is not None:
        return {"target": None, "detail": failure}

    app = context.application()
    if app is None:
        return {"target": None, "detail": "no single ASGI application was found"}

    for name, module in context.modules.items():
        for attribute, value in vars(module).items():
            if value is app:
                return {"target": f"{name}:{attribute}", "detail": f"found in {name}"}
    return {"target": None, "detail": "the application has no name in any imported module"}


def locate_queue(plan: dict[str, Any]) -> dict[str, Any]:
    """Where the task queue is, as `module:attribute`, and what a worker should run with.

    Asked of the project, never guessed (§5.8). `-A proj` is a celery convention that is
    wrong the moment a project is laid out differently, and the concurrency is celery's own
    configured value -- which is where the queue node's knob went, so the button and the
    knob cannot drift apart.
    """
    context, failure = _import_all(plan)
    if failure is not None:
        return {"target": None, "detail": failure}

    app = _queue(context)
    if app is None:
        return {"target": None, "detail": "no single task queue was found"}

    concurrency = getattr(app.conf, "worker_concurrency", None)
    for name, module in context.modules.items():
        for attribute, value in vars(module).items():
            if value is app:
                return {
                    "target": f"{name}:{attribute}",
                    "concurrency": int(concurrency) if concurrency else 0,
                    "detail": f"found in {name}",
                }
    return {"target": None, "detail": "the queue has no name in any imported module"}


def ping_queue(plan: dict[str, Any]) -> dict[str, Any]:
    """Wait for a worker to answer the queue, and say how many did.

    A worker publishes no port, so P13's readiness question has a different answer here:
    the queue is asked whether anything is listening to it. A log line saying "ready" is a
    string the process chose to print; a reply to a ping is the thing itself.
    """
    context, failure = _import_all(plan)
    if failure is not None:
        return {"ready": False, "detail": failure}

    app = _queue(context)
    if app is None:
        return {"ready": False, "detail": "no single task queue was found"}

    deadline = time.monotonic() + float(plan.get("wait_s", 0) or 0)
    while True:
        try:
            replies = app.control.ping(timeout=1) or []
        except Exception as exc:
            replies = []
            failure = f"the queue could not be asked ({type(exc).__name__}: {exc})"
        if replies:
            return {"ready": True, "workers": len(replies), "detail": f"{len(replies)} worker(s)"}
        if time.monotonic() >= deadline:
            return {"ready": False, "detail": failure or "no worker answered the queue"}


# -- the two MCP verbs: connect, and call one tool --------------------------------
#
# Both are **actions**, and they live here rather than in the core for the reason every
# other question about the project does: the connection belongs to the project's own
# object, and that object exists only in the project's interpreter. The asynchrony that
# made this look hard is handled the way `queue_ready` is -- one short-lived question,
# `asyncio.run` around it, JSON back. No coroutine and no held-open connection ever
# reaches the process the UI is talking to.


def _connect_and(declaration: Any, work: Any) -> Any:
    """Open the project's own connection, do one thing through it, and close it.

    Through `connect()`, never straight into the SDK: that is the convention the prompt
    fixes, and it is what makes "the agent actually uses this server" observable at all --
    a call that goes directly to the library leaves only library frames, so the tracer sees
    nothing and no flow arrow is ever drawn.
    """
    import asyncio

    async def once() -> Any:
        async with declaration.connect() as client:
            return await work(client)

    return asyncio.run(once())


def _tool_names(listing: Any) -> list[dict[str, str]]:
    """What came back from `tools/list`, in the one shape the wire carries."""
    tools = getattr(listing, "tools", listing)
    return [
        {
            "name": str(getattr(tool, "name", tool)),
            "description": str(getattr(tool, "description", "") or ""),
        }
        for tool in tools
    ]


def _allowed(declaration: Any) -> list[str]:
    """The subset of the server's tools this project may call -- a knob, comma-separated."""
    raw = getattr(declaration, "allowed_tools", "")
    if isinstance(raw, str):
        return [name.strip() for name in raw.split(",") if name.strip()]
    return [str(name) for name in raw or []]


def _rejected(exc: BaseException) -> bool:
    """Did the server answer and refuse us, rather than fail to answer at all?

    The one judgement call in the phase's verdicts, and it is decided the same way as the
    rest: credentials are not in the code, so a rejection is not the code's fault.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        signal in text
        for signal in ("unauthor", "forbidden", "401", "403", "invalid_token", "invalid token")
    )


def _declared_server(plan: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    """The project's declaration for the server a verb names, or the answer to give back."""
    context, failure = _import_all(plan)
    if failure is not None:
        return None, {"ok": False, "status": "unproven", "detail": failure}

    declaration, problem = _declaration(context, {"carrier": plan["carrier"]})
    if problem is not None:
        return None, {"ok": False, "status": "broken", "detail": problem}
    if not callable(getattr(declaration, "connect", None)):
        return None, {
            "ok": False,
            "status": "broken",
            "detail": "the declaration exposes no connect(), so nothing can reach the server",
        }

    variable = str(getattr(declaration, "token_env", "") or "")
    if variable and not os.environ.get(variable):
        return None, {
            "ok": False,
            "status": "unproven",
            "detail": f"{variable} is not set; the server's token has to be in the environment",
        }
    return declaration, None


def inspect_server(plan: dict[str, Any]) -> dict[str, Any]:
    """Connect, initialize, and list what the server offers (P15).

    Three verdicts, and the line between them is the one the whole system already draws:
    the absence of an environment is never red, a contradiction inside the project always
    is. Not connected or no token -> `unproven`. Answered, but our code names a tool it
    does not offer -> `broken`, exactly as a schedule entry naming an unknown task is: that
    is not an environment, it is code referring to something that does not exist, and the
    alternative to saying so here is finding out in production.

    Nothing is written down. A colleague who has not connected sees `unproven` rather than
    somebody else's yesterday, and that falls out of I-1 rather than being a feature.
    """
    declaration, answer = _declared_server(plan)
    if answer is not None:
        return {**answer, "tools": [], "allowed": [], "missing": []}

    allowed = _allowed(declaration)
    try:
        offered = _connect_and(declaration, lambda client: client.list_tools())
    except Exception as exc:
        detail = (
            "the server rejected our credentials"
            if _rejected(exc)
            else f"the server could not be reached ({type(exc).__name__}: {exc})"
        )
        return {
            "ok": False,
            "status": "unproven",
            "detail": detail,
            "tools": [],
            "allowed": allowed,
            "missing": [],
        }

    tools = _tool_names(offered)
    names = {tool["name"] for tool in tools}
    missing = sorted(name for name in allowed if name not in names)
    if missing:
        return {
            "ok": False,
            "status": "broken",
            "detail": (
                f"this project may call tools the server does not offer: {', '.join(missing)}"
            ),
            "tools": tools,
            "allowed": allowed,
            "missing": missing,
        }
    return {
        "ok": True,
        "status": "green",
        "detail": f"the server answered and offers {len(tools)} tool(s)",
        "tools": tools,
        "allowed": allowed,
        "missing": [],
    }


def call_server_tool(plan: dict[str, Any]) -> dict[str, Any]:
    """Call one tool with input a person typed (Q7).

    Never invented, and never defaulted into existence: a pass manufactured from a made-up
    argument is the same lie as a decorator moved to satisfy the parser. The allow-list is
    enforced here as well as shown, because it is the project's own statement about what it
    may call and a verb that ignored it would be lying about the node it is attached to.
    """
    declaration, answer = _declared_server(plan)
    if answer is not None:
        return {**answer, "result": ""}

    tool = str(plan.get("tool") or "")
    if not tool:
        return {"ok": False, "status": "broken", "detail": "no tool was named", "result": ""}

    allowed = _allowed(declaration)
    if allowed and tool not in allowed:
        return {
            "ok": False,
            "status": "broken",
            "detail": f"{tool} is not in this server's allow-list ({', '.join(allowed)})",
            "result": "",
        }

    arguments = plan.get("arguments") or {}
    try:
        answered = _connect_and(declaration, lambda client: client.call_tool(tool, arguments))
    except Exception as exc:
        detail = (
            "the server rejected our credentials"
            if _rejected(exc)
            else f"the call did not complete ({type(exc).__name__}: {exc})"
        )
        return {"ok": False, "status": "unproven", "detail": detail, "result": ""}

    return {
        "ok": not getattr(answered, "is_error", False),
        "status": "green" if not getattr(answered, "is_error", False) else "broken",
        "detail": f"{tool} answered",
        "result": _rendered(answered),
    }


def _rendered(answered: Any) -> str:
    """What a tool said, as text a person can read on a node."""
    structured = getattr(answered, "structured_content", None)
    if structured is not None:
        return json.dumps(structured)
    parts = [
        str(getattr(block, "text", ""))
        for block in getattr(answered, "content", []) or []
        if getattr(block, "text", None)
    ]
    return "\n".join(parts) if parts else str(answered)


def build_pipeline_index(plan: dict[str, Any]) -> dict[str, Any]:
    """Hand the pipeline its documents, and report what the store said afterwards (P17.5).

    The same relation as a conversation with a different verb (Q18): an action on the
    pipeline's node, dispatched by **kind** rather than by what a carrier looks like, and
    reached through the entry point the system prompt guarantees -- `build_index()`, in the
    pipeline's own package, unique there or refused.

    It is a **write into somebody's store**, which is why it happens only because a person
    pressed a button and never as a consequence of drawing a graph (P11).

    What comes back is what the store will say about itself: its own type, and how much it
    holds **if it answers `len`** -- Python's own question, never a library's internals, and
    never the number of documents we sent it. Counting the input would report our side of
    the exchange as though it were the store's, which is the one thing this verb must not do.
    """
    context, failure = _import_all(plan)
    if failure is not None:
        return {"ok": False, "status": "broken", "detail": failure, "held": ""}

    if str(plan.get("how", "")) != "rag.build_index":
        return {
            "ok": False,
            "status": "unproven",
            "detail": f"{plan.get('how', '') or 'this node'} holds no index to write into",
            "held": "",
        }

    build, refusal = _named_in(context, plan, "build_index")
    if build is None:
        return {"ok": False, "status": "unproven", "detail": refusal, "held": ""}

    try:
        store = build()
    except Exception as exc:
        return {
            "ok": False,
            "status": "broken",
            "detail": f"indexing raised {type(exc).__name__}: {exc}",
            "held": "",
        }

    return {
        "ok": True,
        "status": "green",
        "detail": f"the pipeline indexed into {type(store).__name__}",
        "held": _held_by(store),
    }


def _held_by(store: Any) -> str:
    """How much the store admits to holding, asked with Python's own question.

    `len` and nothing else. Reaching past it -- `store.store`, `_collection`, a client's
    count endpoint -- is reading a library's internals, and the rule for that is an entry in
    `kinds.TECHNOLOGIES` with the release it was written against. RAG deliberately has none,
    so a store that does not answer `len` is reported as not having said, which is true.
    """
    try:
        return str(len(store))
    except Exception:
        # A store that refuses the question is reported as not having answered it. Data,
        # never an exception: this verb's job is to say what happened, not to raise.
        return ""


def converse(plan: dict[str, Any]) -> int:
    """Hold one conversation with a node, for as long as questions keep arriving (P17.1).

    Unlike every other `ask` here, this one does not answer and exit -- it stays. The reason
    is Q19: the conversation's memory belongs to the project, and an in-memory checkpointer
    only works while the memory is still there. A process per turn would quietly turn a
    dialogue into a series of strangers.

    Two streams, and keeping them apart is the same rule this codebase already applies one
    level up: **stdout carries the events and nothing else.** The project may print whatever
    it likes, and it would otherwise land in the middle of a line the reader is parsing --
    so `sys.stdout` is pointed at stderr for the duration, and events go to the handle that
    was stdout when we started.
    """
    events = sys.stdout
    sys.stdout = sys.stderr  # the project's own printing, kept out of the stream

    def emit(event: dict[str, Any]) -> None:
        events.write(json.dumps(event) + "\n")
        events.flush()

    context, failure = _import_all(plan)
    if failure is not None:
        emit({"type": "failed", "detail": failure})
        return 0

    dotted = str(plan.get("carrier", ""))
    ask, refusal = _way_in(context, plan)
    if ask is None:
        emit({"type": "failed", "detail": refusal})
        return 0

    emit({"type": "ready", "detail": refusal, "carrier": dotted})

    # End of input is the end of the conversation: the caller closes the pipe to say so,
    # which is why nothing here needs a "goodbye" message anybody could forget to send.
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            asked = json.loads(line)
        except json.JSONDecodeError:
            emit({"type": "failed", "detail": "that question did not arrive whole"})
            continue
        text = str(asked.get("say", ""))
        emit({"type": "asked", "text": text})
        try:
            answered = ask(text)
        except Exception as exc:
            # Data, never an exception: a question that broke the agent is an answer about
            # the agent, and the conversation survives it.
            emit(
                {
                    "type": "failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
            continue
        emit({"type": "answer", "text": _spoken(answered)})
    return 0


#: Which conversation each way in is, keyed by the `converses` value its kind names.
#:
#: A kind opts in by naming one of these; nothing here is chosen by looking at a carrier.
#: Both are **somebody else's convention that we follow**, never one we invented: the first
#: is LangGraph's own way of being asked, the second is the entry point the system prompt
#: requires a generated pipeline to expose -- which is what makes it a guarantee rather than
#: a hope.
def _way_in(context: Context, plan: dict[str, Any]) -> tuple[Callable[[str], Any] | None, str]:
    """How this node is asked things, or why it cannot be.

    Dispatch is by **kind**, never by sniffing what the carrier looks like. Calling anything
    that happens to be callable would cheerfully construct a class and report its `repr` as
    an answer -- which is the failure mode this codebase minds most: a button that appears to
    work.
    """
    how = str(plan.get("how", ""))
    dotted = str(plan.get("carrier", ""))

    # Why an entry point and not the compiled graph itself: **the library cannot be asked
    # this.** A LangGraph agent's input is the project's own state contract -- the reference
    # agent's schema requires `question`, `notes`, `answer` and `steps`, all four -- so there
    # is no general way to put a sentence into it, and picking a field would be a guess
    # dressed as a convention. Measured before it was decided: the obvious
    # `{"messages": [...]}` shape failed against the reference project with `KeyError`.
    if how == "langgraph.ask":
        entry, refusal = _named_in(context, plan, "ask")
        return entry, refusal or "the agent is listening"

    if how == "rag.ask":
        entry, refusal = _named_in(context, plan, "answer")
        return entry, refusal or "the pipeline is listening"

    if how:
        return None, f"{how!r} is not a conversation this build knows how to have"
    return None, f"{dotted or 'this node'} is not something that can be talked to"


def _named_in(
    context: Context, plan: dict[str, Any], name: str
) -> tuple[Callable[..., Any] | None, str]:
    """The one function the node exposes under an agreed name, or why there is not one.

    An agreed name and not a guessed one: the system prompt requires it, so generated code
    has it, and a project that answers under some other name is told so rather than being
    searched for something that looks close enough.

    Looked for **inside the node**, not across the project. The probe imports every module
    there is, tests included (Q12), and a suite that defines its own `ask` helper is
    ordinary -- searching the whole project would find it and refuse over a collision that
    is not one. The node is a group whose carrier is a package, so what belongs to it is
    what lives under that package.

    **Unique or nothing** within it, the same rule `_compiled_graph` follows. A tie is not
    something to break by import order: an agent's step function and its entry point can
    easily share a word, and calling the wrong one would look like an answer.
    """
    inside = str(plan.get("carrier", ""))
    found = {
        f"{module_name}.{name}": candidate
        for module_name, module in context.modules.items()
        if module_name == inside or module_name.startswith(f"{inside}.")
        if callable(candidate := getattr(module, name, None))
    }
    if not found:
        return None, f"{inside or 'this project'} exposes no {name}(question) to ask"
    if len(found) > 1:
        return None, f"more than one {name}(question) in {inside}: {', '.join(sorted(found))}"
    return next(iter(found.values())), ""


def _spoken(answered: Any) -> str:
    """What the node said, as text.

    Deliberately shallow: a string is the answer, and anything else is shown as what it is.
    Reaching into an object to find "the real" answer means knowing a library's shape, and
    that knowledge belongs to a node kind (P17.2) rather than to this generic path -- where
    it would be a guess dressed as a convention.
    """
    if isinstance(answered, str):
        return answered
    # LangGraph answers with the whole state, and the reply is the last message in it. Read
    # rather than assumed: a state with no messages is shown as what it is instead of being
    # reached into until something comes out.
    if isinstance(answered, dict):
        # The entry point may hand back the whole final state rather than a sentence, and the
        # prompt names the field the reply is in. Read, not searched for: a state without it
        # is shown as what it is instead of being rummaged through until a string falls out.
        reply = answered.get("answer")
        if isinstance(reply, str) and reply:
            return reply

    messages = answered.get("messages") if isinstance(answered, dict) else None
    if isinstance(messages, list) and messages:
        last = messages[-1]
        content = getattr(last, "content", None)
        if content is None and isinstance(last, dict):
            content = last.get("content")
        if isinstance(content, str):
            return content
    return repr(answered)


def _import_all(plan: dict[str, Any]) -> tuple[Context, str | None]:
    """The project's modules, imported once. The first failure is the whole answer."""
    sys.path.insert(0, plan["project"])

    context = Context()
    for name in plan.get("modules", []):
        try:
            context.modules[name] = importlib.import_module(name)
        except Exception as exc:
            return context, f"{name} did not import: {type(exc).__name__}: {exc}"
    return context, None


def main() -> int:
    # The first line, not the whole stream: every other ask sends one line and closes, but a
    # conversation keeps its stdin open for the questions that follow, and reading to end of
    # input would wait for a close that is never coming.
    first = sys.stdin.readline()
    try:
        plan = json.loads(first)
    except json.JSONDecodeError:
        plan = json.loads(first + sys.stdin.read())

    if plan.get("ask") == "converse":
        return converse(plan)
    if plan.get("ask") == "application":
        print(json.dumps(locate_application(plan)))
        return 0
    if plan.get("ask") == "queue":
        print(json.dumps(locate_queue(plan)))
        return 0
    if plan.get("ask") == "queue_ready":
        print(json.dumps(ping_queue(plan)))
        return 0
    if plan.get("ask") == "mcp_inspect":
        print(json.dumps(inspect_server(plan)))
        return 0
    if plan.get("ask") == "index":
        print(json.dumps(build_pipeline_index(plan)))
        return 0
    if plan.get("ask") == "mcp_call":
        print(json.dumps(call_server_tool(plan)))
        return 0
    results, flow, completeness = run_plan_with_flow(plan)
    print(json.dumps({"results": results, "flow": flow, "completeness": completeness}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
