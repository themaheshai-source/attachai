from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orbit_ai.app import create_app
from orbit_ai.config import Settings


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    def make_client(data_dir=None):
        data = data_dir or tmp_path
        monkeypatch.setenv("NODE_ENV", "test")
        monkeypatch.setenv("HOST", "127.0.0.1")
        monkeypatch.setenv("PORT", "3000")
        monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key-with-32-characters")
        monkeypatch.setenv("DATA_DIR", str(data))
        monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
        monkeypatch.setenv("DATABASE_PROVIDER", "sqlite")
        monkeypatch.delenv("REPOSITORY_PROVIDER", raising=False)
        monkeypatch.setenv("STORAGE_PROVIDER", "local")
        monkeypatch.setenv("VECTOR_PROVIDER", "local")
        monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "outbox")
        monkeypatch.setenv("LLM_PROVIDER_TYPE", "local")
        monkeypatch.setenv("ALLOWED_ORIGINS", "")
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        app = create_app(Settings.from_env())
        return TestClient(app)
    return make_client


def create_tenant(client: TestClient, *, slug: str = "sample-tenant", domain: str = "client.example", notification_email: str | None = None):
    config = {
        "assistantName": "Orbit Helper",
        "fallbackMessage": "I cannot answer that from the current knowledge.",
        "collectLead": True,
        "leadFields": ["email", "requirement"],
    }
    if notification_email:
        config["notificationEmail"] = notification_email
    response = client.post(
        "/admin/clients",
        headers={"x-admin-api-key": "test-admin-key-with-32-characters"},
        json={
            "name": "Sample Tenant",
            "slug": slug,
            "domains": [domain],
            "config": config,
            "prompt": "Answer clearly, using tenant knowledge as evidence.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["client"], body["apiKey"]
