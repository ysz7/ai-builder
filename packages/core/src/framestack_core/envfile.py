"""One key in the project's `.env`, read and written a line at a time.

`.env` is a file node: shown, opened, edited, never coloured. It is also where a secret
belongs — gitignored, visible, debuggable, and the same place the project's own code already
looks. A keychain can come later as a setting; this ships first because a person can open it.

## Line-wise on purpose, and never a parser

That file belongs to the person and to whatever loads it at runtime. A reader of ours that
understood the whole format would be a second opinion about it, and it would be wrong in
exactly the ways a hand-written file is interesting: quoting, `export`, multi-line values,
a comment after a value. So this finds a key at the start of a line, replaces the rest of
that line, and appends when there is none — and **everything the edit is not about stays
exactly as it was left**, comments, ordering and blank lines included. The same promise the
settings writer makes about a `.py`, kept with the tool a text file deserves.

## Names leave, values do not

`names` exists because a payload may say *that* a key is set and must never say what it is:
a secret in a payload is one console log away from being somewhere permanent. `read_value`
is for this process's own use — a token about to be put in an `Authorization` header — and
what it returns goes into a request, never into an answer.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["ENV_FILE", "names", "read_value", "write_value"]

#: The one file. The convention names it, and the file node draws it.
ENV_FILE = ".env"

#: What a key may be called. Deliberately narrow: this is used to build a variable name out
#: of a server's name, and a name that cannot be written safely is refused rather than
#: mangled into one that can.
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _at(line: str, key: str) -> bool:
    """Whether this line sets `key`. `export FOO=` counts; `# FOO=` does not."""
    stripped = line.strip()
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    return stripped.startswith(f"{key}=")


def names(project: Path | str) -> set[str]:
    """The variable **names** the file sets. No value is ever read out of it here."""
    path = Path(project) / ENV_FILE
    found: set[str] = set()
    for line in _lines(path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        found.add(stripped.split("=", 1)[0].strip())
    return found


def read_value(project: Path | str, key: str) -> str:
    """One value, for this process's own use. What it returns goes into a request, never
    into a payload — see the module docstring."""
    if not KEY.match(key):
        return ""
    for line in _lines(Path(project) / ENV_FILE):
        if not _at(line, key):
            continue
        value = line.strip()
        if value.startswith("export "):
            value = value[len("export ") :].lstrip()
        return value[len(key) + 1 :].strip().strip("\"'")
    return ""


def write_value(project: Path | str, key: str, value: str) -> bool:
    """Set one key. Replaces its line where there is one, appends where there is not.

    The file is created when it is missing, because a project that has never had one is the
    ordinary case for the first secret it is given.
    """
    if not KEY.match(key):
        return False
    path = Path(project) / ENV_FILE
    lines = _lines(path)
    for index, line in enumerate(lines):
        if _at(line, key):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True
