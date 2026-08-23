"""The notes routes, which need the database the compose file declares."""

from fastapi.testclient import TestClient


def test_a_note_is_stored_and_found_again(client: TestClient) -> None:
    created = client.post("/notes", json={"body": "the graph is a projection of the code"})

    assert created.status_code == 201
    assert created.json()["id"] > 0

    found = client.get("/notes/search", params={"q": "graph projection"})

    assert found.status_code == 200
    assert any("projection" in note for note in found.json())


def test_search_returns_at_most_top_k(client: TestClient) -> None:
    from app.vectors import vectors

    for index in range(6):
        client.post("/notes", json={"body": f"note number {index}"})

    assert len(client.get("/notes/search", params={"q": "note"}).json()) <= vectors.top_k
