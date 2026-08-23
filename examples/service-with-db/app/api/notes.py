"""The notes routes: write one, search them."""

from pydantic import BaseModel

from app.vectors import vectors
from bp import editable, generated, node


class NoteIn(BaseModel):
    body: str


class NoteOut(BaseModel):
    id: int


@node(id="notes.add", kind="fastapi.route", title="Add note")
@editable(signature_locked=True)
def add_note(payload: NoteIn) -> NoteOut:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return NoteOut(id=vectors.add(payload.body))


@node(id="notes.search", kind="fastapi.route", title="Search notes")
@editable(signature_locked=True)
def search_notes(q: str) -> list[str]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return vectors.search(q)


@node(
    id="notes",
    kind="fastapi.router",
    title="Notes",
    members=[add_note, search_notes],
)
@generated()
def notes_router() -> object:
    # GENERATED. Route registration; edited through the graph, not by hand.
    from fastapi import APIRouter

    router = APIRouter(prefix="/notes", tags=["notes"])
    router.add_api_route("", add_note, methods=["POST"], response_model=NoteOut, status_code=201)
    router.add_api_route("/search", search_notes, methods=["GET"], response_model=list[str])
    return router
