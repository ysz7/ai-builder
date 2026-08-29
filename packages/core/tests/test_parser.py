"""The parser reads what the code says, and nothing else.

Two things are being defended here. That the graph is *derived* -- every fact traced to a
syntax node, never to a convention or a guess (I-1). And that reading a project never runs
it: a parser that imported would execute a stranger's module to draw a picture of it, and
would go blind exactly when a project is broken and the graph matters most.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from framestack_core.parser import parse_project, parse_source


def parse(source: str) -> object:
    return parse_source(textwrap.dedent(source).lstrip())


def write_project(root: Path, files: dict[str, str]) -> Path:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return root


# -- carriers and zones ----------------------------------------------------------


def test_a_decorated_function_becomes_a_node_with_its_carrier() -> None:
    graph = parse(
        """
        from bp import editable, node

        @node(id="health", kind="fastapi.route", title="Health")
        @editable(signature_locked=True)
        def health() -> dict[str, str]:
            return {"status": "ok"}
        """
    )

    node = graph.node("health")
    assert node is not None
    assert (node.kind, node.title) == ("fastapi.route", "Health")
    assert node.carrier == "module.health"
    assert node.carrier_type == "function"
    assert node.zone == "editable"
    assert node.location.file == "module.py"
    assert node.location.start_line == 3


def test_a_decorated_class_becomes_a_node() -> None:
    graph = parse(
        """
        from bp import node

        @node(id="settings", kind="fastapi.settings")
        class ApiSettings:
            pass
        """
    )

    node = graph.node("settings")
    assert node is not None
    assert node.carrier_type == "class"
    assert node.carrier == "module.ApiSettings"


def test_an_editable_signature_is_locked_unless_it_says_otherwise() -> None:
    """An omitted argument must not quietly turn the contract optional."""
    graph = parse(
        """
        from bp import editable

        @editable()
        def rank(items: list[int]) -> list[int]:
            return items
        """
    )

    assert graph.functions[0].signature_locked is True


def test_an_unlocked_signature_is_reported_as_unlocked() -> None:
    graph = parse(
        """
        from bp import editable

        @editable(signature_locked=False)
        def rank(items: list[int]) -> list[int]:
            return items
        """
    )

    assert graph.functions[0].signature_locked is False


def test_unmarked_functions_are_reported_not_dropped() -> None:
    """The gate's rule is "no unmarked functions"; it cannot check what it never sees."""
    graph = parse(
        """
        from bp import generated

        @generated()
        def wired() -> None:
            pass

        def forgotten() -> None:
            pass
        """
    )

    zones = {function.path: function.zone for function in graph.functions}
    assert zones == {"module.wired": "generated", "module.forgotten": None}


def test_methods_of_a_class_carrier_are_classified_too() -> None:
    graph = parse(
        """
        from bp import editable, node

        @node(id="chunker", kind="fastapi.settings")
        class Chunker:
            @editable()
            def chunk(self, text: str) -> list[str]:
                return [text]
        """
    )

    assert [function.path for function in graph.functions] == ["module.Chunker.chunk"]
    assert graph.functions[0].zone == "editable"


def test_signatures_are_read_in_full() -> None:
    graph = parse(
        """
        from bp import editable

        @editable()
        def search(q: str, *, limit: int = 10, **extra: str) -> list[str]:
            return []
        """
    )

    rendered = graph.functions[0].signature.render()

    assert rendered == "(q: str, limit: int = 10, **extra: str) -> list[str]"


# -- knobs -----------------------------------------------------------------------


def test_knobs_are_read_with_their_metadata_and_address() -> None:
    graph = parse(
        """
        from typing import Annotated

        from bp import Param, node

        @node(id="settings", kind="fastapi.settings")
        class ApiSettings:
            timeout_s: Annotated[int, Param(min=1, max=120, label="Timeout")] = 30
            level: Annotated[str, Param(widget="select", choices=("info", "debug"))] = "info"
        """
    )

    timeout, level = graph.node("settings").knobs

    assert (timeout.name, timeout.type, timeout.default) == ("timeout_s", "int", "30")
    assert (timeout.min, timeout.max, timeout.label) == (1, 120, "Timeout")
    assert timeout.widget is None  # the type picks the control (architecture §5.5)
    assert timeout.location.object == "ApiSettings.timeout_s"

    assert (level.widget, level.choices) == ("select", ("info", "debug"))


def test_an_annotated_field_without_param_is_not_a_knob() -> None:
    """`Annotated` is a general-purpose type tool; only `Param` declares a knob."""
    graph = parse(
        """
        from typing import Annotated

        from bp import node

        @node(id="settings", kind="fastapi.settings")
        class ApiSettings:
            name: Annotated[str, "not ours"] = "x"
            plain: int = 5
        """
    )

    assert graph.node("settings").knobs == ()


def test_a_computed_bound_is_reported_as_absent_rather_than_invented() -> None:
    graph = parse(
        """
        from typing import Annotated

        from bp import Param, node

        LIMIT = 120

        @node(id="settings", kind="fastapi.settings")
        class ApiSettings:
            timeout_s: Annotated[int, Param(min=1, max=LIMIT)] = 30
        """
    )

    knob = graph.node("settings").knobs[0]
    assert knob.min == 1
    assert knob.max is None


# -- groups ----------------------------------------------------------------------


def test_group_members_resolve_across_modules_by_reference(tmp_path: Path) -> None:
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/health.py": """
                from bp import node

                @node(id="health", kind="fastapi.route")
                def health() -> dict[str, str]:
                    return {}
            """,
            "app/__node__.py": """
                from bp import group_node

                from app.health import health

                service = group_node(id="api", kind="fastapi.service", members=[health])
            """,
        },
    )

    graph = parse_project(root)
    service = graph.node("api")

    assert service.members == ("health",)
    assert service.carrier_type == "group"
    # The carrier is the subsystem, not the file that happens to declare it.
    assert service.carrier == "app"
    assert [node.id for node in graph.top_level] == ["api"]


def test_a_single_carrier_node_may_declare_members() -> None:
    """Containment is not carriership: a router has one carrier and still holds routes."""
    graph = parse(
        """
        from bp import editable, generated, node

        @node(id="route", kind="fastapi.route")
        @editable()
        def list_users() -> list[str]:
            return []

        @node(id="router", kind="fastapi.router", members=[list_users])
        @generated()
        def users_router() -> object:
            return list_users
        """
    )

    assert graph.node("router").members == ("route",)
    assert [node.id for node in graph.top_level] == ["router"]


def test_membership_is_declared_not_inferred_from_references() -> None:
    """A reference is not a claim. Only `members=` makes one node the parent of another."""
    graph = parse(
        """
        from bp import generated, node

        @node(id="route", kind="fastapi.route")
        def list_users() -> list[str]:
            return []

        @node(id="router", kind="fastapi.router")
        @generated()
        def users_router() -> object:
            return list_users
        """
    )

    assert graph.node("router").members == ()
    assert {node.id for node in graph.top_level} == {"router", "route"}
    # The relation is still visible -- as what it actually is, an edge.
    assert [(edge.source, edge.target) for edge in graph.edges] == [("router", "route")]


def test_relative_imports_resolve(tmp_path: Path) -> None:
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/health.py": """
                from bp import node

                @node(id="health", kind="fastapi.route")
                def health() -> dict[str, str]:
                    return {}
            """,
            "app/__node__.py": """
                from bp import group_node

                from .health import health

                service = group_node(id="api", kind="fastapi.service", members=[health])
            """,
        },
    )

    assert parse_project(root).node("api").members == ("health",)


def test_aliased_markup_imports_are_followed() -> None:
    graph = parse(
        """
        from bp import node as declare

        @declare(id="health", kind="fastapi.route")
        def health() -> None:
            pass
        """
    )

    assert graph.node("health") is not None


# -- edges -----------------------------------------------------------------------


def test_an_edge_carries_the_target_signature_as_its_contract() -> None:
    graph = parse(
        """
        from bp import editable, generated, node

        @node(id="route", kind="fastapi.route")
        @editable()
        def list_users(limit: int = 10) -> list[str]:
            return []

        @node(id="router", kind="fastapi.router")
        @generated()
        def users_router() -> object:
            return list_users
        """
    )

    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert (edge.source, edge.target) == ("router", "route")
    assert edge.contract == "(limit: int = 10) -> list[str]"


def test_a_name_bound_to_a_carrier_still_resolves_to_it(tmp_path: Path) -> None:
    """`settings = ApiSettings()` is how a settings node is actually reached."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/settings.py": """
                from bp import node

                @node(id="settings", kind="fastapi.settings")
                class ApiSettings:
                    page_size: int = 25

                settings = ApiSettings()
            """,
            "app/routes.py": """
                from bp import editable, node

                from app.settings import settings

                @node(id="route", kind="fastapi.route")
                @editable()
                def list_users() -> int:
                    return settings.page_size
            """,
        },
    )

    graph = parse_project(root)

    assert [(edge.source, edge.target, edge.contract) for edge in graph.edges] == [
        ("route", "settings", "ApiSettings")
    ]


def test_a_reference_to_something_that_is_not_a_node_draws_no_edge() -> None:
    graph = parse(
        """
        from bp import generated, node

        def helper() -> int:
            return 1

        @node(id="router", kind="fastapi.router")
        @generated()
        def users_router() -> int:
            return helper()
        """
    )

    assert graph.edges == ()


def test_field_names_are_not_mistaken_for_references() -> None:
    """In `settings.page_size` the reference is `settings`; `page_size` is not a name."""
    graph = parse(
        """
        from bp import generated, node

        @node(id="a", kind="fastapi.route")
        def page_size() -> int:
            return 1

        @node(id="b", kind="fastapi.router")
        @generated()
        def router(config: object) -> int:
            return config.page_size
        """
    )

    assert graph.edges == ()


# -- robustness ------------------------------------------------------------------


def test_the_parser_does_not_import_the_project(tmp_path: Path) -> None:
    """A module that would blow up on import still parses. Reading is not running."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/boom.py": """
                from bp import node

                raise RuntimeError("importing this would fail")

                @node(id="boom", kind="fastapi.route")
                def boom() -> None:
                    pass
            """,
        },
    )

    graph = parse_project(root)

    assert graph.node("boom") is not None
    assert graph.unparsed == ()


def test_a_file_that_will_not_parse_is_reported_and_the_rest_survives(tmp_path: Path) -> None:
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/broken.py": "def (:\n",
            "app/good.py": """
                from bp import node

                @node(id="good", kind="fastapi.route")
                def good() -> None:
                    pass
            """,
        },
    )

    graph = parse_project(root)

    assert graph.node("good") is not None
    assert [location.file for location in graph.unparsed] == ["app/broken.py"]


def test_a_node_without_a_usable_id_still_reaches_the_graph() -> None:
    """It is exactly the case the gate must report, so it needs a handle to be reported by."""
    graph = parse(
        """
        from bp import node

        @node(kind="fastapi.route")
        def nameless() -> None:
            pass
        """
    )

    assert [node.id for node in graph.nodes] == ["<unidentified:module.nameless>"]


def test_caches_and_environments_are_not_read(tmp_path: Path) -> None:
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/.venv/lib/vendored.py": """
                from bp import node

                @node(id="vendored", kind="fastapi.route")
                def vendored() -> None:
                    pass
            """,
        },
    )

    assert parse_project(root).nodes == ()


# -- the example project, whole --------------------------------------------------

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"
SNAPSHOT = Path(__file__).parent / "data" / "fastapi_service_graph.json"


def test_the_example_project_produces_the_expected_graph() -> None:
    """The acceptance test for the parser (roadmap P2).

    A snapshot rather than a handful of assertions, because the thing being fixed is the
    *whole* shape -- ids, carriers, zones, knobs, members, contracts and every address.
    A change here is never incidental: either the example changed on purpose, or the
    parser started reading the same code differently. Regenerate with

        UPDATE_SNAPSHOTS=1 uv run pytest packages/core/tests/test_parser.py

    and read the diff before committing it.
    """
    import json
    import os

    graph = parse_project(EXAMPLE).to_dict()
    graph.pop("root")  # an absolute path; it says nothing about the graph

    # Compared as JSON, not as Python objects: JSON is the form the shell and the UI
    # actually receive, and it is where a tuple and a list stop being different things.
    serialized = json.dumps(graph, indent=2) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(serialized, encoding="utf-8")

    assert json.loads(serialized) == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_every_kind_in_the_example_is_registered() -> None:
    """An unregistered kind has no shape and no observable check -- it is a typo (§5.6)."""
    from framestack_core.kinds import is_registered

    unknown = [node.kind for node in parse_project(EXAMPLE).nodes if not is_registered(node.kind)]

    assert unknown == []


def test_the_example_has_no_unmarked_functions_inside_a_carrier() -> None:
    """The rule the gate enforces: unmarked *inside a carrier* is a forgotten mark (§4).

    Outside every carrier -- the project's own tests, its conftest -- a function needs no
    mark and gets none. The parser still sees those functions; they simply are not the
    graph's to classify.
    """
    from framestack_core.gate import check_graph

    unclassified = [
        diagnostic.location.object
        for diagnostic in check_graph(parse_project(EXAMPLE)).diagnostics
        if diagnostic.code == "function.unclassified"
    ]

    assert unclassified == []
