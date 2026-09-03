"""The models on this machine, and pulling one (Phase 8).

Ollama is the only node in the graph that makes "no data leaves this machine" literally true,
which is why it gets panel content the other dependencies do not. What it must not become is a
**catalogue**: nothing here ships a list of models or knows what any of them is for, and the
tests say so by asserting the shape of what comes back rather than any name in it.

The daemon may or may not be running on the machine these tests run on. Every assertion here
holds either way -- one that demanded a live Ollama would pass on one laptop and fail on the
next, which proves nothing about the code.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import OLLAMA_SCHEMA, ollama_models, ollama_read
from framestack_core.dependencies import SIGNS
from framestack_core.ollama import LOG_PATH, pull_model, read_models, read_pull, stop_pull
from framestack_core.parser import read_graph

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


# -- the list ---------------------------------------------------------------------------


def test_the_list_is_whatever_this_machine_has_and_never_a_catalogue(tmp_path: Path) -> None:
    """A registry of model names shipped with the toolchain would be stale the week after.

    So the answer is a read of this machine, and where the daemon is not running it is a
    refusal with the reason said -- never a list of what a person "could" pull.
    """
    answer = read_models(project(tmp_path))

    if answer.ok:
        assert all(model.name for model in answer.models)
        assert all(model.size >= 0 for model in answer.models)
    else:
        assert "11434" in answer.detail
        assert answer.models == ()


def test_the_list_comes_back_sorted(tmp_path: Path) -> None:
    """Two reads of an unchanged machine answer identically. The daemon's own order is a
    detail of how it stores them, not a fact anybody chose."""
    answer = read_models(project(tmp_path))

    names = [model.name for model in answer.models]
    assert names == sorted(names)


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    assert pull_model(tmp_path / "nowhere", "llama3.1").ok is False


# -- pulling ----------------------------------------------------------------------------


def test_nothing_is_pulled_because_a_panel_was_opened(tmp_path: Path) -> None:
    """P11, at the one place in this phase where it could be broken.

    Reading the list and polling a pull are both reads. Only `pull` fetches, and only a press
    reaches it.
    """
    root = project(tmp_path)
    read_models(root)
    read_pull(root, 0)

    assert not (root / LOG_PATH).exists()


def test_a_pull_with_no_model_named_is_refused(tmp_path: Path) -> None:
    answer = pull_model(project(tmp_path), "   ")

    assert answer.ok is False
    assert answer.running is False


def test_a_pull_is_polled_with_an_offset_the_caller_keeps(tmp_path: Path) -> None:
    """The P13 shape, and the reason a panel opened mid-pull can still watch one.

    The model is deliberately one nobody has: what is asserted is the *contract* -- output
    arrives, an offset comes back, and the second read starts where the first stopped -- not
    that a download succeeded.
    """
    root = project(tmp_path)
    started = pull_model(root, "framestack-no-such-model")
    assert started.ok is True
    assert started.pulling == "framestack-no-such-model"

    first = read_pull(root, 0)
    assert first.output.startswith("pulling framestack-no-such-model")
    assert first.offset > 0

    second = read_pull(root, first.offset)
    assert second.offset >= first.offset
    # And the second read does not repeat what the first already carried.
    assert first.output not in second.output or second.output == ""

    stop_pull(root)


def test_a_second_pull_in_one_project_is_refused_rather_than_queued(tmp_path: Path) -> None:
    """A queue is a thing to manage. The honest answer is that one is already running."""
    root = project(tmp_path)
    pull_model(root, "framestack-no-such-model")

    second = pull_model(root, "another-one")

    # Either the first is still going -- and the second is refused by name -- or it already
    # failed, which is the same machine-dependent race every network test has. Both are
    # correct; what must never happen is two pulls writing one log.
    if not second.ok:
        assert "framestack-no-such-model" in second.detail

    stop_pull(root)


def test_stopping_a_pull_that_is_not_running_is_a_result_and_not_an_error(
    tmp_path: Path,
) -> None:
    answer = stop_pull(project(tmp_path))

    assert answer.ok is True
    assert answer.running is False


def settled(root: Path) -> None:
    """Wait, briefly, for a pull to be over. A stop is cooperative, not a kill.

    The thread ends at the next line the daemon sends, which is at once for a model that does
    not exist and immediately for a daemon that is not running -- but it is not synchronous
    with the request, and a test that assumed it was would be flaky by design.
    """
    for _ in range(100):
        if not read_pull(root, 0).running:
            return
        time.sleep(0.05)


def test_a_fresh_pull_does_not_show_the_end_of_the_last_one(tmp_path: Path) -> None:
    """A panel opened during the second pull must not read the first one's tail as progress."""
    root = project(tmp_path)
    pull_model(root, "framestack-no-such-model")
    stop_pull(root)
    settled(root)

    started = pull_model(root, "framestack-other-model")
    assert started.ok is True, started.detail
    fresh = read_pull(root, 0)

    assert "framestack-no-such-model" not in fresh.output
    assert fresh.output.startswith("pulling framestack-other-model")
    stop_pull(root)


# -- the edge --------------------------------------------------------------------------


def test_a_settings_model_written_the_framework_s_way_names_ollama(tmp_path: Path) -> None:
    """`ollama/llama3.1` is how a framework says "served by Ollama", and it is a literal.

    A bare `llama3.1:8b` is not recognised, and that is the deliberate half: recognising one
    would need a list of model names in this toolchain, which is a catalogue.
    """
    root = project(tmp_path)
    (root / "agent" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class AgentSettings(BaseSettings):\n"
        '    model: str = "ollama/llama3.1:8b"\n',
        encoding="utf-8",
    )

    graph = read_graph(root)
    assert "ollama" in {node.id for node in graph.nodes if node.kind == "dependency"}
    assert ("agent", "ollama") in {(edge.source, edge.target) for edge in graph.edges}


def test_ollama_is_never_a_paid_check() -> None:
    """It is on this machine. There is nothing to bill, and nothing that could be."""
    sign = next(one for one in SIGNS if one.node == "ollama")

    assert sign.paid is False


# -- the contract ----------------------------------------------------------------------


def test_the_payload_matches_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    validate(wire_form(ollama_models(root)), OLLAMA_SCHEMA)
    validate(wire_form(ollama_read(root, 0)), OLLAMA_SCHEMA)
