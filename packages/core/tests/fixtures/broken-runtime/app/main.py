"""App assembly. Correct in every way the parser can see."""

from bp import generated
from fastapi import FastAPI

from app.routes import boom, healthy


@generated()
def create_app() -> FastAPI:
    # GENERATED. App assembly; edited through the graph, not by hand.
    app = FastAPI(title="Broken service")
    app.add_api_route("/healthy", healthy, methods=["GET"])
    app.add_api_route("/boom", boom, methods=["GET"])
    return app


app = create_app()
