"""Colour, and what it costs to earn (Phase 2).

Every test here runs the reference project's real suite in a real subprocess. That is the
point rather than an inconvenience: the claim under test is "this node is green because a
passing test executed its code", and a fake coverage database would prove that the joining
logic works while proving nothing at all about the thing the product is selling.

The rule the whole file is arranged around is I-3, **green is earned by a run**. So the
tests that matter most are the ones where nothing turns green: a node nothing reached, a
suite that cannot run, a suite that reached the network. A parser bug shows up as a wrong
colour; an honesty bug shows up as a colour that should not be there at all.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import OBSERVE_SCHEMA, observe_last, observe_read, observe_start
from framestack_core.observe import (
    OBSERVATION_PATH,
    Observation,
    last_observation,
    read_observation,
    start_observation,
)
from framestack_core.parser import is_system, read_graph

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "reference"

#: Long enough for a cold interpreter to import pytest on a loaded machine, short enough that
#: a hang fails the suite rather than holding CI open.
PATIENCE = 180


def project(tmp_path: Path, name: str = "project") -> Path:
    """A writable copy. Observe writes into `.framestack/`; the reference is not ours to."""
    root = tmp_path / name
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def observe(root: Path) -> Observation:
    """Run it and wait. The polling is the contract (P13), so the helper uses it."""
    started = start_observation(root)
    assert started.ok or started.observation is not None, started.detail

    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        answer = read_observation(root, 0)
        if not answer.running:
            assert answer.observation is not None, answer.detail
            return answer.observation
        time.sleep(0.1)
    raise AssertionError("the run did not finish")


def colours(observation: Observation) -> dict[str, str]:
    return {verdict.node: verdict.verdict for verdict in observation.verdicts}


def one(observation: Observation, node: str) -> object:
    found = [verdict for verdict in observation.verdicts if verdict.node == node]
    assert found, f"no verdict for {node!r} in {sorted(colours(observation))}"
    return found[0]


def only_this_test(root: Path, name: str, body: str) -> None:
    """Replace the suite with one file. The cheapest way to say what a run did *not* reach."""
    shutil.rmtree(root / "tests")
    (root / "tests").mkdir()
    (root / "tests" / name).write_text(body, encoding="utf-8")


def child(root: Path, name: str, works: bool = True) -> None:
    """A nested agent under `agent/agents/`, exporting `run` as its kind requires."""
    package = root / "agent" / "agents" / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        f"from agent.agents.{name}.work import run\n\n__all__ = ['run']\n", encoding="utf-8"
    )
    (package / "work.py").write_text(
        "def run(message: str, **kw: object) -> str:\n"
        + ("    return message.upper()\n" if works else "    raise AssertionError('not yet')\n"),
        encoding="utf-8",
    )


# -- the run that works ---------------------------------------------------------------------


def test_the_reference_comes_back_green_with_the_tests_that_earned_it(tmp_path: Path) -> None:
    """The whole mechanism in one assertion, evidence included.

    The list of tests is asserted as well as the colour, because the colour on its own is
    exactly what every other builder already has. What makes it a verdict rather than a
    decoration is that it can be traced back to a named test somebody can run.
    """
    observation = observe(project(tmp_path))

    assert colours(observation) == {
        "agent": "green",
        "api": "green",
        "rag": "green",
        "worker": "green",
    }
    assert (
        "tests/test_rag.py::test_indexing_makes_a_document_findable"
        in one(  # type: ignore[attr-defined]
            observation, "rag"
        ).tests
    )


def test_only_packages_are_ever_given_a_verdict(tmp_path: Path) -> None:
    """Files and MCP servers are shown, opened and edited. Nothing runs them, so nothing
    can prove them.

    The server half is the one that would have broken quietly. Observe used to select what to
    measure with `kind != "file"`, which meant "is it a package" only while `file` was the
    sole exception — the moment servers became nodes (Phase 10) that test would have handed
    `mcp.json` to coverage as a source directory and turned every server grey for not being
    reached by a test. Grey is a claim about somebody's code, and this one would have been
    a claim about a file that has no code in it.
    """
    root = project(tmp_path)
    observation = observe(root)
    coloured = set(colours(observation))

    assert not {".env", "Dockerfile", "compose.yaml", "mcp.json"} & coloured
    assert not {node.id for node in read_graph(root).nodes if node.kind == "mcp"} & coloured
    # And what *is* coloured is exactly the packages, so nothing was quietly dropped either.
    assert coloured == {node.id for node in read_graph(root).nodes if is_system(node)}


def test_three_runs_produce_an_identical_verdict_set(tmp_path: Path) -> None:
    """Invariant 4, as the plan asks for it: a CI test, not a manual check.

    The verdict set, not the whole observation: the timestamp moves by design, and a run
    dated the same as the one before it would be a run that did not happen.
    """
    root = project(tmp_path)

    sets = [
        json.dumps([verdict.as_dict() for verdict in observe(root).verdicts], sort_keys=True)
        for _ in range(3)
    ]

    assert sets[0] == sets[1] == sets[2]


def test_the_run_leaves_its_verdict_where_the_next_window_will_find_it(tmp_path: Path) -> None:
    """A record on disk survives a crash. Read back without running anything."""
    root = project(tmp_path)
    observe(root)

    assert (root / OBSERVATION_PATH).is_file()
    kept = last_observation(root)

    assert kept.running is False
    assert kept.observation is not None
    assert colours(kept.observation)["rag"] == "green"


def test_nothing_is_known_before_anything_is_observed(tmp_path: Path) -> None:
    """The ordinary first state of a project, and it is not a failure."""
    answer = last_observation(project(tmp_path))

    assert answer.ok is True
    assert answer.observation is None


# -- the colours that are not green -----------------------------------------------------------


def test_a_node_no_test_reaches_is_grey_and_never_green(tmp_path: Path) -> None:
    """The acceptance criterion, with the reference's own coupling taken into account.

    Deleting `tests/test_rag.py` alone would leave `rag` green, because the agent's tests
    reach it through an import — which is correct, and is the sort of thing a coverage-based
    verdict knows and a naming convention could never work out. So the suite is reduced to
    one test that touches the worker's `echo` and nothing else.
    """
    root = project(tmp_path)
    only_this_test(
        root,
        "test_echo.py",
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).parents[1]))\n\n"
        "from worker import HANDLERS\n\n\n"
        "def test_echo_answers() -> None:\n"
        "    assert HANDLERS['echo']({'a': 1}) == {'echoed': {'a': 1}}\n",
    )

    observation = observe(root)

    assert colours(observation)["rag"] == "grey"
    assert colours(observation)["agent"] == "grey"
    assert "no test reached it" in one(observation, "rag").reason  # type: ignore[attr-defined]


def test_breaking_search_turns_rag_red_and_names_the_failing_test(tmp_path: Path) -> None:
    """Red is actionable or it is decoration, so the verdict carries the test's own name.

    Broken at *runtime* rather than at import. A package that cannot be imported takes the
    whole collection down with it, and that is a suite that could not run — `skipped`, which
    is a different claim and has its own test below.
    """
    root = project(tmp_path)
    store = root / "rag" / "store.py"
    store.write_text(
        store.read_text(encoding="utf-8").replace(
            "    return [chunk for _, chunk in hits[: settings.top_k]]",
            "    return []",
        ),
        encoding="utf-8",
    )

    observation = observe(root)
    rag = one(observation, "rag")

    assert rag.verdict == "red"  # type: ignore[attr-defined]
    # Named, and named the same way every time. Which of several failing tests is quoted is
    # settled by sorting rather than by any notion of a test "belonging to" a package —
    # that guess is the naming convention this design refuses, and picking one at random
    # would break I-4 the first time two tests failed together.
    assert rag.reason.endswith(" failed")  # type: ignore[attr-defined]
    assert rag.reason.removesuffix(" failed") in rag.tests  # type: ignore[attr-defined]
    assert "tests/test_rag.py::test_indexing_makes_a_document_findable" in rag.tests  # type: ignore[attr-defined]


def test_red_beats_green_within_one_package(tmp_path: Path) -> None:
    """A package with a passing test and a failing one has something wrong with it.

    A colour that reported the good news would be a colour nobody could act on, so this is
    stated as a test rather than left to the order the verdicts happen to be computed in.

    The failing test **calls into the package**, which is what makes it evidence about the
    package. A test that only reads a name off an already-imported module executes nothing
    inside it and rightly says nothing about it — see the note on import-time coverage in
    `observe.py`.
    """
    root = project(tmp_path)
    (root / "tests" / "test_worker_extra.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).parents[1]))\n\n"
        "from worker import HANDLERS\n\n\n"
        "def test_echo_is_expected_to_do_something_else() -> None:\n"
        "    assert HANDLERS['echo']({'a': 1}) == {'a': 2}\n",
        encoding="utf-8",
    )

    assert colours(observe(root))["worker"] == "red"


# -- aggregation ------------------------------------------------------------------------------


def test_a_parent_with_an_unreached_child_is_amber_and_never_green(tmp_path: Path) -> None:
    """Amber is a distinct state, not a shade of green.

    "Everything I could check passed and one part was never checked" is a different claim
    from "everything passed", and blending them would spend the earned colour on an
    unearned one.
    """
    root = project(tmp_path)
    for name in ("researcher", "writer", "reviewer"):
        child(root, name)
    # Two of the three are exercised. The third is written and never called.
    (root / "tests" / "test_children.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).parents[1]))\n\n"
        "from agent.agents.researcher import run as researcher\n"
        "from agent.agents.writer import run as writer\n\n\n"
        "def test_the_researcher_answers() -> None:\n"
        "    assert researcher('hello') == 'HELLO'\n\n\n"
        "def test_the_writer_answers() -> None:\n"
        "    assert writer('hello') == 'HELLO'\n",
        encoding="utf-8",
    )

    found = colours(observe(root))

    assert found["agent.researcher"] == "green"
    assert found["agent.writer"] == "green"
    assert found["agent.reviewer"] == "grey"
    assert found["agent"] == "amber"


def test_reaching_the_last_child_turns_the_parent_green_in_the_same_run(tmp_path: Path) -> None:
    """The acceptance criterion, and the proof that aggregation is computed and not cached."""
    root = project(tmp_path)
    for name in ("researcher", "writer", "reviewer"):
        child(root, name)
    (root / "tests" / "test_children.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).parents[1]))\n\n"
        "from agent.agents.researcher import run as researcher\n"
        "from agent.agents.writer import run as writer\n"
        "from agent.agents.reviewer import run as reviewer\n\n\n"
        "def test_all_three_answer() -> None:\n"
        "    assert [researcher('a'), writer('a'), reviewer('a')] == ['A', 'A', 'A']\n",
        encoding="utf-8",
    )

    found = colours(observe(root))

    assert found["agent.reviewer"] == "green"
    assert found["agent"] == "green"


def test_one_red_child_makes_the_parent_red(tmp_path: Path) -> None:
    root = project(tmp_path)
    child(root, "researcher", works=False)
    (root / "tests" / "test_children.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).parents[1]))\n\n"
        "from agent.agents.researcher import run\n\n\n"
        "def test_the_researcher_answers() -> None:\n"
        "    assert run('hello') == 'HELLO'\n",
        encoding="utf-8",
    )

    found = colours(observe(root))

    assert found["agent.researcher"] == "red"
    assert found["agent"] == "red"


# -- the runs that prove nothing ----------------------------------------------------------------


def test_a_suite_that_reaches_the_network_is_skipped_and_colours_nothing(
    tmp_path: Path,
) -> None:
    """The determinism rule, enforced rather than requested.

    A check that reaches the network passes or fails for reasons outside the repository, so
    the run cannot be reproduced. The whole verdict set is `skipped` — not red, which would
    blame the code, and certainly not green.
    """
    root = project(tmp_path)
    (root / "tests" / "test_online.py").write_text(
        "import socket\n\n\n"
        "def test_it_asks_the_internet() -> None:\n"
        "    # Swallowed on purpose: a green node earned by catching the refusal is exactly\n"
        "    # what recording the attempt exists to prevent.\n"
        "    try:\n"
        "        socket.create_connection(('example.com', 80), timeout=1).close()\n"
        "    except OSError:\n"
        "        pass\n"
        "    assert True\n",
        encoding="utf-8",
    )

    observation = observe(root)

    assert set(colours(observation).values()) == {"skipped"}
    assert observation.ok is False
    assert "network" in observation.detail


def test_a_suite_that_cannot_run_is_skipped_and_nothing_turns_green(tmp_path: Path) -> None:
    """Do not invent a verdict when the suite errors. Grey would blame the code for it."""
    root = project(tmp_path)
    (root / "tests" / "test_broken.py").write_text("def test_(:\n", encoding="utf-8")

    observation = observe(root)

    assert set(colours(observation).values()) == {"skipped"}
    assert observation.ok is False
    assert "green" not in observation.detail


def test_loopback_is_not_the_network(tmp_path: Path) -> None:
    """A test talking to something it started itself is still self-contained.

    Denying this would rule out every service test there is, so the guard's boundary is
    stated as a test rather than left to be discovered by somebody whose suite went grey.
    """
    root = project(tmp_path)
    (root / "tests" / "test_local.py").write_text(
        "import socket\n\n\n"
        "def test_it_talks_to_itself() -> None:\n"
        "    listener = socket.socket()\n"
        "    listener.bind(('127.0.0.1', 0))\n"
        "    listener.listen(1)\n"
        "    caller = socket.create_connection(listener.getsockname())\n"
        "    caller.close()\n"
        "    listener.close()\n",
        encoding="utf-8",
    )

    assert colours(observe(root))["rag"] == "green"


def test_a_project_with_no_system_starts_nothing(tmp_path: Path) -> None:
    """There is no node to colour, so there is no reason to run a stranger's code (P11)."""
    empty = tmp_path / "empty"
    empty.mkdir()

    answer = start_observation(empty)

    assert answer.ok is True
    assert answer.running is False
    assert answer.observation is not None
    assert answer.observation.verdicts == ()


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    assert start_observation(tmp_path / "nowhere").ok is False
    assert read_observation(tmp_path / "nowhere").ok is False


# -- the payload -----------------------------------------------------------------------------


def test_every_verb_matches_the_declared_contract(tmp_path: Path) -> None:
    """Strictly, in both directions: an undeclared field fails as loudly as a missing one."""
    root = project(tmp_path)

    validate(wire_form(observe_last(root)), OBSERVE_SCHEMA)
    validate(wire_form(observe_start(root)), OBSERVE_SCHEMA)

    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        answer = observe_read(root, 0)
        validate(wire_form(answer), OBSERVE_SCHEMA)
        if not answer["running"]:
            break
        time.sleep(0.1)

    validate(wire_form(observe_last(root)), OBSERVE_SCHEMA)
