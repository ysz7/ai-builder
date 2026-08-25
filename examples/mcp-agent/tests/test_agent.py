"""The agent's own tests, and therefore the run the graph observes.

The consult step really connects: a stdio server started as a real process, spoken to over
a real transport. No account, no key and no network is involved, so the interesting path is
exercised on any machine rather than skipped everywhere a service is missing.
"""

from agent.graph import ask, graph
from agent.servers import notes
from agent.tools import shout


def test_the_agent_shouts_then_summarizes_through_the_server() -> None:
    final = ask("keep this. drop that.")

    assert final["answer"] == "KEEP THIS."


def test_the_local_tool_is_an_ordinary_function() -> None:
    assert shout("quiet") == "QUIET"


def test_the_tool_is_bound_to_the_agent() -> None:
    assert "tools" in set(graph.nodes)


def test_the_declaration_names_only_tools_the_server_offers() -> None:
    import asyncio

    async def offered() -> set[str]:
        async with notes.connect() as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    assert set(notes.allowed_tools.split(",")) <= asyncio.run(offered())
