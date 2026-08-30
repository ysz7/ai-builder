"""Places a model can be reached from, and what runs there.

The sixth file in `.framestack/`, and it belongs to the same family as the layout: state the
toolchain keeps *about* a project without the project depending on any of it. Delete it and
nothing changes -- every node still names its own model, the graph is identical, every
verdict is identical. That is the test this file has to keep passing, because a store that
failed it would be the second source of truth I-1 forbids.

**What a node uses is in the node's knobs, in code.** This is a list of options, not a list
of facts: it makes a model nameable in one click instead of retyped, and it is asked nothing
else. No check reads it, no node exists because of it, nothing here can be green, and a knob
holding a model this file has never heard of is an ordinary state rather than a divergence
-- which is why the surface built on it must suggest and never restrict.

**Unlike the layout, this one is understood on purpose.** `layout.py` refuses to look inside
what it stores, and the refusal protects it from ever being asked to produce a layout. Here
the danger runs the other way: the thing a person will try to put in a provider is their
key, and `.framestack/` is a directory in their repository. So the shape is closed and an
entry carrying anything but the four fields below is refused -- `api_key_env` holds the
**name** of an environment variable, exactly as a knob does (P15), and the value belongs in
`.env` where the panel next door puts it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "PROVIDERS_PATH",
    "Provider",
    "ProviderWrite",
    "read_providers",
    "write_providers",
]

#: Beside the layout and the snapshot. Tooling state, never project source.
PROVIDERS_PATH = Path(".framestack") / "providers.json"

#: The whole shape. A fifth field is a decision, not a convenience: see the header.
FIELDS = ("name", "base_url", "api_key_env", "models")

#: Refused outright, whatever else is wrong with the entry. These are the names somebody
#: reaches for when they mean to paste the key itself, and the refusal has to say so rather
#: than store it -- a secret in `.framestack/` is a secret on its way into a commit.
SECRETS = ("api_key", "key", "secret", "token", "password", "credentials")


@dataclass(frozen=True)
class Provider:
    """One place a model can be reached from. Holds no secret and cannot hold one."""

    name: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "models": list(self.models),
        }


@dataclass(frozen=True)
class ProviderWrite:
    """Whether it was stored. A refusal is a result, like every other write here."""

    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail}


def _entry(raw: Any) -> Provider | None:
    """One stored entry, or nothing. A malformed entry is dropped, never repaired."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    models = raw.get("models")
    kept: tuple[str, ...] = ()
    if isinstance(models, list):
        kept = tuple(one.strip() for one in models if isinstance(one, str) and one.strip())
    base_url = raw.get("base_url")
    api_key_env = raw.get("api_key_env")
    return Provider(
        name=name.strip(),
        base_url=base_url.strip() if isinstance(base_url, str) else "",
        api_key_env=api_key_env.strip() if isinstance(api_key_env, str) else "",
        models=kept,
    )


def read_providers(project: Path | str) -> list[Provider]:
    """What was stored, or nothing at all.

    Every failure reads as "nothing stored", for the reason `read_layout` gives: an empty
    list is what a project looks like the first time it is opened, so there is nothing here
    worth reporting as a failure, and a corrupt cache must never stop a panel from drawing.
    """
    path = Path(project) / PROVIDERS_PATH
    if not path.is_file():
        return []
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(stored, list):
        return []
    return [entry for raw in stored if (entry := _entry(raw)) is not None]


def write_providers(project: Path | str, providers: list[dict[str, Any]]) -> ProviderWrite:
    """Store the list, whole. The previous contents are replaced, never merged.

    Refuses before it writes rather than sanitising as it goes: an entry silently stripped of
    the key somebody pasted would leave them believing it had been stored somewhere, and the
    next thing they do is stop looking for where their credential went.
    """
    root = Path(project)
    if not root.is_dir():
        # The same refusal `write_layout` makes, for the same reason: a store for a project
        # that is not there invents the project under a mistyped path.
        return ProviderWrite(False, f"there is no project at {root}")
    if not isinstance(providers, list):
        return ProviderWrite(False, "providers must be a list")

    kept: list[dict[str, Any]] = []
    for raw in providers:
        if not isinstance(raw, dict):
            return ProviderWrite(False, "each provider must be an object")
        for field in raw:
            if field.lower() in SECRETS:
                return ProviderWrite(
                    False,
                    f"'{field}' is refused: a provider holds the *name* of an environment "
                    "variable (api_key_env), never a key. The value belongs in .env.",
                )
            if field not in FIELDS:
                known = ", ".join(FIELDS)
                return ProviderWrite(False, f"'{field}' is not a provider field: {known}")
        entry = _entry(raw)
        if entry is None:
            return ProviderWrite(False, "a provider needs a name")
        kept.append(entry.as_dict())

    names = [one["name"] for one in kept]
    if len(set(names)) != len(names):
        # Two providers of one name make "which one did I pick?" unanswerable, and the
        # panel addresses them by name.
        return ProviderWrite(False, "two providers share a name")

    path = root / PROVIDERS_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(kept, indent=2)
        path.write_text(text + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        return ProviderWrite(
            False, f"the providers could not be stored: {type(exc).__name__}: {exc}"
        )
    return ProviderWrite(True, f"{len(kept)} provider(s) stored")
