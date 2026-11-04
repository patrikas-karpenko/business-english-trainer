import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("UNLOCK_ALL", "1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        c.post("/login", data={"name": "Tester"})
        yield c
