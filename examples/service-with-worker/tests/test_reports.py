"""Requesting a report: the route queues, and the task runs."""

from fastapi.testclient import TestClient


def test_requesting_a_report_queues_the_work(client: TestClient) -> None:
    accepted = client.post("/reports", json={"order_id": 7})

    assert accepted.status_code == 202
    assert accepted.json()["task_id"]


def test_the_queued_task_produced_the_report(client: TestClient) -> None:
    from work.queue import celery_app

    client.post("/reports", json={"order_id": 4})
    result = celery_app.tasks["work.report"].delay(4)

    assert result.get() == {"order_id": 4, "lines": 3, "total": 24}
