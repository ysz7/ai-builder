"""MCP and tools (P15), and the completeness rule that came with them (Q12).

Three roles wear the same word, and the whole phase is the refusal to let them become one
kind. A server this project **consumes** is a declaration of how to reach a foreign
program; a tool this project **exposes** is its own code; a tool **bound to an agent** is a
function the agent may call. They are proven by three different things, and the tests here
are mostly about keeping those three apart:

* connecting is an **action** -- the checks never do it, and no flag makes them;
* a remote tool is **contents**, never a node, because there is no carrier for one;
* a tool is proven by a **run that entered it**, never by being registered;
* and nothing about a connection is ever **written down**, so a colleague who has not
  connected sees `unproven` rather than somebody else's yesterday.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from test_api import validate, wire_form

from framestack_core.api import (
    MCP_CALL_SCHEMA,
    MCP_INSPECT_SCHEMA,
    mcp_call,
    mcp_inspect,
    read_graph,
)
from framestack_core.diagnostics import Code
from framestack_core.kinds import REGISTRY, CarrierType
from framestack_core.observe import run_observations
from framestack_core.parser import parse_project
from framestack_core.runner import call_server_tool, inspect_server
from framestack_core.writer import set_knob

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "mcp-agent"

#: The node that owns the connection to the server this project consumes.
SERVER = "agent.notes"


def copy(tmp_path: Path, *, with_tests: bool = True) -> Path:
    root = tmp_path / "mcp-agent"
    shutil.copytree(
        EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack", ".pytest_cache")
    )
    if not with_tests:
        # A project whose own run proves nothing, so every node falls back to its direct
        # check -- which is where the "never connects" rule is actually visible.
        shutil.rmtree(root / "tests")
    return root


# -- the three roles are three kinds ---------------------------------------------


def test_the_three_roles_are_three_kinds_and_none_of_them_is_the_others() -> None:
    """One word, three things. Collapsing them is the design error the phase avoids."""
    consumed, exposed, bound = (
        REGISTRY["mcp.server"],
        REGISTRY["mcp.tool"],
        REGISTRY["langgraph.tool"],
    )

    assert consumed.carriers == {CarrierType.CLASS, CarrierType.MODULE}
    assert exposed.carriers == {CarrierType.FUNCTION}
    assert bound.carriers == {CarrierType.FUNCTION}
    assert len({consumed.check, exposed.check, bound.check}) == 3
    # The server we expose is a subsystem of its own; a consumed one is a member of
    # whatever consults it, and could not stand at the top level.
    assert REGISTRY["mcp.service"].top_level
    assert not consumed.top_level


def test_the_registry_names_types_never_vendors() -> None:
    """Unlimited servers, fixed vocabulary -- which is why Q2 is not reopened by MCP.

    Gmail, Slack and a hand-written server are `mcp.server` instances with different ids
    and different knob values. A user installing one costs the registry nothing.
    """
    assert not [name for name in REGISTRY if "gmail" in name or "slack" in name]


def test_the_example_puts_every_role_on_the_graph() -> None:
    graph = parse_project(EXAMPLE)
    kinds = {node.id: node.kind for node in graph.nodes}

    assert kinds[SERVER] == "mcp.server"
    assert kinds["agent.shout"] == "langgraph.tool"
    assert kinds["tools.summarize"] == "mcp.tool"
    assert kinds["tools"] == "mcp.service"


# -- a remote tool is contents, never a node (Q12) -------------------------------


def test_the_servers_tools_are_read_from_the_server_and_are_not_nodes() -> None:
    """The listing is contents of the node, and the graph is untouched by it.

    A remote tool has no carrier: nothing here declares it, no body can be edited, no knob
    can be written to it, and it changes under the user when that server is updated. So it
    is read from `tools/list` the way a service's ports are read -- and the graph looks
    exactly the same before and after somebody connects, which is what "contents, not
    nodes" means in practice.
    """
    before = {node.id for node in parse_project(EXAMPLE).nodes}
    answer = inspect_server(EXAMPLE, SERVER)
    after = {node.id for node in parse_project(EXAMPLE).nodes}

    assert answer["ok"] and {tool["name"] for tool in answer["tools"]} == {
        "summarize",
        "word_count",
    }
    assert before == after
    # And nothing hangs beneath the server node: it has no members, by construction.
    assert [node.members for node in parse_project(EXAMPLE).nodes if node.id == SERVER] == [()]


def test_what_this_project_may_call_is_a_knob_and_the_rest_is_only_offered() -> None:
    answer = inspect_server(EXAMPLE, SERVER)

    assert answer["allowed"] == ["summarize"]
    assert "word_count" in {tool["name"] for tool in answer["tools"]}


# -- connecting is an action, never a side effect of reading (P11) ---------------


def test_reading_the_graph_never_connects_to_a_consumed_server(tmp_path: Path) -> None:
    """The check has no path to a connection -- not a flag, not a fallback.

    The server in this example is reachable and would answer instantly; the node stays
    unproven anyway, with the button named. That is the whole rule: a graph being drawn
    must not reach into a third party's process.
    """
    root = copy(tmp_path, with_tests=False)

    run = run_observations(parse_project(root), root)

    assert SERVER not in run.observations
    assert "mcp.inspect" in run.skipped[SERVER]


def test_a_server_whose_token_is_missing_is_unproven_with_the_variable_named(
    tmp_path: Path,
) -> None:
    """The absence of an environment is never red -- the same shape as a stopped container."""
    root = copy(tmp_path, with_tests=False)
    assert set_knob(root, SERVER, "token_env", "NOTES_TOKEN").written is True

    run = run_observations(parse_project(root), root)

    assert "NOTES_TOKEN is not set" in run.skipped[SERVER]
    assert inspect_server(root, SERVER)["status"] == "unproven"


def test_a_knob_holds_the_name_of_a_variable_and_never_a_secret() -> None:
    """A knob is a syntax node in this project's source; a token written into one goes to git."""
    declaration = next(node for node in parse_project(EXAMPLE).nodes if node.id == SERVER)
    knobs = {knob.name for knob in declaration.knobs}

    assert "token_env" in knobs
    assert not {"token", "api_key", "secret", "password"} & knobs


# -- the three verdicts ----------------------------------------------------------


def test_a_server_that_answers_and_offers_what_we_call_is_green() -> None:
    answer = inspect_server(EXAMPLE, SERVER)

    assert (answer["ok"], answer["status"], answer["missing"]) == (True, "green", [])


def test_naming_a_tool_the_server_does_not_offer_is_broken(tmp_path: Path) -> None:
    """Not an environment problem: code referring to something that does not exist.

    The precedent is P14's schedule check, which fails rather than skips when an entry
    names a task the queue does not know. A tool withdrawn from a server is that case, and
    the graph is where it should surface -- the alternative is finding out in production.
    """
    root = copy(tmp_path)
    assert set_knob(root, SERVER, "allowed_tools", "summarize,archive").written is True

    answer = inspect_server(root, SERVER)

    assert answer["status"] == "broken"
    assert answer["missing"] == ["archive"]


def test_a_verb_pointed_at_a_node_that_is_not_a_consumed_server_says_so() -> None:
    answer = inspect_server(EXAMPLE, "agent.shout")

    assert not answer["ok"]
    assert "langgraph.tool" in answer["detail"]


# -- calling a tool: real input, and only what the project may call ---------------


def test_a_tool_is_called_with_the_input_it_was_given(tmp_path: Path) -> None:
    answer = call_server_tool(EXAMPLE, SERVER, "summarize", {"text": "One. Two.", "sentences": 1})

    assert answer["ok"] and "One." in answer["result"]


def test_a_tool_outside_the_allow_list_is_refused() -> None:
    """The allow-list is the project's own statement about what it may call.

    A verb that ignored it would be lying about the node it is attached to -- and the
    refusal is a result, never a protocol fault.
    """
    answer = call_server_tool(EXAMPLE, SERVER, "word_count", {"text": "a b"})

    assert not answer["ok"]
    assert "allow-list" in answer["detail"]


# -- evidence is never stored ----------------------------------------------------


def test_nothing_about_a_connection_is_written_down(tmp_path: Path) -> None:
    """A stale graph is impossible because there is nothing to go stale (I-1).

    A colleague who has not connected sees `unproven`, not somebody else's yesterday --
    and that falls out of the code being the only source of truth rather than being a
    feature somebody remembered to build.
    """
    root = copy(tmp_path, with_tests=False)
    assert inspect_server(root, SERVER)["ok"] is True

    run = run_observations(parse_project(root), root)

    assert SERVER not in run.observations
    assert not (root / ".framestack").is_dir()


# -- a tool is proven by a run that entered it, not by registration ---------------


def test_a_tool_is_proven_by_a_run_and_not_by_being_exposed() -> None:
    """Registration says a client *could* call it; a run says it works (Q11's rule again)."""
    run = run_observations(parse_project(EXAMPLE), EXAMPLE)

    assert run.observations["tools.summarize"].check == "tests.exercised"
    assert run.observations["agent.shout"].check == "tests.exercised"


def test_without_a_run_a_tool_falls_back_to_the_wiring_question(tmp_path: Path) -> None:
    """Which is a smaller claim, and says so: exposed, bound -- not proven to work."""
    root = copy(tmp_path, with_tests=False)

    run = run_observations(parse_project(root), root)

    assert run.observations["tools.summarize"].check == "mcp.tool_exposed"
    assert run.observations["agent.shout"].check == "graph.tool_bound"


def test_the_agent_actually_using_the_server_is_a_flow_arrow(tmp_path: Path) -> None:
    """The second claim, and it is drawn by a run -- never declared, never parsed (Q9).

    It works only because the call goes through the project's own object: straight into
    the SDK and the tracer sees library frames, so there is no arrow and no evidence.
    """
    run = run_observations(parse_project(EXAMPLE), EXAMPLE)

    assert {"source": "agent.consult", "target": SERVER, "origin": "observed"} in run.flow


# -- completeness: if it is not on the graph, it is not in the code (Q12) --------


def test_a_clean_project_is_proven_complete() -> None:
    payload = read_graph(EXAMPLE, observe=True)

    assert payload["completeness"]["state"] == "proven"
    assert payload["completeness"]["undeclared"] == []


def test_completeness_needs_a_run_and_says_so_without_one() -> None:
    """Claiming a complete graph from a static read would be the I-5 failure one level up."""
    payload = read_graph(EXAMPLE)

    assert payload["completeness"]["state"] == "unproven"


def test_a_tool_added_without_markup_is_reported_with_its_address(tmp_path: Path) -> None:
    root = copy(tmp_path)
    (root / "server" / "tools.py").write_text(
        (root / "server" / "tools.py").read_text()
        + "\n\ndef secret_tool(text: str) -> str:\n    return text[::-1]\n\n\n"
        'mcp_server.add_tool(secret_tool, name="secret", description="Undeclared.")\n'
    )

    payload = read_graph(root, observe=True)
    undeclared = [
        diagnostic
        for diagnostic in payload["diagnostics"]
        if diagnostic["code"] == Code.UNDECLARED_CARRIER.value
    ]

    assert len(undeclared) == 1
    assert undeclared[0]["location"]["file"] == "server/tools.py"
    assert undeclared[0]["location"]["object"] == "secret_tool"
    assert undeclared[0]["location"]["start_line"] > 1


def test_a_client_in_a_file_with_no_markup_is_found_too(tmp_path: Path) -> None:
    """The file with no markup in it is exactly the file this rule exists for.

    Which is why the probe imports **every** module rather than only the annotated ones --
    a deliberate widening of what gets executed in the subprocess.
    """
    root = copy(tmp_path)
    (root / "agent" / "rogue.py").write_text(
        "import sys\n\nfrom mcp import Client, StdioServerParameters\n\n"
        'rogue = Client(StdioServerParameters(command=sys.executable, args=["-m", "server"]))\n'
    )

    payload = read_graph(root, observe=True)
    undeclared = [
        diagnostic
        for diagnostic in payload["diagnostics"]
        if diagnostic["code"] == Code.UNDECLARED_CARRIER.value
    ]

    assert [diagnostic["location"]["file"] for diagnostic in undeclared] == ["agent/rogue.py"]
    assert "rogue" in undeclared[0]["location"]["object"]


def test_a_module_that_will_not_import_costs_the_claim_and_not_the_nodes(
    tmp_path: Path,
) -> None:
    """A corner of the project the graph knows nothing about must not redden a node.

    It costs the completeness claim instead, which is the thing it actually bears on.
    """
    root = copy(tmp_path)
    (root / "agent" / "broken.py").write_text("import a_module_that_is_not_installed\n")

    payload = read_graph(root, observe=True)

    assert payload["completeness"]["state"] == "unproven"
    assert "agent.broken" in payload["completeness"]["detail"]
    assert all(observation["passed"] for observation in payload["observations"].values())


def test_a_kind_joins_the_completeness_rule_through_the_registry() -> None:
    """The rule is general, not MCP-shaped: routes and the rest can follow with no new
    mechanism, by naming a probe here."""
    opted_in = {name for name, kind in REGISTRY.items() if kind.completeness}

    assert opted_in == {"mcp.tool", "mcp.server", "langgraph.tool"}


# -- the wire ---------------------------------------------------------------------


def test_both_verbs_answer_in_the_shape_they_declare() -> None:
    """A payload that announces its version can be handled; one that drifts cannot."""
    validate(wire_form(mcp_inspect(EXAMPLE, SERVER)), MCP_INSPECT_SCHEMA)
    validate(
        wire_form(mcp_call(EXAMPLE, SERVER, "summarize", {"text": "One. Two."})),
        MCP_CALL_SCHEMA,
    )


def test_the_verbs_are_methods_in_the_core() -> None:
    """The extension point is `HANDLERS`, never a new command in the Rust shell."""
    from framestack_core.handlers import dispatch

    answer = dispatch("mcp.inspect", {"project": str(EXAMPLE), "node": SERVER})

    assert answer["ok"] is True
    assert {tool["name"] for tool in answer["tools"]} == {"summarize", "word_count"}
