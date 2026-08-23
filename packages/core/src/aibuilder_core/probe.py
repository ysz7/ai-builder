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
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any

__all__ = ["main", "run_plan"]

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

    results: list[Result] = []
    for node in nodes:
        check = CHECKS.get(node["check"])
        if check is None:
            results.append(
                Result(node["id"], node["check"], SKIPPED, "no runner for this check yet")
            )
            continue

        try:
            status, detail = check(context, node)
        except Exception:
            # The traceback is the diagnosis. Truncated because a node badge is not a
            # place to read a stack, and the tail is the part that names the cause.
            trace = traceback.format_exc().strip().splitlines()
            status, detail = FAILED, f"the check raised: {trace[-1]}"
        results.append(Result(node["id"], node["check"], status, detail))

    return [result.as_dict() for result in results]


def main() -> int:
    plan = json.loads(sys.stdin.read())
    print(json.dumps({"results": run_plan(plan)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
