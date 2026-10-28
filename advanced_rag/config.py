"""Environment-based configuration with dependency-free .env loading."""
from dataclasses import dataclass, field
from pathlib import Path
import os


def _load_env_file() -> None:
    """Load project/cwd .env without overriding explicitly set process variables."""
    package_root = Path(__file__).resolve().parent.parent
    candidates = []
    for candidate in (Path.cwd() / ".env", package_root / ".env"):
        if candidate not in candidates:
            candidates.append(candidate)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[7:].strip()
            if "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name or not name.replace("_", "").isalnum() or name in os.environ:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            else:
                # Support unquoted trailing comments without damaging URL fragments.
                value = value.split(" #", 1)[0].rstrip()
            os.environ[name] = value


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _provider_name(value):
    """Normalize common provider aliases from existing AttachAI deployments."""
    name = str(value or "none").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {"openai-compatible": "openai", "openai-compatible-api": "openai", "openai-api": "openai",
               "google": "gemini", "google-gemini": "gemini", "local": "none", "offline": "none"}
    return aliases.get(name, name)


@dataclass
class Settings:
    knowledge_dir: Path = Path("knowledge")
    data_dir: Path = Path(".rag_data")
    collection_name: str = "knowledge"
    embedding_model: str = "lexical"
    embedding_dim: int = 384
    chunk_size: int = 900
    chunk_overlap: int = 120
    top_k: int = 8
    retrieval_k: int = 20
    rrf_k: int = 60
    min_domain_score: float = 0.12
    context_chars: int = 7000
    llm_provider: str = "none"
    llm_model: str = ""
    api_key: str = ""
    gemini_api_key: str = ""
    nvidia_api_key: str = ""
    api_base: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    qdrant_url: str = ""
    qdrant_path: Path = Path(".rag_data/qdrant")
    query_understanding_enabled: bool = True
    query_max_variants: int = 4
    recovery_multiplier: int = 3
    partial_recovery_threshold: float = 0.35
    conversation_db_path: Path | None = None
    chat_context_chars: int = 6000
    chat_total_context_chars: int = 15000
    chat_full_history_threshold: int = 12
    chat_recent_turns: int = 6
    chat_memory_top_k: int = 4
    chat_summary_chars: int = 1200
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides):
        _load_env_file()
        data_dir = Path(os.getenv("RAG_DATA_DIR", ".rag_data"))
        values = {
            "knowledge_dir": Path(os.getenv("RAG_KNOWLEDGE_DIR", "knowledge")),
            "data_dir": data_dir,
            "collection_name": os.getenv("RAG_COLLECTION", "knowledge"),
            "embedding_model": os.getenv("RAG_EMBEDDING_MODEL", "lexical"),
            "embedding_dim": int(os.getenv("RAG_EMBEDDING_DIM", "384")),
            "chunk_size": int(os.getenv("RAG_CHUNK_SIZE", "900")),
            "chunk_overlap": int(os.getenv("RAG_CHUNK_OVERLAP", "120")),
            "top_k": int(os.getenv("RAG_TOP_K", "8")),
            "retrieval_k": int(os.getenv("RAG_RETRIEVAL_K", "20")),
            "rrf_k": int(os.getenv("RAG_RRF_K", "60")),
            "min_domain_score": float(os.getenv("RAG_MIN_DOMAIN_SCORE", "0.12")),
            "context_chars": int(os.getenv("RAG_CONTEXT_CHARS", "7000")),
            "llm_provider": _provider_name(
                (os.getenv("RAG_LLM_PROVIDER", "").strip()
                 if os.getenv("RAG_LLM_PROVIDER", "").strip() and os.getenv("RAG_LLM_PROVIDER", "").strip().lower() != "none"
                 else (os.getenv("LLM_PROVIDER_TYPE") or os.getenv("LLM_PROVIDER_NAME") or os.getenv("RAG_LLM_PROVIDER") or "none"))
            ),
            "llm_model": os.getenv("RAG_LLM_MODEL") or os.getenv("LLM_MODEL", ""),
            "api_key": os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY", ""),
            "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
            "nvidia_api_key": os.getenv("NVIDIA_API_KEY", ""),
            "api_base": os.getenv("RAG_API_BASE") or os.getenv("LLM_BASE_URL", ""),
            "host": os.getenv("RAG_HOST", "127.0.0.1"),
            "port": int(os.getenv("RAG_PORT") or os.getenv("PORT", "8000")),
            "qdrant_url": os.getenv("QDRANT_URL", ""),
            "qdrant_path": Path(os.getenv("QDRANT_PATH", str(data_dir / "qdrant"))),
            "query_understanding_enabled": _as_bool(os.getenv("RAG_QUERY_UNDERSTANDING_ENABLED", "true"), True),
            "query_max_variants": int(os.getenv("RAG_QUERY_MAX_VARIANTS", "4")),
            "recovery_multiplier": int(os.getenv("RAG_RECOVERY_MULTIPLIER", "3")),
            "partial_recovery_threshold": float(os.getenv("RAG_PARTIAL_RECOVERY_THRESHOLD", "0.35")),
            "conversation_db_path": Path(os.getenv("RAG_CONVERSATION_DB", str(data_dir / "conversations.sqlite3"))),
            "chat_context_chars": int(os.getenv("RAG_CHAT_CONTEXT_CHARS", "6000")),
            "chat_total_context_chars": int(os.getenv("RAG_CHAT_TOTAL_CONTEXT_CHARS", "15000")),
            "chat_full_history_threshold": int(os.getenv("RAG_CHAT_FULL_HISTORY_THRESHOLD", "12")),
            "chat_recent_turns": int(os.getenv("RAG_CHAT_RECENT_TURNS", "6")),
            "chat_memory_top_k": int(os.getenv("RAG_CHAT_MEMORY_TOP_K", "4")),
            "chat_summary_chars": int(os.getenv("RAG_CHAT_SUMMARY_CHARS", "1200")),
        }
        values.update(overrides)
        values["llm_provider"] = _provider_name(values.get("llm_provider", "none"))
        # LLM_API_KEY is a provider-agnostic alias used by some AttachAI deployments.
        provider_key = os.getenv("LLM_API_KEY", "")
        if provider_key and values["llm_provider"] in {"gemini", "google"} and not values.get("gemini_api_key"):
            values["gemini_api_key"] = provider_key
        if provider_key and values["llm_provider"] == "nvidia" and not values.get("nvidia_api_key"):
            values["nvidia_api_key"] = provider_key
        # Derived persistence paths follow an overridden data directory unless the
        # caller explicitly supplied a dedicated path or corresponding environment value.
        if "conversation_db_path" not in overrides and not os.getenv("RAG_CONVERSATION_DB"):
            values["conversation_db_path"] = Path(values["data_dir"]) / "conversations.sqlite3"
        if "qdrant_path" not in overrides and not os.getenv("QDRANT_PATH"):
            values["qdrant_path"] = Path(values["data_dir"]) / "qdrant"
        for key in ("knowledge_dir", "data_dir", "qdrant_path", "conversation_db_path"):
            if isinstance(values.get(key), str):
                values[key] = Path(values[key])
        if values.get("conversation_db_path") is None:
            values["conversation_db_path"] = values["data_dir"] / "conversations.sqlite3"
        values["query_understanding_enabled"] = _as_bool(values.get("query_understanding_enabled"), True)
        settings = cls(**values)
        return settings.ensure_dirs()

    @classmethod
    def from_yaml(cls, path, **overrides):
        p = Path(path)
        try:
            import yaml
            values = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except ImportError:
            values = {}
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#") and ":" in line:
                    key, value = line.split(":", 1)
                    values[key.strip()] = value.strip().strip("\"'")
        values.update(overrides)
        integer_fields = {
            "embedding_dim", "chunk_size", "chunk_overlap", "top_k", "retrieval_k", "rrf_k", "context_chars", "port",
            "query_max_variants", "recovery_multiplier", "chat_context_chars", "chat_total_context_chars", "chat_full_history_threshold", "chat_recent_turns",
            "chat_memory_top_k", "chat_summary_chars",
        }
        for key in integer_fields:
            if key in values:
                try:
                    values[key] = int(values[key])
                except (TypeError, ValueError):
                    pass
        if "query_understanding_enabled" in values:
            values["query_understanding_enabled"] = _as_bool(values["query_understanding_enabled"], True)
        for key in ("partial_recovery_threshold", "min_domain_score"):
            if key in values:
                try:
                    values[key] = float(values[key])
                except (TypeError, ValueError):
                    pass
        return cls.from_env(**values)

    def ensure_dirs(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.parent.mkdir(parents=True, exist_ok=True)
        if self.conversation_db_path is None:
            self.conversation_db_path = self.data_dir / "conversations.sqlite3"
        self.conversation_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.query_max_variants = max(1, min(int(self.query_max_variants), 8))
        self.recovery_multiplier = max(1, min(int(self.recovery_multiplier), 8))
        self.partial_recovery_threshold = min(1.0, max(0.0, float(self.partial_recovery_threshold)))
        self.chat_context_chars = max(500, int(self.chat_context_chars))
        self.chat_total_context_chars = max(3000, int(self.chat_total_context_chars))
        self.chat_full_history_threshold = max(2, int(self.chat_full_history_threshold))
        self.chat_recent_turns = max(1, int(self.chat_recent_turns))
        self.chat_memory_top_k = max(0, int(self.chat_memory_top_k))
        self.chat_summary_chars = max(200, int(self.chat_summary_chars))
        return self
