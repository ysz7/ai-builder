"""The agent node.

The subsystem has no single carrier -- the state, the three step nodes and the router are
equal parts of it -- so the top-level node is a group, listing its direct children by
object reference.
"""

from agent.nodes import answer, gather, plan
from agent.routing import enough_notes
from agent.settings import AgentSettings
from agent.state import AgentState
from bp import group_node

subsystem = group_node(
    id="agent",
    kind="langgraph.agent",
    title="Research agent",
    members=[AgentState, plan, gather, answer, enough_notes, AgentSettings],
)
