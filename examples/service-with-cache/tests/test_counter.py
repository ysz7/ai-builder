"""The counter: an ordinary test that needs the service the project declares.

Nothing here knows about the builder, and nothing skips itself when the cache is missing.
It simply fails -- and it is the builder's job to notice that the environment, not the
code, is what was absent.
"""

from fastapi.testclient import TestClient


def test_counting_a_visit_increments(client: TestClient) -> None:
    first = client.get("/counter")
    second = client.get("/counter")

    assert first.status_code == 200
    assert second.json()["visits"] == first.json()["visits"] + 1
