"""The service's own tests.

Ordinary FastAPI tests, written the way any project would write them -- no markup, no
knowledge of the builder. That is the point: this is the run the graph observes (Q7), so
it has to be the run the project would have had anyway. The builder instruments the
carriers while these execute and records which nodes actually fired; nothing here is
arranged for its benefit.

`POST /users` is here for the same reason. It is the route no direct call can prove
without inventing a request body, and the only place a valid body can come from is
someone who knows what a user is.
"""

from fastapi.testclient import TestClient


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_listing_users_returns_the_seeded_two(client: TestClient) -> None:
    response = client.get("/users")

    assert response.status_code == 200
    assert [user["name"] for user in response.json()] == ["ada", "grace"]


def test_listing_users_respects_an_explicit_limit(client: TestClient) -> None:
    response = client.get("/users", params={"limit": 1})

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_creating_a_user_returns_it_with_an_id(client: TestClient) -> None:
    response = client.post("/users", json={"name": "hopper"})

    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "hopper"
    assert created["id"] > 0


def test_a_created_user_is_then_listed(client: TestClient) -> None:
    client.post("/users", json={"name": "lovelace"})

    listed = client.get("/users").json()

    assert "lovelace" in [user["name"] for user in listed]


def test_the_settings_carry_their_declared_defaults() -> None:
    from app.settings import ApiSettings

    settings = ApiSettings()

    assert settings.page_size == 25
    assert settings.log_level == "info"
