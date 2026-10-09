from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["embedding_model"] == "all-MiniLM-L6-v2"


def test_similarity_requires_body() -> None:
    with TestClient(app) as client:
        response = client.post("/api/similarity", json={"source": "hi"})

    assert response.status_code == 422
