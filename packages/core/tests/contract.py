"""The payload contract check, shared by the tests that make one.

It lives in a module of its own rather than in a `conftest.py` because the reference project
has a `conftest.py` too, and two of them on `sys.path` are one importable `conftest`. It is
here rather than in one test module because more than one of them needs it.

The payload's shape is a promise made across a gap -- the UI ships separately -- and a schema
snapshot is how that promise is kept honest. Adding a field, removing one, or changing a type
all fail, and the failure is the prompt to decide whether `GRAPH_API_VERSION` has to move.
"""

from __future__ import annotations

import json
from typing import Any


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

    if schema == "<opaque>":
        # Declared as "the core does not look inside this". The contract is the refusal,
        # so there is nothing here to check beyond the fact that something arrived.
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
