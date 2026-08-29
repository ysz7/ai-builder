# Example: a service with a database and a vector store

The project P12 is proven on: a FastAPI service that stores notes in Postgres and searches
them by vector similarity, with the database declared in `compose.yaml`.

Three kinds of node, each proven by a different thing, and none of them by a guess:

- **`db.session`** on `app/db.py` — the module that owns the connection. Its check opens the
  connection and closes it. The container behind it is not this node: that is
  `compose.yaml`, a node of its own carried by the file itself.
- **`vector.store`** on `app/vectors.py` — embedding and similarity search, with `top_k` and
  the vector size as its knobs. Adding and searching both need real input, so what this node
  actually does is proven by `tests/`, and nowhere else.
- **`docker.compose`** on `compose.yaml` — the services this project declares. Its check is
  whether anything answers where they publish, and starting them is the button on it.

With the database down, every node here is green or unproven and none is broken — a service
that is not running says nothing about the code that would have used it. Bring it up and the
same run proves the rest:

```bash
uv run python -m framestack_core env-up examples/service-with-db
uv run python -m framestack_core check examples/service-with-db --observe
uv run python -m framestack_core env-down examples/service-with-db
```

The embedding is a hash spread over sixteen dimensions — deterministic, local, no key and no
model download, for the same reason every other example avoids one. The storage and the
search are the real thing: `pgvector`, and the `<->` operator doing the work.
