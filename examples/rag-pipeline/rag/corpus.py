"""The documents the pipeline indexes.

Module-level data outside every carrier, so the graph neither shows it nor classifies it.
It is here so the example needs no network, no API key and no model download: a pipeline
that could only be observed with credentials could not be observed in CI at all.
"""

DOCUMENTS: list[str] = [
    "Unreal Blueprints render compiled state. The graph is a projection of the code, "
    "never a second source of truth, which is why a node cannot exist without a carrier.",
    "A node is green only when it parses and passes its observable check. A check that "
    "could not run reports skipped, and the node stays unproven rather than fine.",
    "The markup layer is inert. Strip it and the application runs identically; that is "
    "the property the whole design is arranged around.",
]
