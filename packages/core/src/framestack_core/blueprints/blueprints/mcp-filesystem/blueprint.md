# Filesystem MCP server

A server this project **consumes**: read, list and search files under roots the node
allows. The node is the declaration of how to reach a foreign program, never the program
itself — the same relation a compose file has to `redis:7-alpine` (P15).

## What it lands

`integrations/filesystem_server.py` — one `mcp.server` node with the knobs that decide the
connection: the command, its arguments, the roots the server may see, a connect timeout,
and which of the server's tools this project allows itself to call.

## It needs a home

An `mcp.server` is never top-level: the top level holds groups only, so this node must be
claimed as a member of the group that consumes it — usually the agent. Inserting lands the
file; claiming is the second press, and until it happens the gate reports
`node.top_level_not_group` against this node, which is correct rather than broken.

## What it does not do

Nothing is written down about the connection, so a stale graph is impossible rather than
merely unlikely. Nothing is started by drawing it. The remote tools it offers are read from
`tools/list` when somebody presses Inspect and are **contents, never nodes** — they have no
carrier here (Q12).

## Proving it

`mcp.server_reachable` never connects, and no flag makes it. Evidence comes from pressing
Inspect, or from the project's own tests exercising a carrier that calls through
`connect()`. A node this entry lands is **unproven** until one of those happens.
