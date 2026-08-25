"""Agent integration: two inputs, one set of rules, and a record of what goes wrong.

§3's claim is that chat and blueprint differ **only in how detailed the request is**. That
is checkable, and the check is the first test here: the same system prompt, byte for byte,
whichever input produced the brief. The moment a blueprint could change the rules,
parseability would depend on which blueprint was picked -- which is precisely the failure
§3 was written to prevent.

The second thing this file pins is the `kind` registry (Q2). `kinds.REGISTRY` is the
authority and the prompt's table is the same list written for the agent; a drift between
them is how an agent ends up told about a kind the checker cannot dispatch on, so it fails
here rather than in generated code.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from aibuilder_core.agent import (
    AGENT_LOG_PATH,
    build_brief,
    failure_modes,
    prompt_kinds,
    prompt_path,
    record_outcome,
    system_prompt,
)
from aibuilder_core.api import agent_blueprints, agent_brief, read_graph
from aibuilder_core.catalog import find_catalog, list_blueprints, load_blueprint
from aibuilder_core.kinds import REGISTRY

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"
MIS_ANNOTATED = Path(__file__).parent / "fixtures" / "mis-annotated"

SPEC = """# Cursor Pagination — BLUEPRINT

> Pages that stay correct while rows are being inserted underneath them.

## 5. The contract

The endpoint returns `items` and an opaque `next_cursor`.
"""

DIAGRAM = "graph TD\n  client --> endpoint\n"


@pytest.fixture(autouse=True)
def _no_ambient_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test says which catalog it means.

    Nothing is discovered any more, but the environment variable still points somewhere on
    a machine that has one set -- and a test that silently read it would pass or fail for
    reasons that have nothing to do with the code.
    """
    monkeypatch.delenv("AIBUILDER_BLUEPRINTS", raising=False)


def catalog(tmp_path: Path, text: str = SPEC) -> Path:
    """A catalog with one blueprint in it, and the diagram that must not travel."""
    root = tmp_path / "catalog"
    entry = root / "blueprints" / "cursor-pagination"
    entry.mkdir(parents=True)
    (entry / "blueprint.md").write_text(text)
    (entry / "architecture.mmd").write_text(DIAGRAM)
    return root


def project(tmp_path: Path, source: Path = EXAMPLE) -> Path:
    root = tmp_path / "project"
    shutil.copytree(source, root)
    return root


# -- one set of rules ------------------------------------------------------------------


def test_both_inputs_carry_the_same_rules(tmp_path: Path) -> None:
    """§3: the annotation rules live in the system prompt, not in the blueprints."""
    chat = build_brief(EXAMPLE, request="add a health endpoint")
    blueprint = build_brief(
        EXAMPLE,
        request="add cursor pagination",
        blueprint="cursor-pagination",
        catalog=catalog(tmp_path),
    )

    assert chat.system_prompt == blueprint.system_prompt == system_prompt()
    assert (chat.source, blueprint.source) == ("chat", "blueprint")


def test_a_blueprint_full_of_markup_still_does_not_set_the_rules(tmp_path: Path) -> None:
    """A blueprint that talks about `bp` is a catalog hygiene problem and nothing more."""
    root = catalog(tmp_path, SPEC + "\n@node(id='pagination', kind='invented.kind')\n")

    brief = build_brief(EXAMPLE, blueprint="cursor-pagination", catalog=root)

    assert brief.blueprint is not None and brief.blueprint.carries_markup
    assert brief.system_prompt == system_prompt()
    assert "the markup rules in force are the ones in the system prompt" in brief.instructions


def test_the_diagram_beside_a_blueprint_is_never_handed_over(tmp_path: Path) -> None:
    """§3: the graph is built from annotated code, never from a blueprint's diagram."""
    brief = build_brief(EXAMPLE, blueprint="cursor-pagination", catalog=catalog(tmp_path))

    assert "graph TD" not in brief.instructions
    assert brief.blueprint is not None and brief.blueprint.text is not None
    assert "next_cursor" in brief.blueprint.text


def test_the_prompt_states_exactly_the_registry(tmp_path: Path) -> None:
    """Q2: a kind is added deliberately, in the registry and in the prompt, or not at all."""
    assert set(prompt_kinds()) == set(REGISTRY)


def test_every_registered_kind_reaches_the_agent() -> None:
    brief = build_brief(EXAMPLE, request="add a route")

    for name in REGISTRY:
        assert f"`{name}`" in brief.instructions
    assert brief.kinds == tuple(sorted(REGISTRY))


def test_the_prompt_is_found_where_it_is_written() -> None:
    """One file. A built-in fallback copy would be a second set of rules in force."""
    assert prompt_path().name == "system-prompt-claude-code.md"
    assert prompt_path().parent.name == "prompts"
    assert "The markup layer is inert at runtime" in system_prompt()


# -- the brief -------------------------------------------------------------------------


def test_the_brief_shows_the_project_as_it_stands() -> None:
    """The agent audits before it writes; ids already taken are ids it must not reuse."""
    brief = build_brief(EXAMPLE, request="add a second router")

    assert [node.id for node in brief.outline]
    assert "api" in {node.id for node in brief.outline}
    assert "health" in brief.instructions


def test_a_project_that_does_not_exist_yet_is_stated_as_empty(tmp_path: Path) -> None:
    brief = build_brief(tmp_path / "nothing-here", request="create a FastAPI service")

    assert brief.project_exists is False
    assert brief.outline == ()
    assert "does not exist yet" in brief.instructions


def test_a_blueprint_alone_is_a_complete_request(tmp_path: Path) -> None:
    brief = build_brief(EXAMPLE, blueprint="cursor-pagination", catalog=catalog(tmp_path))

    assert brief.source == "blueprint"
    assert "Apply the blueprint below" in brief.instructions


def test_a_brief_with_nothing_to_act_on_is_refused() -> None:
    with pytest.raises(ValueError, match="request"):
        build_brief(EXAMPLE)


def test_an_unknown_blueprint_is_refused_not_downgraded_to_chat(tmp_path: Path) -> None:
    """The caller asked for a specification; an unaccompanied sentence is not that."""
    root = catalog(tmp_path)

    with pytest.raises(ValueError, match="no blueprint"):
        build_brief(EXAMPLE, request="do it", blueprint="not-a-blueprint", catalog=root)

    refused = agent_brief(str(EXAMPLE), "do it", "not-a-blueprint", str(root))
    assert refused["brief"] is None and refused["refused"]


# -- the catalog -----------------------------------------------------------------------


def test_a_catalog_is_listed_without_its_texts(tmp_path: Path) -> None:
    listed = list_blueprints(catalog(tmp_path))

    assert [blueprint.id for blueprint in listed] == ["cursor-pagination"]
    assert listed[0].text is None
    assert listed[0].title == "Cursor Pagination — BLUEPRINT"


def test_a_published_index_supplies_the_titles(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    (root / "catalogue.json").write_text(
        json.dumps({"items": [{"id": "cursor-pagination", "title": "Cursor Pagination"}]})
    )

    assert list_blueprints(root)[0].title == "Cursor Pagination"


def test_a_broken_index_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    (root / "catalogue.json").write_text("{not json")

    assert list_blueprints(root)[0].id == "cursor-pagination"


def test_a_pointer_that_is_not_a_catalog_answers_nothing(tmp_path: Path) -> None:
    """It must not fall through to some other catalog the caller did not name."""
    assert find_catalog(tmp_path / "empty") is None
    assert list_blueprints(tmp_path / "empty") == []
    assert load_blueprint("cursor-pagination", tmp_path / "empty") is None


def test_no_catalog_is_an_answer_not_an_error(tmp_path: Path) -> None:
    payload = agent_blueprints(str(tmp_path / "empty"))

    assert payload["catalog"] is None and payload["blueprints"] == []


# -- the failure log -------------------------------------------------------------------


def test_a_generation_that_misses_is_recorded_with_its_addresses(tmp_path: Path) -> None:
    """Soft mode's whole purpose: collect the misses instead of refusing the output (§7)."""
    root = project(tmp_path, MIS_ANNOTATED)

    entry = record_outcome(root, source="chat", request="add an endpoint")

    assert entry["diagnostics"]
    assert all(diagnostic["address"] for diagnostic in entry["diagnostics"])
    assert (root / AGENT_LOG_PATH).is_file()


def test_an_entry_addresses_the_conversation_turn_it_came_from(tmp_path: Path) -> None:
    """Q16: the agent is driven as a chat, so an entry is a turn rather than a whole input.

    This narrowed what the log is -- an entry used to be replayable on its own and is now a
    point inside a discussion that carried state the entry does not hold. Recording the
    address of that turn is the honest version of the change: the entry points into a
    transcript instead of pretending to be self-contained.
    """
    root = project(tmp_path, MIS_ANNOTATED)

    entry = record_outcome(
        root,
        source="chat",
        request="add an endpoint",
        session="62ffbbf8-d2e9-439d-bec2-f39b0c7db1c5",
        turn=3,
    )

    assert entry["session"] == "62ffbbf8-d2e9-439d-bec2-f39b0c7db1c5"
    assert entry["turn"] == 3


def test_a_generation_driven_by_hand_says_so_rather_than_omitting_it(tmp_path: Path) -> None:
    """Absent is an answer, not a missing field. Nothing drove this from a session."""
    root = project(tmp_path, MIS_ANNOTATED)

    entry = record_outcome(root, source="chat", request="add an endpoint")

    assert entry["session"] is None
    assert entry["turn"] is None


def test_the_failure_modes_are_tallied_across_generations(tmp_path: Path) -> None:
    root = project(tmp_path, MIS_ANNOTATED)

    record_outcome(root, source="chat", request="one")
    record_outcome(root, source="blueprint", request="two", blueprint="cursor-pagination")
    tally = failure_modes(root)

    assert (tally["generations"], tally["clean"]) == (2, 0)
    assert tally["codes"]
    assert tally["codes"][0]["count"] >= 2
    assert tally["codes"] == sorted(tally["codes"], key=lambda code: -int(code["count"]))


def test_a_clean_generation_records_no_failures(tmp_path: Path) -> None:
    root = project(tmp_path)

    entry = record_outcome(root, source="chat", request="nothing to fix")

    assert entry["diagnostics"] == []
    assert failure_modes(root)["clean"] == 1


def test_nothing_is_read_out_of_the_log(tmp_path: Path) -> None:
    """The log is evidence about the agent, never a source the graph draws from (I-1)."""
    root = project(tmp_path)
    before = read_graph(root)

    record_outcome(root, source="chat", request="one")
    with_log = read_graph(root)
    (root / AGENT_LOG_PATH).unlink()

    assert before == with_log == read_graph(root)


def test_a_truncated_log_line_does_not_cost_the_record(tmp_path: Path) -> None:
    root = project(tmp_path, MIS_ANNOTATED)
    record_outcome(root, source="chat", request="one")
    with (root / AGENT_LOG_PATH).open("a") as handle:
        handle.write('{"at": "trunca\n')

    assert failure_modes(root)["generations"] == 1


def test_an_empty_log_tallies_to_nothing(tmp_path: Path) -> None:
    assert failure_modes(tmp_path)["generations"] == 0


# -- over the wire ---------------------------------------------------------------------


def request(method: str, **params: Any) -> dict[str, Any]:
    from aibuilder_core.__main__ import handle_line

    line = handle_line(json.dumps({"id": 1, "method": method, "params": params}))
    assert line is not None
    return dict(json.loads(line))


def test_the_brief_answers_over_the_protocol(tmp_path: Path) -> None:
    response = request(
        "agent.brief",
        project=str(EXAMPLE),
        request="add cursor pagination",
        blueprint="cursor-pagination",
        catalog=str(catalog(tmp_path)),
    )

    assert response["ok"] is True
    assert response["result"]["brief"]["source"] == "blueprint"


def test_a_brief_without_a_project_is_a_parameter_error() -> None:
    response = request("agent.brief", request="add a route")

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_params"
