import os

os.environ["ANTHROPIC_API_KEY"] = ""  # tests never call the model; they exercise deterministic paths
os.environ["SARVAM_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

seed()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def teacher_headers(client):
    r = client.post("/v1/auth/login", json={"school_code": "DEMO", "pin": "1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def parent_headers(client):
    r = client.post("/v1/parent/login", json={"school_code": "DEMO", "child_roll": 12,
                                              "parent_phone": "9876500000", "pin": "0000"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def _reset_login_lockout():
    """Wrong-PIN counting is per process; tests that guess wrong on purpose must not lock out later ones."""
    from app.api import parent
    parent._FAILED_LOGINS.clear()
    yield
    parent._FAILED_LOGINS.clear()
