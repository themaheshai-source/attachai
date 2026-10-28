from fastapi.testclient import TestClient

from advanced_rag.api import create_app
from advanced_rag.app import RAGApp
from advanced_rag.config import Settings


def test_chat_api_creates_reusable_isolated_sessions_and_keeps_legacy_request(tmp_path):
    settings = Settings.from_env(
        knowledge_dir=tmp_path / "knowledge",
        data_dir=tmp_path / "data",
        conversation_db_path=tmp_path / "data" / "memory.sqlite3",
        llm_provider="none",
        embedding_model="lexical",
    )
    service = RAGApp(settings)
    client = TestClient(create_app(service))

    first = client.post("/chat", json={"message": "Hi"})
    assert first.status_code == 200
    first_data = first.json()
    first_id = first_data["session_id"]
    assert first_id
    assert first_data["status"] == "CONVERSATIONAL"

    second = client.post("/chat", json={"message": "Thanks", "session_id": first_id})
    assert second.status_code == 200
    assert second.json()["session_id"] == first_id
    restored = client.get(f"/sessions/{first_id}")
    assert restored.status_code == 200
    assert [m["role"] for m in restored.json()["messages"]] == ["user", "assistant", "user", "assistant"]

    legacy = client.post("/query", json={"message": "Hello"})
    assert legacy.status_code == 200
    assert legacy.json()["session_id"] != first_id

    assert client.get("/sessions/unknown-session").status_code == 404
    invalid = client.post("/chat", json={"message": "What is it?", "session_id": "unknown-session"})
    assert invalid.status_code == 404
