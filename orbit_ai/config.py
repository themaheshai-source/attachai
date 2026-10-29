from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re


def load_dotenv(path: Path | None = None) -> None:
    """Load a simple .env file without overriding deployment-injected settings."""
    path = path or Path.cwd() / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        os.environ[key] = value


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _int(name: str, default: int, minimum: int | None = None) -> int:
    value = int(os.getenv(name, str(default)))
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _port(name: str, default: int) -> int:
    value = _int(name, default, 1)
    if value > 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


def _validate_http_url(name: str, value: str | None, *, allow_path: bool = True) -> str | None:
    if value is None or value == "":
        return value
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or (not allow_path and parsed.path not in {"", "/"})):
        raise ValueError(f"{name} must be an HTTP(S) URL without credentials, query, or fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} contains an invalid port") from exc
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    node_env: str
    host: str
    port: int
    admin_api_key: str
    data_dir: Path
    public_base_url: str
    allowed_origins: tuple[str, ...]
    database_provider: str
    storage_provider: str
    vector_provider: str
    embedding_provider: str
    openai_base_url: str
    openai_api_key: str | None
    openai_embedding_model: str
    openai_embedding_dimensions: int
    supabase_url: str | None
    supabase_service_role_key: str | None
    supabase_anon_key: str | None
    supabase_storage_bucket: str
    supabase_outbox_table: str
    supabase_vector_dimensions: int
    qdrant_url: str
    qdrant_api_key: str | None
    notification_provider: str
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_pass: str | None
    smtp_from: str | None
    llm_provider_type: str
    llm_provider_name: str
    llm_base_url: str | None
    llm_model: str | None
    llm_api_key: str | None
    llm_api_key_env: str
    llm_timeout_ms: int
    llm_max_retries: int
    llm_retry_base_ms: int
    llm_temperature: float
    llm_top_p: float | None
    llm_max_tokens: int | None
    llm_stream: bool
    llm_chat_path: str
    llm_health_path: str
    llm_auth_header_name: str
    llm_auth_scheme: str
    llm_headers: dict[str, str]
    llm_query_params: dict[str, str]
    orbit_rag_diagnostics: bool
    # Preserved legacy/compatibility settings. Debug IDs are deliberately not
    # enabled automatically and are never written to normal application logs.
    orbit_temp_debug_client_id: str | None
    orbit_temp_debug_gousto: str | None
    orbit_temp_debug_llm_input: str | None
    orbit_temp_debug_puregym: str | None
    tts_api_key: str | None
    node_version_legacy: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        node_env = os.getenv("NODE_ENV", "development").strip().lower()
        if node_env not in {"development", "test", "production"}:
            raise ValueError("NODE_ENV must be development, test, or production")
        admin_key = os.getenv("ADMIN_API_KEY", "local-development-admin-key")
        if node_env == "production" and (admin_key == "local-development-admin-key" or admin_key.strip().lower().startswith("replace-with") or len(admin_key) < 24):
            raise ValueError("ADMIN_API_KEY must be explicitly configured with at least 24 characters in production")

        # ALLOWED_ORIGINS is the contract name. CORS_ORIGINS remains a tested alias.
        origins_raw = os.getenv("ALLOWED_ORIGINS", "").strip()
        if not origins_raw:
            origins_raw = os.getenv("CORS_ORIGINS", "")
        origins = tuple(x.strip() for x in origins_raw.split(",") if x.strip())

        db_provider = (os.getenv("REPOSITORY_PROVIDER") or os.getenv("DATABASE_PROVIDER", "sqlite")).lower()
        storage_provider = os.getenv("STORAGE_PROVIDER", "local").lower()
        vector_provider = os.getenv("VECTOR_PROVIDER", "local").lower()
        embedding_provider = os.getenv("EMBEDDING_PROVIDER", "local").lower()
        notification_provider = os.getenv("NOTIFICATION_PROVIDER", "outbox").lower()
        llm_type = os.getenv("LLM_PROVIDER_TYPE", "local").lower()
        if db_provider not in {"sqlite", "supabase"}:
            raise ValueError("DATABASE_PROVIDER must be sqlite or supabase")
        if storage_provider not in {"local", "supabase"}:
            raise ValueError("STORAGE_PROVIDER must be local or supabase")
        if vector_provider not in {"local", "qdrant", "supabase"}:
            raise ValueError("VECTOR_PROVIDER must be local, qdrant, or supabase")
        if embedding_provider not in {"local", "openai"}:
            raise ValueError("EMBEDDING_PROVIDER must be local or openai")
        if notification_provider not in {"outbox", "smtp", "supabase"}:
            raise ValueError("NOTIFICATION_PROVIDER must be outbox, smtp, or supabase")
        if llm_type not in {"local", "openai-compatible"}:
            # Keep compatibility with the original provider alias `openai`.
            if llm_type == "openai":
                llm_type = "openai-compatible"
            else:
                raise ValueError("LLM_PROVIDER_TYPE must be local or openai-compatible")

        api_key_env = os.getenv("LLM_API_KEY_ENV", "LLM_API_KEY")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", api_key_env):
            raise ValueError("LLM_API_KEY_ENV must be a valid environment variable name")
        raw_headers = os.getenv("LLM_HEADERS", "").strip()
        raw_query = os.getenv("LLM_QUERY_PARAMS", "").strip()
        import json
        try:
            headers = json.loads(raw_headers) if raw_headers else {}
            query_params = json.loads(raw_query) if raw_query else {}
        except json.JSONDecodeError as exc:
            raise ValueError("LLM_HEADERS and LLM_QUERY_PARAMS must be JSON objects") from exc
        if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
            raise ValueError("LLM_HEADERS must be a JSON object with string values")
        if not isinstance(query_params, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in query_params.items()):
            raise ValueError("LLM_QUERY_PARAMS must be a JSON object with string values")
        auth_header = os.getenv("LLM_AUTH_HEADER_NAME", "authorization")
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", auth_header):
            raise ValueError("LLM_AUTH_HEADER_NAME is invalid")
        forbidden = {"proxy-authorization", "content-type", "content-length", "host", "transfer-encoding"}
        for name, value in headers.items():
            low = name.lower()
            if (not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or "\r" in value or "\n" in value
                or low in forbidden or low == auth_header.lower()
                or re.search(r"api[-_]?key|token|secret|password", low, re.I)):
                raise ValueError("LLM_HEADERS cannot contain invalid, secret, authentication, or transport headers")
        for name, value in query_params.items():
            if not name or re.search(r"api[-_]?key|token|secret|password|authorization", name, re.I) or any(c in name + value for c in "\r\n"):
                raise ValueError("LLM_QUERY_PARAMS cannot contain invalid or secret parameters")

        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_CHAT_MODEL")
        api_key = os.getenv(api_key_env) or (os.getenv("OPENAI_API_KEY") if api_key_env == "LLM_API_KEY" else None)
        if llm_type != "local":
            if not base_url or not model or not api_key:
                raise ValueError(f"Missing non-local LLM configuration: {', '.join(n for n, v in [("LLM_BASE_URL", base_url), ("LLM_MODEL", model), (api_key_env, api_key)] if not v)}")
            from urllib.parse import urlsplit
            parsed = urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("LLM_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment")
            base_url = base_url.rstrip("/")
        chat_path = os.getenv("LLM_CHAT_PATH", "/chat/completions")
        health_path = os.getenv("LLM_HEALTH_PATH", "/models")
        for name, path in (("LLM_CHAT_PATH", chat_path), ("LLM_HEALTH_PATH", health_path)):
            if not path.startswith("/") or path.startswith("//") or re.search(r"[?#\r\n]", path) or any(p in {".", ".."} for p in path.split("/")):
                raise ValueError(f"{name} must be a normalized absolute path")
        timeout = _int("LLM_TIMEOUT_MS", 15000, 100)
        retries = _int("LLM_MAX_RETRIES", 2, 0)
        retry_base = _int("LLM_RETRY_BASE_MS", 250, 0)
        sampling_temp = float(os.getenv("LLM_TEMPERATURE", "0"))
        top_p_raw = os.getenv("LLM_TOP_P")
        max_tokens_raw = os.getenv("LLM_MAX_TOKENS")
        if not 0 <= sampling_temp <= 2:
            raise ValueError("LLM_TEMPERATURE must be between 0 and 2")
        if top_p_raw is not None and not 0 <= float(top_p_raw) <= 1:
            raise ValueError("LLM_TOP_P must be between 0 and 1")
        if max_tokens_raw is not None and int(max_tokens_raw) < 1:
            raise ValueError("LLM_MAX_TOKENS must be positive")

        public_base_url = _validate_http_url("PUBLIC_BASE_URL", os.getenv("PUBLIC_BASE_URL", "http://localhost:3000")) or "http://localhost:3000"
        openai_base_url = _validate_http_url("OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")) or "https://api.openai.com/v1"
        qdrant_url = _validate_http_url("QDRANT_URL", os.getenv("QDRANT_URL", "http://localhost:6333"), allow_path=False) or "http://localhost:6333"
        supabase_url = _validate_http_url("SUPABASE_URL", os.getenv("SUPABASE_URL"), allow_path=False)
        storage_bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "knowledge")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", storage_bucket):
            raise ValueError("SUPABASE_STORAGE_BUCKET must contain only letters, digits, dot, underscore, or hyphen")
        supabase_dims = _int("SUPABASE_VECTOR_DIMENSIONS", 128, 1)
        service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if (db_provider == "supabase" or storage_provider == "supabase" or vector_provider == "supabase" or notification_provider == "supabase") and (not supabase_url or not service_role_key):
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for server-side Supabase providers; anon-key access is not sufficient for the configured RLS policy")
        openai_embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL") or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        embedding_dims_raw = os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "").strip()
        openai_embedding_dimensions = int(embedding_dims_raw) if embedding_dims_raw else (supabase_dims if vector_provider == "supabase" else 1536)
        if openai_embedding_dimensions < 1:
            raise ValueError("OPENAI_EMBEDDING_DIMENSIONS must be positive")
        if vector_provider == "supabase" and embedding_provider == "local" and supabase_dims != 128:
            raise ValueError("The local embedding provider emits 128 dimensions; SUPABASE_VECTOR_DIMENSIONS must be 128 or configure compatible OpenAI embeddings")
        if embedding_provider == "openai" and vector_provider == "supabase":
            if openai_embedding_dimensions != supabase_dims:
                raise ValueError("OPENAI_EMBEDDING_DIMENSIONS must match SUPABASE_VECTOR_DIMENSIONS for Supabase vector storage")
            if not openai_embedding_model.startswith("text-embedding-3-") and openai_embedding_dimensions != 1536:
                raise ValueError("Supabase vector dimensions other than 1536 require an OpenAI text-embedding-3 model that supports the dimensions parameter")

        port = _int("PORT", 3000, 1)
        if port > 65535:
            raise ValueError("PORT must be between 1 and 65535")
        outbox_table = os.getenv("SUPABASE_OUTBOX_TABLE", "notifications")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", outbox_table):
            raise ValueError("SUPABASE_OUTBOX_TABLE must be a valid SQL identifier")
        data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            node_env=node_env,
            host=os.getenv("HOST", "0.0.0.0"),
            port=port,
            admin_api_key=admin_key,
            data_dir=data_dir,
            public_base_url=public_base_url,
            allowed_origins=origins,
            database_provider=db_provider,
            storage_provider=storage_provider,
            vector_provider=vector_provider,
            embedding_provider=embedding_provider,
            openai_base_url=openai_base_url,
            openai_api_key=os.getenv("OPENAI_API_KEY") or os.getenv("EMBEDDING_API_KEY"),
            openai_embedding_model=openai_embedding_model,
            openai_embedding_dimensions=openai_embedding_dimensions,
            supabase_url=supabase_url,
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY"),
            supabase_storage_bucket=storage_bucket,
            supabase_outbox_table=outbox_table,
            supabase_vector_dimensions=supabase_dims,
            qdrant_url=qdrant_url,
            qdrant_api_key=os.getenv("QDRANT_API_KEY"),
            notification_provider=notification_provider,
            smtp_host=os.getenv("SMTP_HOST"), smtp_port=_port("SMTP_PORT", 587),
            smtp_user=os.getenv("SMTP_USER"), smtp_pass=os.getenv("SMTP_PASS"), smtp_from=os.getenv("SMTP_FROM"),
            llm_provider_type=llm_type,
            llm_provider_name=os.getenv("LLM_PROVIDER_NAME", os.getenv("LLM_PROVIDER", "local" if llm_type == "local" else "openai-compatible")),
            llm_base_url=base_url,
            llm_model=model,
            llm_api_key=api_key,
            llm_api_key_env=api_key_env,
            llm_timeout_ms=timeout,
            llm_max_retries=retries,
            llm_retry_base_ms=retry_base,
            llm_temperature=sampling_temp,
            llm_top_p=float(top_p_raw) if top_p_raw is not None else None,
            llm_max_tokens=int(max_tokens_raw) if max_tokens_raw is not None else None,
            llm_stream=_bool("LLM_STREAM", False),
            llm_chat_path=chat_path,
            llm_health_path=health_path,
            llm_auth_header_name=auth_header,
            llm_auth_scheme=os.getenv("LLM_AUTH_SCHEME", "Bearer"),
            llm_headers=headers,
            llm_query_params=query_params,
            orbit_rag_diagnostics=_bool("ORBIT_RAG_DIAGNOSTICS", False),
            orbit_temp_debug_client_id=os.getenv("ORBIT_TEMP_DEBUG_CLIENT_ID"),
            orbit_temp_debug_gousto=os.getenv("ORBIT_TEMP_DEBUG_GOUSTO"),
            orbit_temp_debug_llm_input=os.getenv("ORBIT_TEMP_DEBUG_LLM_INPUT"),
            orbit_temp_debug_puregym=os.getenv("ORBIT_TEMP_DEBUG_PUREGYM"),
            tts_api_key=os.getenv("TTS_API_KEY"),
            node_version_legacy=os.getenv("NODE_VERSION"),
        )
