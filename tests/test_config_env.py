from advanced_rag.config import Settings


def test_dotenv_is_loaded_without_overriding_process_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RAG_LLM_PROVIDER=openai\nRAG_PORT=8123\nOPENAI_API_KEY=example-local-key\nRAG_QUERY_UNDERSTANDING_ENABLED=false\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for key in ("RAG_LLM_PROVIDER", "RAG_PORT", "OPENAI_API_KEY", "RAG_QUERY_UNDERSTANDING_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RAG_PORT", "9999")

    settings = Settings.from_env(data_dir=tmp_path / "data")
    assert settings.llm_provider == "openai"
    assert settings.port == 9999
    assert settings.api_key == "example-local-key"
    assert settings.query_understanding_enabled is False
    assert settings.conversation_db_path == tmp_path / "data" / "conversations.sqlite3"
