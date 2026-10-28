# AttachAI 1.2.0 — Implementation Notes

## Platform overview

The project has been extended from a single-tenant local RAG engine into AttachAI, a multi-client assistant platform. The original ingestion, retrieval, evidence evaluation, grounded answer generation, query understanding, and session memory remain available. A FastAPI admin platform is added on top.

## Added platform modules

- `advanced_rag/platform.py`: SQLite tenant registry, admin-key initialization, hashed client API key storage and rotation, client settings and domain allowlists, per-client directories, per-client RAG service instances, request rate limiting, lead storage, and conversation/document counts.
- `advanced_rag/api.py`: authenticated `/api/admin/*` routes; client-specific document upload/ingestion and conversation/lead endpoints; domain-checked public widget config/chat/lead routes; legacy RAG endpoints remain for compatibility and are protected by default in production.
- `advanced_rag/web.py` and root `web.py`: ASGI entrypoints for local/dev and hosting startup.
- `advanced_rag/static/dashboard.html`: responsive admin console with Overview, Clients, per-client assistant settings, widget design, Knowledge base, Conversations, Leads, and Publish & API panels.
- `advanced_rag/static/widget.js`: embeddable, shadow-DOM website widget with tenant-specific settings, domain-aware loading, chat, suggested questions, and an optional visitor follow-up form with contact consent.
- `render.yaml`: Render Blueprint with a persistent disk, generated production admin key, health check, and web startup command.

## Tenant isolation model

Each client has a unique ID (`cl_...`) and a directory under `RAG_DATA_DIR/clients/<client_id>/`. The `knowledge/` folder, local vector store/Qdrant collection and chat-memory SQLite database are separate per client. The admin registry stores only a SHA-256 digest and short prefix for client API keys; the raw client key is returned at creation/rotation only. The embeddable widget sends a public client ID, not a private key, and the server checks the HTTP origin against that client's allowed domains. A valid private client key may alternatively authenticate trusted server-to-server requests.

The default admin key is read from `ADMIN_API_KEY`. In local development only, if it is missing, AttachAI creates `.rag_data/admin_bootstrap_key.txt` with restrictive Unix file permissions where available. Production startup rejects missing or known placeholder admin keys. Admin endpoints require a bearer key. Public chat and lead submission use a per-process client/IP rate limiter; high-scale multi-instance deployments should replace it with a shared limiter.

## Storage/provider boundaries

Current default data persistence is SQLite plus local files/vectors, with the existing optional Qdrant adapter. Render requires a persistent disk at `RAG_DATA_DIR` or client registry, documents, vectors, and chat memory can be lost when an ephemeral filesystem is replaced. Supabase `URL`/service-role/storage variables and the broader Node/storage/TTS/notification variables are listed in `.env.example` as compatibility placeholders, but there are no Supabase database/storage/pgvector or text-to-speech/notification adapters in this version. Do not treat these values as active providers.

Global model settings accept both RAG variables and the aliases used by AttachAI deployments: `LLM_PROVIDER_TYPE`, `LLM_PROVIDER_NAME`, `LLM_MODEL`, `LLM_API_KEY`, and `LLM_BASE_URL`. Provider-agnostic `LLM_API_KEY` maps to the selected Gemini/NVIDIA/OpenAI-compatible provider. `LLM_TIMEOUT_MS` controls provider request timeout; `LLM_MAX_RETRIES` configures OpenAI-compatible retry behavior.

## Verification performed during build

- Existing RAG/memory regression suite plus added platform tests: **29 passed**.
- `python -m compileall -q advanced_rag main.py web.py`: passed.
- Inline dashboard JavaScript and website widget JavaScript parse checks with Node: passed.
- Domain normalization and provider alias checks: passed.
- FastAPI TestClient exercised admin authentication, create/update/delete, client key rotation, allowed-domain enforcement, upload and indexing, per-client corpus/memory separation, widget chat, lead consent/storage/listing, health/dashboard/static widget endpoints, and production legacy-route authentication.
- A local Uvicorn HTTP smoke test passed `/health`, dashboard and widget asset delivery, unauthenticated admin rejection, authenticated client creation, multipart knowledge upload + indexing, allowed-origin widget config/chat, conversation persistence, and rejection of an unapproved origin.
- The headless Chromium environment blocked navigation to loopback URLs with `ERR_BLOCKED_BY_ADMINISTRATOR`, so a full interactive browser session was not reported as passing. The front-end was syntax-checked, but client-side visual behavior should still be checked once deployed or in a browser environment that permits localhost navigation.
- No live Render deployment or real hosted-model network call was made from this environment.
