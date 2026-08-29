"""App assembly.

Generated zone from top to bottom: creating the app, mounting middleware, including
routers. Nothing here is a decision the user makes by hand -- they make it through a node,
and the writer puts it back here.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import health
from app.api.users import users_router
from app.settings import settings
from bp import generated


@generated()
def create_app() -> FastAPI:
    # GENERATED. App assembly; edited through the graph, not by hand.
    app = FastAPI(title="Example Service")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_api_route("/health", health, methods=["GET"])
    app.include_router(users_router())
    return app


app = create_app()
