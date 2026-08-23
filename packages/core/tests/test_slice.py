"""The vertical slice: one FastAPI service, all the way through (P9).

Every earlier phase is tested where it lives. This file tests the only thing none of them
can: that the parts compose into the loop the product claims to be --

    brief -> annotated project -> graph -> knob written back -> deliberate breakage ->
    reconciliation -> repair -> green again -> the stripped copy proving the same things

in that order, on one project, with each step's output being the next step's input. A
suite of green units and a loop that does not close is exactly the failure this phase
exists to rule out.

Two things it insists on at the end, because they are where a shortcut would hide:

* **Green means both conditions.** The loop is not finished when the parser is happy; it
  is finished when the nodes are proven by a run (I-5).
* **The markup is still inert.** The stripped copy is put through the same observable
  checks, planned from the annotated graph and run against code that no longer has any
  markup in it (I-2). If the loop could only be closed with `bp` present, the product
  would be a graph-first builder with extra steps.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from aibuilder_core.agent import build_brief
from aibuilder_core.api import repairs_available, snapshot_status
from aibuilder_core.gate import check_graph
from aibuilder_core.observe import run_observations
from aibuilder_core.parser import parse_project
from aibuilder_core.repair import apply_repair
from aibuilder_core.snapshot import save_snapshot, take_snapshot
from aibuilder_core.strip import strip_project
from aibuilder_core.verdict import Verdict
from aibuilder_core.writer import set_knob

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def service(tmp_path: Path) -> Path:
    """The slice's project: the reference service, somewhere it can be edited."""
    root = tmp_path / "service"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".aibuilder"))
    return root


def verdicts(project: Path) -> dict[str, str]:
    """The full verdict: parsed **and** proven by a run. There is no other kind (I-5)."""
    graph = parse_project(project)
    run = run_observations(graph, project)
    return check_graph(graph, observations=run.observations).verdicts


def test_the_slice_runs_end_to_end(tmp_path: Path) -> None:
    root = service(tmp_path)

    # 1. The brief. The agent's input for this project is assembled from the prompt, the
    #    request and what already exists -- and what already exists is what the parser
    #    reads, not a description of it.
    brief = build_brief(root, request="add a users router")
    assert "users" in {node.id for node in brief.outline}
    assert brief.system_prompt.startswith("# System prompt")

    # 2. The graph, and the green verdict that requires a run. Every node proven: the
    #    POST route by the project's own test, the rest by their direct checks.
    assert set(verdicts(root).values()) == {Verdict.GREEN.value}

    # 3. The reference. Taken from a state that passed, which is the only state a
    #    reference may be taken from.
    save_snapshot(take_snapshot(parse_project(root)), root)
    assert snapshot_status(root)["divergences"] == []

    # 4. A knob edited through its node, written back through the syntax tree.
    written = set_knob(root, "api.settings", "page_size", 100)
    assert written.written is True
    assert (
        "page_size: Annotated[int, Param(min=1, max=200, step=10"
        in (root / "app" / "settings.py").read_text()
    )
    assert _knob(root, "api.settings", "page_size") == "100"

    # A knob write is a graph edit, so it is not a divergence -- the writer moved the
    # reference with it.
    assert snapshot_status(root)["divergences"] == []

    # 5. Deliberate breakage, by hand, in the generated zone: someone edits app assembly
    #    in an editor instead of through a node.
    main = root / "app" / "main.py"
    main.write_text(main.read_text().replace('title="Example Service"', 'title="By Hand"'))

    # 6. Reconciliation notices, and says what it is and whose it is.
    divergences = snapshot_status(root)["divergences"]
    assert [divergence["code"] for divergence in divergences] == ["function.generated_touched"]
    assert divergences[0]["fault"] == "generated"
    assert set(divergences[0]["resolutions"]) == {"revert", "accept"}

    # 7. The repair. The toolchain will not choose between reverting and accepting, so the
    #    resolution is passed in; here the caller reverts.
    listed = repairs_available(root)["repairs"]
    assert "do not choose between reverting and re-annotating" in listed[0]["request"]

    repaired = apply_repair(
        root, code="function.generated_touched", target="create_app", resolution="revert"
    )
    assert repaired.applied is True
    assert repaired.snapshot_updated is True
    assert 'title="Example Service"' in main.read_text()

    # 8. Green again -- proven, not merely parsed -- and the reference is clean.
    assert set(verdicts(root).values()) == {Verdict.GREEN.value}
    assert snapshot_status(root)["divergences"] == []

    # 9. The stripped copy, put through the same checks. The plan comes from the annotated
    #    graph; the code it runs against has no markup left in it at all (I-2).
    stripped = tmp_path / "stripped"
    strip_project(root, stripped)
    assert "bp" not in (stripped / "app" / "settings.py").read_text()

    annotated_run = run_observations(parse_project(root), root)
    stripped_run = run_observations(parse_project(root), stripped)

    assert stripped_run.skipped == annotated_run.skipped == {}
    assert {
        node: observation.passed for node, observation in stripped_run.observations.items()
    } == {node: observation.passed for node, observation in annotated_run.observations.items()}

    # And the knob the user set through the graph survived the strip, because it was
    # always just a default in ordinary Python.
    assert "page_size: int = 100" in (stripped / "app" / "settings.py").read_text()


def test_the_loop_closes_from_a_blueprint_too(tmp_path: Path) -> None:
    """§3's claim, at the level the slice tests: the input changes, the mechanics do not."""
    root = service(tmp_path)
    catalog = tmp_path / "catalog" / "blueprints" / "fastapi-routing"
    catalog.mkdir(parents=True)
    (catalog / "blueprint.md").write_text("# FastAPI Routing\n\nOne router per resource.\n")

    chat = build_brief(root, request="split the routes by resource")
    blueprint = build_brief(
        root,
        request="split the routes by resource",
        blueprint="fastapi-routing",
        catalog=tmp_path / "catalog",
    )

    assert chat.system_prompt == blueprint.system_prompt
    assert blueprint.blueprint is not None
    assert "One router per resource." in blueprint.instructions
    # Both describe the same project, at the same state, to the same rules.
    assert chat.outline == blueprint.outline


def test_a_node_that_stops_working_stops_being_green(tmp_path: Path) -> None:
    """The loop's failure direction, on the same service.

    A repair that satisfied the parser while leaving the service broken has to end here,
    or acceptance condition 2 is decorative.
    """
    root = service(tmp_path)
    health = root / "app" / "api" / "health.py"
    health.write_text(
        health.read_text().replace('return {"status": "ok"}', 'raise RuntimeError("no")')
    )

    assert check_graph(parse_project(root)).diagnostics == ()  # the static gate is content
    assert verdicts(root)["health"] == Verdict.BROKEN.value


def _knob(project: Path, node: str, knob: str) -> str | None:
    graph = parse_project(project)
    carrier = graph.node(node)
    assert carrier is not None
    return next(item.default for item in carrier.knobs if item.name == knob)
