"""Two routes. One works, one does not."""

from bp import editable, node


@node(id="healthy", kind="fastapi.route", title="Healthy")
@editable(signature_locked=True)
def healthy() -> dict[str, str]:
    return {"status": "ok"}


@node(id="boom", kind="fastapi.route", title="Boom")
@editable(signature_locked=True)
def boom() -> dict[str, str]:
    # Annotated exactly as the rules require, and wrong at runtime. That gap is the
    # whole reason acceptance condition 2 exists.
    raise RuntimeError("this endpoint was never going to work")
