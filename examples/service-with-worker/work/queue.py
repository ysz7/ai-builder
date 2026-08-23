"""The task queue: the broker it talks to, and the knobs a worker is run with.

The node here is the **Python that owns the queue**, never the container behind it -- that
one is `compose.yaml`, a node of its own carried by the file itself. The knobs go into
celery's own configuration, which is what makes them answerable: the builder asks celery
what concurrency it is configured for rather than remembering what it wrote.
"""

from typing import Annotated

from celery import Celery

from bp import Param, generated, node


@node(id="work.queue", kind="queue.app", title="Task queue")
class TaskQueue:
    """The queue's configuration. Every knob here reaches celery, or it is decoration."""

    broker_url: Annotated[str, Param(label="Broker URL")] = "redis://localhost:56379/0"
    concurrency: Annotated[int, Param(min=1, max=16, label="Worker concurrency")] = 2
    task_time_limit_s: Annotated[int, Param(min=1, max=3600, step=10, label="Time limit (s)")] = 300
    sweep_every_s: Annotated[int, Param(min=60, max=86400, step=60, label="Sweep every (s)")] = 3600

    @generated()
    def build(self) -> Celery:
        # GENERATED. Queue assembly; edited through the graph, not by hand.
        app = Celery("work", broker=self.broker_url)
        app.conf.worker_concurrency = self.concurrency
        app.conf.task_time_limit = self.task_time_limit_s
        return app


queue = TaskQueue()
celery_app = queue.build()
