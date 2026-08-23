"""Service knobs.

`poll_after_s` is what the service tells a caller about work it has just queued. It is a
property of the API, not of the queue -- the queue's own knobs live on its node.
"""

from typing import Annotated

from pydantic import BaseModel

from bp import Param, node


@node(id="api.settings", kind="fastapi.settings", title="Settings")
class ApiSettings(BaseModel):
    poll_after_s: Annotated[int, Param(min=1, max=600, step=1, label="Suggested poll delay")] = 5


settings = ApiSettings()
