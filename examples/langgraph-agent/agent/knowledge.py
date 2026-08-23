"""The tiny corpus the agent looks things up in.

Ordinary module-level data, outside every carrier, so the graph neither shows it nor
classifies it. It is here so the example needs no network and no model: an agent that
could only be observed with an API key could not be observed in CI at all.
"""

NOTES: dict[str, str] = {
    "blueprints": "Unreal Blueprints project compiled state; they are never a second source.",
    "graph": "A node is green only when it parses and passes its observable check.",
    "markup": "The markup layer is inert: strip it and the application runs identically.",
}


def lookup(question: str) -> list[str]:
    """Every note whose key appears in the question. Deliberately dumb and deterministic."""
    return [note for key, note in NOTES.items() if key in question.lower()]
