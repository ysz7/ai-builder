# MCP agent and server

All three roles that wear the word "tool", in one project: a server this project **exposes**,
the same server **consumed** as a foreign program, and a tool **bound** to an agent. It is
the shape that keeps the distinction visible, because the three are not the same thing.

## Architecture

- **A tool this project exposes** is its own code, so it is a node with a carrier.
- **A server this project consumes** is a *declaration of how to reach a foreign program* —
  the node is the declaration, never the server, exactly as a compose file declares
  `redis:7-alpine` without redis's source being in the repository. What the remote offers is
  read from `tools/list` and shown on that node; it has no carrier, so it is not a node.
- **A tool bound to an agent** is a third fact, held by the compiled graph.

Servers are configured in the project's own Python. **A knob holds the name of an environment
variable, never a secret** — the first write of a real key would put it on its way to git.

## Contracts

- `server/app.py` exposes the server; each tool is a plain annotated function
- `agent/servers.py` declares how to reach a server, and `connect()` is how it is reached
- `agent/tools.py` binds tools to the agent
- nothing about a connection is written down, which is what makes a stale graph impossible

## Failure modes this shape avoids

- **Connecting as a side effect of drawing.** Reachability is a check that never connects;
  inspecting and calling are buttons, and they run in the project's own interpreter through
  the project's own `connect()`.
- **A tool the graph does not know about.** Every carrier has a node, checked by asking the
  library what it holds after a run.

## Done when

`pytest` passes, the exposed tools are green because a test entered them, and inspecting the
consumed server lists what it offers.
