# Example: an annotated FastAPI service

The reference project the toolchain is proven against. It is written the way the
[system prompt](../../packages/core/src/aibuilder_core/prompts/system-prompt-claude-code.md) requires the agent to write, so every rule
in that prompt has a working instance here:

- the service is a **group node** (`app/api/__node__.py`), members by object reference;
- each router is a single-carrier node whose body is generated zone;
- each route handler is a node whose body is `@editable` with a locked signature;
- knobs are `Annotated` fields with literal defaults (`app/settings.py`);
- **no function inside a carrier is unmarked**.

It has no dependency on the toolchain, and `bp` only ever contributes no-ops — which is what
`aibuilder-core strip` proves: strip the markup and this same service still serves the same
responses.

Run it like any FastAPI app:

```bash
uv run uvicorn app.main:app --app-dir examples/fastapi-service
```
