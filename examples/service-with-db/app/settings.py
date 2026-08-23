"""Service knobs.

`dsn` names the database the compose file declares. The two files describe different things
-- one what the service is, the other how the application reaches it -- and neither is
generated from the other.
"""

from typing import Annotated

from pydantic import BaseModel

from bp import Param, node


@node(id="api.settings", kind="fastapi.settings", title="Settings")
class ApiSettings(BaseModel):
    dsn: Annotated[str, Param(label="Database URL")] = (
        "postgresql://notes:notes@localhost:55432/notes"
    )
    page_size: Annotated[int, Param(min=1, max=200, step=10, label="Notes per page")] = 20


settings = ApiSettings()
