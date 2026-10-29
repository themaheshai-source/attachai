from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import create_tenant

ADMIN = {"x-admin-api-key": "test-admin-key-with-32-characters"}


def test_admin_auth_tenant_and_public_key_origin(client_factory):
    with client_factory() as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.post("/admin/auth/validate", headers=ADMIN).json() == {"authenticated": True}
        assert client.post("/admin/auth/validate", headers={"x-admin-api-key": "wrong"}).status_code == 401
        tenant, key = create_tenant(client)
        public_headers = {"x-api-key": key, "origin": "https://client.example"}
        assert client.get("/v1/config", headers=public_headers).status_code == 200
        assert client.get("/v1/config", headers={"x-api-key": key, "origin": "https://attacker.example"}).status_code == 403
        assert client.get("/v1/config", headers={"origin": "https://client.example"}).status_code == 401
        assert tenant["id"]


def test_upload_retrieval_citations_and_conversation_persistence(client_factory):
    with client_factory() as client:
        tenant, key = create_tenant(client)
        upload = client.post(
            f"/admin/clients/{tenant['id']}/knowledge",
            headers=ADMIN,
            files={"file": ("faq.txt", b"Plans cost $12 per month. The annual option costs $120 per year.", "text/plain")},
        )
        assert upload.status_code == 200, upload.text
        assert upload.json()["chunks"] >= 1

        chat = client.post("/v1/chat", headers={"x-api-key": key, "origin": "https://client.example"}, json={"message": "What do plans cost?"})
        assert chat.status_code == 200, chat.text
        response = chat.json()
        assert "$12" in response["answer"]
        assert response["sources"]
        assert response["sources"][0]["source"] == "faq.txt"

        conversations = client.get(f"/admin/clients/{tenant['id']}/conversations", headers=ADMIN)
        assert conversations.status_code == 200
        assert len(conversations.json()) == 1
        detail = client.get(f"/admin/clients/{tenant['id']}/conversations/{response['conversationId']}", headers=ADMIN)
        assert detail.status_code == 200
        assert [m["role"] for m in detail.json()["messages"]] == ["user", "assistant"]


def test_invalid_json_is_a_client_error_and_lead_name_cannot_be_blank(client_factory):
    with client_factory() as client:
        invalid = client.post("/admin/clients", headers={**ADMIN, "content-type": "application/json"}, content=b"{")
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "INVALID_JSON"

        tenant, key = create_tenant(client, notification_email="team@example.com")
        lead = client.post(
            "/v1/leads",
            headers={"x-api-key": key, "origin": "https://client.example"},
            json={"name": "   ", "message": "Please contact me"},
        )
        assert lead.status_code == 400


def test_sse_endpoint_emits_validated_answer(client_factory):
    with client_factory() as client:
        tenant, key = create_tenant(client)
        client.post(
            f"/admin/clients/{tenant['id']}/knowledge",
            headers=ADMIN,
            files={"file": ("faq.txt", b"The Orbit plan costs $12 monthly.", "text/plain")},
        )
        response = client.post("/v1/chat/stream", headers={"x-api-key": key, "origin": "https://client.example"}, json={"message": "What is the Orbit plan price?"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: token" in response.text
        assert "event: done" in response.text
        assert "$12" in response.text


def test_tenant_vector_isolation(client_factory):
    with client_factory() as client:
        first, first_key = create_tenant(client, slug="tenant-one", domain="one.example")
        second, second_key = create_tenant(client, slug="tenant-two", domain="two.example")
        uploaded = client.post(
            f"/admin/clients/{first['id']}/knowledge",
            headers=ADMIN,
            files={"file": ("secret.txt", b"Tenant one internal code is ORBIT-9281.", "text/plain")},
        )
        assert uploaded.status_code == 200
        response = client.post("/v1/chat", headers={"x-api-key": second_key, "origin": "https://two.example"}, json={"message": "What is the internal code?"})
        assert response.status_code == 200
        assert "ORBIT-9281" not in response.json()["answer"]
        assert response.json()["sources"] == []


def test_persistence_survives_app_recreation(client_factory, tmp_path):
    data = tmp_path / "persistent"
    with client_factory(data) as first:
        tenant, key = create_tenant(first, slug="persistent-tenant", domain="persist.example")
        first.post(
            f"/admin/clients/{tenant['id']}/knowledge",
            headers=ADMIN,
            files={"file": ("faq.txt", b"The support email is support@example.com.", "text/plain")},
        )
    with client_factory(data) as second:
        tenants = second.get("/admin/clients", headers=ADMIN).json()
        assert any(x["slug"] == "persistent-tenant" for x in tenants)
        response = second.post("/v1/chat", headers={"x-api-key": key, "origin": "https://persist.example"}, json={"message": "What is the support email?"})
        assert response.status_code == 200
        assert "support@example.com" in response.json()["answer"]


def test_serves_existing_dashboard_and_widget(client_factory):
    with client_factory() as client:
        assert client.get("/").status_code == 200
        assert client.get("/widget.js").status_code == 200


def test_hinglish_follow_up_uses_persisted_conversation_context(client_factory):
    with client_factory() as client:
        tenant, key = create_tenant(client, slug="hinglish-tenant", domain="hinglish.example")
        upload = client.post(
            f"/admin/clients/{tenant['id']}/knowledge",
            headers=ADMIN,
            files={"file": ("plans.txt", b"The Orbit Standard plan costs $12 per month. The Orbit Standard annual plan costs $120 per year.", "text/plain")},
        )
        assert upload.status_code == 200, upload.text
        headers = {"x-api-key": key, "origin": "https://hinglish.example"}
        first = client.post("/v1/chat", headers=headers, json={"message": "What is the Orbit Standard plan?"})
        assert first.status_code == 200, first.text
        session_id = first.json()["sessionId"]
        follow_up = client.post(
            "/v1/chat",
            headers=headers,
            json={"message": "Aur iska monthly price?", "sessionId": session_id},
        )
        assert follow_up.status_code == 200, follow_up.text
        response = follow_up.json()
        assert "$12" in response["answer"]
        assert response["sources"]
        assert response["sessionId"] == session_id



def test_summary_request_summarizes_prior_conversation(client_factory):
    with client_factory() as client:
        tenant, key = create_tenant(client, slug="summary-tenant", domain="summary.example")
        headers = {"x-api-key": key, "origin": "https://summary.example"}
        first = client.post("/v1/chat", headers=headers, json={"message": "hello"})
        assert first.status_code == 200
        result = client.post("/v1/chat", headers=headers, json={"message": "Summarize our conversation", "sessionId": first.json()["sessionId"]})
        assert result.status_code == 200, result.text
        assert "Conversation summary" in result.json()["answer"]
        assert "hello" in result.json()["answer"].lower()
        assert "I cannot answer that" not in result.json()["answer"]


def test_identity_question_uses_local_identity_answer(client_factory):
    with client_factory() as client:
        _tenant, key = create_tenant(client, slug="identity-tenant", domain="identity.example")
        response = client.post("/v1/chat", headers={"x-api-key": key, "origin": "https://identity.example"}, json={"message": "What is your name?"})
        assert response.status_code == 200
        assert "Orbit Helper" in response.json()["answer"]
        assert response.json()["sources"] == []


def test_filename_is_canonicalized_for_storage_index_and_delete(client_factory):
    with client_factory() as client:
        tenant, _key = create_tenant(client, slug="filename-tenant", domain="filename.example")
        upload = client.post(
            f"/admin/clients/{tenant['id']}/knowledge", headers=ADMIN,
            files={"file": ("customer guide (final).txt", b"The secret phrase is ORBIT-FILENAME-441.", "text/plain")},
        )
        assert upload.status_code == 200, upload.text
        filename = upload.json()["filename"]
        assert " " not in filename and "(" not in filename and ")" not in filename
        listed = client.get(f"/admin/clients/{tenant['id']}/knowledge", headers=ADMIN).json()
        assert any(x["filename"] == filename for x in listed)
        deleted = client.delete(f"/admin/clients/{tenant['id']}/knowledge/{filename}", headers=ADMIN)
        assert deleted.status_code == 200, deleted.text
        assert client.get(f"/admin/clients/{tenant['id']}/knowledge", headers=ADMIN).json() == []
        assert client.app.state.vector.rows == []


def test_csv_export_neutralizes_formula_injection(client_factory):
    with client_factory() as client:
        tenant, key = create_tenant(client, slug="csv-tenant", domain="csv.example", notification_email="team@example.com")
        lead = client.post("/v1/leads", headers={"x-api-key": key, "origin": "https://csv.example"}, json={"name": "=HYPERLINK(\"https://attacker.example\")", "email": "lead@example.com", "requirement": "+cmd|' /C calc'!A0"})
        assert lead.status_code == 200, lead.text
        exported = client.get(f"/admin/clients/{tenant['id']}/leads.csv", headers=ADMIN)
        assert exported.status_code == 200
        assert "'=HYPERLINK" in exported.text
        assert "'+cmd" in exported.text


def test_admin_cors_requires_exact_scheme_and_port(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from orbit_ai.app import create_app
    from orbit_ai.config import Settings
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key-with-32-characters")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PROVIDER", "sqlite")
    monkeypatch.delenv("REPOSITORY_PROVIDER", raising=False)
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("VECTOR_PROVIDER", "local")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("NOTIFICATION_PROVIDER", "outbox")
    monkeypatch.setenv("LLM_PROVIDER_TYPE", "local")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://admin.example")
    with TestClient(create_app(Settings.from_env())) as client:
        assert client.options("/admin/auth/validate", headers={"origin": "https://admin.example"}).status_code == 204
        assert client.options("/admin/auth/validate", headers={"origin": "http://admin.example"}).status_code == 403
        assert client.options("/admin/auth/validate", headers={"origin": "https://admin.example:8443"}).status_code == 403


def test_request_rate_limit_identity_map_is_bounded(client_factory):
    with client_factory() as client:
        mapping = client.app.state.request_times
        mapping.update({f"192.0.2.{i}": __import__("collections").deque([__import__("time").monotonic()]) for i in range(1, 10001)})
        assert client.get("/health").status_code == 200
        assert len(mapping) <= 10000


def test_provider_body_rejects_newline_injection():
    from pydantic import ValidationError
    from orbit_ai.models import ProviderBody
    try:
        ProviderBody.model_validate({"provider": "custom", "baseUrl": "https://example.com\nLLM_API_KEY=leak", "model": "model"})
    except ValidationError:
        pass
    else:
        raise AssertionError("baseUrl containing newline must be rejected")
    try:
        ProviderBody.model_validate({"provider": "custom", "baseUrl": "https://example.com", "model": "model\nLLM_API_KEY=leak"})
    except ValidationError:
        pass
    else:
        raise AssertionError("model containing newline must be rejected")


def test_streaming_body_limit_applies_without_content_length(client_factory):
    with client_factory() as client:
        def chunks():
            for _ in range(20):
                yield b"x" * (64 * 1024)
        response = client.post("/admin/clients", headers=ADMIN, content=chunks())
        assert response.status_code == 413, response.text[:300]
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_failed_tenant_cleanup_disables_tenant_and_can_be_retried(client_factory, monkeypatch):
    with client_factory() as client:
        tenant, key = create_tenant(client, slug="cleanup-tenant", domain="cleanup.example")
        storage = client.app.state.storage
        original_remove_tenant = storage.remove_tenant

        async def fail_remove_tenant(client_id):
            raise RuntimeError("simulated storage outage")

        monkeypatch.setattr(storage, "remove_tenant", fail_remove_tenant)
        failed = client.delete(f"/admin/clients/{tenant['id']}", headers=ADMIN)
        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "TENANT_CLEANUP_INCOMPLETE"
        retained = client.app.state.repo.get_client(tenant["id"])
        assert retained is not None and retained["enabled"] is False
        assert client.get("/v1/config", headers={"x-api-key": key, "origin": "https://cleanup.example"}).status_code == 401

        monkeypatch.setattr(storage, "remove_tenant", original_remove_tenant)
        retried = client.delete(f"/admin/clients/{tenant['id']}", headers=ADMIN)
        assert retried.status_code == 204
        assert client.app.state.repo.get_client(tenant["id"]) is None


def test_public_origin_matching_accepts_default_port_but_not_non_http_scheme():
    from orbit_ai.security import origin_matches

    assert origin_matches("https://client.example:443", ["client.example"])
    assert origin_matches("http://client.example:80", ["client.example"])
    assert not origin_matches("https://client.example:8443", ["client.example"])
    assert origin_matches("https://client.example:8443", ["client.example:8443"])
    assert not origin_matches("ftp://client.example", ["client.example"])


def test_failed_notification_does_not_ask_user_to_retry_persisted_lead(client_factory, monkeypatch):
    with client_factory() as client:
        tenant, key = create_tenant(client, slug="notification-outage", domain="notification.example", notification_email="team@example.com")

        async def fail_notification(*args, **kwargs):
            raise RuntimeError("simulated SMTP outage")

        monkeypatch.setattr(client.app.state.notification, "notify", fail_notification)
        response = client.post(
            "/v1/leads",
            headers={"x-api-key": key, "origin": "https://notification.example"},
            json={"name": "Example Lead", "email": "person@example.com", "requirement": "Needs a callback"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "accepted"
        assert response.json()["notificationStatus"] == "failed"
        leads = client.app.state.repo.list_leads(tenant["id"])
        assert len(leads) == 1


def test_usage_analytics_failure_does_not_fail_a_persisted_chat_answer(client_factory, monkeypatch):
    with client_factory() as client:
        tenant, key = create_tenant(client, slug="usage-outage", domain="usage.example")

        def fail_usage(*args, **kwargs):
            raise RuntimeError("simulated usage log outage")

        monkeypatch.setattr(client.app.state.repo, "usage", fail_usage)
        response = client.post(
            "/v1/chat",
            headers={"x-api-key": key, "origin": "https://usage.example"},
            json={"message": "hello"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["answer"]
        conversation = client.app.state.repo.conversation_for_client(tenant["id"], response.json()["conversationId"])
        assert conversation is not None
        assert [message["role"] for message in conversation["messages"]] == ["user", "assistant"]


def test_external_retrieval_transport_error_returns_service_unavailable(client_factory, monkeypatch):
    import httpx

    with client_factory() as client:
        _tenant, key = create_tenant(client, slug="provider-transport-failure", domain="provider-failure.example")

        async def list_evidence(client_id, limit=2000):
            return [{"id": "existing", "text": "Refunds are available within 30 days.", "source": "policy.txt", "score": 0.0}]

        async def fail_search(*args, **kwargs):
            raise httpx.ConnectError("simulated provider unavailable")

        monkeypatch.setattr(client.app.state.vector, "list_tenant", list_evidence)
        monkeypatch.setattr(client.app.state.vector, "search", fail_search)
        response = client.post(
            "/v1/chat",
            headers={"x-api-key": key, "origin": "https://provider-failure.example"},
            json={"message": "What is the refund policy?"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "CHAT_PROVIDER_FAILED"


def test_provider_response_shape_error_returns_service_unavailable_not_bad_request(client_factory, monkeypatch):
    with client_factory() as client:
        _tenant, key = create_tenant(client, slug="provider-shape-failure", domain="provider-shape.example")

        async def list_evidence(client_id, limit=2000):
            return [{"id": "existing", "text": "Refunds are available within 30 days.", "source": "policy.txt", "score": 0.0}]

        async def malformed_provider_result(*args, **kwargs):
            raise ValueError("provider returned malformed JSON")

        monkeypatch.setattr(client.app.state.vector, "list_tenant", list_evidence)
        monkeypatch.setattr(client.app.state.vector, "search", malformed_provider_result)
        response = client.post(
            "/v1/chat",
            headers={"x-api-key": key, "origin": "https://provider-shape.example"},
            json={"message": "What is the refund policy?"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "CHAT_PROVIDER_FAILED"
