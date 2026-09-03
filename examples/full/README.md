# full

The whole convention in one project, and the one this builder is written against.

```
rag/            search(query, **kw) -> list      index(paths) -> None
agent/          run(message, **kw) -> str        one tool per file in agent/tools/
api/            app                              routes/, and routes/chat.py
worker/         HANDLERS                         (dict[str, Callable])
repositories/   two tables, and the only place that talks to the database

.env  compose.yaml  Dockerfile  mcp.json         file nodes: shown, never coloured
```

```bash
docker compose up                     # api on :8000, postgres beside it
open http://localhost:8000/chat
```

Or its tests, with the builder uninstalled — they use SQLite, so nothing has to be running:

```bash
pip install -r requirements.txt pytest
pytest
```

Nothing here only Framestack understands: no decorator, no marker, no manifest. The structure
*is* the directory layout, and nothing in `.env` is a credential.

`agent/tools/look_up.py` imports from `rag`, which is the only reason there is an edge
between those two nodes. Removing the import removes the edge.
