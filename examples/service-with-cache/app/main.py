"""App assembly. Generated zone from top to bottom."""

from fastapi import FastAPI

from app.api.counter import counter
from app.api.health import health
from bp import generated


@generated()
def create_app() -> FastAPI:
    # GENERATED. App assembly; edited through the graph, not by hand.
    app = FastAPI(title="Cached Service")
    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/counter", counter, methods=["GET"])
    return app


app = create_app()
