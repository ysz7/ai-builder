"""Routes, each broken in exactly one way."""

from bp import editable, generated, node


@node(kind="fastapi.route")  # DEFECT: no id=
@editable()
def nameless() -> dict[str, str]:
    return {}


@node(id="duplicated", kind="fastapi.route")
@editable()
def first() -> None:
    return None


@node(id="duplicated", kind="fastapi.route")  # DEFECT: id already taken by `first`
@editable()
def second() -> None:
    return None


@node(id="shared", kind="fastapi.route")
@editable()
def shared() -> None:
    return None


@node(id="orphan", kind="fastapi.route")  # DEFECT: no parent claims it
@editable()
def orphan() -> None:
    return None


@node(id="invented", kind="fastapi.teleport")  # DEFECT: kind is not registered
@generated()
def invented() -> None:
    return None


# DEFECT: `shared` is claimed here and by the service group as well.
@node(id="router", kind="fastapi.router", members=[shared])
@generated()
def router() -> None:
    return None


def forgotten() -> None:  # DEFECT: neither @editable nor @generated
    return None
