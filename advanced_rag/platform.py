"""AttachAI multi-tenant admin platform primitives.

Each client receives an isolated knowledge directory, vector database and conversation
SQLite database. Only hashes of client API keys are stored.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import urlparse

from .app import RAGApp
from .config import Settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any, fallback):
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, type(fallback)) else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def normalize_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "://" not in value and not value.startswith("*."):
        value = "https://" + value
    wildcard = value.startswith("*.") or "://*" in value
    if value.startswith("*."):
        cleaned = value[2:]
        parsed = urlparse("https://" + cleaned)
    elif "://*." in value:
        cleaned = value.replace("://*.", "://", 1)
        parsed = urlparse(cleaned)
    else:
        parsed = urlparse(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").strip(".").lower()
    if not host or any(c.isspace() for c in host) or "/" in host:
        raise ValueError("Enter a valid website domain, for example example.com")
    if len(host) > 253:
        raise ValueError("Website domain is too long")
    return ("*." if wildcard else "") + host


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _default_settings() -> dict[str, Any]:
    return {
        "welcome_message": "Hi! How can I help you today?",
        "fallback_message": "I could not find a supported answer in the available knowledge base. Please contact the business team for help.",
        "system_prompt": "Be helpful, concise, and professional. Answer business-specific factual questions only from the uploaded knowledge base.",
        "llm_provider": "inherit",
        "llm_model": "",
    }


def _default_widget() -> dict[str, Any]:
    return {
        "primary_color": "#6757e8",
        "theme": "light",
        "position": "right",
        "width": 360,
        "height": 520,
        "suggested_questions": ["What services do you offer?", "How can I contact you?"],
    }


class AdminStore:
    """SQLite-backed tenant registry and admin-key management."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tenant_root = self.data_dir / "clients"
        self.tenant_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "attachai_admin.sqlite3"
        self._lock = threading.RLock()
        self.admin_key = self._load_admin_key()
        self._initialize()

    def _load_admin_key(self) -> str:
        key = os.getenv("ADMIN_API_KEY", "").strip()
        unsafe = {"set", "change-me", "changeme", "your-admin-key", "password", "admin"}
        is_prod = os.getenv("NODE_ENV", "").lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production" or bool(os.getenv("RENDER"))
        if key and key.lower() in unsafe:
            if is_prod:
                raise RuntimeError("ADMIN_API_KEY is a placeholder. Set a strong unique secret in your deployment environment.")
            key = ""
        if key:
            return key
        if is_prod:
            raise RuntimeError("ADMIN_API_KEY is required in production. Set it in the hosting environment before starting AttachAI.")
        key_path = self.data_dir / "admin_bootstrap_key.txt"
        try:
            existing = key_path.read_text(encoding="utf-8").strip()
            if len(existing) >= 32:
                return existing
        except OSError:
            pass
        generated = secrets.token_urlsafe(36)
        key_path.write_text(generated + "\n", encoding="utf-8")
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return generated

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self):
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT '',
                allowed_domains_json TEXT NOT NULL DEFAULT '[]',
                api_key_hash TEXT NOT NULL,
                api_key_prefix TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused')),
                settings_json TEXT NOT NULL DEFAULT '{}',
                widget_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS ix_clients_status ON clients(status)")
            db.execute("""CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS ix_leads_client_created ON leads(client_id, created_at DESC)")

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "name": row["name"], "domain": row["domain"],
            "allowed_domains": _json(row["allowed_domains_json"], []),
            "api_key_prefix": row["api_key_prefix"], "status": row["status"],
            "settings": _json(row["settings_json"], _default_settings()),
            "widget": _json(row["widget_json"], _default_widget()),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def list_clients(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM clients ORDER BY created_at DESC").fetchall()
        return [self._row(row) for row in rows]

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return self._row(row) if row else None

    def create_client(self, name: str, domain: str = "", allowed_domains: list[str] | None = None) -> tuple[dict[str, Any], str]:
        clean_name = " ".join((name or "").split())
        if not clean_name or len(clean_name) > 120:
            raise ValueError("Client name is required and must be 120 characters or fewer")
        main_domain = normalize_domain(domain)
        domains = [normalize_domain(x) for x in (allowed_domains or []) if str(x).strip()]
        if main_domain and main_domain not in domains:
            domains.insert(0, main_domain)
        domains = list(dict.fromkeys(domains))
        client_id = "cl_" + secrets.token_hex(6)
        key = "att_live_" + secrets.token_urlsafe(32)
        now = _now()
        with self._db() as db:
            db.execute(
                "INSERT INTO clients(id,name,domain,allowed_domains_json,api_key_hash,api_key_prefix,status,settings_json,widget_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (client_id, clean_name, main_domain, json.dumps(domains), _key_hash(key), key[:17], "active",
                 json.dumps(_default_settings()), json.dumps(_default_widget()), now, now),
            )
        (self.tenant_root / client_id / "knowledge").mkdir(parents=True, exist_ok=True)
        return self.get_client(client_id) or {}, key

    def update_client(self, client_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        client = self.get_client(client_id)
        if not client:
            return None
        allowed = {"name", "domain", "allowed_domains", "status", "settings", "widget"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError("Unsupported client fields: " + ", ".join(sorted(unknown)))
        updates = dict(client)
        updates.update(payload)
        if "name" in payload:
            updates["name"] = " ".join(str(payload["name"]).split())
            if not updates["name"] or len(updates["name"]) > 120:
                raise ValueError("Client name is required and must be 120 characters or fewer")
        if "domain" in payload:
            updates["domain"] = normalize_domain(str(payload.get("domain") or ""))
        if "allowed_domains" in payload:
            if not isinstance(payload["allowed_domains"], list):
                raise ValueError("allowed_domains must be a list")
            updates["allowed_domains"] = list(dict.fromkeys(normalize_domain(str(x)) for x in payload["allowed_domains"] if str(x).strip()))
        if updates.get("domain") and updates["domain"] not in updates["allowed_domains"]:
            updates["allowed_domains"].insert(0, updates["domain"])
        if "status" in payload and payload["status"] not in {"active", "paused"}:
            raise ValueError("status must be active or paused")
        if "settings" in payload:
            if not isinstance(payload["settings"], dict):
                raise ValueError("settings must be an object")
            updates["settings"] = {**client["settings"], **payload["settings"]}
            for field in ("welcome_message", "fallback_message", "system_prompt"):
                val = str(updates["settings"].get(field, ""))
                if len(val) > 8000:
                    raise ValueError(f"{field} must be 8000 characters or fewer")
                updates["settings"][field] = val
            provider = str(updates["settings"].get("llm_provider", "inherit")).lower()
            if provider not in {"inherit", "none", "openai", "nvidia", "gemini"}:
                raise ValueError("llm_provider must be inherit, none, openai, nvidia, or gemini")
        if "widget" in payload:
            if not isinstance(payload["widget"], dict):
                raise ValueError("widget must be an object")
            widget = {**client["widget"], **payload["widget"]}
            color = str(widget.get("primary_color", "#6757e8"))
            if not (len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
                raise ValueError("primary_color must be a hex color such as #6757e8")
            widget["primary_color"] = color
            widget["theme"] = "dark" if widget.get("theme") == "dark" else "light"
            widget["position"] = "left" if widget.get("position") == "left" else "right"
            widget["width"] = max(300, min(520, int(widget.get("width", 360))))
            widget["height"] = max(360, min(760, int(widget.get("height", 520))))
            questions = widget.get("suggested_questions", [])
            if isinstance(questions, str):
                questions = questions.splitlines()
            widget["suggested_questions"] = [str(q).strip()[:160] for q in questions if str(q).strip()][:6]
            updates["widget"] = widget
        now = _now()
        with self._db() as db:
            db.execute("""UPDATE clients SET name=?,domain=?,allowed_domains_json=?,status=?,settings_json=?,widget_json=?,updated_at=? WHERE id=?""",
                       (updates["name"], updates["domain"], json.dumps(updates["allowed_domains"]), updates["status"],
                        json.dumps(updates["settings"], ensure_ascii=False), json.dumps(updates["widget"], ensure_ascii=False), now, client_id))
        return self.get_client(client_id)

    def authenticate_client_key(self, client_id: str, key: str) -> bool:
        client = self.get_client(client_id)
        return bool(client and key and secrets.compare_digest(self.key_hash_for_id(client_id), _key_hash(key)))

    def key_hash_for_id(self, client_id: str) -> str:
        with self._db() as db:
            row = db.execute("SELECT api_key_hash FROM clients WHERE id=? AND status='active'", (client_id,)).fetchone()
        return row[0] if row else ""

    def rotate_key(self, client_id: str) -> str | None:
        key = "att_live_" + secrets.token_urlsafe(32)
        with self._db() as db:
            cur = db.execute("UPDATE clients SET api_key_hash=?,api_key_prefix=?,updated_at=? WHERE id=?",
                             (_key_hash(key), key[:17], _now(), client_id))
        return key if cur.rowcount else None

    def delete_client(self, client_id: str) -> bool:
        with self._db() as db:
            cur = db.execute("DELETE FROM clients WHERE id=?", (client_id,))
        if cur.rowcount:
            shutil.rmtree(self.tenant_root / client_id, ignore_errors=True)
            return True
        return False

    def create_lead(self, client_id: str, name: str, email: str, phone: str = "", message: str = "", origin: str = "") -> dict[str, Any]:
        clean_name = " ".join(str(name or "").split())
        clean_email = str(email or "").strip().lower()
        clean_phone = str(phone or "").strip()
        clean_message = str(message or "").strip()
        if not clean_name or len(clean_name) > 120:
            raise ValueError("Name is required and must be 120 characters or fewer")
        if len(clean_email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean_email):
            raise ValueError("Enter a valid email address")
        if len(clean_phone) > 50 or len(clean_message) > 2000:
            raise ValueError("Phone or message is too long")
        lead = {"id": "ld_" + secrets.token_hex(8), "client_id": client_id, "name": clean_name,
                "email": clean_email, "phone": clean_phone, "message": clean_message,
                "origin": str(origin or "")[:500], "created_at": _now()}
        with self._db() as db:
            db.execute("INSERT INTO leads(id,client_id,name,email,phone,message,origin,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (lead["id"], client_id, lead["name"], lead["email"], lead["phone"], lead["message"], lead["origin"], lead["created_at"]))
        return lead

    def list_leads(self, client_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._db() as db:
            if client_id:
                rows = db.execute("SELECT l.*, c.name AS client_name FROM leads l JOIN clients c ON c.id=l.client_id WHERE l.client_id=? ORDER BY l.created_at DESC LIMIT ?", (client_id, limit)).fetchall()
            else:
                rows = db.execute("SELECT l.*, c.name AS client_name FROM leads l JOIN clients c ON c.id=l.client_id ORDER BY l.created_at DESC LIMIT ?", (limit,)).fetchall()
        return [{k: row[k] for k in row.keys()} for row in rows]

    def count_leads(self, client_id: str | None = None) -> int:
        with self._db() as db:
            if client_id:
                row = db.execute("SELECT COUNT(*) FROM leads WHERE client_id=?", (client_id,)).fetchone()
            else:
                row = db.execute("SELECT COUNT(*) FROM leads").fetchone()
        return int(row[0] if row else 0)

    def documents(self, client_id: str) -> list[dict[str, Any]]:
        root = self.tenant_root / client_id / "knowledge"
        if not root.exists():
            return []
        docs = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".txt", ".md", ".csv"}:
                stat = path.stat()
                docs.append({"name": path.name, "path": str(path.relative_to(root)), "size": stat.st_size,
                             "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")})
        return docs

    def count_conversations(self, client_id: str) -> int:
        path = self.tenant_root / client_id / "data" / "conversations.sqlite3"
        if not path.exists():
            return 0
        try:
            with sqlite3.connect(str(path), timeout=3) as db:
                return int(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        except sqlite3.Error:
            return 0


class AttachAIPlatform:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = AdminStore(settings.data_dir)
        self._rags: dict[str, RAGApp] = {}
        self._rag_lock = threading.RLock()
        self._rate: dict[tuple[str, str], tuple[int, float]] = {}

    def get_rag(self, client: dict[str, Any]) -> RAGApp:
        client_id = client["id"]
        with self._rag_lock:
            if client_id in self._rags:
                return self._rags[client_id]
            root = self.store.tenant_root / client_id
            data_dir = root / "data"
            configuration = client.get("settings") or {}
            provider = configuration.get("llm_provider", "inherit")
            if provider == "inherit":
                provider = self.settings.llm_provider
            model = configuration.get("llm_model") or self.settings.llm_model
            key_field = {"gemini": "gemini_api_key", "google": "gemini_api_key", "nvidia": "nvidia_api_key"}.get(str(provider).lower(), "api_key")
            key = getattr(self.settings, key_field, "")
            # A dashboard client can choose a configured provider/model but cannot save a raw provider secret.
            overrides = {
                "knowledge_dir": root / "knowledge",
                "data_dir": data_dir,
                "conversation_db_path": data_dir / "conversations.sqlite3",
                "qdrant_path": data_dir / "qdrant",
                "collection_name": "client_" + client_id,
                "llm_provider": provider,
                "llm_model": model,
                "api_key": key if key_field == "api_key" else self.settings.api_key,
                "gemini_api_key": self.settings.gemini_api_key,
                "nvidia_api_key": self.settings.nvidia_api_key,
                "api_base": self.settings.api_base,
                "extra": {**self.settings.extra, "system_prompt": configuration.get("system_prompt", "")},
            }
            tenant_settings = replace(self.settings, **overrides).ensure_dirs()
            rag = RAGApp(tenant_settings)
            self._rags[client_id] = rag
            return rag

    def is_origin_allowed(self, client: dict[str, Any], origin: str | None) -> bool:
        # A server-to-server caller may use the client key; browser widgets are domain-bound.
        if not origin:
            return False
        try:
            host = (urlparse(origin).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        domains = client.get("allowed_domains") or []
        if not domains:
            return host in {"localhost", "127.0.0.1", "::1"}
        for rule in domains:
            rule = str(rule).lower()
            if rule.startswith("*."):
                suffix = rule[1:]
                if host.endswith(suffix) and host != rule[2:]:
                    return True
            elif host == rule or (rule in {"localhost", "127.0.0.1"} and host == rule):
                return True
        return False

    def allow_request_rate(self, client_id: str, ip: str, limit: int = 45, period: int = 60) -> bool:
        now = time.monotonic()
        key = (client_id, ip)
        with self._rag_lock:
            count, start = self._rate.get(key, (0, now))
            if now - start >= period:
                count, start = 0, now
            if count >= limit:
                self._rate[key] = (count, start)
                return False
            self._rate[key] = (count + 1, start)
            if len(self._rate) > 5000:
                self._rate = {k: v for k, v in self._rate.items() if now - v[1] < period}
            return True

    def overview(self) -> dict[str, Any]:
        clients = self.store.list_clients()
        return {
            "product": "AttachAI",
            "total_clients": len(clients),
            "active_clients": sum(1 for c in clients if c["status"] == "active"),
            "paused_clients": sum(1 for c in clients if c["status"] == "paused"),
            "total_documents": sum(len(self.store.documents(c["id"])) for c in clients),
            "total_conversations": sum(self.store.count_conversations(c["id"]) for c in clients),
            "total_leads": self.store.count_leads(),
            "api_status": "online",
        }
