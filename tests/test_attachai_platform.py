from __future__ import annotations

import os

from fastapi.testclient import TestClient

from advanced_rag.api import create_app
from advanced_rag.app import RAGApp
from advanced_rag.config import Settings


def build_client(tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("ATTACHAI_SECURE_LEGACY_API", "false")
    settings = Settings.from_env(
        knowledge_dir=tmp_path / "legacy-knowledge",
        data_dir=tmp_path / "data",
        conversation_db_path=tmp_path / "data" / "legacy-conversations.sqlite3",
        llm_provider="none",
        embedding_model="lexical",
        qdrant_url="",
        qdrant_path=tmp_path / "data" / "legacy-qdrant",
    )
    service = RAGApp(settings)
    app = create_app(service)
    client = TestClient(app)
    token = app.state.attachai_platform.store.admin_key
    return client, token, app


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_auth_client_lifecycle_and_key_rotation(tmp_path, monkeypatch):
    client, token, app = build_client(tmp_path, monkeypatch)

    assert client.get("/api/admin/overview").status_code == 401
    created = client.post("/api/admin/clients", headers=auth(token), json={"name": "Acme Support", "domain": "https://www.acme.test/path"})
    assert created.status_code == 201, created.text
    data = created.json()
    client_id = data["client"]["id"]
    client_key = data["api_key"]
    assert client_id.startswith("cl_")
    assert client_key.startswith("att_live_")
    assert "api_key" not in data["client"]

    listing = client.get("/api/admin/clients", headers=auth(token))
    assert listing.status_code == 200
    row = listing.json()["clients"][0]
    assert row["id"] == client_id
    assert "api_key" not in row

    # Domain allowlist is enforced for public widget requests.
    good = client.get("/api/client/config", params={"client_id": client_id}, headers={"Origin": "https://www.acme.test"})
    assert good.status_code == 200, good.text
    bad = client.get("/api/client/config", params={"client_id": client_id}, headers={"Origin": "https://attacker.invalid"})
    assert bad.status_code == 403

    # A server integration can use the private client key without a browser origin.
    service_auth = {"X-Client-Key": client_key}
    assert client.get("/api/client/config", params={"client_id": client_id}, headers=service_auth).status_code == 200
    rotated = client.post(f"/api/admin/clients/{client_id}/rotate-key", headers=auth(token))
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != client_key
    assert client.get("/api/client/config", params={"client_id": client_id}, headers=service_auth).status_code == 403
    assert client.get("/api/client/config", params={"client_id": client_id}, headers={"X-Client-Key": new_key}).status_code == 200

    paused = client.patch(f"/api/admin/clients/{client_id}", headers=auth(token), json={"status": "paused"})
    assert paused.status_code == 200
    assert client.get("/api/client/config", params={"client_id": client_id}, headers={"Origin": "https://www.acme.test"}).status_code == 403
    deleted = client.delete(f"/api/admin/clients/{client_id}", headers=auth(token))
    assert deleted.status_code == 200
    assert client.get(f"/api/admin/clients/{client_id}", headers=auth(token)).status_code == 404


def test_client_knowledge_is_isolated_and_widget_can_chat(tmp_path, monkeypatch):
    client, token, app = build_client(tmp_path, monkeypatch)
    headers = auth(token)
    first = client.post("/api/admin/clients", headers=headers, json={"name": "North Shop", "domain": "north.test"}).json()
    second = client.post("/api/admin/clients", headers=headers, json={"name": "South Shop", "domain": "south.test"}).json()
    c1, c2 = first["client"]["id"], second["client"]["id"]

    payload = b"North Shop internal product code is COBALT-719. It offers bicycle repairs."
    uploaded = client.post(
        f"/api/admin/clients/{c1}/documents",
        headers=headers,
        files={"file": ("north-facts.txt", payload, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    rejected = client.post(
        f"/api/admin/clients/{c1}/documents",
        headers=headers,
        files={"file": ("run.exe", b"no", "application/octet-stream")},
    )
    assert rejected.status_code == 415

    ingested = client.post(f"/api/admin/clients/{c1}/ingest", headers=headers)
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["indexed_chunks"] >= 1

    client1 = app.state.attachai_platform.store.get_client(c1)
    client2 = app.state.attachai_platform.store.get_client(c2)
    rag1 = app.state.attachai_platform.get_rag(client1)
    rag2 = app.state.attachai_platform.get_rag(client2)
    assert any("COBALT-719" in chunk.text for chunk in rag1.chunks)
    assert all("COBALT-719" not in chunk.text for chunk in rag2.chunks)
    assert rag1.memory.path != rag2.memory.path

    widget = client.post(
        "/api/client/chat",
        headers={"Origin": "https://north.test", "Content-Type": "application/json"},
        json={"client_id": c1, "message": "What is the internal product code?"},
    )
    assert widget.status_code == 200, widget.text
    assert widget.json().get("session_id")

    cross_site = client.post(
        "/api/client/chat",
        headers={"Origin": "https://south.test", "Content-Type": "application/json"},
        json={"client_id": c1, "message": "What is the internal product code?"},
    )
    assert cross_site.status_code == 403


def test_dashboard_health_widget_asset_and_legacy_production_auth(tmp_path, monkeypatch):
    client, token, app = build_client(tmp_path, monkeypatch)
    assert client.get("/admin").status_code == 200
    assert "AttachAI" in client.get("/admin").text
    assert client.get("/widget.js").status_code == 200
    assert client.get("/health").json()["product"] == "AttachAI"

    # Production mode protects legacy shared-tenant routes by default.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_API_KEY", "a-production-test-key-that-is-long-and-random-7799")
    monkeypatch.setenv("ATTACHAI_SECURE_LEGACY_API", "true")
    # The app's production policy is fixed when create_app runs, so make a new app instance.
    service = app.state.rag_service
    protected_app = create_app(service)
    protected = TestClient(protected_app)
    assert protected.post("/ingest").status_code == 401
    protected_token = protected_app.state.attachai_platform.store.admin_key
    assert protected.post("/ingest", headers=auth(protected_token)).status_code in {200, 500}


def test_widget_lead_capture_and_admin_lead_management(tmp_path, monkeypatch):
    client, token, _app = build_client(tmp_path, monkeypatch)
    headers = auth(token)
    made = client.post("/api/admin/clients", headers=headers, json={"name": "Follow Up Shop", "domain": "followup.test"})
    assert made.status_code == 201, made.text
    client_id = made.json()["client"]["id"]

    body = {"client_id": client_id, "name": "Jamie Example", "email": "jamie@example.test", "phone": "555-0100", "message": "Please call about service options.", "consent": False}
    denied = client.post("/api/client/leads", headers={"Origin": "https://followup.test"}, json=body)
    assert denied.status_code == 422
    body["consent"] = True
    accepted = client.post("/api/client/leads", headers={"Origin": "https://followup.test"}, json=body)
    assert accepted.status_code == 201, accepted.text
    assert "email" not in accepted.json()  # Public response must not echo submitted personal data.

    listing = client.get("/api/admin/clients/" + client_id + "/leads", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()["leads"]) == 1
    assert listing.json()["leads"][0]["email"] == "jamie@example.test"
    all_leads = client.get("/api/admin/leads", headers=headers)
    assert all_leads.status_code == 200
    assert all_leads.json()["leads"][0]["client_name"] == "Follow Up Shop"
    assert client.get("/api/admin/leads").status_code == 401
    assert client.get("/api/admin/overview", headers=headers).json()["total_leads"] == 1


def test_provider_aliases_override_default_none(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "none")
    monkeypatch.setenv("LLM_PROVIDER_TYPE", "openai-compatible")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-used-for-network")
    settings = Settings.from_env(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "knowledge", embedding_model="lexical")
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "test-model"
    assert settings.api_key == "test-key-not-used-for-network"
