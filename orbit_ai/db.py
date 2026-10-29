from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def uid() -> str:
    return str(uuid.uuid4())


class SQLiteRepository:
    """Thread-safe SQLite implementation preserving Orbit AI's existing local schema."""

    name = "sqlite"

    def __init__(self, file: Path | str):
        self.file = Path(file)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.file, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=15000")
        self.init()
        if os.name != "nt":
            for db_file in (self.file, Path(str(self.file) + "-wal"), Path(str(self.file) + "-shm")):
                if db_file.exists():
                    try:
                        os.chmod(db_file, 0o600)
                    except OSError:
                        pass

    def init(self) -> None:
        with self.lock, self.db:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,slug TEXT UNIQUE NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,config TEXT NOT NULL,prompt TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY,client_id TEXT UNIQUE NOT NULL,key_hash TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS domains(client_id TEXT NOT NULL,domain TEXT NOT NULL,PRIMARY KEY(client_id,domain),FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,client_id TEXT NOT NULL,session_id TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(client_id,session_id),FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','assistant')),content TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,client_id TEXT NOT NULL,conversation_id TEXT,data TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new',FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL);
            CREATE TABLE IF NOT EXISTS usage_logs(id TEXT PRIMARY KEY,client_id TEXT NOT NULL,kind TEXT NOT NULL,units INTEGER NOT NULL,latency_ms REAL NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_logs(id TEXT PRIMARY KEY,client_id TEXT,action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS prompt_versions(id TEXT PRIMARY KEY,client_id TEXT NOT NULL,prompt TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS knowledge_files(client_id TEXT NOT NULL,filename TEXT NOT NULL,size INTEGER NOT NULL,chunks INTEGER NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(client_id,filename),FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lead_workflow(lead_id TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'new',assignee TEXT,notes TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS conversations_client_created_idx ON conversations(client_id,created_at DESC);
            CREATE INDEX IF NOT EXISTS messages_conversation_created_idx ON messages(conversation_id,created_at);
            CREATE INDEX IF NOT EXISTS leads_client_created_idx ON leads(client_id,created_at DESC);
            CREATE INDEX IF NOT EXISTS usage_client_created_idx ON usage_logs(client_id,created_at DESC);
            CREATE INDEX IF NOT EXISTS audit_client_created_idx ON audit_logs(client_id,created_at DESC);
            """)
            self._ensure_column("api_keys", "enabled", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column("leads", "status", "TEXT NOT NULL DEFAULT 'new'")
            # SQLite creates/updates the workflow row lazily to preserve compatibility with older DB files.

    def _ensure_column(self, table: str, col: str, declaration: str) -> None:
        existing = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in existing:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {declaration}")

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def health(self) -> dict[str, Any]:
        try:
            with self.lock:
                self.db.execute("SELECT 1").fetchone()
            return {"provider": self.name, "connected": True}
        except sqlite3.Error as exc:
            return {"provider": self.name, "connected": False, "detail": type(exc).__name__}

    @staticmethod
    def _json(value: Any, fallback: Any = None) -> Any:
        try:
            return json.loads(value) if value is not None else fallback
        except (TypeError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _client(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"], "name": row["name"], "slug": row["slug"],
            "enabled": bool(row["enabled"]), "config": json.loads(row["config"]),
            "prompt": row["prompt"], "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    def create_client(self, value: dict[str, Any]) -> dict[str, Any]:
        t = now()
        with self.lock, self.db:
            self.db.execute("INSERT INTO clients(id,name,slug,enabled,config,prompt,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (value["id"], value["name"], value["slug"], 1, json.dumps(value["config"]), value["prompt"], t, t))
            self.db.execute("INSERT INTO api_keys(id,client_id,key_hash,created_at,enabled) VALUES(?,?,?,?,1)", (uid(), value["id"], value["keyHash"], t))
            self.db.executemany("INSERT INTO domains(client_id,domain) VALUES(?,?)", [(value["id"], d) for d in sorted(set(value["domains"]))])
        return self.get_client(value["id"])  # type: ignore[return-value]

    def list_clients(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM clients ORDER BY created_at").fetchall()
        return [self._client(r) for r in rows if r is not None]  # type: ignore[list-item]

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self._client(self.db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone())

    def get_client_by_key_hash(self, hashed: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT c.* FROM clients c JOIN api_keys k ON k.client_id=c.id WHERE k.key_hash=? AND k.enabled=1", (hashed,)).fetchone()
            return self._client(row)

    def update_client(self, client_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_client(client_id)
        if not old:
            return None
        data = {**old, **updates, "updatedAt": now()}
        with self.lock, self.db:
            self.db.execute("UPDATE clients SET name=?,config=?,prompt=?,enabled=?,updated_at=? WHERE id=?",
                (data["name"], json.dumps(data["config"]), data["prompt"], int(bool(data["enabled"])), data["updatedAt"], client_id))
        return self.get_client(client_id)

    def delete_client(self, client_id: str) -> bool:
        with self.lock, self.db:
            cur = self.db.execute("DELETE FROM clients WHERE id=?", (client_id,))
            return cur.rowcount > 0

    def domains(self, client_id: str) -> list[str]:
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT domain FROM domains WHERE client_id=? ORDER BY domain", (client_id,)).fetchall()]

    def all_domains(self) -> list[str]:
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT DISTINCT d.domain FROM domains d JOIN clients c ON c.id=d.client_id WHERE c.enabled=1").fetchall()]

    def set_domains(self, client_id: str, domains: list[str]) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM domains WHERE client_id=?", (client_id,))
            self.db.executemany("INSERT INTO domains(client_id,domain) VALUES(?,?)", [(client_id, d) for d in sorted(set(domains))])

    def rotate_key(self, client_id: str, hashed: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE api_keys SET key_hash=?,created_at=?,enabled=1 WHERE client_id=?", (hashed, now(), client_id))

    def key_status(self, client_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT enabled,created_at FROM api_keys WHERE client_id=?", (client_id,)).fetchone()
            return {"enabled": row["enabled"], "created_at": row["created_at"]} if row else None

    def set_key_enabled(self, client_id: str, enabled: bool) -> bool:
        with self.lock, self.db:
            cur = self.db.execute("UPDATE api_keys SET enabled=? WHERE client_id=?", (int(enabled), client_id))
            return cur.rowcount > 0

    def create_conversation(self, client_id: str, session_id: str) -> str:
        with self.lock, self.db:
            row = self.db.execute("SELECT id FROM conversations WHERE client_id=? AND session_id=?", (client_id, session_id)).fetchone()
            if row:
                return row["id"]
            ident = uid()
            self.db.execute("INSERT INTO conversations(id,client_id,session_id,created_at) VALUES(?,?,?,?)", (ident, client_id, session_id, now()))
            return ident

    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)", (uid(), conversation_id, role, content, now()))

    def messages(self, conversation_id: str, limit: int | None = None) -> list[dict[str, str]]:
        with self.lock:
            if limit is None:
                rows = self.db.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at,rowid", (conversation_id,)).fetchall()
            else:
                bounded = max(1, min(int(limit), 1000))
                rows = self.db.execute(
                    "SELECT role,content FROM (SELECT role,content,created_at,rowid FROM messages WHERE conversation_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?) ORDER BY created_at,rowid",
                    (conversation_id, bounded),
                ).fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows]

    def conversation_for_client(self, client_id: str, conversation_id: str) -> dict[str, Any] | None:
        with self.lock:
            conv = self.db.execute("SELECT * FROM conversations WHERE id=? AND client_id=?", (conversation_id, client_id)).fetchone()
            if not conv:
                return None
            msgs = self.db.execute("SELECT role,content,created_at FROM messages WHERE conversation_id=? ORDER BY created_at,rowid", (conversation_id,)).fetchall()
            return {"id": conv["id"], "sessionId": conv["session_id"], "createdAt": conv["created_at"], "messages": [{"role": m["role"], "content": m["content"], "createdAt": m["created_at"]} for m in msgs]}

    def list_conversations(self, client_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("""SELECT c.id,c.session_id,c.created_at,
                (SELECT content FROM messages m WHERE m.conversation_id=c.id ORDER BY m.created_at DESC,m.rowid DESC LIMIT 1) last_message,
                (SELECT role FROM messages m WHERE m.conversation_id=c.id ORDER BY m.created_at DESC,m.rowid DESC LIMIT 1) last_role,
                (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id) message_count
                FROM conversations c WHERE c.client_id=? ORDER BY c.created_at DESC LIMIT ?""", (client_id, max(1, min(limit, 1000)))).fetchall()
            return [{"id": r["id"], "sessionId": r["session_id"], "createdAt": r["created_at"], "lastMessage": r["last_message"] or "", "lastRole": r["last_role"], "messageCount": r["message_count"]} for r in rows]

    def save_lead(self, client_id: str, conversation_id: str | None, data: dict[str, str]) -> str:
        ident, t = uid(), now()
        with self.lock, self.db:
            if conversation_id:
                conv = self.db.execute("SELECT id FROM conversations WHERE id=? AND client_id=?", (conversation_id, client_id)).fetchone()
                if not conv:
                    raise ValueError("Conversation not found for client")
            self.db.execute("INSERT INTO leads(id,client_id,conversation_id,data,created_at,status) VALUES(?,?,?,?,?,'new')", (ident, client_id, conversation_id, json.dumps(data), t))
            self.db.execute("INSERT OR REPLACE INTO lead_workflow(lead_id,status,assignee,notes,updated_at) VALUES(?,?,?,?,?)", (ident, "new", None, "", t))
        return ident

    def list_leads(self, client_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("""SELECT l.id,l.conversation_id,l.data,l.created_at,l.status,w.assignee,w.notes,w.updated_at
                FROM leads l LEFT JOIN lead_workflow w ON w.lead_id=l.id WHERE l.client_id=? ORDER BY l.created_at DESC""", (client_id,)).fetchall()
        output = []
        for r in rows:
            item = {"id": r["id"], "conversationId": r["conversation_id"], **(self._json(r["data"], {}) or {}),
                    "status": r["status"], "assignee": r["assignee"], "notes": r["notes"] or "",
                    "createdAt": r["created_at"], "updatedAt": r["updated_at"] or r["created_at"]}
            output.append(item)
        return output

    def update_lead(self, client_id: str, lead_id: str, data: dict[str, Any]) -> bool:
        with self.lock, self.db:
            row = self.db.execute("SELECT id,status FROM leads WHERE id=? AND client_id=?", (lead_id, client_id)).fetchone()
            if not row:
                return False
            current = self.db.execute("SELECT assignee,notes,status FROM lead_workflow WHERE lead_id=?", (lead_id,)).fetchone()
            status = data.get("status", current["status"] if current else row["status"])
            assignee = data.get("assignee", current["assignee"] if current else None)
            notes = data.get("notes", current["notes"] if current else "")
            self.db.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
            self.db.execute("INSERT OR REPLACE INTO lead_workflow(lead_id,status,assignee,notes,updated_at) VALUES(?,?,?,?,?)", (lead_id, status, assignee, notes, now()))
            return True

    def save_prompt_version(self, client_id: str, prompt: str) -> str:
        ident = uid()
        with self.lock, self.db:
            self.db.execute("INSERT INTO prompt_versions(id,client_id,prompt,created_at) VALUES(?,?,?,?)", (ident, client_id, prompt, now()))
        return ident

    def prompt_versions(self, client_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT id,client_id,prompt,created_at FROM prompt_versions WHERE client_id=? ORDER BY created_at DESC,rowid DESC", (client_id,)).fetchall()
        return [{"id": r["id"], "clientId": r["client_id"], "prompt": r["prompt"], "createdAt": r["created_at"]} for r in rows]

    def prompt_version(self, version_id: str) -> dict[str, Any] | None:
        with self.lock:
            r = self.db.execute("SELECT id,client_id,prompt FROM prompt_versions WHERE id=?", (version_id,)).fetchone()
            return {"id": r["id"], "client_id": r["client_id"], "prompt": r["prompt"]} if r else None

    def save_knowledge(self, client_id: str, filename: str, size: int, chunks: int, status: str = "ready") -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO knowledge_files(client_id,filename,size,chunks,status,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(client_id,filename) DO UPDATE SET size=excluded.size,chunks=excluded.chunks,status=excluded.status,updated_at=excluded.updated_at", (client_id, filename, size, chunks, status, now()))

    def knowledge(self, client_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT filename,size,chunks,status,updated_at FROM knowledge_files WHERE client_id=? ORDER BY filename", (client_id,)).fetchall()
            return [{"filename": r["filename"], "size": r["size"], "chunks": r["chunks"], "status": r["status"], "updatedAt": r["updated_at"]} for r in rows]

    def remove_knowledge(self, client_id: str, filename: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM knowledge_files WHERE client_id=? AND filename=?", (client_id, filename))

    def usage(self, client_id: str, kind: str, units: int, latency_ms: float) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO usage_logs(id,client_id,kind,units,latency_ms,created_at) VALUES(?,?,?,?,?,?)", (uid(), client_id, kind, units, latency_ms, now()))

    def audit(self, client_id: str | None, action: str, detail: Any) -> None:
        # Audit metadata is JSON only; callers must not pass raw API keys or document content.
        with self.lock, self.db:
            self.db.execute("INSERT INTO audit_logs(id,client_id,action,detail,created_at) VALUES(?,?,?,?,?)", (uid(), client_id, action, json.dumps(detail, ensure_ascii=False, default=str), now()))

    def audits(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT id,client_id,action,detail,created_at FROM audit_logs ORDER BY created_at DESC,rowid DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [{"id": r["id"], "clientId": r["client_id"], "action": r["action"], "detail": self._json(r["detail"], {}), "createdAt": r["created_at"]} for r in rows]

    def setting(self, key: str) -> Any:
        with self.lock:
            r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return self._json(r["value"], None) if r else None

    def set_setting(self, key: str, value: Any) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key, json.dumps(value), now()))

    def stats(self, client_id: str) -> dict[str, Any]:
        with self.lock:
            r = self.db.execute("""SELECT (SELECT count(*) FROM conversations WHERE client_id=?) conversations,
                (SELECT count(*) FROM messages m JOIN conversations x ON x.id=m.conversation_id WHERE x.client_id=?) messages,
                (SELECT count(*) FROM leads WHERE client_id=?) leads,
                (SELECT coalesce(sum(units),0) FROM usage_logs WHERE client_id=?) units""", (client_id, client_id, client_id, client_id)).fetchone()
        return dict(r) if r else {"conversations": 0, "messages": 0, "leads": 0, "units": 0}

    def overview(self) -> dict[str, Any]:
        with self.lock:
            r = self.db.execute("SELECT (SELECT count(*) FROM clients) clients,(SELECT count(*) FROM clients WHERE enabled=1) activeClients,(SELECT count(*) FROM conversations) conversations,(SELECT count(*) FROM messages) messages,(SELECT count(*) FROM leads) leads,(SELECT coalesce(sum(units),0) FROM usage_logs) units").fetchone()
        return dict(r) if r else {}

    def analytics(self, client_id: str, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self.lock:
            rows = self.db.execute("SELECT substr(created_at,1,10) day,count(*) messages FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.client_id=? AND created_at>=? GROUP BY substr(created_at,1,10) ORDER BY day", (client_id, since)).fetchall()
            lead_count = self.db.execute("SELECT count(*) FROM leads WHERE client_id=? AND created_at>=?", (client_id, since)).fetchone()[0]
            conversation_count = self.db.execute("SELECT count(*) FROM conversations WHERE client_id=? AND created_at>=?", (client_id, since)).fetchone()[0]
        return {"series": [{"date": r["day"], "messages": r["messages"]} for r in rows], "leads": lead_count, "conversations": conversation_count, "periodDays": days}

    def lead_conversation(self, client_id: str, conversation_id: str) -> dict[str, Any] | None:
        return self.conversation_for_client(client_id, conversation_id)

class SupabaseRepository:
    """PostgREST-backed repository matching the original Supabase schema."""
    name = "supabase"

    def __init__(self, url: str, key: str):
        import httpx
        self.url = url.rstrip("/") + "/rest/v1"
        self.key = key
        self.client = httpx.Client(timeout=15.0, headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"})

    def _request(self, method: str, table: str, params: dict[str, str] | None = None, data: Any = None, prefer: str | None = None) -> tuple[Any, Any]:
        headers = {}
        if prefer:
            headers["Prefer"] = prefer
        response = self.client.request(method, f"{self.url}/{table}", params=params or {}, json=data, headers=headers)
        if response.status_code >= 400:
            # Do not include request headers or credentials in errors.
            try:
                message = response.json().get("message", "Supabase request failed")
            except Exception:
                message = "Supabase request failed"
            raise RuntimeError(f"Supabase {method} {table} failed ({response.status_code}): {message}")
        payload = response.json() if response.content else None
        count = None
        content_range = response.headers.get("content-range", "")
        if "/" in content_range:
            try:
                count = int(content_range.rsplit("/", 1)[1])
            except ValueError:
                pass
        return payload, count

    def _all_rows(self, table: str, params: dict[str, str] | None = None, *, page_size: int = 1000) -> list[dict[str, Any]]:
        """Fetch every row in deterministic bounded pages, avoiding PostgREST's row cap."""
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        base = dict(params or {})
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            query = {**base, "limit": str(page_size), "offset": str(offset)}
            page, _ = self._request("GET", table, query)
            batch = page or []
            if not isinstance(batch, list):
                raise RuntimeError(f"Supabase returned an invalid row page for {table}")
            rows.extend(batch)
            if len(batch) < page_size:
                return rows
            offset += len(batch)

    def init(self) -> None:
        # Supabase schema is managed by the checked-in migration.
        return None
    def close(self) -> None:
        self.client.close()
    def health(self) -> dict[str, Any]:
        try:
            self._request("GET", "clients", {"select": "id", "limit": "1"})
            return {"provider": self.name, "connected": True}
        except Exception:
            return {"provider": self.name, "connected": False, "detail": "Supabase request failed"}

    @staticmethod
    def _client(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None: return None
        return {"id": str(row["id"]), "name": str(row["name"]), "slug": str(row["slug"]), "enabled": bool(row.get("enabled", True)), "config": row["config"] if isinstance(row["config"], dict) else json.loads(row["config"]), "prompt": str(row["prompt"]), "createdAt": str(row["created_at"]), "updatedAt": str(row["updated_at"])}

    def create_client(self, v: dict[str, Any]) -> dict[str, Any]:
        t = now()
        self._request("POST", "clients", data={"id": v["id"], "name": v["name"], "slug": v["slug"], "enabled": True, "config": v["config"], "prompt": v["prompt"], "created_at": t, "updated_at": t}, prefer="return=minimal")
        try:
            self._request("POST", "api_keys", data={"id": uid(), "client_id": v["id"], "key_hash": v["keyHash"], "enabled": True, "created_at": t}, prefer="return=minimal")
            if v["domains"]:
                self._request("POST", "domains", data=[{"client_id": v["id"], "domain": d} for d in v["domains"]], prefer="return=minimal")
        except Exception:
            try: self._request("DELETE", "clients", {"id": f"eq.{v['id']}"}, prefer="return=minimal")
            except Exception: pass
            raise
        return self.get_client(v["id"])  # type: ignore[return-value]

    def list_clients(self) -> list[dict[str, Any]]:
        rows = self._all_rows("clients", {"select": "*", "order": "created_at.asc,id.asc"})
        return [self._client(r) for r in rows]  # type: ignore[list-item]
    def get_client(self, client_id: str) -> dict[str, Any] | None:
        rows, _ = self._request("GET", "clients", {"select": "*", "id": f"eq.{client_id}", "limit": "1"})
        return self._client(rows[0]) if rows else None
    def get_client_by_key_hash(self, hashed: str) -> dict[str, Any] | None:
        rows, _ = self._request("GET", "clients", {"select": "*,api_keys!inner(key_hash,enabled)", "api_keys.key_hash": f"eq.{hashed}", "api_keys.enabled": "eq.true", "limit": "1"})
        return self._client(rows[0]) if rows else None
    def update_client(self, client_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_client(client_id)
        if not old: return None
        data = {**old, **updates, "updatedAt": now()}
        self._request("PATCH", "clients", {"id": f"eq.{client_id}"}, {"name": data["name"], "config": data["config"], "prompt": data["prompt"], "enabled": data["enabled"], "updated_at": data["updatedAt"]}, "return=minimal")
        return self.get_client(client_id)
    def delete_client(self, client_id: str) -> bool:
        _, count = self._request("DELETE", "clients", {"id": f"eq.{client_id}"}, prefer="return=representation,count=exact")
        return (count or 0) > 0
    def domains(self, client_id: str) -> list[str]:
        rows = self._all_rows("domains", {"select": "domain", "client_id": f"eq.{client_id}", "order": "domain.asc,client_id.asc"})
        return [str(r["domain"]) for r in rows]
    def all_domains(self) -> list[str]:
        rows = self._all_rows("domains", {"select": "domain,client_id,clients!inner(enabled)", "clients.enabled": "eq.true", "order": "client_id.asc,domain.asc"})
        return sorted({str(r["domain"]) for r in rows})
    def set_domains(self, client_id: str, domains: list[str]) -> None:
        normalized = sorted(set(domains))
        # Prefer a database-side transaction; the compatibility fallback below is
        # retained for projects that have not yet applied migration 0003.
        try:
            self._request(
                "POST", "rpc/replace_client_domains",
                data={"p_client_id": client_id, "p_domains": normalized},
                prefer="return=minimal",
            )
            return
        except RuntimeError as exc:
            if "failed (404)" not in str(exc):
                raise
        old_domains = self.domains(client_id)
        self._request("DELETE", "domains", {"client_id": f"eq.{client_id}"}, prefer="return=minimal")
        try:
            if normalized:
                self._request("POST", "domains", data=[{"client_id": client_id, "domain": d} for d in normalized], prefer="return=minimal")
        except Exception:
            # Best-effort compensation for projects not yet migrated to the RPC.
            try:
                self._request("DELETE", "domains", {"client_id": f"eq.{client_id}"}, prefer="return=minimal")
                if old_domains:
                    self._request("POST", "domains", data=[{"client_id": client_id, "domain": d} for d in old_domains], prefer="return=minimal")
            except Exception as rollback_error:
                raise RuntimeError("Domain update failed and restoring the previous allowlist also failed; inspect this tenant's domains immediately") from rollback_error
            raise
    def rotate_key(self, client_id: str, hashed: str) -> None:
        self._request("PATCH", "api_keys", {"client_id": f"eq.{client_id}"}, {"key_hash": hashed, "created_at": now(), "enabled": True}, "return=minimal")
    def key_status(self, client_id: str) -> dict[str, Any] | None:
        rows, _ = self._request("GET", "api_keys", {"select": "enabled,created_at", "client_id": f"eq.{client_id}", "limit": "1"})
        return rows[0] if rows else None
    def set_key_enabled(self, client_id: str, enabled: bool) -> bool:
        rows, _ = self._request("PATCH", "api_keys", {"client_id": f"eq.{client_id}"}, {"enabled": enabled}, "return=representation")
        return bool(rows)
    def create_conversation(self, client_id: str, session_id: str) -> str:
        rows, _ = self._request("GET", "conversations", {"select": "id", "client_id": f"eq.{client_id}", "session_id": f"eq.{session_id}", "limit": "1"})
        if rows: return str(rows[0]["id"])
        ident = uid()
        try:
            self._request("POST", "conversations", data={"id": ident, "client_id": client_id, "session_id": session_id, "created_at": now()}, prefer="return=minimal")
            return ident
        except RuntimeError:
            rows, _ = self._request("GET", "conversations", {"select": "id", "client_id": f"eq.{client_id}", "session_id": f"eq.{session_id}", "limit": "1"})
            if rows: return str(rows[0]["id"])
            raise
    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        self._request("POST", "messages", data={"id": uid(), "conversation_id": conversation_id, "role": role, "content": content, "created_at": now()}, prefer="return=minimal")
    def messages(self, conversation_id: str, limit: int | None = None) -> list[dict[str, str]]:
        params = {"select": "role,content,created_at,id", "conversation_id": f"eq.{conversation_id}"}
        if limit is None:
            rows = self._all_rows("messages", {**params, "order": "created_at.asc,id.asc"})
        else:
            bounded = max(1, min(int(limit), 1000))
            rows, _ = self._request("GET", "messages", {**params, "order": "created_at.desc,id.desc", "limit": str(bounded)})
            rows = list(reversed(rows or []))
        return [{"role": str(r["role"]), "content": str(r["content"])} for r in rows or []]
    def conversation_for_client(self, client_id: str, conversation_id: str) -> dict[str, Any] | None:
        rows, _ = self._request("GET", "conversations", {"select": "id,session_id,created_at", "id": f"eq.{conversation_id}", "client_id": f"eq.{client_id}", "limit": "1"})
        if not rows: return None
        msgs = self._all_rows("messages", {"select": "role,content,created_at,id", "conversation_id": f"eq.{conversation_id}", "order": "created_at.asc,id.asc"})
        r = rows[0]
        return {"id": r["id"], "sessionId": r["session_id"], "createdAt": r["created_at"], "messages": [{"role": m["role"], "content": m["content"], "createdAt": m["created_at"]} for m in msgs or []]}
    def list_conversations(self, client_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows, _ = self._request("GET", "conversations", {"select": "id,session_id,created_at", "client_id": f"eq.{client_id}", "order": "created_at.desc", "limit": str(max(1, min(limit, 1000)))})
        result = []
        for r in rows or []:
            msgs, _ = self._request("GET", "messages", {"select": "role,content", "conversation_id": f"eq.{r['id']}", "order": "created_at.desc", "limit": "1"})
            result.append({"id": r["id"], "sessionId": r["session_id"], "createdAt": r["created_at"], "lastMessage": msgs[0]["content"] if msgs else "", "lastRole": msgs[0]["role"] if msgs else None})
        return result
    def save_lead(self, client_id: str, conversation_id: str | None, data: dict[str, str]) -> str:
        ident = uid()
        self._request("POST", "leads", data={"id": ident, "client_id": client_id, "conversation_id": conversation_id, "data": data, "status": "new", "created_at": now()}, prefer="return=minimal")
        self._request("POST", "lead_workflow", data={"lead_id": ident, "status": "new", "notes": "", "updated_at": now()}, prefer="return=minimal")
        return ident
    def list_leads(self, client_id: str) -> list[dict[str, Any]]:
        rows = self._all_rows("leads", {"select": "id,conversation_id,data,created_at,status,lead_workflow(assignee,notes,updated_at,status)", "client_id": f"eq.{client_id}", "order": "created_at.desc,id.desc"})
        out = []
        for r in rows or []:
            w = r.get("lead_workflow") or []
            if isinstance(w, list): w = w[0] if w else {}
            d = r.get("data") or {}
            if isinstance(d, str): d = json.loads(d)
            out.append({"id": r["id"], "conversationId": r.get("conversation_id"), **d, "status": r.get("status") or w.get("status", "new"), "assignee": w.get("assignee"), "notes": w.get("notes") or "", "createdAt": r["created_at"], "updatedAt": w.get("updated_at")})
        return out
    def update_lead(self, client_id: str, lead_id: str, data: dict[str, Any]) -> bool:
        rows, _ = self._request("GET", "leads", {"select": "id,status", "id": f"eq.{lead_id}", "client_id": f"eq.{client_id}", "limit": "1"})
        if not rows: return False
        if "status" in data: self._request("PATCH", "leads", {"id": f"eq.{lead_id}", "client_id": f"eq.{client_id}"}, {"status": data["status"]}, "return=minimal")
        old, _ = self._request("GET", "lead_workflow", {"select": "*", "lead_id": f"eq.{lead_id}", "limit": "1"})
        current = old[0] if old else {"status": rows[0].get("status", "new"), "assignee": None, "notes": ""}
        update = {key: data[key] for key in ("status", "assignee", "notes") if key in data}
        update = {"status": update.get("status", current["status"]), "assignee": update.get("assignee", current.get("assignee")), "notes": update.get("notes", current.get("notes", "")), "updated_at": now()}
        if old: self._request("PATCH", "lead_workflow", {"lead_id": f"eq.{lead_id}"}, update, "return=minimal")
        else: self._request("POST", "lead_workflow", data={"lead_id": lead_id, **update}, prefer="return=minimal")
        return True
    def save_prompt_version(self, client_id: str, prompt: str) -> str:
        ident = uid(); self._request("POST", "prompt_versions", data={"id": ident, "client_id": client_id, "prompt": prompt, "created_at": now()}, prefer="return=minimal"); return ident
    def prompt_versions(self, client_id: str) -> list[dict[str, Any]]:
        rows = self._all_rows("prompt_versions", {"select": "id,prompt,created_at", "client_id": f"eq.{client_id}", "order": "created_at.desc,id.desc"})
        return [{"id": r["id"], "prompt": r["prompt"], "createdAt": r["created_at"]} for r in rows]
    def prompt_version(self, version_id: str) -> dict[str, Any] | None:
        rows, _ = self._request("GET", "prompt_versions", {"select": "id,client_id,prompt", "id": f"eq.{version_id}", "limit": "1"})
        if not rows: return None
        return {"id": rows[0]["id"], "client_id": rows[0]["client_id"], "prompt": rows[0]["prompt"]}
    def save_knowledge(self, client_id: str, filename: str, size: int, chunks: int, status: str = "ready") -> None:
        self._request("POST", "knowledge_files", data={"client_id": client_id, "filename": filename, "size": size, "chunks": chunks, "status": status, "updated_at": now()}, prefer="resolution=merge-duplicates,return=minimal")
    def knowledge(self, client_id: str) -> list[dict[str, Any]]:
        rows = self._all_rows("knowledge_files", {"select": "filename,size,chunks,status,updated_at", "client_id": f"eq.{client_id}", "order": "updated_at.desc,filename.asc"})
        return [{"filename": r["filename"], "size": r["size"], "chunks": r["chunks"], "status": r["status"], "updatedAt": r["updated_at"]} for r in rows]
    def remove_knowledge(self, client_id: str, filename: str) -> None:
        self._request("DELETE", "knowledge_files", {"client_id": f"eq.{client_id}", "filename": f"eq.{filename}"}, prefer="return=minimal")
    def usage(self, client_id: str, kind: str, units: int, latency_ms: float) -> None:
        self._request("POST", "usage_logs", data={"id": uid(), "client_id": client_id, "kind": kind, "units": units, "latency_ms": latency_ms, "created_at": now()}, prefer="return=minimal")
    def audit(self, client_id: str | None, action: str, detail: Any) -> None:
        self._request("POST", "audit_logs", data={"id": uid(), "client_id": client_id, "action": action, "detail": detail, "created_at": now()}, prefer="return=minimal")
    def audits(self, limit: int = 20) -> list[dict[str, Any]]:
        rows, _ = self._request("GET", "audit_logs", {"select": "id,client_id,action,detail,created_at", "order": "created_at.desc", "limit": str(max(1, min(limit, 200)))})
        return [{"id": r["id"], "clientId": r["client_id"], "action": r["action"], "detail": r["detail"], "createdAt": r["created_at"]} for r in rows or []]
    def setting(self, key: str) -> Any:
        rows, _ = self._request("GET", "settings", {"select": "value", "key": f"eq.{key}", "limit": "1"})
        return rows[0].get("value") if rows else None
    def set_setting(self, key: str, value: Any) -> None:
        self._request("POST", "settings", data={"key": key, "value": value, "updated_at": now()}, prefer="resolution=merge-duplicates,return=minimal")
    def stats(self, client_id: str) -> dict[str, Any]:
        conversations = self._count_rows("conversations", {"client_id": f"eq.{client_id}"})
        messages = self._count_rows("messages", {"select": "id,conversations!inner(client_id)", "conversations.client_id": f"eq.{client_id}"}) if conversations else 0
        leads = self._count_rows("leads", {"client_id": f"eq.{client_id}"})
        units = self._sum_usage_units({"client_id": f"eq.{client_id}"})
        return {"conversations": conversations, "messages": messages, "leads": leads, "units": units}
    def _count_rows(self, table: str, filters: dict[str, str] | None = None) -> int:
        params = {"select": "id", "limit": "1", **(filters or {})}
        _rows, count = self._request("GET", table, params, prefer="count=exact")
        if count is not None:
            return count
        # A missing Content-Range means the server did not provide an exact count.
        raise RuntimeError(f"Supabase did not return an exact count for {table}")

    def _sum_usage_units(self, filters: dict[str, str] | None = None) -> int:
        total = 0
        offset = 0
        base = {"select": "units", "order": "id.asc", **(filters or {})}
        while True:
            rows, _ = self._request("GET", "usage_logs", {**base, "limit": "1000", "offset": str(offset)})
            page = rows or []
            total += sum(int(row.get("units", 0) or 0) for row in page)
            if len(page) < 1000:
                return total
            offset += len(page)

    def overview(self) -> dict[str, Any]:
        return {
            "clients": self._count_rows("clients"),
            "activeClients": self._count_rows("clients", {"enabled": "eq.true"}),
            "conversations": self._count_rows("conversations"),
            "messages": self._count_rows("messages"),
            "leads": self._count_rows("leads"),
            "units": self._sum_usage_units(),
        }
    def analytics(self, client_id: str, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        convs = self._all_rows("conversations", {"select": "id,created_at", "client_id": f"eq.{client_id}", "created_at": f"gte.{since}", "order": "created_at.asc,id.asc"})
        series: dict[str, int] = {}
        messages = 0
        for conv in convs:
            rows = self._all_rows("messages", {"select": "created_at,id", "conversation_id": f"eq.{conv['id']}", "created_at": f"gte.{since}", "order": "created_at.asc,id.asc"})
            for r in rows:
                day = str(r["created_at"])[:10]; series[day] = series.get(day, 0) + 1; messages += 1
        leads = self._all_rows("leads", {"select": "id,created_at", "client_id": f"eq.{client_id}", "created_at": f"gte.{since}", "order": "created_at.asc,id.asc"})
        return {"series": [{"date": k, "messages": v} for k, v in sorted(series.items())], "leads": len(leads), "conversations": len(convs), "periodDays": days, "messages": messages}
