from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import platform
import re
import sys
import time
import httpx
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, UploadFile, Depends
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.datastructures import UploadFile as StarletteUploadFile

from . import __version__
from .config import Settings
from .db import SQLiteRepository, SupabaseRepository
from .security import generate_api_key, hash_key, normalize_domain, normalize_origin, origin_matches, safe_equal, clean_filename
from .models import (ClientConfig, CreateClientBody, ChatBody, LeadBody, ClientPatchBody, LeadPatchBody,
                     PromptPreviewBody, DuplicateClientBody, ProviderBody)
from .providers import (LocalEmbedding, OpenAIEmbedding, LocalVector, QdrantVector, SupabaseVector,
                        LocalStorage, SupabaseStorage, LocalLLM, OpenAICompatibleLLM,
                        OutboxNotification, SMTPNotification, SupabaseOutboxNotification)
from .knowledge import KnowledgeService
from .chat import ChatService

logger = logging.getLogger("orbit_ai")


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Enforce request byte limits while streaming, including chunked bodies without Content-Length."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _limit(scope: dict[str, Any]) -> int:
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").lower()
        if method == "POST" and path.endswith("/knowledge"):
            return 110 * 1024 * 1024
        if content_type.startswith(b"multipart/form-data"):
            return 10 * 1024 * 1024
        return 1024 * 1024

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(scope)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    body = b'{"error":{"code":"PAYLOAD_TOO_LARGE","message":"Request body is too large"}}'
                    await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
            except ValueError:
                pass
        seen = 0
        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    if not response_started:
                        body = b'{"error":{"code":"PAYLOAD_TOO_LARGE","message":"Request body is too large"}}'
                        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                        await send({"type": "http.response.body", "body": body})
                    raise _RequestBodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            # The 413 response was emitted above; unwind request parsing safely.
            return


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        self.status_code, self.code, self.message, self.details = status_code, code, message, details
        super().__init__(message)


class Metrics:
    def __init__(self):
        self.started = time.monotonic()
        self.latencies = deque(maxlen=5000)
        self.statuses: dict[str, int] = defaultdict(int)
        self.total = 0

    def record(self, latency_ms: float, status: int) -> None:
        self.latencies.append(max(0.0, latency_ms)); self.statuses[str(status)] += 1; self.total += 1

    def snapshot(self) -> dict[str, Any]:
        items = sorted(self.latencies)
        avg = sum(items) / len(items) if items else 0.0
        return {"requests": self.total, "uptimeSeconds": round(time.monotonic() - self.started, 2), "latencyMs": {"avg": round(avg, 2), "p95": round(items[min(len(items)-1, int(len(items)*0.95))], 2) if items else 0.0}, "statusCodes": dict(self.statuses)}

    def prometheus(self) -> str:
        return "\n".join(["# HELP orbit_http_requests_total Total HTTP requests", "# TYPE orbit_http_requests_total counter", f"orbit_http_requests_total {self.total}", "# HELP orbit_http_response_status_total Responses by status", "# TYPE orbit_http_response_status_total counter", *[f'orbit_http_response_status_total{{status="{k}"}} {v}' for k, v in sorted(self.statuses.items())]]) + "\n"


def _validated(model: type, value: Any) -> Any:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "Request validation failed", [{"path": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]) from exc


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ApiError(400, "INVALID_JSON", "Request body must be valid JSON") from exc


def _valid_uuid(value: str, label: str = "id") -> str:
    try:
        UUID(value)
        return value
    except (ValueError, TypeError, AttributeError) as exc:
        raise ApiError(400, "VALIDATION_ERROR", f"{label} must be a UUID") from exc


def _config_dump(value: ClientConfig) -> dict[str, Any]:
    return value.model_dump(exclude_none=True)


def _safe_url(value: str | None) -> bool:
    return bool(value and value.startswith(("http://", "https://")))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.database_provider == "sqlite":
        repo: Any = SQLiteRepository(settings.data_dir / "metadata.sqlite")
    else:
        repo = SupabaseRepository(settings.supabase_url or "", settings.supabase_service_role_key or "")
        repo.init()

    storage = SupabaseStorage(settings) if settings.storage_provider == "supabase" else LocalStorage(settings.data_dir / "objects")
    embedding = OpenAIEmbedding(settings) if settings.embedding_provider == "openai" else LocalEmbedding()
    if settings.vector_provider == "qdrant":
        vector: Any = QdrantVector(settings)
    elif settings.vector_provider == "supabase":
        vector = SupabaseVector(settings)
    else:
        vector = LocalVector(settings.data_dir / "vectors.json")
    llm = OpenAICompatibleLLM(settings) if settings.llm_provider_type != "local" else LocalLLM()
    if settings.notification_provider == "smtp":
        notification: Any = SMTPNotification(settings)
    elif settings.notification_provider == "supabase":
        notification = SupabaseOutboxNotification(settings)
    else:
        notification = OutboxNotification(settings.data_dir / "outbox")
    knowledge = KnowledgeService(settings, repo, storage, embedding, vector)
    chat = ChatService(settings, repo, embedding, vector, llm)
    metrics = Metrics()
    public_dir = Path(__file__).resolve().parent.parent / "public"
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            close = getattr(repo, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    app = FastAPI(title="Orbit AI", version=__version__, docs_url=None if settings.node_env == "production" else "/docs", redoc_url=None, lifespan=lifespan)
    app.add_middleware(RequestBodyLimitMiddleware)
    app.state.settings = settings
    app.state.repo = repo
    app.state.storage = storage
    app.state.embedding = embedding
    app.state.vector = vector
    app.state.llm = llm
    app.state.notification = notification
    app.state.knowledge = knowledge
    app.state.chat = chat
    app.state.metrics = metrics

    # Process-local limit matching the original 100 requests / minute default.
    request_times: dict[str, deque[float]] = defaultdict(deque)
    app.state.request_times = request_times
    max_rate_limit_identities = 10_000

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        started = time.perf_counter()
        ip = request.client.host if request.client else "unknown"
        now_ts = time.monotonic()
        # Keep the process-local limiter bounded even if clients rotate source IPs.
        if ip not in request_times and len(request_times) >= max_rate_limit_identities:
            for stale_ip, stale_window in list(request_times.items()):
                while stale_window and now_ts - stale_window[0] > 60:
                    stale_window.popleft()
                if not stale_window:
                    request_times.pop(stale_ip, None)
                if len(request_times) < max_rate_limit_identities:
                    break
            if len(request_times) >= max_rate_limit_identities:
                request_times.pop(next(iter(request_times)))
        window = request_times[ip]
        while window and now_ts - window[0] > 60:
            window.popleft()
        if len(window) >= 100:
            response = JSONResponse({"error": {"code": "RATE_LIMITED", "message": "Too many requests"}}, status_code=429)
            response.headers["Retry-After"] = "60"
            metrics.record((time.perf_counter() - started) * 1000, 429)
            return response
        window.append(now_ts)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                limit = 110 * 1024 * 1024 if request.url.path.endswith("/knowledge") and request.method == "POST" else (10 * 1024 * 1024 if request.headers.get("content-type", "").startswith("multipart/form-data") else 1024 * 1024)
                if length > limit:
                    response = JSONResponse({"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large"}}, status_code=413)
                    metrics.record((time.perf_counter() - started) * 1000, 413)
                    return response
            except ValueError:
                pass
        origin = request.headers.get("origin")
        allowed = False
        if origin:
            if request.url.path == "/v1" or request.url.path.startswith("/v1/"):
                try:
                    allowed = origin_matches(origin, repo.all_domains())
                except Exception:
                    allowed = False
            else:
                try:
                    allowed = any(normalize_origin(origin) == normalize_origin(x) for x in settings.allowed_origins)
                except Exception:
                    allowed = False
                if settings.node_env != "production" and not settings.allowed_origins:
                    allowed = True
        if request.method == "OPTIONS" and origin:
            response = Response(status_code=204 if allowed else 403)
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("unhandled request error")
                response = JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred"}}, status_code=500)
        if origin and allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "content-type, x-admin-api-key, x-api-key"
            response.headers["Access-Control-Max-Age"] = "600"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        metrics.record((time.perf_counter() - started) * 1000, response.status_code)
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        data: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            data["details"] = exc.details
        return JSONResponse({"error": data}, status_code=exc.status_code)

    @app.exception_handler(ValidationError)
    async def pydantic_error_handler(request: Request, exc: ValidationError):
        return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed", "details": [{"path": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]}}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        codes = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 429: "RATE_LIMITED"}
        return JSONResponse({"error": {"code": codes.get(exc.status_code, "HTTP_ERROR"), "message": str(exc.detail)}}, status_code=exc.status_code, headers=exc.headers)

    def admin_auth(request: Request) -> None:
        key = request.headers.get("x-admin-api-key", "")
        if not key or not safe_equal(key, settings.admin_api_key):
            raise ApiError(401, "ADMIN_UNAUTHORIZED", "Admin authentication required")

    def public_client(request: Request) -> dict[str, Any]:
        key = request.headers.get("x-api-key")
        origin = request.headers.get("origin")
        if not key:
            raise ApiError(401, "INVALID_API_KEY", "Valid public client credential required")
        client = repo.get_client_by_key_hash(hash_key(key))
        if not client or not client["enabled"]:
            raise ApiError(401, "INVALID_API_KEY", "Valid public client credential required")
        if not origin or not origin_matches(origin, repo.domains(client["id"])):
            raise ApiError(403, "ORIGIN_FORBIDDEN", "Origin is not allowed")
        return client

    async def provider_health() -> dict[str, Any]:
        health_results = await asyncio.gather(repo.health() if asyncio.iscoroutinefunction(repo.health) else asyncio.to_thread(repo.health), storage.health(), embedding.health(), vector.health(), llm.health(), notification.health(), return_exceptions=True)
        labels = ["database", "storage", "embedding", "vector", "llm", "notification"]
        result: dict[str, Any] = {}
        for label, value in zip(labels, health_results):
            if isinstance(value, BaseException):
                result[label] = {"provider": label, "connected": False, "detail": "health check failed"}
            else:
                result[label] = value
        return result

    # Public/system endpoints
    @app.get("/health")
    async def system_health():
        return {"status": "ok", "version": __version__, "providers": await provider_health(), **metrics.snapshot()}

    @app.get("/ready")
    async def ready():
        statuses = await provider_health()
        required = ["database", "storage", "embedding", "vector", "llm", "notification"]
        ready_flag = all(bool(statuses[k].get("connected")) for k in required)
        return JSONResponse({"ready": ready_flag, "providers": statuses}, status_code=200 if ready_flag else 503)

    @app.get("/metrics")
    async def prometheus_metrics():
        return PlainTextResponse(metrics.prometheus(), media_type="text/plain; version=0.0.4")

    @app.post("/admin/auth/validate")
    async def admin_validate(request: Request):
        admin_auth(request); return {"authenticated": True}

    @app.get("/admin/overview")
    async def admin_overview(request: Request):
        admin_auth(request)
        overview = repo.overview()
        health_vec = await vector.health()
        return {**overview, "recentAudits": repo.audits(12), "providers": {"llm": llm.name, "vector": health_vec.get("provider"), "embedding": embedding.name}}

    @app.post("/admin/clients")
    async def create_client(request: Request):
        admin_auth(request)
        body = _validated(CreateClientBody, await _json_body(request))
        client_id, api_key = str(uuid4()), generate_api_key()
        domains = []
        for domain in body.domains:
            try: domains.append(normalize_domain(domain))
            except ValueError as exc: raise ApiError(400, "VALIDATION_ERROR", "Invalid domain") from exc
        try:
            client = repo.create_client({"id": client_id, "name": body.name, "slug": body.slug, "domains": domains, "config": _config_dump(body.config), "prompt": body.prompt, "keyHash": hash_key(api_key)})
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ApiError(409, "CONFLICT", "Resource already exists") from exc
            raise
        repo.audit(client_id, "client.created", {"slug": body.slug})
        widget_url = settings.public_base_url.rstrip("/") + "/widget.js"
        return {"client": client, "apiKey": api_key, "embedCode": f'<script src="{widget_url}" data-api-key="{api_key}" async></script>', "copyOnce": True}

    @app.get("/admin/clients")
    async def list_clients(request: Request):
        admin_auth(request)
        raw = request.query_params
        try:
            q = raw.get("q", "")
            if len(q) > 120: raise ValueError("q must be at most 120 characters")
            status = raw.get("status", "all")
            if status not in {"all", "active", "suspended"}: raise ValueError("status is invalid")
            page, page_size = int(raw.get("page", "1")), int(raw.get("pageSize", "25"))
            if page < 1 or page_size < 1 or page_size > 100: raise ValueError("page or pageSize is invalid")
        except ValueError as exc: raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc
        results = []
        for item in repo.list_clients():
            if q and q.casefold() not in f"{item['name']} {item['slug']} {item['config'].get('teamEmail','')}".casefold(): continue
            if status != "all" and item["enabled"] != (status == "active"): continue
            key = repo.key_status(item["id"])
            results.append({**item, "domains": repo.domains(item["id"]), "apiKey": {"enabled": bool(key and key.get("enabled")), "createdAt": key.get("created_at") if key else None}})
        if not raw:
            return results
        return {"items": results[(page - 1) * page_size:page * page_size], "total": len(results), "page": page, "pageSize": page_size}

    @app.get("/admin/clients/{client_id}")
    async def get_client(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        client = repo.get_client(client_id)
        if not client: raise ApiError(404, "NOT_FOUND", "Client not found")
        key = repo.key_status(client_id)
        return {**client, "domains": repo.domains(client_id), "stats": repo.stats(client_id), "apiKey": {"enabled": bool(key and key.get("enabled")), "createdAt": key.get("created_at") if key else None}}

    @app.patch("/admin/clients/{client_id}")
    async def patch_client(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        body = _validated(ClientPatchBody, await _json_body(request))
        current = repo.get_client(client_id)
        if not current: raise ApiError(404, "NOT_FOUND", "Client not found")
        changes = body.model_dump(exclude_unset=True)
        if "config" in changes and changes["config"] is not None: changes["config"] = _config_dump(body.config)
        if "domains" in changes and changes["domains"] is not None:
            try: repo.set_domains(client_id, [normalize_domain(d) for d in changes.pop("domains")])
            except ValueError as exc: raise ApiError(400, "VALIDATION_ERROR", "Invalid domain") from exc
        if changes.get("prompt"):
            repo.save_prompt_version(client_id, current["prompt"])
        updated = repo.update_client(client_id, changes)
        repo.audit(client_id, "client.updated", {"fields": list(body.model_fields_set)})
        return updated

    @app.delete("/admin/clients/{client_id}", status_code=204)
    async def delete_client(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        current = repo.get_client(client_id)
        if not current: raise ApiError(404, "NOT_FOUND", "Client not found")
        # Disable first so provider cleanup failures cannot leave an active tenant
        # whose metadata has already been deleted. Retrying DELETE completes cleanup.
        if current["enabled"]:
            repo.update_client(client_id, {"enabled": False})
        try:
            await storage.remove_tenant(client_id)
            await vector.delete_tenant(client_id)
            repo.delete_client(client_id)
        except Exception as exc:
            logger.error("tenant cleanup incomplete for %s (%s)", client_id, type(exc).__name__)
            raise ApiError(503, "TENANT_CLEANUP_INCOMPLETE", "Tenant has been disabled, but data cleanup is incomplete. Retry deletion after resolving the provider failure.") from exc
        return Response(status_code=204)

    @app.post("/admin/clients/{client_id}/duplicate")
    async def duplicate_client(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        old = repo.get_client(client_id)
        if not old: raise ApiError(404, "NOT_FOUND", "Client not found")
        body = _validated(DuplicateClientBody, await _json_body(request))
        api_key, new_id = generate_api_key(), str(uuid4())
        try:
            new_client = repo.create_client({"id": new_id, "name": body.name, "slug": body.slug, "domains": repo.domains(client_id), "config": old["config"], "prompt": old["prompt"], "keyHash": hash_key(api_key)})
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower(): raise ApiError(409, "CONFLICT", "Resource already exists") from exc
            raise
        repo.audit(new_id, "client.created", {"slug": body.slug, "duplicatedFrom": client_id})
        widget_url = settings.public_base_url.rstrip("/") + "/widget.js"
        return {"client": new_client, "apiKey": api_key, "embedCode": f'<script src="{widget_url}" data-api-key="{api_key}" async></script>', "copyOnce": True}

    @app.post("/admin/clients/{client_id}/rotate-key")
    async def rotate_key(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        key = generate_api_key(); repo.rotate_key(client_id, hash_key(key)); repo.audit(client_id, "key.rotated", {})
        widget_url = settings.public_base_url.rstrip("/") + "/widget.js"
        return {"apiKey": key, "embedCode": f'<script src="{widget_url}" data-api-key="{key}" async></script>', "copyOnce": True}

    @app.post("/admin/clients/{client_id}/key/{action}")
    async def key_action(client_id: str, action: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if action not in {"enable", "disable"}: raise ApiError(400, "VALIDATION_ERROR", "Action must be enable or disable")
        if not repo.set_key_enabled(client_id, action == "enable"): raise ApiError(404, "NOT_FOUND", "Client not found")
        repo.audit(client_id, f"key.{action}d", {})
        return {"enabled": action == "enable"}

    @app.get("/admin/clients/{client_id}/prompts/history")
    async def prompt_history(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        return repo.prompt_versions(client_id)

    @app.post("/admin/clients/{client_id}/prompts/{version_id}/restore")
    async def restore_prompt(client_id: str, version_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id); _valid_uuid(version_id, "versionId")
        version = repo.prompt_version(version_id); current = repo.get_client(client_id)
        if not version or version["client_id"] != client_id or not current: raise ApiError(404, "NOT_FOUND", "Prompt version not found")
        repo.save_prompt_version(client_id, current["prompt"])
        return repo.update_client(client_id, {"prompt": version["prompt"]})

    @app.post("/admin/clients/{client_id}/prompts/reset")
    async def reset_prompt(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        current = repo.get_client(client_id)
        if not current: raise ApiError(404, "NOT_FOUND", "Client not found")
        repo.save_prompt_version(client_id, current["prompt"])
        return repo.update_client(client_id, {"prompt": "Answer using only the supplied knowledge. If the answer is unavailable, use the configured fallback message."})

    @app.post("/admin/clients/{client_id}/prompts/preview")
    async def preview_prompt(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        body = _validated(PromptPreviewBody, await _json_body(request))
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        preview = await chat.preview(client_id, body.question, body.prompt)
        evidence = preview["retrieval"]["evidence"]
        sources = [{"source": x["source"], "score": round(float(x.get("score", 0)), 3), "chunkId": x["id"]} for x in evidence]
        return {"answer": preview["answer"], "retrieval": {"count": len(evidence), "sources": sources}, "sources": sources}

    @app.post("/admin/clients/{client_id}/prompt")
    async def upload_prompt(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        current = repo.get_client(client_id)
        if not current: raise ApiError(404, "NOT_FOUND", "Client not found")
        form = await request.form(); part = form.get("file")
        if not isinstance(part, StarletteUploadFile):
            # Tolerate the first uploaded file irrespective of its form field name.
            part = next((v for _, v in form.multi_items() if isinstance(v, StarletteUploadFile)), None)
        if not part or not re.search(r"\.(txt|md)$", part.filename or "", re.I): raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Prompt must be TXT or MD")
        raw = await part.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024: raise ApiError(413, "PAYLOAD_TOO_LARGE", "Prompt file is too large")
        prompt = raw.decode("utf-8-sig", errors="replace").strip()
        if not prompt: raise ApiError(400, "VALIDATION_ERROR", "Prompt cannot be empty")
        repo.save_prompt_version(client_id, current["prompt"]); repo.update_client(client_id, {"prompt": prompt})
        return {"updated": True}

    @app.post("/admin/clients/{client_id}/config")
    async def upload_config(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        form = await request.form(); part = form.get("file")
        if not isinstance(part, StarletteUploadFile):
            part = next((v for _, v in form.multi_items() if isinstance(v, StarletteUploadFile)), None)
        if not part or not re.search(r"\.json$", part.filename or "", re.I): raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Config must be JSON")
        raw = await part.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024: raise ApiError(413, "PAYLOAD_TOO_LARGE", "Config file is too large")
        try: data = json.loads(raw)
        except json.JSONDecodeError as exc: raise ApiError(400, "VALIDATION_ERROR", "Config is not valid JSON") from exc
        config = _validated(ClientConfig, data)
        repo.update_client(client_id, {"config": _config_dump(config)})
        return {"updated": True, "config": _config_dump(config)}

    @app.post("/admin/clients/{client_id}/knowledge")
    async def upload_knowledge(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        form = await request.form()
        uploads = [v for _, v in form.multi_items() if isinstance(v, StarletteUploadFile)]
        if not uploads: raise ApiError(400, "FILE_REQUIRED", "At least one file is required")
        if len(uploads) > 10: raise ApiError(413, "PAYLOAD_TOO_LARGE", "At most 10 files are allowed per request")
        results = []
        for upload in uploads:
            data = await upload.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024: raise ApiError(413, "PAYLOAD_TOO_LARGE", "Each uploaded file must be at most 10 MB")
            try: results.append(await knowledge.upload(client_id, upload.filename or "document.txt", data))
            except ValueError as exc: raise ApiError(415 if "Unsupported" in str(exc) else 400, "UNSUPPORTED_MEDIA_TYPE" if "Unsupported" in str(exc) else "DOCUMENT_INVALID", str(exc)) from exc
        return results[0] if len(results) == 1 else {"items": results}

    @app.get("/admin/clients/{client_id}/knowledge")
    async def list_knowledge(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        return await knowledge.list(client_id)

    @app.delete("/admin/clients/{client_id}/knowledge/{filename}")
    async def delete_knowledge(client_id: str, filename: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        try: name = clean_filename(filename)
        except ValueError as exc: raise ApiError(400, "VALIDATION_ERROR", "Invalid filename") from exc
        try: return await knowledge.remove(client_id, name)
        except FileNotFoundError as exc: raise ApiError(404, "NOT_FOUND", "Knowledge file not found") from exc

    @app.post("/admin/clients/{client_id}/knowledge/rebuild")
    async def rebuild_knowledge(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        return await knowledge.rebuild(client_id)

    @app.get("/admin/clients/{client_id}/leads.csv")
    async def leads_csv(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        rows = repo.list_leads(client_id); columns = ["id", "name", "email", "phone", "requirement", "status", "assignee", "notes", "createdAt"]
        output = io.StringIO(newline=""); writer = csv.writer(output); writer.writerow(columns)
        def csv_safe(value: Any) -> str:
            text = str(value if value is not None else "")
            # Spreadsheet programs may evaluate cells beginning with a formula marker.
            if text.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
                return "'" + text
            return text
        for row in rows: writer.writerow([csv_safe(row.get(k, "")) for k in columns])
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="leads.csv"'})

    @app.get("/admin/clients/{client_id}/leads")
    async def list_leads(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        raw = request.query_params
        q, status = raw.get("q", ""), raw.get("status", "all")
        if len(q) > 120 or status not in {"all", "new", "contacted", "qualified", "won", "lost"}: raise ApiError(400, "VALIDATION_ERROR", "Invalid lead filters")
        try: page, page_size = int(raw.get("page", "1")), int(raw.get("pageSize", "25"))
        except ValueError as exc: raise ApiError(400, "VALIDATION_ERROR", "page and pageSize must be integers") from exc
        if page < 1 or page_size < 1 or page_size > 500: raise ApiError(400, "VALIDATION_ERROR", "Invalid page or pageSize")
        rows = [r for r in repo.list_leads(client_id) if (status == "all" or r.get("status") == status) and (not q or q.casefold() in json.dumps(r, ensure_ascii=False).casefold())]
        if not raw: return rows
        return {"items": rows[(page - 1) * page_size:page * page_size], "total": len(rows), "page": page, "pageSize": page_size}

    @app.patch("/admin/clients/{client_id}/leads/{lead_id}")
    async def patch_lead(client_id: str, lead_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id); _valid_uuid(lead_id, "leadId")
        body = _validated(LeadPatchBody, await _json_body(request)); changes = body.model_dump(exclude_unset=True)
        if not changes: return {"updated": True}
        if not repo.update_lead(client_id, lead_id, changes): raise ApiError(404, "NOT_FOUND", "Lead not found")
        repo.audit(client_id, "lead.updated", {"leadId": lead_id, "fields": list(changes)})
        return {"updated": True}

    @app.get("/admin/clients/{client_id}/leads/{lead_id}")
    async def get_lead(client_id: str, lead_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id); _valid_uuid(lead_id, "leadId")
        row = next((r for r in repo.list_leads(client_id) if r["id"] == lead_id), None)
        if row is None: raise ApiError(404, "NOT_FOUND", "Lead not found")
        row["conversation"] = repo.conversation_for_client(client_id, row["conversationId"]) if row.get("conversationId") else None
        return row

    @app.get("/admin/clients/{client_id}/conversations")
    async def list_conversations(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        try: limit = min(1000, max(1, int(request.query_params.get("limit", "500"))))
        except ValueError as exc: raise ApiError(400, "VALIDATION_ERROR", "limit must be an integer") from exc
        return repo.list_conversations(client_id, limit)

    @app.get("/admin/clients/{client_id}/conversations/{conversation_id}")
    async def get_conversation(client_id: str, conversation_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id); _valid_uuid(conversation_id, "conversationId")
        conv = repo.conversation_for_client(client_id, conversation_id)
        if not conv: raise ApiError(404, "NOT_FOUND", "Conversation not found")
        return conv

    @app.get("/admin/clients/{client_id}/analytics")
    async def client_analytics(client_id: str, request: Request):
        admin_auth(request); _valid_uuid(client_id)
        if not repo.get_client(client_id): raise ApiError(404, "NOT_FOUND", "Client not found")
        period = request.query_params.get("period", "daily")
        if period not in {"daily", "weekly", "monthly"}: raise ApiError(400, "VALIDATION_ERROR", "period must be daily, weekly, or monthly")
        days = {"daily": 30, "weekly": 84, "monthly": 365}[period]
        return repo.analytics(client_id, days)

    provider_presets = {"nvidia": "https://integrate.api.nvidia.com/v1", "openai": "https://api.openai.com/v1", "openrouter": "https://openrouter.ai/api/v1", "groq": "https://api.groq.com/openai/v1", "together": "https://api.together.xyz/v1", "deepseek": "https://api.deepseek.com/v1"}

    @app.get("/admin/settings/provider")
    async def get_provider_settings(request: Request):
        admin_auth(request)
        saved = repo.setting("provider") or {}
        return {"running": {"provider": settings.llm_provider_name, "type": settings.llm_provider_type, "baseUrl": settings.llm_base_url, "model": settings.llm_model, "configured": bool(settings.llm_api_key) or settings.llm_provider_type == "local"}, "staged": saved, "restartRequired": bool(saved), "presets": list(provider_presets)}

    @app.put("/admin/settings/provider")
    async def stage_provider(request: Request):
        admin_auth(request); body = _validated(ProviderBody, await _json_body(request))
        saved = body.model_dump(exclude={"apiKey"}, exclude_none=True)
        repo.set_setting("provider", saved); repo.audit(None, "provider.settings.staged", {"provider": body.provider})
        return {"saved": True, "restartRequired": True, "secretPersisted": False}

    @app.post("/admin/settings/provider/test")
    async def test_provider(request: Request):
        admin_auth(request); body = _validated(ProviderBody, await _json_body(request))
        if body.provider == "local": return {"connected": True, "status": "ready", "provider": "local"}
        base_url = body.baseUrl or provider_presets.get(body.provider)
        if not base_url or not body.model or not body.apiKey: raise ApiError(400, "VALIDATION_ERROR", "Base URL, model, and API key are required")
        try: normalize_domain(base_url)
        except ValueError:
            # Provider URLs may contain API paths; validate origin syntax without normalizing paths.
            from urllib.parse import urlsplit
            parsed = urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password: raise ApiError(400, "VALIDATION_ERROR", "Invalid provider base URL")
        temp = replace(settings, llm_provider_type="openai-compatible", llm_provider_name=body.provider, llm_base_url=base_url.rstrip("/"), llm_model=body.model, llm_api_key=body.apiKey, llm_timeout_ms=5000, llm_max_retries=0)
        result = await OpenAICompatibleLLM(temp).health()
        return {"connected": result.get("connected", False), "status": result.get("status", "unknown"), "provider": body.provider, "reachable": result.get("reachable", False), "authentication": result.get("authentication", "unknown")}

    @app.post("/admin/settings/provider/env")
    async def provider_env(request: Request):
        admin_auth(request); body = _validated(ProviderBody, await _json_body(request))
        base_url = body.baseUrl or provider_presets.get(body.provider, "")
        content = "\n".join([f"LLM_PROVIDER_TYPE={'local' if body.provider == 'local' else 'openai-compatible'}", f"LLM_PROVIDER_NAME={body.provider}", f"LLM_BASE_URL={base_url}", f"LLM_MODEL={body.model or ''}", "LLM_API_KEY=REPLACE_WITH_SECRET"])
        return {"filename": ".env", "restartRequired": True, "content": content}

    @app.get("/admin/settings/system")
    async def system_settings(request: Request):
        admin_auth(request)
        return {"general": {"publicBaseUrl": settings.public_base_url, "nodeEnv": settings.node_env},
                "smtp": {"provider": settings.notification_provider, "host": settings.smtp_host, "port": settings.smtp_port, "user": "configured" if settings.smtp_user else None, "password": "••••••••" if settings.smtp_pass else None},
                "storage": {"provider": storage.name, "dataDir": str(settings.data_dir)}, "database": {"provider": repo.name},
                "api": {"corsOrigins": list(settings.allowed_origins)},
                "environment": {"runtime": "python", "pythonVersion": platform.python_version(), "nodeVersion": settings.node_version_legacy or "not used by Python backend", "platform": sys.platform, "arch": platform.machine(), "secrets": {"adminApiKey": "••••••••", "llmApiKey": "••••••••" if settings.llm_api_key else None}}}

    @app.get("/admin/health")
    async def admin_health(request: Request):
        admin_auth(request)
        return {"status": "ok", "version": __version__, "providers": await provider_health(), **metrics.snapshot()}

    # Public widget API. Public credentials and Origin are required for every call.
    @app.get("/v1/config")
    async def public_config(request: Request, client: dict[str, Any] = Depends(public_client)):
        cfg = client["config"]
        return {"clientName": client["name"], "assistantName": cfg.get("assistantName", client["name"]), "welcomeMessage": cfg.get("welcomeMessage") or cfg.get("widget", {}).get("welcomeMessage") or "How can I help you?", "widget": cfg.get("widget") or {}, "theme": cfg.get("theme") or {}}

    async def _public_chat(request: Request, client: dict[str, Any], streaming: bool = False):
        payload = _validated(ChatBody, await _json_body(request))
        try:
            return await chat.chat(client["id"], payload.message, str(payload.sessionId) if payload.sessionId else None)
        except PermissionError as exc:
            raise ApiError(403, "TENANT_DISABLED", "Tenant is disabled") from exc

    @app.post("/v1/chat")
    async def public_chat(request: Request, client: dict[str, Any] = Depends(public_client)):
        try:
            return await _public_chat(request, client)
        except (RuntimeError, ValueError, httpx.HTTPError) as exc:
            # Provider transport/status/response-shape errors and stored-index
            # incompatibilities are service failures, not client validation errors.
            raise ApiError(503, "CHAT_PROVIDER_FAILED", "Unable to complete the response") from exc

    @app.post("/v1/chat/stream")
    async def public_chat_stream(request: Request, client: dict[str, Any] = Depends(public_client)):
        payload = _validated(ChatBody, await _json_body(request))
        async def generate():
            try:
                result = await chat.chat(client["id"], payload.message, str(payload.sessionId) if payload.sessionId else None)
                # Emit only the fully validated answer, matching the original buffered-grounding behavior.
                for token in re.findall(r"\S+\s*", result["answer"]):
                    yield "event: token\ndata: " + json.dumps({"token": token}, ensure_ascii=False) + "\n\n"
                yield "event: done\ndata: " + json.dumps(result, ensure_ascii=False) + "\n\n"
            except Exception:
                yield "event: error\ndata: " + json.dumps({"message": "Unable to complete the response"}) + "\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.post("/v1/leads")
    async def public_lead(request: Request, client: dict[str, Any] = Depends(public_client)):
        body = _validated(LeadBody, await _json_body(request))
        data = body.model_dump(exclude={"conversationId"}, exclude_none=True)
        for value in data.values():
            if isinstance(value, str) and ("\r" in value or "\n" in value): raise ApiError(400, "INVALID_LEAD", "Lead fields contain invalid characters")
        conversation_id = str(body.conversationId) if body.conversationId else None
        if conversation_id and not repo.conversation_for_client(client["id"], conversation_id): raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
        destination = client["config"].get("notificationEmail") or client["config"].get("teamEmail")
        if not destination: raise ApiError(503, "LEAD_DELIVERY_UNAVAILABLE", "Lead delivery is not configured")
        lead_id = repo.save_lead(client["id"], conversation_id, data)
        try:
            await notification.notify(destination, f"New lead for {client['name']}", {"id": lead_id, "client": client["name"], "receivedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "name": data.get("name"), "email": data.get("email"), "message": data.get("message") or data.get("requirement"), "phone": data.get("phone")}, client["id"], {"replyTo": data.get("email")})
            notification_status = "queued" if settings.notification_provider in {"outbox", "supabase"} else "sent"
        except Exception as exc:
            # The lead record is already durable at this point. Returning 503 with
            # "please retry" creates duplicate leads when the user resubmits. Report
            # acceptance honestly and expose the notification failure separately.
            notification_status = "failed"
            logger.warning("lead notification failed for tenant %s (%s)", client["id"], type(exc).__name__)
            try:
                repo.audit(client["id"], "lead.notification_failed", {"leadId": lead_id, "provider": settings.notification_provider})
            except Exception as audit_exc:
                logger.warning("lead notification failure audit failed for tenant %s (%s)", client["id"], type(audit_exc).__name__)
        if notification_status != "failed":
            try:
                repo.audit(client["id"], "lead.created", {"leadId": lead_id, "notificationStatus": notification_status})
            except Exception as audit_exc:
                logger.warning("lead creation audit failed for tenant %s (%s)", client["id"], type(audit_exc).__name__)
        return {"id": lead_id, "status": "accepted", "notificationStatus": notification_status}

    # Static dashboard, demo page, and browser widget are deliberately retained.
    @app.get("/", include_in_schema=False)
    async def dashboard_home():
        return RedirectResponse(url="/admin/", status_code=307)

    if public_dir.exists():
        app.mount("/", StaticFiles(directory=str(public_dir), html=True, check_dir=True), name="static")
    return app


app = create_app()
