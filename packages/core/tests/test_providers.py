"""Places a model can be reached from.

Almost every test here is about what this store is **not** allowed to be. It cannot change
the graph, it cannot make a node green, it cannot hold a secret, and deleting it changes
nothing about the project -- which is the whole difference between a list of options and the
second source of truth I-1 forbids.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from test_api import validate, wire_form

from framestack_core.api import (
    PROVIDERS_READ_SCHEMA,
    PROVIDERS_WRITE_SCHEMA,
    providers_get,
    providers_put,
)
from framestack_core.parser import parse_project
from framestack_core.providers import PROVIDERS_PATH, read_providers, write_providers

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "rag-pipeline"

OLLAMA = {
    "name": "Ollama",
    "base_url": "http://localhost:11434/v1",
    "api_key_env": "",
    "models": ["llama3.1", "nomic-embed-text"],
}
HOSTED = {
    "name": "OpenRouter",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
    "models": ["anthropic/claude-sonnet-4.5"],
}


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def test_providers_come_back_as_they_were_stored(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert write_providers(root, [OLLAMA, HOSTED]).ok is True

    stored = read_providers(root)
    assert [one.name for one in stored] == ["Ollama", "OpenRouter"]
    assert stored[0].models == ("llama3.1", "nomic-embed-text")
    assert stored[1].api_key_env == "OPENROUTER_API_KEY"


def test_none_is_an_ordinary_answer(tmp_path: Path) -> None:
    assert read_providers(project(tmp_path)) == []


def test_a_corrupt_store_never_costs_a_panel(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_providers(root, [OLLAMA])
    (root / PROVIDERS_PATH).write_text("{not json", encoding="utf-8")

    assert read_providers(root) == []


def test_a_field_holding_a_key_is_refused_rather_than_stripped(tmp_path: Path) -> None:
    """The reason this module understands what it stores at all.

    `.framestack/` is a directory in somebody's repository, and an entry quietly stripped of
    the key they pasted would leave them believing it had been kept somewhere -- after which
    they stop looking for where their credential went.
    """
    root = project(tmp_path)

    for field in ("api_key", "token", "secret", "password"):
        result = write_providers(root, [{"name": "x", field: "sk-live-nope"}])
        assert result.ok is False
        assert field in result.detail

    assert not (root / PROVIDERS_PATH).exists()
    assert "sk-live-nope" not in json.dumps(providers_get(str(root)))


def test_an_unknown_field_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)

    result = write_providers(root, [{"name": "x", "organisation": "acme"}])

    assert result.ok is False
    assert "not a provider field" in result.detail


def test_two_providers_of_one_name_are_refused(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert write_providers(root, [OLLAMA, dict(OLLAMA)]).ok is False


def test_a_write_replaces_and_never_merges(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_providers(root, [OLLAMA, HOSTED])

    write_providers(root, [HOSTED])

    assert [one.name for one in read_providers(root)] == ["OpenRouter"]


def test_it_is_not_a_source_the_graph_reads_from(tmp_path: Path) -> None:
    """I-1. A model named here is not a model any node uses.

    What a node reaches is in its knobs, in code. This is a list of options, and a provider
    nobody applied leaves the graph byte for byte as it was.
    """
    root = project(tmp_path)
    before = parse_project(root).to_dict()

    write_providers(root, [OLLAMA, HOSTED])

    assert parse_project(root).to_dict() == before


def test_deleting_it_changes_nothing_about_the_project(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_providers(root, [OLLAMA])
    before = parse_project(root).to_dict()

    (root / PROVIDERS_PATH).unlink()

    assert parse_project(root).to_dict() == before
    assert read_providers(root) == []


def test_it_is_stored_beside_the_other_tooling_state(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_providers(root, [OLLAMA])

    assert (root / ".framestack" / "providers.json").is_file()


def test_nothing_is_written_for_a_project_that_is_not_there(tmp_path: Path) -> None:
    absent = tmp_path / "no-such-project"

    result = write_providers(absent, [OLLAMA])

    assert result.ok is False
    assert not absent.exists()


def test_the_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)

    validate(wire_form(providers_put(str(root), [OLLAMA])), PROVIDERS_WRITE_SCHEMA)
    validate(wire_form(providers_get(str(root))), PROVIDERS_READ_SCHEMA)


def test_the_capability_is_a_method_in_the_core(tmp_path: Path) -> None:
    from framestack_core.handlers import dispatch

    root = project(tmp_path)
    dispatch("providers.write", {"project": str(root), "providers": [OLLAMA]})

    answer = dispatch("providers.read", {"project": str(root)})
    assert answer["providers"] == [OLLAMA]


def test_something_that_is_not_a_list_is_a_protocol_fault() -> None:
    from framestack_core.handlers import dispatch
    from framestack_core.protocol import ProtocolError

    try:
        dispatch("providers.write", {"project": ".", "providers": {"name": "x"}})
    except ProtocolError as error:
        assert "must be a list" in str(error)
    else:  # pragma: no cover
        raise AssertionError("an object is not a list of providers")
