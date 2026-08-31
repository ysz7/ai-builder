# reference

The project the builder is written against: four systems, four file nodes, and a test suite
that proves each export does something.

```
rag/       search(query, **kw) -> list      index(paths) -> None
agent/     run(message, **kw) -> str
api/       app                              (a plain ASGI application)
worker/    HANDLERS                         (dict[str, Callable])

.env  compose.yaml  Dockerfile  mcp.json    file nodes: shown, opened, never coloured
```

There is nothing here that only Framestack understands. No decorator, no marker, no
manifest -- the structure *is* the directory layout, and `pytest` in this directory works
with the builder uninstalled:

```bash
pip install -r requirements.txt pytest
pytest
```

`agent/tools.py` imports from `rag`, which is the only reason there is an edge between
those two nodes. Removing the import removes the edge.
