"""Curated tests for DevTeam AI example evaluation tasks."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_item_accepts_valid_payload() -> None:
    response = client.post("/items", json={"name": "Demo Item", "quantity": 2})

    assert response.status_code == 201
    assert response.json() == {
        "id": "item-demo-item",
        "name": "Demo Item",
        "quantity": 2,
    }


def test_create_item_rejects_invalid_payload() -> None:
    response = client.post("/items", json={"name": "", "quantity": 0})

    assert response.status_code == 422


def test_jwt_auth_skeleton_accepts_bearer_token() -> None:
    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer header.payload.signature"},
    )

    assert response.status_code == 200
    assert response.json() == {"username": "demo-user", "scopes": ["read:profile"]}


def test_jwt_auth_skeleton_rejects_missing_token() -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing bearer token"}


def test_ping_returns_pong() -> None:
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"message": "pong"}
