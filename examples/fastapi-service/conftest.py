"""Test configuration.

Its presence is what puts the project root on `sys.path`, so `import app` works when
pytest is run from anywhere -- the ordinary FastAPI arrangement, and nothing to do with
the builder.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
