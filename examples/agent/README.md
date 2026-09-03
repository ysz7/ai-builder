# agent

An agent with three tools and one MCP server. `run` takes a message, calls the tools the
message names, and answers — with no model and no key, because `OFFLINE=true`.

```
agent/          run(message, **kw) -> str
agent/tools/    one file per tool: arithmetic, clock, notes
mcp.json        one server the agent is configured to reach
```

Talk to it:

```bash
docker compose run --rm agent python -c "import agent; print(agent.run('calculate: 2 * 21'))"
```

Or run its tests, with the builder uninstalled:

```bash
pip install -r requirements.txt pytest
pytest
```

Set `OFFLINE=false` and the marked line in `agent/loop.py` is where a model call belongs. The
compose stack brings up Ollama for that, so nothing has to leave the machine.

Nothing in `.env` is a credential.
