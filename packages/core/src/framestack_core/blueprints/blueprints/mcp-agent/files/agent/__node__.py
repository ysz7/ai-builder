"""The agent node.

The consumed server is a **member of the agent**, not a subsystem of its own: reaching it
is something this agent does, and the declaration is the agent's code. The server this
project *exposes* is the other group, because it is a program of its own.
"""

from agent.servers import NotesServer
from agent.settings import AgentSettings
from agent.state import AgentState
from agent.steps import consult, plan
from agent.tools import shout
from bp import group_node

subsystem = group_node(
    id="agent",
    kind="langgraph.agent",
    title="Notes agent",
    members=[AgentState, plan, consult, shout, NotesServer, AgentSettings],
)
