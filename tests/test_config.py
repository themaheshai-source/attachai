from __future__ import annotations

from orbit_ai.config import Settings


def test_legacy_database_and_cors_aliases_are_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PROVIDER", "supabase")
    monkeypatch.setenv("REPOSITORY_PROVIDER", "sqlite")
    monkeypatch.setenv("ALLOWED_ORIGINS", "")
    monkeypatch.setenv("CORS_ORIGINS", "https://admin.example, https://ops.example")
    monkeypatch.setenv("NODE_VERSION", "legacy-build-label")
    monkeypatch.setenv("ORBIT_TEMP_DEBUG_GOUSTO", "retained-value")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    cfg = Settings.from_env()
    assert cfg.database_provider == "sqlite"
    assert cfg.allowed_origins == ("https://admin.example", "https://ops.example")
    assert cfg.node_version_legacy == "legacy-build-label"
    assert cfg.orbit_temp_debug_gousto == "retained-value"


def test_production_refuses_default_admin_key(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_API_KEY", "local-development-admin-key")
    monkeypatch.delenv("REPOSITORY_PROVIDER", raising=False)
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "ADMIN_API_KEY" in str(exc)
    else:
        raise AssertionError("production must reject the default admin key")


def test_production_refuses_example_placeholder_admin_key(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_API_KEY", "replace-with-at-least-24-random-characters")
    monkeypatch.delenv("REPOSITORY_PROVIDER", raising=False)
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "ADMIN_API_KEY" in str(exc)
    else:
        raise AssertionError("production must reject the example admin key placeholder")


def test_supabase_outbox_table_identifier_is_validated(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SUPABASE_OUTBOX_TABLE", "notifications;drop table leads")
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "SUPABASE_OUTBOX_TABLE" in str(exc)
    else:
        raise AssertionError("invalid SQL identifiers must be rejected")



def test_supabase_server_provider_requires_service_role_key(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PROVIDER", "supabase")
    monkeypatch.delenv("REPOSITORY_PROVIDER", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-anon-key")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "SUPABASE_SERVICE_ROLE_KEY" in str(exc)
    else:
        raise AssertionError("server-side Supabase adapters must require the service role key")


def test_openai_embedding_dimensions_default_to_supabase_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PROVIDER", "sqlite")
    monkeypatch.delenv("REPOSITORY_PROVIDER", raising=False)
    monkeypatch.setenv("VECTOR_PROVIDER", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("SUPABASE_VECTOR_DIMENSIONS", "128")
    monkeypatch.setenv("OPENAI_EMBEDDING_DIMENSIONS", "")
    cfg = Settings.from_env()
    assert cfg.openai_embedding_dimensions == cfg.supabase_vector_dimensions == 128


def test_local_embedding_cannot_target_mismatched_supabase_vector_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PROVIDER", "sqlite")
    monkeypatch.delenv("REPOSITORY_PROVIDER", raising=False)
    monkeypatch.setenv("VECTOR_PROVIDER", "supabase")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("SUPABASE_VECTOR_DIMENSIONS", "256")
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "local embedding provider emits 128 dimensions" in str(exc)
    else:
        raise AssertionError("configuration must reject the incompatible 128/256 vector dimensions")


def test_smtp_port_rejects_values_above_tcp_port_range(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMTP_PORT", "65536")
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "SMTP_PORT must be between 1 and 65535" in str(exc)
    else:
        raise AssertionError("SMTP port outside valid TCP range must be rejected")
