"""The compose stack: what each service is, whether it is up, and the five fields a panel
may change (Phase 9).

`compose.yaml` and the `Dockerfile` are file nodes; `docker` is a dependency with a status.
What this module adds is the middle of the two -- the services by name, the state the daemon
reports for each, and a way to change the handful of things a person changes while building.

## Two questions, two mechanisms, and they are not mixed

**What is running is asked of docker.** `docker compose ps` reports the state and the ports
the daemon actually published, and nothing here infers either from the file: a `ports:` line
is what somebody asked for, and a published port is what happened.

**What is written is read from the file**, because that is the thing being edited. This is
the one place in the codebase that opens `compose.yaml`, and the reason is narrow: a panel
that offered to change a value it had not read would be a panel typing into the dark.
The *shape* of the stack -- which services exist at all -- is still `docker compose config
--services`, asked of the program that owns the format, and `deploy.py` still reads not one
line of the file.

## Writing follows the libcst discipline

Everything the edit was not about stays byte-identical: comments, key order, quoting style,
the blank line between two services. That is what a round-trip loader is for, and it is the
same promise `settings.py` makes about Python -- `git diff` after a write shows the field
that changed and nothing else.

**Five fields, and the limit is the design.** `image`, `ports`, `environment`, `volumes`,
`depends_on` are what come up while building; a full compose editor is a second product, and
the file is one click away for everything else. A field outside the five is refused by name
rather than quietly ignored, because a write that reports success and changes nothing is
worse than a refusal.

The answer to a write is always the file **re-read**. A caller is never told what the writer
believes it did.
"""

from __future__ import annotations

import io
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

from framestack_core.deploy import COMPOSE_FILE, docker_program

__all__ = [
    "EDITABLE",
    "Compose",
    "Service",
    "read_compose",
    "write_compose",
]

#: The fields the panel may change. Everything else is edited in the file itself.
#:
#: `image` is a string; the other four are lists. That difference is in the wire contract as
#: well, because a caller sending the wrong one is confused about what it is editing.
EDITABLE = ("image", "ports", "environment", "volumes", "depends_on")

#: How long `docker compose ps` may take. Short: this is polled while a panel is open, and a
#: check that hung would hold the panel behind it.
SECONDS = 30


@dataclass(frozen=True)
class Service:
    """One service: what the file declares about it, and what the daemon says it is doing."""

    name: str
    #: `""` where the service builds its own image rather than pulling one. Not a failure --
    #: a `build:` service is ordinary, and it is `examples/full`'s own `api`.
    image: str
    ports: tuple[str, ...]
    #: The short form, `KEY=value`, whichever of compose's two forms the file uses. A write
    #: puts back the form that was there.
    environment: tuple[str, ...]
    volumes: tuple[str, ...]
    depends_on: tuple[str, ...]
    #: What `docker compose ps` reports: `running`, `exited`, `created`... `""` means the
    #: daemon has no container for it, which is a different claim from `exited` and is never
    #: merged with one.
    state: str
    #: The host ports the daemon actually published, `"5432"`. Empty while nothing is up.
    published: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "image": self.image,
            "ports": list(self.ports),
            "environment": list(self.environment),
            "volumes": list(self.volumes),
            "depends_on": list(self.depends_on),
            "state": self.state,
            "published": list(self.published),
        }


@dataclass(frozen=True)
class Compose:
    """The answer to every verb here. A refusal is a result, never a protocol fault."""

    ok: bool
    detail: str
    #: Whether there is a `compose.yaml` at all. A project without one is ordinary.
    present: bool
    #: Whether there is a docker to ask. Without it the states are empty rather than wrong --
    #: the file still says what it says, and it is still editable.
    available: bool
    path: str
    services: tuple[Service, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "present": self.present,
            "available": self.available,
            "path": self.path,
            "services": [service.as_dict() for service in self.services],
        }


def _yaml() -> YAML:
    """A round-trip loader, configured to give back what it was given.

    `preserve_quotes` because `"8000:8000"` unquoted is the number 8000 in YAML's sexagesimal
    reading of it, and rewriting somebody's quoting is exactly the collateral damage this
    module exists to avoid. The width is enormous for the same reason: a re-wrapped line is a
    diff nobody asked for.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _load(path: Path) -> tuple[Any, str]:
    """`(the document, "")`, or `(None, why not)`. A file we cannot parse is never guessed at."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{COMPOSE_FILE} could not be read: {exc}"
    try:
        document = _yaml().load(text)
    except YAMLError as exc:
        return None, f"{COMPOSE_FILE} is not valid YAML: {exc}"
    if not isinstance(document, dict):
        return None, f"{COMPOSE_FILE} does not describe a stack"
    return document, ""


def _strings(value: Any) -> tuple[str, ...]:
    """A compose list, as strings, whichever of its forms it was written in.

    `environment` may be a mapping or a sequence, and `depends_on` may be a mapping with
    conditions under it. Both are reported in the short form, because that is the form a
    person edits and the one a text field can hold.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(f"{key}={'' if item is None else item}" for key, item in value.items())
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                # `ports:` long form, `depends_on:` with a condition. Named, never expanded:
                # a panel that flattened one would offer to write back something else.
                name = item.get("target") or item.get("source") or ""
                out.append(str(name) if name else json.dumps(item, sort_keys=True))
            else:
                out.append(str(item))
        return tuple(out)
    return (str(value),)


def _declared(document: Any) -> dict[str, Any]:
    services = document.get("services") if isinstance(document, dict) else None
    return services if isinstance(services, dict) else {}


def _running(docker: str, root: Path) -> dict[str, tuple[str, tuple[str, ...]]]:
    """What the daemon has for this project, keyed by service.

    Asked with `--format json`, which compose has emitted line-per-object for most of its
    life and as one array in recent versions. Both are accepted: a state nobody could read
    would be drawn as "no container", which is a claim about the stack rather than about us.
    """
    try:
        answer = subprocess.run(  # noqa: S603 -- docker, located by `docker_program`
            [docker, "compose", "-f", COMPOSE_FILE, "ps", "--all", "--format", "json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if answer.returncode != 0:
        return {}

    rows: list[Any] = []
    text = answer.stdout.strip()
    if not text:
        return {}
    try:
        one = json.loads(text)
        rows = one if isinstance(one, list) else [one]
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    found: dict[str, tuple[str, tuple[str, ...]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Service") or "")
        if not name:
            continue
        ports: list[str] = []
        for publisher in row.get("Publishers") or []:
            if isinstance(publisher, dict) and publisher.get("PublishedPort"):
                ports.append(str(publisher["PublishedPort"]))
        found[name] = (str(row.get("State") or ""), tuple(dict.fromkeys(ports)))
    return found


def read_compose(project: Path | str) -> Compose:
    """What the stack is made of, and what of it is up. A read: it brings nothing up.

    It spawns `docker compose ps`, which is not a contradiction of P11 -- asking the daemon
    what it already holds starts nothing.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return Compose(False, f"there is no project at {root}", False, False, COMPOSE_FILE)
    path = root / COMPOSE_FILE
    if not path.is_file():
        return Compose(True, f"there is no {COMPOSE_FILE} here", False, False, COMPOSE_FILE)

    document, why = _load(path)
    if document is None:
        return Compose(False, why, True, False, COMPOSE_FILE)

    docker, _ = docker_program()
    live = _running(docker, root) if docker else {}

    services: list[Service] = []
    for name, body in _declared(document).items():
        entry = body if isinstance(body, dict) else {}
        state, published = live.get(str(name), ("", ()))
        image = entry.get("image")
        services.append(
            Service(
                name=str(name),
                image=str(image) if isinstance(image, (str, int, float)) else "",
                ports=_strings(entry.get("ports")),
                environment=_strings(entry.get("environment")),
                volumes=_strings(entry.get("volumes")),
                depends_on=_strings(entry.get("depends_on")),
                state=state,
                published=published,
            )
        )

    return Compose(
        True,
        f"{len(services)} service(s)",
        True,
        bool(docker),
        COMPOSE_FILE,
        tuple(services),
    )


def _refused(reading: Compose, detail: str) -> Compose:
    """The current reading, carrying a refusal.

    A refusal answers with the file **as it still is**, because that is the honest thing to
    draw: nothing was written, and a panel showing the value it tried to set would be showing
    a file that does not exist.
    """
    return Compose(
        False, detail, reading.present, reading.available, reading.path, reading.services
    )


def _as_written(existing: Any, values: tuple[str, ...]) -> Any:
    """The new value, in the form the file already used.

    A file that wrote `environment` as a mapping gets a mapping back. Rewriting it as a list
    would be correct compose and a diff on every line of it, which is the whole of what this
    module refuses to do.
    """
    if isinstance(existing, dict):
        out = CommentedMap()
        for line in values:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
        return out
    return CommentedSeq(
        [DoubleQuotedScalarString(line) if _quoted(existing) else line for line in values]
    )


def _quoted(existing: Any) -> bool:
    """Whether this list was written with its entries in quotes.

    Compose files quote ports (`"8000:8000"`) and leave volumes bare, and both are ordinary.
    The style is the file's, not ours: a writer that imposed its own would make the *one*
    line a person changed look like a house-style sweep, and reviewing that diff is exactly
    the work this module is supposed to save.
    """
    if not isinstance(existing, list) or not existing:
        return False
    return all(
        isinstance(item, (DoubleQuotedScalarString, SingleQuotedScalarString)) for item in existing
    )


def write_compose(project: Path | str, service: str, field: str, value: Any) -> Compose:
    """Change one field of one service, and give back the file re-read.

    Everything the edit was not about stays byte-identical. A refused write leaves the file
    untouched -- never half-applied, and never reported as done.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return Compose(False, f"there is no project at {root}", False, False, COMPOSE_FILE)
    path = root / COMPOSE_FILE
    if not path.is_file():
        return Compose(True, f"there is no {COMPOSE_FILE} here", False, False, COMPOSE_FILE)

    if field not in EDITABLE:
        # Named rather than ignored. The five are a decision, and a caller reaching past them
        # is a caller who thinks this is a compose editor.
        return _refused(
            read_compose(project),
            f"{field!r} is not edited from the panel -- only {', '.join(EDITABLE)}",
        )

    document, why = _load(path)
    if document is None:
        return Compose(False, why, True, False, COMPOSE_FILE)
    declared = _declared(document)
    if service not in declared or not isinstance(declared[service], dict):
        return _refused(
            read_compose(project), f"{COMPOSE_FILE} declares no service named {service!r}"
        )

    entry = declared[service]
    if field == "image":
        if not isinstance(value, str) or not value.strip():
            return _refused(read_compose(project), "'image' must be a non-empty string")
        entry["image"] = value.strip()
    else:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return _refused(read_compose(project), f"{field!r} must be a list of strings")
        lines = tuple(item for item in (line.strip() for line in value) if item)
        if not lines:
            # An empty list removes the key rather than writing `ports: []`. Compose needs
            # neither, and the shorter of the two is the one a person would have written.
            entry.pop(field, None)
        else:
            entry[field] = _as_written(entry.get(field), lines)

    buffer = io.StringIO()
    try:
        _yaml().dump(document, buffer)
    except YAMLError as exc:
        return _refused(read_compose(project), f"the edit could not be written: {exc}")
    try:
        path.write_text(buffer.getvalue(), encoding="utf-8")
    except OSError as exc:
        return _refused(read_compose(project), f"{COMPOSE_FILE} could not be written: {exc}")

    # The file re-read, never a description of what the writer believes it did.
    return read_compose(project)
