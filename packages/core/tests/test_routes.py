"""The routes an `api/` package declares, and where each one sends the request (Phase 3).

Stated about `examples/full` and about copies of it, like every other test here. The
reference is the case the plan names last and cares about most: it serves its routes from a
table it built by hand, with no decorator anywhere, and the answer has to be an empty list
and no error rather than a failure.

Every test changes **one handler** and asserts the one thing that moves in the list. That is
possible because nothing here is configured: a route is a decorator with a path, and an arrow
is the names the body calls.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import ROUTES_SCHEMA, routes_read
from framestack_core.routes import Routes, read_routes

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"


def project(tmp_path: Path) -> Path:
    """A writable copy with a service worth reading: a router, a queue and a repository.

    The reference's own `api/` has no decorators at all, which is exactly why it is the
    fixture for "degrade, never error" and cannot be the fixture for anything else.
    """
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))

    # The example has both of these; this replaces them with the smallest versions the
    # tests below are stated about, so a change to the example cannot quietly change what
    # a route resolves to here.
    (root / "repositories").mkdir(exist_ok=True)
    for stale in (root / "repositories").glob("*.py"):
        stale.unlink()
    (root / "repositories" / "__init__.py").write_text(
        "def get_document(doc_id: str) -> dict:\n    return {}\n", encoding="utf-8"
    )
    (root / "api" / "routes").mkdir(exist_ok=True)
    for stale in (root / "api" / "routes").glob("*.py"):
        stale.unlink()
    (root / "api" / "routes" / "__init__.py").write_text("", encoding="utf-8")
    return root


def serve(root: Path, body: str) -> Routes:
    """Write one route module and read the service back."""
    (root / "api" / "routes" / "documents.py").write_text(body, encoding="utf-8")
    return read_routes(root, "api")


def only(answer: Routes) -> tuple[str, ...]:
    """The single route's targets, or `("?",)` where the handler resolved to nothing."""
    assert len(answer.routes) == 1, [route.path for route in answer.routes]
    route = answer.routes[0]
    return ("?",) if route.unsure else route.targets


# -- what is a route -------------------------------------------------------------------


def test_a_project_with_no_decorators_is_an_empty_list_and_not_a_failure() -> None:
    """The plan's fourth criterion, and the example proves it as it stands.

    `examples/full` builds its ASGI app around a table it wrote by hand -- no decorator
    anywhere in it. Nothing in this codebase recognises that, and the honest answer is
    nothing at all: not an error, and not a route guessed out of the table.
    """
    answer = read_routes(EXAMPLE, "api")
    assert answer.ok is True
    assert answer.routes == ()


def test_an_attribute_decorator_is_a_route(tmp_path: Path) -> None:
    """`@router.post("/documents")`. FastAPI and Starlette both write it this way."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
        '@router.post("/documents")\nasync def upload(body: dict) -> dict:\n    return {}\n',
    )
    assert [(route.method, route.path, route.handler) for route in answer.routes] == [
        ("POST", "/documents", "upload")
    ]


def test_a_bare_decorator_is_a_route(tmp_path: Path) -> None:
    """`@get("/x")`, imported from the framework. Litestar writes it this way."""
    answer = serve(
        project(tmp_path),
        'from litestar import get\n\n\n@get("/health")\n'
        "async def health() -> dict:\n    return {}\n",
    )
    assert [(route.method, route.path) for route in answer.routes] == [("GET", "/health")]


def test_every_verb_the_plan_names_is_read(tmp_path: Path) -> None:
    """Six verbs, and no framework named anywhere to recognise them."""
    body = "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
    for verb in ("get", "post", "put", "patch", "delete", "websocket"):
        body += f'@router.{verb}("/{verb}")\nasync def h_{verb}() -> dict:\n    return {{}}\n\n\n'
    answer = serve(project(tmp_path), body)
    assert {route.method for route in answer.routes} == {
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "WEBSOCKET",
    }


def test_a_method_that_shares_a_verb_s_name_is_not_a_route(tmp_path: Path) -> None:
    """`@cache.get("key")` is not a route, and the path literal is what says so.

    A route's path starts with a slash. Without that test every decorator named `get` in
    every project would appear in this list, which is the failure mode of reading a name.
    """
    answer = serve(
        project(tmp_path),
        'import cache\n\n\n@cache.get("documents")\ndef warmed() -> dict:\n    return {}\n',
    )
    assert answer.routes == ()


def test_a_path_that_is_not_a_literal_is_not_read(tmp_path: Path) -> None:
    """A path built at import time is one nobody reading the file could have known."""
    answer = serve(
        project(tmp_path),
        'from fastapi import APIRouter\n\nrouter = APIRouter()\nPREFIX = "/documents"\n\n\n'
        "@router.get(PREFIX)\nasync def listing() -> dict:\n    return {}\n",
    )
    assert answer.routes == ()


def test_a_module_that_cannot_be_parsed_costs_its_own_routes_and_nothing_else(
    tmp_path: Path,
) -> None:
    """One broken module does not take the service's other routes with it."""
    root = project(tmp_path)
    (root / "api" / "routes" / "broken.py").write_text("def (\n", encoding="utf-8")
    answer = serve(
        root,
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
        '@router.get("/ok")\nasync def fine() -> dict:\n    return {}\n',
    )
    assert [route.path for route in answer.routes] == ["/ok"]


# -- where the request goes ------------------------------------------------------------


def test_a_route_that_enqueues_shows_the_worker(tmp_path: Path) -> None:
    """The plan's first criterion. `HANDLERS` came from `worker/`, so the arrow does too."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nfrom worker import HANDLERS\n\n"
        'router = APIRouter()\n\n\n@router.post("/documents")\n'
        'async def upload(body: dict) -> dict:\n    HANDLERS["reindex"](body)\n'
        "    return {}\n",
    )
    assert only(answer) == ("worker",)


def test_a_route_that_only_reads_shows_postgres(tmp_path: Path) -> None:
    """The plan's second criterion. A repository is the boundary in front of the database."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nfrom repositories import get_document\n\n"
        'router = APIRouter()\n\n\n@router.get("/documents/{id}")\n'
        "async def read_one(id: str) -> dict:\n    return get_document(id)\n",
    )
    assert only(answer) == ("postgres",)


def test_a_route_that_calls_a_system_export_shows_that_system(tmp_path: Path) -> None:
    """`from agent import run` in the file, `run(...)` in the body. Two facts, one arrow."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nfrom agent import run\n\n"
        'router = APIRouter()\n\n\n@router.post("/chat")\n'
        "async def chat(message: str) -> str:\n    return run(message)\n",
    )
    assert only(answer) == ("agent",)


def test_several_targets_are_listed_rather_than_chosen_between(tmp_path: Path) -> None:
    """A handler that enqueues *and* reads does both, and the row says both."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nfrom repositories import get_document\n"
        "from worker import HANDLERS\n\n"
        'router = APIRouter()\n\n\n@router.get("/mixed/{id}")\n'
        'async def mixed(id: str) -> dict:\n    HANDLERS["echo"]({})\n'
        "    return get_document(id)\n",
    )
    assert only(answer) == ("postgres", "worker")


def test_an_ambiguous_handler_shows_the_unknown_and_does_not_guess(tmp_path: Path) -> None:
    """The plan's third criterion. `helper` came from nowhere this can attribute.

    It is somebody's local function or a framework's, and naming a target for it would be
    the wrong arrow -- which a person cannot un-read once the panel has asserted it.
    """
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
        "def helper(body: dict) -> None:\n    return None\n\n\n"
        '@router.post("/ping")\nasync def ping(body: dict) -> dict:\n    helper(body)\n'
        "    return {}\n",
    )
    assert only(answer) == ("?",)


def test_a_handler_that_calls_nothing_has_no_downstream_rather_than_an_unknown_one(
    tmp_path: Path,
) -> None:
    """Three states, not two. `?` about a function that plainly does nothing is manufactured
    doubt, and it is the same defect as a default verdict pointed the other way."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
        '@router.get("/health")\nasync def health() -> dict:\n    return {"ok": True}\n',
    )
    route = answer.routes[0]
    assert route.targets == ()
    assert route.unsure is False


def test_an_alias_still_points_at_the_package_it_came_from(tmp_path: Path) -> None:
    """`from agent import run as answer` renames it here, not there."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nfrom agent import run as reply\n\n"
        'router = APIRouter()\n\n\n@router.post("/chat")\n'
        "async def chat(message: str) -> str:\n    return reply(message)\n",
    )
    assert only(answer) == ("agent",)


def test_a_local_name_is_never_attributed(tmp_path: Path) -> None:
    """`db.execute(...)` where `db` is a parameter resolves to nothing, and says so."""
    answer = serve(
        project(tmp_path),
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
        '@router.get("/rows")\nasync def rows(db: object) -> dict:\n    db.execute("select 1")\n'
        "    return {}\n",
    )
    assert only(answer) == ("?",)


def test_removing_the_import_changes_the_arrow(tmp_path: Path) -> None:
    """A projection like every other: the arrow is the code, so editing the code moves it."""
    root = project(tmp_path)
    with_import = (
        "from fastapi import APIRouter\n\nfrom agent import run\n\n"
        'router = APIRouter()\n\n\n@router.post("/chat")\n'
        "async def chat(message: str) -> str:\n    return run(message)\n"
    )
    assert only(serve(root, with_import)) == ("agent",)
    assert only(serve(root, with_import.replace("from agent import run\n", ""))) == ("?",)


# -- what it refuses -------------------------------------------------------------------


def test_a_node_that_is_not_a_service_is_refused_rather_than_answered_empty(
    tmp_path: Path,
) -> None:
    """Two different sentences: "has no routes" and "cannot have routes".

    A caller told the first would go looking for the reason there are none.
    """
    answer = read_routes(project(tmp_path), "rag")
    assert answer.ok is False
    assert "not a service" in answer.detail


def test_a_node_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    answer = read_routes(project(tmp_path), "nowhere")
    assert answer.ok is False
    assert answer.routes == ()


def test_reading_a_service_twice_gives_the_same_answer(tmp_path: Path) -> None:
    """I-4 in the small: the same question three times, the same answer three times."""
    root = project(tmp_path)
    body = (
        "from fastapi import APIRouter\n\nfrom agent import run\n"
        "from repositories import get_document\n\nrouter = APIRouter()\n\n\n"
        '@router.post("/chat")\nasync def chat(m: str) -> str:\n    return run(m)\n\n\n'
        '@router.get("/documents/{id}")\nasync def one(id: str) -> dict:\n'
        "    return get_document(id)\n"
    )
    seen = {tuple(route.as_dict()["path"] for route in serve(root, body).routes) for _ in range(3)}
    assert len(seen) == 1


# -- the contract ----------------------------------------------------------------------


def test_the_payload_matches_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    serve(
        root,
        "from fastapi import APIRouter\n\nfrom agent import run\n\n"
        'router = APIRouter()\n\n\n@router.post("/chat")\n'
        "async def chat(m: str) -> str:\n    return run(m)\n",
    )
    validate(wire_form(routes_read(root, "api")), ROUTES_SCHEMA)


def test_a_refusal_matches_the_same_contract(tmp_path: Path) -> None:
    validate(wire_form(routes_read(project(tmp_path), "rag")), ROUTES_SCHEMA)
