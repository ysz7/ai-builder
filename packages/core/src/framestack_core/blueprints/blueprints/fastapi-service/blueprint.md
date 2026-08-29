# FastAPI service

An HTTP service with its routers, its routes, its dependencies and one settings object —
the shape every FastAPI project converges on, annotated so the graph can draw it and the
checks can prove it.

## Architecture

A **group over the routers and the settings**. The service is the subsystem, the routers are
what it mounts, and the routes are what they own; the settings class is a member rather than
a detail, because it is the home of the service's knobs and a person setting `page_size` is
looking for a node, not a file.

`app/main.py` assembles the application. That assembly is a **generated zone**: it is written
by the graph when a router is added, and edited through the node rather than by hand.

## Contracts

- `app.main:app` — the ASGI application, and what `run.*` starts
- each router exposes an `APIRouter`, mounted with a prefix
- each route is a plain function with typed parameters and a typed return
- settings are a class of annotated fields with literal defaults

## Failure modes this shape avoids

- **Routes that cannot be called without inventing input.** A route with required body
  parameters cannot be proven by a synthesized request, so the tests are what prove it. The
  fixture in `conftest.py` is a `TestClient` over the real application.
- **Settings resolved from the environment at import.** The literal default is what the graph
  reads and writes; a value assembled at import has no address to write to.

## Done when

`pytest` passes, every route is green because a test entered it, and the service answers on
the port it publishes.
