"""Test configuration: its presence puts the project root on `sys.path`.

The queue runs its tasks in this process for the duration of the suite. That is celery's
own testing mode, and it is honest about what it proves: the task's code, with real input,
from the code path that queues it. **It does not prove delivery** -- that a broker took the
message and a worker picked it up is what the queue node's own check and the worker button
are for.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from work.queue import celery_app


@pytest.fixture(scope="session", autouse=True)
def tasks_run_here() -> None:
    celery_app.conf.task_always_eager = True


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
