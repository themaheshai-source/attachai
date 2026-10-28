"""AttachAI FastAPI API: legacy RAG endpoints plus authenticated admin/client platform."""
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any

from .app import RAGApp
from .conversation_memory import SessionNotFoundError
from .platform import AttachAIPlatform


def create_app(rag=None):
    try:
        from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Query
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Install fastapi, uvicorn, and python-multipart to use the API") from exc

    service = rag or RAGApp()
    platform = AttachAIPlatform(service.settings)
    app = FastAPI(title="AttachAI Platform API", version="1.2.0", description="Multi-client grounded assistant platform")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Client-ID", "X-Client-Key"],
        max_age=600,
    )

    static_dir = Path(__file__).resolve().parent / "static"
    production = os.getenv("NODE_ENV", "").lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production" or bool(os.getenv("RENDER"))
    secure_legacy = os.getenv("ATTACHAI_SECURE_LEGACY_API", "true" if production else "false").lower() in {"1", "true", "yes", "on"}

    class ChatRequest(BaseModel):
        message: str = Field(min_length=1, max_length=12000)
        session_id: str | None = Field(default=None, min_length=1, max_length=128)
        k: int | None = Field(default=None, ge=1, le=50)

    class CreateClientRequest(BaseModel):
        name: str = Field(min_length=1, max_length=120)
        domain: str = Field(default="", max_length=300)
        allowed_domains: list[str] = Field(default_factory=list, max_length=30)

    class ClientChatRequest(BaseModel):
        client_id: str = Field(min_length=3, max_length=64)
        message: str = Field(min_length=1, max_length=12000)
        session_id: str | None = Field(default=None, min_length=1, max_length=128)
        k: int | None = Field(default=None, ge=1, le=50)

    class ClientLeadRequest(BaseModel):
        client_id: str = Field(min_length=3, max_length=64)
        name: str = Field(min_length=1, max_length=120)
        email: str = Field(min_length=3, max_length=254)
        phone: str = Field(default="", max_length=50)
        message: str = Field(default="", max_length=2000)
        consent: bool = False

    def admin_auth(request: Request):
        header = request.headers.get("authorization", "")
        supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not supplied or not secrets.compare_digest(supplied, platform.store.admin_key):
            raise HTTPException(status_code=401, detail="Admin authentication required", headers={"WWW-Authenticate": "Bearer"})

    def legacy_auth(request: Request):
        if secure_legacy:
            admin_auth(request)

    def get_active_client(client_id: str) -> dict[str, Any]:
        client = platform.store.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        if client["status"] != "active":
            raise HTTPException(status_code=403, detail="This client assistant is paused")
        return client

    def check_client_origin(request: Request, client: dict[str, Any], require_key_when_no_origin: bool = True):
        origin = request.headers.get("origin")
        if origin and platform.is_origin_allowed(client, origin):
            return
        supplied_key = request.headers.get("x-client-key", "")
        if supplied_key and platform.store.authenticate_client_key(client["id"], supplied_key):
            return
        if not origin and not require_key_when_no_origin:
            return
        raise HTTPException(status_code=403, detail="Origin is not on this client's domain allowlist")

    @app.get("/", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    def admin_dashboard():
        dashboard = static_dir / "dashboard.html"
        if not dashboard.is_file():
            return HTMLResponse("<h1>AttachAI</h1><p>Dashboard asset is missing.</p>", status_code=500)
        return HTMLResponse(dashboard.read_text(encoding="utf-8"))

    @app.get("/widget.js", include_in_schema=False)
    def widget_script():
        path = static_dir / "widget.js"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Widget script not found")
        return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "public, max-age=300"})

    @app.get("/health")
    def health():
        return {"status": "ok", "product": "AttachAI", "version": "1.2.0", "chunks": len(service.chunks), "platform": "online"}

    # Legacy single-tenant RAG API (backward compatible for local development).
    @app.post("/ingest")
    def ingest_endpoint(request: Request, force: bool = False):
        legacy_auth(request)
        try:
            return service.ingest(force=force)
        except Exception:
            raise HTTPException(status_code=500, detail="Ingestion failed. Check server-side configuration and logs.") from None

    @app.post("/sessions")
    def create_session_endpoint(request: Request):
        legacy_auth(request)
        try:
            return {"session_id": service.new_session()}
        except Exception:
            raise HTTPException(status_code=500, detail="Could not create a chat session.") from None

    @app.get("/sessions/{session_id}")
    def get_session_endpoint(session_id: str, request: Request):
        legacy_auth(request)
        try:
            messages = service.session_history(session_id)
            return {"session_id": session_id, "messages": [
                {"message_id": m["message_id"], "role": m["role"], "content": m["content"], "created_at": m["created_at"], "metadata": m["metadata"]}
                for m in messages
            ]}
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="Chat session not found.") from None
        except Exception:
            raise HTTPException(status_code=500, detail="Could not load chat history.") from None

    @app.post("/chat")
    def chat_endpoint(body: ChatRequest, request: Request):
        legacy_auth(request)
        try:
            return service.query(body.message, body.k, session_id=body.session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="Chat session not found.") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception:
            raise HTTPException(status_code=500, detail="Query failed. Check server-side configuration and logs.") from None

    @app.post("/query")
    def query_endpoint(body: ChatRequest, request: Request):
        return chat_endpoint(body, request)

    @app.get("/debug/retrieval")
    def debug_endpoint(request: Request):
        legacy_auth(request)
        if not service.settings.extra.get("debug", False):
            raise HTTPException(status_code=404, detail="Debug mode is disabled")
        return service.last_debug

    # Authenticated admin APIs.
    @app.get("/api/admin/overview")
    def admin_overview(request: Request):
        admin_auth(request)
        return platform.overview()

    @app.get("/api/admin/leads")
    def list_all_leads(request: Request, limit: int = Query(default=100, ge=1, le=500)):
        admin_auth(request)
        return {"leads": platform.store.list_leads(limit=limit)}

    @app.get("/api/admin/clients")
    def list_clients(request: Request):
        admin_auth(request)
        result = []
        for client in platform.store.list_clients():
            client["document_count"] = len(platform.store.documents(client["id"]))
            client["conversation_count"] = platform.store.count_conversations(client["id"])
            client["lead_count"] = platform.store.count_leads(client["id"])
            result.append(client)
        return {"clients": result}

    @app.post("/api/admin/clients", status_code=201)
    def create_client(body: CreateClientRequest, request: Request):
        admin_auth(request)
        try:
            client, client_key = platform.store.create_client(body.name, body.domain, body.allowed_domains)
            return {"client": client, "api_key": client_key, "message": "Save this API key now. It is only shown at creation and rotation."}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception:
            raise HTTPException(status_code=500, detail="Could not create client") from None

    @app.get("/api/admin/clients/{client_id}")
    def get_client(client_id: str, request: Request):
        admin_auth(request)
        client = platform.store.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        client["documents"] = platform.store.documents(client_id)
        client["document_count"] = len(client["documents"])
        client["conversation_count"] = platform.store.count_conversations(client_id)
        client["lead_count"] = platform.store.count_leads(client_id)
        return {"client": client}

    @app.patch("/api/admin/clients/{client_id}")
    async def update_client(client_id: str, request: Request):
        admin_auth(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            client = platform.store.update_client(client_id, payload)
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")
            # Invalidate cached service if its provider/prompt configuration changed.
            platform._rags.pop(client_id, None)
            return {"client": client}
        except HTTPException:
            raise
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @app.post("/api/admin/clients/{client_id}/rotate-key")
    def rotate_client_key(client_id: str, request: Request):
        admin_auth(request)
        key = platform.store.rotate_key(client_id)
        if not key:
            raise HTTPException(status_code=404, detail="Client not found")
        return {"api_key": key, "message": "Save this API key now. Existing integrations using the previous key must be updated."}

    @app.delete("/api/admin/clients/{client_id}")
    def delete_client(client_id: str, request: Request):
        admin_auth(request)
        platform._rags.pop(client_id, None)
        if not platform.store.delete_client(client_id):
            raise HTTPException(status_code=404, detail="Client not found")
        return {"deleted": True, "client_id": client_id}

    @app.get("/api/admin/clients/{client_id}/documents")
    def list_documents(client_id: str, request: Request):
        admin_auth(request)
        if not platform.store.get_client(client_id):
            raise HTTPException(status_code=404, detail="Client not found")
        return {"documents": platform.store.documents(client_id)}

    @app.post("/api/admin/clients/{client_id}/documents", status_code=201)
    async def upload_document(client_id: str, request: Request, file: UploadFile = File(...)):
        admin_auth(request)
        client = platform.store.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        original = Path(file.filename or "upload").name
        suffix = Path(original).suffix.lower()
        if suffix not in {".pdf", ".docx", ".txt", ".md", ".csv"}:
            raise HTTPException(status_code=415, detail="Supported file types: PDF, DOCX, TXT, Markdown, and CSV")
        payload = await file.read(10 * 1024 * 1024 + 1)
        await file.close()
        if not payload:
            raise HTTPException(status_code=422, detail="Uploaded file is empty")
        if len(payload) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Each uploaded file must be 10 MB or smaller")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._") or ("document" + suffix)
        dest = platform.store.tenant_root / client_id / "knowledge" / safe_name
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}_{secrets.token_hex(3)}{dest.suffix}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return {"uploaded": True, "document": {"name": dest.name, "size": len(payload)}, "message": "File uploaded. Run knowledge ingestion to index it."}

    @app.delete("/api/admin/clients/{client_id}/documents/{document_name}")
    def delete_document(client_id: str, document_name: str, request: Request):
        admin_auth(request)
        client = platform.store.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        safe_name = Path(document_name).name
        if safe_name != document_name:
            raise HTTPException(status_code=400, detail="Invalid document name")
        target = platform.store.tenant_root / client_id / "knowledge" / safe_name
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Document not found")
        target.unlink()
        platform._rags.pop(client_id, None)
        return {"deleted": True, "document": safe_name, "note": "Run ingestion to remove old chunks from the index."}

    @app.post("/api/admin/clients/{client_id}/ingest")
    def ingest_client(client_id: str, request: Request, force: bool = False):
        admin_auth(request)
        client = platform.store.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        try:
            rag_instance = platform.get_rag(client)
            stats = rag_instance.ingest(force=force)
            return {"success": True, "stats": stats, "document_count": len(platform.store.documents(client_id)), "indexed_chunks": len(rag_instance.chunks)}
        except Exception:
            raise HTTPException(status_code=500, detail="Knowledge ingestion failed. Check server logs and supported file formats.") from None

    @app.get("/api/admin/clients/{client_id}/leads")
    def list_client_leads(client_id: str, request: Request, limit: int = Query(default=100, ge=1, le=500)):
        admin_auth(request)
        if not platform.store.get_client(client_id):
            raise HTTPException(status_code=404, detail="Client not found")
        return {"leads": platform.store.list_leads(client_id=client_id, limit=limit)}

    @app.get("/api/admin/clients/{client_id}/conversations")
    def list_conversations(client_id: str, request: Request, limit: int = Query(default=30, ge=1, le=100)):
        admin_auth(request)
        client = platform.store.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        db_path = platform.store.tenant_root / client_id / "data" / "conversations.sqlite3"
        if not db_path.exists():
            return {"conversations": []}
        try:
            with sqlite3.connect(str(db_path), timeout=5) as db:
                rows = db.execute("SELECT session_id,created_at,updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
                conversations = []
                for sid, created, updated in rows:
                    last = db.execute("SELECT role,content,created_at FROM messages WHERE session_id=? ORDER BY message_id DESC LIMIT 1", (sid,)).fetchone()
                    conversations.append({"session_id": sid, "created_at": created, "updated_at": updated,
                                          "last_role": last[0] if last else "", "preview": (last[1] if last else "")[:180],
                                          "last_message_at": last[2] if last else ""})
            return {"conversations": conversations}
        except sqlite3.Error:
            raise HTTPException(status_code=500, detail="Could not read this client's conversations") from None

    @app.get("/api/admin/clients/{client_id}/conversations/{session_id}")
    def get_conversation(client_id: str, session_id: str, request: Request):
        admin_auth(request)
        client = platform.store.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        db_path = platform.store.tenant_root / client_id / "data" / "conversations.sqlite3"
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="Conversation not found")
        try:
            with sqlite3.connect(str(db_path), timeout=5) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute("SELECT message_id,role,content,created_at,metadata_json FROM messages WHERE session_id=? ORDER BY message_id", (session_id,)).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="Conversation not found")
            messages = []
            for row in rows:
                try: metadata = json.loads(row["metadata_json"] or "{}")
                except json.JSONDecodeError: metadata = {}
                messages.append({"message_id": row["message_id"], "role": row["role"], "content": row["content"], "created_at": row["created_at"], "metadata": metadata})
            return {"session_id": session_id, "messages": messages}
        except sqlite3.Error:
            raise HTTPException(status_code=500, detail="Could not read this conversation") from None

    # Public widget endpoint. The browser sends the public client ID, never the secret key.
    @app.get("/api/client/config")
    def widget_config(client_id: str, request: Request):
        client = get_active_client(client_id)
        check_client_origin(request, client, require_key_when_no_origin=True)
        settings = client["settings"]
        return {"client_id": client_id, "name": client["name"], "welcome_message": settings.get("welcome_message", "Hi! How can I help?"),
                "fallback_message": settings.get("fallback_message", "Please contact the business team for help."), "widget": client["widget"]}

    @app.post("/api/client/chat")
    def client_chat(body: ClientChatRequest, request: Request):
        client = get_active_client(body.client_id)
        check_client_origin(request, client, require_key_when_no_origin=True)
        ip = request.client.host if request.client else "unknown"
        if not platform.allow_request_rate(body.client_id, ip):
            raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.")
        try:
            result = platform.get_rag(client).query(body.message, body.k, session_id=body.session_id)
            settings = client["settings"]
            if result.get("status") in {"NOT_SUPPORTED", "UNCERTAIN"} and settings.get("fallback_message"):
                result["answer"] = settings["fallback_message"]
            # Never return internal debug retrieval payloads from a public widget.
            result.pop("debug", None)
            return result
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="Chat session not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception:
            raise HTTPException(status_code=500, detail="The assistant could not process this message") from None

    @app.post("/api/client/leads", status_code=201)
    def create_public_lead(body: ClientLeadRequest, request: Request):
        client = get_active_client(body.client_id)
        check_client_origin(request, client, require_key_when_no_origin=True)
        ip = request.client.host if request.client else "unknown"
        if not platform.allow_request_rate(body.client_id, ip, limit=15):
            raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.")
        if not body.consent:
            raise HTTPException(status_code=422, detail="Consent to be contacted is required")
        try:
            lead = platform.store.create_lead(body.client_id, body.name, body.email, body.phone, body.message, request.headers.get("origin", ""))
            # Return only a confirmation reference, not the submitted personal details.
            return {"created": True, "lead_id": lead["id"], "message": "Thank you. Your details have been sent to the business team."}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    app.state.rag_service = service
    app.state.attachai_platform = platform
    app.state.secure_legacy_api = secure_legacy
    return app
