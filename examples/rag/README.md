# rag

Upload a document, index it, ask about it. Two systems and no database — the index is a JSON
file, and swapping it for pgvector changes nothing outside `rag/store.py`.

```
rag/    search(query, **kw) -> list      index(paths) -> None
api/    app                              (a plain ASGI application)
```

Run it:

```bash
docker compose up
curl 'localhost:8000/upload?name=otters.txt&text=Otters+hold+hands.'
curl 'localhost:8000/ask?q=otters'
```

Or run its tests, with the builder uninstalled:

```bash
pip install -r requirements.txt pytest
pytest
```

Nothing in `.env` is a credential: this project talks to nothing that needs one.
