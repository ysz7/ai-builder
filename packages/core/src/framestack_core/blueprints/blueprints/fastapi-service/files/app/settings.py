"""Service knobs.

Every field here is a knob: an `Annotated` type carrying `Param`, with a literal default.
The default is what the graph reads and writes -- one unambiguous target -- so nothing here
may be computed, assembled from another field, or produced by a factory.

`widget=` appears only where the type cannot pick the control on its own (architecture
§5.5): `int` and `bool` need none, a closed set of choices does.
"""

from typing import Annotated

from pydantic import BaseModel

from bp import Param, node


@node(id="api.settings", kind="fastapi.settings", title="Settings")
class ApiSettings(BaseModel):
    """The knobs, and the node they are edited from.

    A knob is edited *in* a node, so the settings object is a carrier of its own rather
    than a loose class the graph would have nowhere to show.
    """

    request_timeout_s: Annotated[int, Param(min=1, max=120, label="Request timeout (s)")] = 30
    page_size: Annotated[int, Param(min=1, max=200, step=10, label="Default page size")] = 25
    log_level: Annotated[
        str, Param(widget="select", choices=("debug", "info", "warning", "error"))
    ] = "info"
    cors_origins: Annotated[list[str], Param(widget="tags", help="Allowed origins")] = ["*"]


settings = ApiSettings()
