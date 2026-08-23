"""Settings, on the wrong kind of carrier, holding a knob nothing can write to."""

from typing import Annotated

from bp import Param, node


@node(id="settings", kind="fastapi.route")  # DEFECT: a route cannot be carried by a class
class Settings:
    timeout_s: Annotated[int, Param(min=1, max=60)]  # DEFECT: no literal default
