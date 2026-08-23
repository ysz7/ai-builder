"""The route that hands work to the queue instead of doing it.

It queues by the task's registered name, which is the only handle the queue promises. What
happens next is not this node's evidence: the route is proven when it queued, and the task
is proven when it ran.
"""

from pydantic import BaseModel

from app.settings import settings
from bp import editable, generated, node
from work.queue import celery_app


class ReportRequest(BaseModel):
    order_id: int


class Queued(BaseModel):
    task_id: str
    poll_after_s: int


@node(id="reports.request", kind="fastapi.route", title="Request report")
@editable(signature_locked=True)
def request_report(payload: ReportRequest) -> Queued:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    queued = celery_app.tasks["work.report"].delay(payload.order_id)
    return Queued(task_id=queued.id, poll_after_s=settings.poll_after_s)


@node(id="reports", kind="fastapi.router", title="Reports", members=[request_report])
@generated()
def reports_router() -> object:
    # GENERATED. Route registration; edited through the graph, not by hand.
    from fastapi import APIRouter

    router = APIRouter(prefix="/reports", tags=["reports"])
    router.add_api_route(
        "", request_report, methods=["POST"], response_model=Queued, status_code=202
    )
    return router
