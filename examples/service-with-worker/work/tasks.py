"""The background tasks, and the generated zone that registers them.

The same split the routes follow: the work is an editable function with a locked signature,
and putting it on the queue is generated assembly. Keeping the carrier a plain function is
what lets a run be *seen* -- the builder watches the code the interpreter enters, and a task
that ran inside a test is the same code object whether a worker or the test called it.
"""

from bp import editable, generated, node
from work.queue import celery_app


@node(id="work.report", kind="queue.task", title="Build report")
@editable(signature_locked=True)
def build_report(order_id: int) -> dict[str, int]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    lines = [order_id * step for step in range(1, 4)]
    return {"order_id": order_id, "lines": len(lines), "total": sum(lines)}


@node(id="work.sweep", kind="queue.task", title="Sweep old reports")
@editable(signature_locked=True)
def sweep_reports(older_than_s: int) -> int:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return max(older_than_s // 3600, 0)


@generated()
def register_tasks(app: object) -> None:
    # GENERATED. Task registration; edited through the graph, not by hand.
    app.task(name="work.report")(build_report)  # type: ignore[attr-defined]
    app.task(name="work.sweep")(sweep_reports)  # type: ignore[attr-defined]


register_tasks(celery_app)
