"""The compose stack, read and edited (Phase 9).

Stated about `examples/full`, which has a real `compose.yaml` with three services, a
comment at the top of it, a service that builds rather than pulls, and an `environment:`
written as a mapping. That is the fixture the editing rules matter for: the promise is that
`git diff` after a write is the line that changed and nothing else.

**Nothing here needs docker.** The states come from the daemon and are empty without one,
which is the honest answer and the one every test asserts around: a service with no
container reads `""` rather than `exited`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import COMPOSE_SCHEMA, compose_read, compose_write
from framestack_core.compose import EDITABLE, Service, read_compose, write_compose

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def one(root: Path, name: str) -> Service:
    found = [service for service in read_compose(root).services if service.name == name]
    assert found, f"no service named {name!r}"
    return found[0]


def text(root: Path) -> str:
    return (root / "compose.yaml").read_text(encoding="utf-8")


# -- what the file says ----------------------------------------------------------------


def test_the_reference_declares_its_three_services() -> None:
    """The names come from the file, in the order it wrote them. A read of a real project."""
    answer = read_compose(EXAMPLE)

    assert answer.ok is True
    assert answer.present is True
    assert [service.name for service in answer.services] == ["api", "worker", "postgres"]


def test_a_service_that_builds_has_no_image_and_that_is_not_a_failure() -> None:
    """`build:` is ordinary. An empty image is the absence said plainly, never an error."""
    answer = read_compose(EXAMPLE)
    api = next(service for service in answer.services if service.name == "api")
    postgres = next(service for service in answer.services if service.name == "postgres")

    assert api.image == ""
    assert postgres.image == "postgres:17-alpine"


def test_the_two_forms_of_a_compose_list_read_the_same_way() -> None:
    """`environment` as a mapping and `ports` as a sequence both come back as short strings.

    A panel has one text field per line either way, and which form the file used is the
    file's business -- until it is written back, where it matters absolutely.
    """
    postgres = read_compose(EXAMPLE).services[2]

    assert postgres.ports == ("5432:5432",)
    assert sorted(postgres.environment) == [
        "POSTGRES_DB=reference",
        "POSTGRES_PASSWORD=reference",
    ]
    assert read_compose(EXAMPLE).services[0].depends_on == ("postgres",)


def test_a_project_with_no_compose_file_is_not_a_failure(tmp_path: Path) -> None:
    """Most projects have none. `present` is false and `ok` is true: nothing went wrong."""
    (tmp_path / "empty").mkdir()
    answer = read_compose(tmp_path / "empty")

    assert answer.ok is True
    assert answer.present is False
    assert answer.services == ()


def test_a_file_that_is_not_yaml_is_refused_rather_than_guessed_at(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "compose.yaml").write_text("services: [oh: dear\n", encoding="utf-8")

    answer = read_compose(root)

    assert answer.ok is False
    assert answer.services == ()


def test_no_state_without_a_daemon_is_empty_rather_than_stopped(tmp_path: Path) -> None:
    """`""` means "no container", `exited` means "there was one and it ended".

    They are different claims, and a reading that merged them would let a stack nobody has
    ever started look like one that crashed.
    """
    root = project(tmp_path)

    assert all(
        service.state in ("", "running", "exited", "created")
        for service in read_compose(root).services
    )


# -- writing keeps everything the edit was not about -----------------------------------


def test_changing_a_port_changes_one_line(tmp_path: Path) -> None:
    """The acceptance criterion, asked of `git` rather than of us.

    The same discipline `settings.py` follows for Python: one field, one line, and a diff a
    person can read at a glance.
    """
    root = project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "compose.yaml"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "in"],
        cwd=root,
        check=True,
    )

    write_compose(root, "postgres", "ports", ["5433:5432"])

    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--", "compose.yaml"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    changed = [
        line
        for line in diff.splitlines()
        if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
    ]
    assert changed == ['-      - "5432:5432"', '+      - "5433:5432"']


def test_a_comment_survives_an_edit(tmp_path: Path) -> None:
    """The other acceptance criterion. A round-trip loader is the whole reason this passes."""
    root = project(tmp_path)
    before = text(root)
    assert before.startswith("# What this project needs running around it.")

    write_compose(root, "postgres", "image", "postgres:16-alpine")

    after = text(root)
    assert after.startswith("# What this project needs running around it.")
    assert "postgres:16-alpine" in after
    # Every other service is untouched, character for character.
    assert before.split("  postgres:")[0] == after.split("  postgres:")[0]


def test_a_mapping_stays_a_mapping(tmp_path: Path) -> None:
    """`environment` written as a map is written back as one.

    Rewriting it as a list would be correct compose and a diff on every line of it, which is
    the collateral damage this module exists to prevent.
    """
    root = project(tmp_path)

    write_compose(root, "postgres", "environment", ["POSTGRES_DB=other", "POSTGRES_PASSWORD=x"])

    assert "POSTGRES_DB: other" in text(root)
    assert "- POSTGRES_DB" not in text(root)


def test_an_empty_list_removes_the_key_rather_than_writing_an_empty_one(tmp_path: Path) -> None:
    root = project(tmp_path)

    write_compose(root, "api", "depends_on", [])

    assert "depends_on" not in text(root).split("  worker:")[0]
    assert one(root, "api").depends_on == ()


def test_a_field_outside_the_five_is_refused_by_name(tmp_path: Path) -> None:
    """A write that reported success and changed nothing would be worse than a refusal."""
    root = project(tmp_path)
    before = text(root)

    answer = write_compose(root, "api", "command", ["true"])

    assert answer.ok is False
    assert "command" in answer.detail
    assert text(root) == before


def test_a_service_the_file_does_not_declare_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)
    before = text(root)

    answer = write_compose(root, "nowhere", "image", "redis:7")

    assert answer.ok is False
    assert text(root) == before


def test_a_wrong_type_is_refused_with_the_file_untouched(tmp_path: Path) -> None:
    """The same rule `settings.write` follows: the answer is the file as it still is."""
    root = project(tmp_path)
    before = text(root)

    assert write_compose(root, "postgres", "image", "").ok is False
    assert write_compose(root, "postgres", "ports", "5432:5432").ok is False
    assert text(root) == before


def test_a_refusal_still_reports_the_file(tmp_path: Path) -> None:
    """A panel that lost its list because a write was refused would be a panel that emptied
    itself for saying no."""
    root = project(tmp_path)

    answer = write_compose(root, "postgres", "command", ["true"])

    assert answer.ok is False
    assert [service.name for service in answer.services] == ["api", "worker", "postgres"]


# -- the wire ---------------------------------------------------------------------------


def test_the_payload_matches_the_contract(tmp_path: Path) -> None:
    root = project(tmp_path)

    validate(wire_form(compose_read(root)), COMPOSE_SCHEMA)
    validate(wire_form(compose_write(root, "postgres", "image", "postgres:16")), COMPOSE_SCHEMA)
    # A refusal crosses the same wire as an answer: it is a result, not a protocol fault.
    validate(wire_form(compose_write(root, "postgres", "command", ["true"])), COMPOSE_SCHEMA)


def test_the_editable_fields_are_declared_to_the_client() -> None:
    """A client draws exactly these controls. A sixth would be a decision, made here."""
    assert compose_read(EXAMPLE)["fields"] == list(EDITABLE)
    assert list(EDITABLE) == ["image", "ports", "environment", "volumes", "depends_on"]
