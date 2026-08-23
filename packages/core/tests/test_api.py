"""The graph API contract.

The UI is delivered separately and on its own schedule, so the payload's shape is a
promise made across a gap. A schema snapshot is how that promise is kept honest: adding a
field, removing one, or changing a type all fail this test, and the failure is the prompt
to decide whether `GRAPH_API_VERSION` has to move.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aibuilder_core.api import (
    AGENT_BLUEPRINTS_SCHEMA,
    AGENT_BRIEF_SCHEMA,
    AGENT_FAILURES_SCHEMA,
    AGENT_RECORD_SCHEMA,
    ENVIRONMENT_SCHEMA,
    GRAPH_API_VERSION,
    GRAPH_KINDS_SCHEMA,
    GRAPH_READ_SCHEMA,
    REPAIR_APPLY_SCHEMA,
    REPAIR_LIST_SCHEMA,
    SERVICE_SCHEMA,
    SNAPSHOT_STATUS_SCHEMA,
    SNAPSHOT_TAKE_SCHEMA,
    WRITE_SCHEMA,
    agent_blueprints,
    agent_brief,
    agent_failures,
    agent_record,
    describe_kinds,
    environment_status,
    read_graph,
    repair_divergence,
    repairs_available,
    services_start,
    snapshot_status,
    take_project_snapshot,
    write_knob,
    write_node_title,
)
from aibuilder_core.gate import GateMode

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"
FIXTURE = Path(__file__).parent / "fixtures" / "mis-annotated"
BROKEN_RUNTIME = Path(__file__).parent / "fixtures" / "broken-runtime"


def validate(payload: Any, schema: Any, path: str = "$") -> None:
    """Check a payload against the declared contract, strictly in both directions.

    An **undeclared field fails**, not just a missing one. A field that appears by
    accident is a promise nobody decided to make, and the first client to depend on it
    turns that accident into a compatibility obligation.
    """
    if isinstance(schema, dict):
        if set(schema) == {"<nullable>"}:
            if payload is None:
                return
            validate(payload, schema["<nullable>"], path)
            return

        assert isinstance(payload, dict), (
            f"{path}: expected an object, got {type(payload).__name__}"
        )

        if set(schema) == {"<key>"}:
            for key, value in payload.items():
                validate(value, schema["<key>"], f"{path}.{key}")
            return

        assert set(payload) == set(schema), (
            f"{path}: keys differ -- "
            f"undeclared {sorted(set(payload) - set(schema))}, "
            f"missing {sorted(set(schema) - set(payload))}"
        )
        for key, sub in schema.items():
            validate(payload[key], sub, f"{path}.{key}")
        return

    if isinstance(schema, list):
        assert isinstance(payload, list), f"{path}: expected a list"
        for index, item in enumerate(payload):
            validate(item, schema[0], f"{path}[{index}]")
        return

    nullable = schema.endswith("?")
    if payload is None:
        assert nullable, f"{path}: null is not allowed here"
        return

    expected = {
        "str": str,
        "int": int,
        "bool": bool,
        "number": (int, float),
    }[schema.removesuffix("?")]
    # bool is a subclass of int in Python; a boolean where a number belongs is a bug.
    assert isinstance(payload, expected) and not (
        expected is not bool and isinstance(payload, bool)
    ), f"{path}: expected {schema}, got {type(payload).__name__}"


def wire_form(payload: dict[str, Any]) -> Any:
    """What actually crosses the boundary.

    The contract is the JSON, not the Python object behind it: `asdict` leaves tuples in
    place, and validating those would be checking an internal representation the client
    never sees.
    """
    return json.loads(json.dumps(payload))


def test_a_clean_project_matches_the_declared_contract() -> None:
    validate(wire_form(read_graph(EXAMPLE)), GRAPH_READ_SCHEMA)


def test_a_broken_project_matches_the_same_contract() -> None:
    """Diagnostics, unparsed files and unresolved members are contract, not exceptions."""
    payload = wire_form(read_graph(FIXTURE))

    validate(payload, GRAPH_READ_SCHEMA)
    assert payload["diagnostics"]
    assert payload["graph"]["unparsed"]


def test_an_observed_payload_matches_the_declared_contract() -> None:
    """Observations and skips are contract too, not an extra the client has to guess at."""
    payload = wire_form(read_graph(BROKEN_RUNTIME, observe=True))

    validate(payload, GRAPH_READ_SCHEMA)
    assert payload["observations"]["boom"]["passed"] is False
    assert payload["verdicts"]["boom"] == "broken"


def test_reading_without_observing_leaves_every_node_unproven() -> None:
    """A read must not run the project, and must not pretend the checks were made."""
    payload = read_graph(BROKEN_RUNTIME)

    assert payload["observations"] == {}
    assert set(payload["verdicts"].values()) == {"unproven"}


def test_the_registry_payload_matches_the_declared_contract() -> None:
    validate(wire_form(describe_kinds()), GRAPH_KINDS_SCHEMA)


def test_an_undeclared_field_is_caught() -> None:
    """The validator has to be strict, or the schema test proves nothing."""
    import pytest

    payload = wire_form(read_graph(EXAMPLE))
    payload["surprise"] = 1

    with pytest.raises(AssertionError, match="undeclared"):
        validate(payload, GRAPH_READ_SCHEMA)


def test_a_retyped_field_is_caught() -> None:
    import pytest

    payload = wire_form(read_graph(EXAMPLE))
    payload["accepted"] = "yes"

    with pytest.raises(AssertionError, match="expected bool"):
        validate(payload, GRAPH_READ_SCHEMA)


def test_every_payload_announces_its_version() -> None:
    assert read_graph(EXAMPLE)["api_version"] == GRAPH_API_VERSION
    assert describe_kinds()["api_version"] == GRAPH_API_VERSION


def test_the_graph_never_arrives_without_its_diagnostics() -> None:
    """A graph rendered without its badges is a graph that lies, so they travel together."""
    payload = read_graph(FIXTURE)

    assert payload["graph"]["nodes"]
    assert payload["diagnostics"]
    assert payload["verdicts"]


def test_the_payload_is_json_serializable() -> None:
    """It crosses a process boundary as NDJSON; anything unserializable is a dead API."""
    json.dumps(read_graph(FIXTURE))
    json.dumps(describe_kinds())


def test_mode_travels_with_the_answer() -> None:
    soft = read_graph(FIXTURE, mode=GateMode.SOFT)
    hard = read_graph(FIXTURE, mode=GateMode.HARD)

    assert (soft["mode"], soft["accepted"]) == ("soft", True)
    assert (hard["mode"], hard["accepted"]) == ("hard", False)


def test_the_registry_is_exposed_for_clients_that_pick_shapes() -> None:
    names = [kind["name"] for kind in describe_kinds()["kinds"]]

    assert "fastapi.service" in names
    assert names == sorted(names)


def test_the_snapshot_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)

    validate(wire_form(snapshot_status(root)), SNAPSHOT_STATUS_SCHEMA)
    validate(wire_form(take_project_snapshot(root)), SNAPSHOT_TAKE_SCHEMA)

    (root / "app" / "main.py").write_text(
        (root / "app" / "main.py").read_text().replace("Example Service", "Edited By Hand")
    )
    status = wire_form(snapshot_status(root))

    validate(status, SNAPSHOT_STATUS_SCHEMA)
    assert status["divergences"]


def test_a_refused_snapshot_matches_the_same_contract() -> None:
    validate(wire_form(take_project_snapshot(FIXTURE)), SNAPSHOT_TAKE_SCHEMA)


def test_the_write_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)

    written = wire_form(write_knob(root, "api.settings", "page_size", 50))
    refused = wire_form(write_knob(root, "api.settings", "page_size", 500))
    renamed = wire_form(write_node_title(root, "health", "Liveness"))

    for payload in (written, refused, renamed):
        validate(payload, WRITE_SCHEMA)

    assert written["written"] is True
    assert refused["written"] is False and refused["refused"]


def test_the_repair_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    import shutil

    from aibuilder_core.parser import parse_project
    from aibuilder_core.snapshot import save_snapshot, take_snapshot

    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)
    save_snapshot(take_snapshot(parse_project(root)), root)

    main = root / "app" / "main.py"
    main.write_text(main.read_text().replace("Example Service", "Edited By Hand"))

    listed = wire_form(repairs_available(root))
    validate(listed, REPAIR_LIST_SCHEMA)
    assert listed["repairs"]

    applied = wire_form(
        repair_divergence(root, "function.generated_touched", "create_app", "revert")
    )
    validate(applied, REPAIR_APPLY_SCHEMA)
    assert applied["applied"] is True


def test_the_agent_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    """The brief crosses the same gap as the graph, so it is the same kind of promise."""
    import shutil

    catalog = tmp_path / "catalog" / "blueprints" / "cursor-pagination"
    catalog.mkdir(parents=True)
    (catalog / "blueprint.md").write_text("# Cursor Pagination\n\nPages that stay correct.\n")

    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)

    chat = wire_form(agent_brief(str(root), "add a route"))
    blueprint = wire_form(
        agent_brief(str(root), "add pagination", "cursor-pagination", str(tmp_path / "catalog"))
    )
    refused = wire_form(agent_brief(str(root)))

    for payload in (chat, blueprint, refused):
        validate(payload, AGENT_BRIEF_SCHEMA)

    assert refused["brief"] is None and refused["refused"]
    assert chat["brief"]["system_prompt"] == blueprint["brief"]["system_prompt"]

    validate(wire_form(agent_blueprints(str(tmp_path / "catalog"))), AGENT_BLUEPRINTS_SCHEMA)
    validate(wire_form(agent_record(str(root), "chat", "add a route")), AGENT_RECORD_SCHEMA)
    validate(wire_form(agent_failures(str(root))), AGENT_FAILURES_SCHEMA)


def test_an_agent_record_of_a_flawed_generation_matches_the_same_contract() -> None:
    """Diagnostics in the log are contract too -- they are the point of recording it."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        import shutil

        root = Path(directory) / "project"
        shutil.copytree(FIXTURE, root)
        payload = wire_form(agent_record(str(root), "chat"))

    validate(payload, AGENT_RECORD_SCHEMA)
    assert payload["entry"]["diagnostics"]


def test_the_environment_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    """Two shapes: what the environment is, and what an action on it answered."""
    validate(wire_form(environment_status(str(EXAMPLE))), ENVIRONMENT_SCHEMA)
    validate(wire_form(services_start(str(tmp_path))), SERVICE_SCHEMA)

    refused = services_start(str(tmp_path))
    assert refused["ok"] is False and "no compose file" in refused["detail"]


# -- over the wire ----------------------------------------------------------------


def request(method: str, **params: Any) -> dict[str, Any]:
    from aibuilder_core.__main__ import handle_line

    line = handle_line(json.dumps({"id": 1, "method": method, "params": params}))
    assert line is not None
    return dict(json.loads(line))


def test_graph_read_answers_over_the_protocol() -> None:
    response = request("graph.read", project=str(EXAMPLE))

    assert response["ok"] is True
    assert response["result"]["api_version"] == GRAPH_API_VERSION


def test_a_missing_project_is_a_parameter_error_not_a_crash() -> None:
    response = request("graph.read")

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_params"


def test_a_refused_write_is_a_result_not_a_protocol_error(tmp_path: Path) -> None:
    """A value outside a knob's bounds is a normal answer, not a fault in the call."""
    import shutil

    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)

    response = request(
        "knob.set", project=str(root), node="api.settings", knob="page_size", value=500
    )

    assert response["ok"] is True
    assert response["result"]["written"] is False
    assert "maximum" in response["result"]["refused"]


def test_a_write_missing_its_value_is_a_parameter_error() -> None:
    response = request("knob.set", project=str(EXAMPLE), node="api.settings", knob="page_size")

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_params"


def test_a_repair_without_a_resolution_is_a_parameter_error() -> None:
    """The wire cannot get around what the function signature enforces (§9 case 2)."""
    response = request(
        "repair.apply", project=str(EXAMPLE), code="function.generated_touched", target="create_app"
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_params"


def test_an_unknown_mode_names_the_modes_that_exist() -> None:
    """An error a caller can act on beats one it has to guess at."""
    response = request("graph.read", project=str(EXAMPLE), mode="lenient")

    assert response["error"]["code"] == "invalid_params"
    assert "soft" in response["error"]["message"]
