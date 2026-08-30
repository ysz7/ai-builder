# Gmail MCP server

A server this project **consumes**: search, read and send mail. The node is the declaration
of how to reach a foreign program, never the program itself (P15).

## What it lands

`integrations/gmail_server.py` — one `mcp.server` node whose knobs hold the command, its
arguments, a connect timeout, the **name** of the environment variable carrying the
server's credentials, and which of its tools this project allows itself to call.

## The credential

`token_env` holds a variable's **name** and never its value: a knob that held a secret
would put somebody's key into the repository on the first write. Set the value in the
builder's Environment panel — and make sure the project loads `.env` itself
(`SettingsConfigDict(env_file=".env")` or `load_dotenv()`), because the builder never
injects one.

The server behind these arguments runs its own Google OAuth flow the first time it starts.

## It needs a home

An `mcp.server` is never top-level. Claim it as a member of the group that consumes it —
usually the agent — which is a second press after the insert. Until then the gate reports
`node.top_level_not_group` against this node, which is correct rather than broken.

## Proving it

`mcp.server_reachable` never connects, and no flag makes it. Press Inspect, or let the
project's own tests exercise a carrier that calls through `connect()`. Check the tool names
this node allows against what the server actually offers — Inspect reports the ones that
are allowed but not offered.
