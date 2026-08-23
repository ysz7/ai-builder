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
import traceback
from dataclasses import dataclass, field
from types import CodeType, FrameType
from typing import Any

__all__ = ["TestRun", "main", "observe_tests", "run_plan"]

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

    def as_dict(self) -> dict[str, str]:
        return {
            "node": self.node,
            "check": self.check,
            "status": self.status,
            "detail": self.detail,
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


CHECKS = {
    "http.app_serves": app_serves,
    "http.route_answers": route_answers,
    "http.router_mounts": router_mounts,
    "http.dependency_resolves": dependency_resolves,
    "settings.load": settings_load,
}


# -- the observed run: the project's own tests, with the carriers instrumented ----


@dataclass
class TestRun:
    """What the project's tests proved about each node, and nothing beyond that."""

    #: node id -> the tests that actually entered its carrier.
    fired: dict[str, set[str]] = field(default_factory=dict)
    #: test id -> "passed" / "failed" / "skipped", as pytest reported it.
    outcomes: dict[str, str] = field(default_factory=dict)
    ran: bool = False
    #: Why the suite did not run, when it did not. Never an absence of information.
    detail: str = ""

    def evidence(self, node: str) -> tuple[str, str] | None:
        """The verdict this run supports for one node, or `None` if it reached it not.

        A node is proven by a test that entered it **and passed**. A node entered only by
        failing tests is not proven -- and it is not merely unproven either, because
        something did run it and something did go wrong in that run.
        """
        tests = self.fired.get(node)
        if not tests:
            return None

        passing = sorted(test for test in tests if self.outcomes.get(test) == "passed")
        if passing:
            return PASSED, f"exercised by {len(passing)} passing test(s), e.g. {passing[0]}"

        failing = sorted(test for test in tests if self.outcomes.get(test) == "failed")
        if failing:
            return FAILED, f"every test that exercised this node failed, e.g. {failing[0]}"
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
        self.outcomes: dict[str, str] = {}
        self.current: str | None = None

    # the trace hook
    def trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if event == "call" and self.current is not None:
            node = self.codes.get(frame.f_code)
            if node is not None:
                self.fired.setdefault(node, set()).add(self.current)
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

    return TestRun(fired=recorder.fired, outcomes=recorder.outcomes, ran=True)


# -- the runner ------------------------------------------------------------------


def run_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    """Import what the plan names, run every check, and report one result per node."""
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
        return [Result(node["id"], node["check"], FAILED, detail).as_dict() for node in nodes]

    # The suite runs after the imports, deliberately: "exercised" means a test entered
    # the carrier, and a carrier that merely ran at import time was not tested.
    run = observe_tests(plan, carrier_codes(context, nodes))

    results: list[Result] = []
    for node in nodes:
        evidence = run.evidence(node["id"])
        if evidence is not None:
            status, detail = evidence
            results.append(Result(node["id"], "tests.exercised", status, detail))
            continue

        results.append(_direct(context, node, run))

    return [result.as_dict() for result in results]


def _direct(context: Context, node: dict[str, Any], run: TestRun) -> Result:
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
    return Result(node["id"], node["check"], status, detail)


def main() -> int:
    plan = json.loads(sys.stdin.read())
    print(json.dumps({"results": run_plan(plan)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
