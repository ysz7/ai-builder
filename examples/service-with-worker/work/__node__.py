"""The background work as a subsystem of its own.

A group beside the service's group, not inside it: the tasks outlive the request that
queued them, and they run in a process the service never starts. What connects the two is
a flow arrow, and only after a run has drawn one.
"""

from bp import group_node
from work.queue import TaskQueue
from work.schedule import beat_schedule
from work.tasks import build_report, sweep_reports

workers = group_node(
    id="work",
    kind="queue.workers",
    title="Background Work",
    members=[TaskQueue, build_report, sweep_reports, beat_schedule],
)
