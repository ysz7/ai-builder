"""App assembly. Generated zone from top to bottom."""

from fastapi import FastAPI

from app.api.health import health
from app.api.reports import reports_router
from bp import generated


@generated()
def create_app() -> FastAPI:
    # GENERATED. App assembly; edited through the graph, not by hand.
    app = FastAPI(title="Reports Service")
    app.add_api_route("/health", health, methods=["GET"])
    app.include_router(reports_router())
    return app


app = create_app()
