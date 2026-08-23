"""Service knobs.

`cache_host` and `cache_port` name the service the compose file declares. They are ordinary
knobs with literal defaults -- the graph writes them, and nothing here is derived from the
compose file: that file describes the service, this describes how the application reaches
it, and neither is generated from the other.
"""

from typing import Annotated

from pydantic import BaseModel

from bp import Param, node


@node(id="api.settings", kind="fastapi.settings", title="Settings")
class ApiSettings(BaseModel):
    cache_host: Annotated[str, Param(label="Cache host")] = "localhost"
    cache_port: Annotated[int, Param(min=1, max=65535, label="Cache port")] = 6379
    connect_timeout_s: Annotated[float, Param(min=0.1, max=10.0, step=0.1)] = 1.0


settings = ApiSettings()
