"""The static gate, and the one thing it must never do.

Most of this file is one test per acceptance check. The tests that matter most are at the
bottom: that a statically clean node is **not** green (I-5), and that every diagnostic
carries an address and a repair instruction -- because a diagnostic that says only what is
wrong turns "repair this" into a guess, and a guess breaks the neighbour (§9).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from aibuilder_core.diagnostics import CATALOGUE, Code, Severity
from aibuilder_core.gate import GateMode, check_graph
from aibuilder_core.parser import parse_project, parse_source
from aibuilder_core.verdict import Observation, Verdict

FIXTURE = Path(__file__).parent / "fixtures" / "mis-annotated"
EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def codes(source: str) -> list[str]:
    graph = parse_source(textwrap.dedent(source).lstrip())
    return [diagnostic.code for diagnostic in check_graph(graph).diagnostics]


# -- one test per acceptance check ------------------------------------------------


def test_a_node_without_a_literal_id_is_reported() -> None:
    assert Code.MISSING_ID.value in codes(
        """
        from bp import group_node, node

        @node(kind="fastapi.route")
        def nameless() -> None:
            pass

        service = group_node(id="api", kind="fastapi.service", members=[nameless])
        """
    )


def test_two_nodes_under_one_id_are_reported() -> None:
    assert Code.DUPLICATE_ID.value in codes(
        """
        from bp import group_node, node

        @node(id="dup", kind="fastapi.route")
        def first() -> None:
            pass

        @node(id="dup", kind="fastapi.route")
        def second() -> None:
            pass

        service = group_node(id="api", kind="fastapi.service", members=[first, second])
        """
    )


def test_an_unregistered_kind_is_reported() -> None:
    assert Code.UNREGISTERED_KIND.value in codes(
        """
        from bp import group_node, node

        @node(id="x", kind="fastapi.teleport")
        def handler() -> None:
            pass

        service = group_node(id="api", kind="fastapi.service", members=[handler])
        """
    )


def test_a_kind_on_the_wrong_sort_of_carrier_is_reported() -> None:
    assert Code.WRONG_CARRIER.value in codes(
        """
        from bp import group_node, node

        @node(id="x", kind="fastapi.route")
        class NotAFunction:
            pass

        service = group_node(id="api", kind="fastapi.service", members=[NotAFunction])
        """
    )


def test_a_node_nobody_claims_is_reported_as_top_level() -> None:
    """The top level holds groups only (Q4), so an unclaimed node is a violation."""
    assert Code.TOP_LEVEL_NOT_GROUP.value in codes(
        """
        from bp import node

        @node(id="orphan", kind="fastapi.route")
        def orphan() -> None:
            pass
        """
    )


def test_a_group_at_the_top_level_is_not_reported() -> None:
    assert (
        codes(
            """
        from bp import group_node

        service = group_node(id="api", kind="fastapi.service")
        """
        )
        == []
    )


def test_a_node_claimed_twice_is_reported() -> None:
    """Containment is a tree: a node has one parent, or the hierarchy is unresolvable."""
    assert Code.MULTIPLE_PARENTS.value in codes(
        """
        from bp import generated, group_node, node

        @node(id="route", kind="fastapi.route")
        def handler() -> None:
            pass

        @node(id="router", kind="fastapi.router", members=[handler])
        @generated()
        def router() -> None:
            pass

        service = group_node(
            id="api", kind="fastapi.service", members=[handler, router]
        )
        """
    )


def test_a_member_that_resolves_to_nothing_is_reported() -> None:
    assert Code.UNRESOLVED_MEMBER.value in codes(
        """
        from bp import group_node

        service = group_node(id="api", kind="fastapi.service", members=[ghost])
        """
    )


def test_an_unmarked_function_in_a_participating_file_is_reported() -> None:
    assert Code.UNCLASSIFIED_FUNCTION.value in codes(
        """
        from bp import group_node, node

        @node(id="route", kind="fastapi.route")
        def handler() -> None:
            pass

        def forgotten() -> None:
            pass

        service = group_node(id="api", kind="fastapi.service", members=[handler])
        """
    )


def test_a_file_with_no_markup_at_all_is_left_alone(tmp_path: Path) -> None:
    """Code outside a carrier is invisible to the graph, not illegal (§4)."""
    (tmp_path / "plain.py").write_text("def helper() -> int:\n    return 1\n")

    assert check_graph(parse_project(tmp_path)).diagnostics == ()


def test_a_knob_without_a_literal_default_is_reported() -> None:
    assert Code.UNADDRESSABLE_KNOB.value in codes(
        """
        from typing import Annotated

        from bp import Param, group_node, node

        @node(id="settings", kind="fastapi.settings")
        class Settings:
            timeout_s: Annotated[int, Param(min=1)]

        service = group_node(id="api", kind="fastapi.service", members=[Settings])
        """
    )


def test_a_file_that_will_not_parse_is_reported(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def (:\n")

    assert [d.code for d in check_graph(parse_project(tmp_path)).diagnostics] == [
        Code.UNPARSED_FILE.value
    ]


# -- the fixture, whole -----------------------------------------------------------


def test_every_check_has_an_instance_in_the_fixture() -> None:
    """The fixture is the gate's coverage test: a check with no instance is untested.

    All but one. Completeness (Q12) is not a static finding and cannot be: "the library
    holds something the graph does not declare" is answered by importing the project and
    asking, so no fixture on disk can produce it here. It is covered where it is decided,
    in the observation run.
    """
    reported = {d.code for d in check_graph(parse_project(FIXTURE)).diagnostics}

    assert reported == {code.value for code in Code} - {Code.UNDECLARED_CARRIER.value}


def test_the_good_example_passes_the_static_gate() -> None:
    assert check_graph(parse_project(EXAMPLE)).diagnostics == ()


# -- the diagnostic contract ------------------------------------------------------


def test_every_diagnostic_carries_an_address_and_a_repair() -> None:
    """§9: a problem carries an address, not just a description.

    This is what makes the request into chat "in `chunking.py` the carrier is gone,
    restore the boundary without touching the signature of `chunk()`" instead of
    "fix RAG".
    """
    for diagnostic in check_graph(parse_project(FIXTURE)).diagnostics:
        assert diagnostic.location.file
        assert diagnostic.location.object
        assert diagnostic.location.start_line >= 1
        assert diagnostic.rule
        assert diagnostic.repair
        assert diagnostic.message


def test_every_catalogue_entry_names_a_rule_and_a_repair() -> None:
    for code, entry in CATALOGUE.items():
        assert entry.rule, code
        assert entry.repair, code
        assert entry.severity in Severity


# -- soft mode --------------------------------------------------------------------


def test_soft_mode_flags_without_rejecting() -> None:
    """The v0 decision (§7): collecting the agent's real misses beats a perfect graph."""
    result = check_graph(parse_project(FIXTURE), mode=GateMode.SOFT)

    assert result.errors
    assert result.accepted is True


def test_hard_mode_refuses_the_same_code() -> None:
    """Deferred as a mode, not as a rewrite -- a demo will want it (§11)."""
    result = check_graph(parse_project(FIXTURE), mode=GateMode.HARD)

    assert result.accepted is False


# -- I-5, the invariant most likely to be quietly eroded --------------------------


def test_a_statically_clean_node_is_not_green() -> None:
    """Parseability alone must never report green. This is the anti-fitting rule."""
    result = check_graph(parse_project(EXAMPLE))

    assert result.diagnostics == ()
    assert set(result.verdicts.values()) == {Verdict.UNPROVEN.value}
    assert Verdict.GREEN.value not in result.verdicts.values()


def test_a_node_goes_green_only_with_a_passing_observation() -> None:
    graph = parse_project(EXAMPLE)
    observations = {"health": Observation(passed=True, check="http.route_answers")}

    verdicts = check_graph(graph, observations=observations).verdicts

    assert verdicts["health"] == Verdict.GREEN.value
    assert verdicts["users"] == Verdict.UNPROVEN.value


def test_a_failing_observation_is_broken_even_when_the_code_parses() -> None:
    """A node that parses perfectly and returns a 500 is red, and says why (P4's shape)."""
    graph = parse_project(EXAMPLE)
    observations = {"health": Observation(passed=False, check="http.route_answers", detail="500")}

    assert check_graph(graph, observations=observations).verdicts["health"] == (
        Verdict.BROKEN.value
    )


def test_a_flagged_node_cannot_be_green_even_if_it_answers() -> None:
    """Both conditions, not one: working code with a lying graph is not green either."""
    graph = parse_project(FIXTURE)
    observations = {
        "settings": Observation(passed=True, check="settings.load"),
    }

    assert check_graph(graph, observations=observations).verdicts["settings"] == (
        Verdict.BROKEN.value
    )
