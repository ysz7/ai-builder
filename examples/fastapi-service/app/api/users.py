"""The users router and its routes.

Three carriers, three nodes: two route handlers whose bodies belong to the user, and the
router that assembles them, whose body does not. `@node` and `@editable`/`@generated` are
orthogonal -- `users_router` is a visible node *and* generated zone.

Registration lives in the router body on purpose: it is mechanical, so the parser reads it
reliably, and it keeps each handler a plain function the graph can address on its own.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.settings import settings
from bp import editable, generated, node


class User(BaseModel):
    id: int
    name: str


class UserCreate(BaseModel):
    name: str


_USERS: list[User] = [User(id=1, name="ada"), User(id=2, name="grace")]


@node(id="users.list", kind="fastapi.route", title="List users")
@editable(signature_locked=True)
def list_users(limit: int | None = None) -> list[User]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return _USERS[: limit or settings.page_size]


@node(id="users.create", kind="fastapi.route", title="Create user")
@editable(signature_locked=True)
def create_user(payload: UserCreate) -> User:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    created = User(id=max((u.id for u in _USERS), default=0) + 1, name=payload.name)
    _USERS.append(created)
    return created


@node(
    id="users",
    kind="fastapi.router",
    title="Users",
    # The routes this router contains. Declared, not inferred: the body references them
    # too, but a reference may be shared between routers and a parent may not.
    members=[list_users, create_user],
)
@generated()
def users_router() -> APIRouter:
    # GENERATED. Route registration; edited through the graph, not by hand.
    router = APIRouter(prefix="/users", tags=["users"])
    router.add_api_route("", list_users, methods=["GET"], response_model=list[User])
    router.add_api_route("", create_user, methods=["POST"], response_model=User, status_code=201)
    return router
