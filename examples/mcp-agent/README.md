# Example: an agent with tools, and MCP on both sides

The project P15 is proven on. Three roles wear the word "tool" and none of them is the
others, so this example has one of each:

| Role | Here | Kind |
| --- | --- | --- |
| **local tool** | `shout`, a function the agent may call | `langgraph.tool` |
| **provider** | the `notes` server this project offers over stdio | `mcp.service` + `mcp.tool` |
| **consumer** | the declaration of how to reach that server | `mcp.server` |

Two top-level groups. `agent` is the agent, and the consumed server is a **member of it** —
reaching that server is something the agent does, and the declaration is the agent's code.
`tools` is the server this project *exposes*, a subsystem of its own, because it is a
program other people connect to and it runs whether the agent does or not.

The server it consumes is its own (`python -m server`). That is deliberate: a real stdio
transport between two real processes, with no account, no key and no network — so the
interesting path is exercised on any machine rather than skipped everywhere a service is
missing. A third party's server would look identical on the graph, with different knob
values.

## What proves what

| Node | Proven by |
| --- | --- |
| `agent.shout` | a run that entered it — the project's own tests |
| `tools.summarize`, `tools.word_count` | the same |
| `tools` | the server being assembled with tools on it |
| `agent.notes` | **connecting**, which is a button and never a side effect |

```bash
uv run python -m framestack_core check examples/mcp-agent --observe
uv run python -m framestack_core inspect examples/mcp-agent agent.notes
uv run python -m framestack_core tool examples/mcp-agent agent.notes summarize '{"text": "One. Two."}'
```

The run draws the flow, and nothing else does (Q9):

```
agent.plan ──observed──▶ agent.shout ──observed──▶ agent.consult ──observed──▶ agent.notes
```

Nothing declared those arrows and nothing parsed them out of the assembly code. A test asked
the agent a question, the run went that way, and the run is what drew it.

## The rules this example exists to hold

**A remote tool is contents, not a node** (Q12). What the notes server offers is read from
`tools/list` after a connect and shown on the node; the subset this project may call is a
knob. Our own tools *are* nodes, because they have carriers — and that includes the tools of
the server this project writes itself, since its own server is its own code.

**Connecting is an action, never a side effect of reading** (P11). `check --observe` never
opens a connection: with no run to go on, `agent.notes` is `unproven` with the button named,
the same shape as a compose file whose services are down. There is no flag that changes
that. What the example's own tests do is a different matter — they really connect, and that
is the project's run, so its evidence counts.

**Three verdicts, and the line between them is the one the whole system draws.** No
connection or no token → `unproven`. The server answered and rejected our credentials →
`unproven` with the reason, because the fix is not in the code. The server answered and
this project names a tool it does not offer → **broken**: that is not an environment, it is
code referring to something that does not exist, and finding out here beats finding out in
production.

**A knob never holds a secret.** `token_env` holds the *name* of an environment variable.
A knob is a syntax node in this project's source, so a token written into one would go
straight to git.

**Calls go through the project's own object.** `notes.connect()` returns a client to
`async with`. Straight into the SDK and the tracer sees only library frames — no arrow, no
evidence that the agent uses this server at all.

**A tool's carrier stays a plain function**, exposed or bound in a generated zone
(`server.add_tool(summarize, ...)`, `StructuredTool.from_function(shout, ...)`). Same split
the routes and the tasks follow, and for the same reason: a carrier wrapped in a decorator
is no longer the function the graph named.

**If it is not on the graph, it is not in the code.** Add a tool to the server or construct
a client without markup and the graph reports it with its address — including from a file
with no markup in it at all, which is exactly the file the rule exists for.
