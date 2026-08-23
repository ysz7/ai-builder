"""Test configuration: its presence puts the project root on `sys.path`."""

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def schema() -> None:
    """Create the tables once, against whatever database the settings point at."""
    database.migrate()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
