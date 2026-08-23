"""What runs on a timer, with the interval coming from the queue's knob.

The entry names a task by the name it was registered under, and the check asks celery
whether that name is one it knows -- the same wiring question a router asks about a route.
"""

from bp import generated, node
from work.queue import celery_app, queue
from work.tasks import register_tasks  # noqa: F401 -- the tasks must be registered first


@node(id="work.schedule", kind="queue.schedule", title="Sweep schedule")
@generated()
def beat_schedule() -> dict[str, dict[str, object]]:
    # GENERATED. Schedule assembly; edited through the graph, not by hand.
    return {
        "sweep-old-reports": {
            "task": "work.sweep",
            "schedule": float(queue.sweep_every_s),
            "args": (queue.sweep_every_s * 24,),
        }
    }


celery_app.conf.beat_schedule = beat_schedule()
