# AttachAI — Multi-client AI Assistant Platform

AttachAI is a local-first RAG (retrieval-augmented generation) engine with a web-based admin console for creating and managing isolated client assistants. It includes an embeddable website chat widget, per-client knowledge ingestion, conversation history, domain allowlists, widget customization, and a FastAPI backend.

## What is included

- **Admin console** at `/admin`, with overview metrics and a Clients workspace.
- **Admin authentication** using a bearer API key. For local development, the first run generates a private bootstrap key in `.rag_data/admin_bootstrap_key.txt`. Production requires `ADMIN_API_KEY` to be set explicitly.
- **Client lifecycle**: create clients, pause/activate assistants, update domains, rotate client keys, and delete a client workspace.
- **Tenant isolation**: each client has its own knowledge directory, vector store/collection, and SQLite conversations database under `<RAG_DATA_DIR>/clients/<client_id>/`.
- **Assistant settings**: display name, welcome and fallback messages, additional instructions, provider/model overrides, and allowed domains.
- **Widget settings**: primary color, light/dark theme, left/right placement, panel size, and suggested questions.
- **Knowledge lifecycle**: upload PDF, DOCX, TXT, Markdown, or CSV files (10 MB per file); index/refresh them per client; remove source files.
- **Publishing**: a per-client website `<script>` embed snippet and `/widget.js` loader. The public widget uses a client ID and origin/domain validation; the private client API key is never placed in website JavaScript.
- **Conversation management**: view recent client sessions and read a transcript.
- **Lead capture**: an optional website-widget contact form requires visitor consent; admins can review leads per client or export the platform-wide lead list as CSV.
- **Existing RAG capabilities**: multilingual query understanding, hybrid retrieval, evidence-aware answers, citations, and session-scoped conversational memory remain in place.
- **Deployment artifacts**: Dockerfile, Docker Compose, and a Render Blueprint with a persistent disk.

## Requirements

- Python 3.10 or newer (Python 3.11/3.12 recommended).
- For no-key local testing, the platform can start, accept clients, ingest documents, and exercise retrieval without an LLM credential. A configured supported LLM provider is needed for normal generated grounded answers; with `RAG_LLM_PROVIDER=none`, factual requests may safely fall back instead of receiving a generated response.
- Optional hosted LLM and Qdrant providers require their own valid configuration and credentials.

## Run locally (Windows PowerShell)

From the extracted project folder named `AttachAI`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
New-Item -ItemType Directory -Force .\knowledge | Out-Null
python -m pytest -q
uvicorn advanced_rag.web:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/admin`. The initial admin key is written to `.rag_data/admin_bootstrap_key.txt`. Open that file and paste its value into the dashboard login page. Keep the file private; do not commit it or send it to a client. If you prefer to choose your own key, set `ADMIN_API_KEY` in `.env` before the first run. Use a long, random, unique value.

### macOS / Linux

```bash
cd AttachAI
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
mkdir -p knowledge
python -m pytest -q
uvicorn advanced_rag.web:app --host 127.0.0.1 --port 8000 --reload
```

### Stop and restart

Stop the server using `Ctrl+C`. Restart with the same `uvicorn` command. The admin registry, tenant files, vectors, and conversation history persist in `.rag_data/` by default.

## Create and publish a client

1. Sign in to `/admin`.
2. Select **New Client**, enter a name, and add the client's primary website domain. Additional domains can be added as separate lines.
3. Save the generated client API key in a secure place. AttachAI shows the raw key only once when creating or rotating it. The browser widget does **not** use that secret key.
4. Open the client workspace, use **Assistant settings** to tune its welcome/fallback message, prompt instructions, model override, and domain allowlist.
5. Use **Knowledge base** to upload approved client documents, then select **Ingest / refresh knowledge**.
6. Use **Widget design** for brand color, theme, placement, dimensions, and suggested questions.
7. Open **Publish & API**, copy the embed snippet, and place it before `</body>` on the approved site. Test on a staging page first.

The standard embed looks like this, with the actual host and client ID filled in by the dashboard:

```html
<script src="https://YOUR-ATTACHAI-HOST/widget.js" data-client-id="cl_CLIENT_ID" defer></script>
```

If a website's origin is not on the client's allowlist, the widget API rejects it. During local development, the widget may be tested from localhost if no domains are configured. For production, configure the real website domain(s).

## Configure an LLM

Set one of the supported providers in `.env`. Existing AttachAI aliases are also accepted:

```dotenv
RAG_LLM_PROVIDER=openai
RAG_LLM_MODEL=your-model-name
RAG_API_BASE=https://api.example.com/v1
OPENAI_API_KEY=your-secret-key
```

Equivalent aliases are `LLM_PROVIDER_TYPE`, `LLM_PROVIDER_NAME`, `LLM_MODEL`, `LLM_API_KEY`, and `LLM_BASE_URL`. Supported provider values include `none`, `openai` (including OpenAI-compatible services), `nvidia`, and `gemini`. Keep API keys only in server environment variables; never put them into assistant instructions, embed snippets, or a public repository. A valid base URL/model/key combination depends on the provider you use. Set these values in `.env` for local use or in the hosting service environment settings for deployment.

## Render deployment

A ready-to-edit `render.yaml` is included. It configures a web service, `/health` health check, production admin-key generation, and a persistent disk mounted at `/var/data` so tenant documents and SQLite state are not lost on process restart. Render persistent disks may require a paid service plan; check the current plan and disk pricing in Render before deploying.

1. Commit the extracted `AttachAI` project to a private Git repository.
2. In Render, create a Blueprint from that repository and review the `attachai-platform` service and disk.
3. Set any optional provider values (`LLM_PROVIDER_TYPE`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`) in Render's environment settings. Leave them unset for the local/fallback provider.
4. Deploy and wait for `/health` to return HTTP 200.
5. Open `https://YOUR-SERVICE.onrender.com/admin`. The Blueprint generates `ADMIN_API_KEY` as a secret environment variable; copy its value from the service's environment settings into the dashboard login.
6. Create clients, add their real production website domains, ingest approved knowledge, and validate widget answers before publishing.

Do not set `ADMIN_API_KEY=SET`, `admin`, `password`, or another placeholder in production. Startup intentionally refuses a placeholder or missing production admin key. Do not use a free/ephemeral filesystem as the only place to store important tenant data.

If a Render Blueprint disk configuration is not suitable for your plan, create an available persistent disk and point `RAG_DATA_DIR` to a directory on that disk. The active code uses a SQLite registry and local tenant document/vector files by default, so persistence is essential.

## Docker

```bash
cp .env.example .env
# Set ADMIN_API_KEY to a strong local secret if you don't want a generated key file.
docker compose up --build
```

Then open `http://localhost:8000/admin`. The Compose file mounts `.rag_data` and `knowledge` into the container. Do not expose the service to the public internet without configuring a strong `ADMIN_API_KEY` and production environment settings.

## API routes

### Platform routes

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/admin` | Admin dashboard |
| `GET` | `/health` | Health check |
| `GET` | `/widget.js` | Website widget script |
| `GET` | `/api/admin/overview` | Platform counts (admin bearer key) |
| `GET` | `/api/admin/clients` | List clients (admin bearer key) |
| `POST` | `/api/admin/clients` | Create client and return its one-time raw key |
| `GET` / `PATCH` / `DELETE` | `/api/admin/clients/{id}` | Read, update, or delete client |
| `POST` | `/api/admin/clients/{id}/rotate-key` | Rotate client server API key |
| `GET` / `POST` | `/api/admin/clients/{id}/documents` | List or upload knowledge files |
| `DELETE` | `/api/admin/clients/{id}/documents/{name}` | Remove a file |
| `POST` | `/api/admin/clients/{id}/ingest` | Index/refresh client knowledge (`?force=true` to rebuild) |
| `GET` | `/api/admin/clients/{id}/leads` | List private leads for a client |
| `GET` | `/api/admin/leads` | List platform leads for admin reporting/export |
| `GET` | `/api/admin/clients/{id}/conversations` | List conversation sessions |
| `GET` | `/api/admin/clients/{id}/conversations/{session_id}` | Read a transcript |
| `GET` | `/api/client/config?client_id=...` | Public widget configuration; domain checked |
| `POST` | `/api/client/chat` | Public widget chat; domain checked and rate-limited |
| `POST` | `/api/client/leads` | Submit a visitor contact request after explicit consent |

Admin APIs require `Authorization: Bearer YOUR_ADMIN_API_KEY`. Server-to-server client integrations may use `X-Client-Key` with a valid client key; store that key securely. The standard website widget intentionally sends only its public client ID and relies on the HTTP origin/domain allowlist. Public chat is rate-limited per client/IP in each running process; for multi-instance high-traffic production use, replace the in-process limiter with a shared rate-limit store and add edge/WAF protection.

### Legacy single-tenant RAG routes

The original `/chat`, `/query`, `/sessions`, `/ingest`, and retrieval diagnostics remain for backwards compatibility. They operate on the base RAG configured by `RAG_KNOWLEDGE_DIR` and `RAG_DATA_DIR`, not on a client tenant. In production mode (`ENVIRONMENT=production`, `NODE_ENV=production`, or Render), those legacy endpoints require admin bearer authentication by default. For normal platform usage, use the client-specific endpoints.

## Environment variables

See `.env.example`. Key settings:

| Variable | Purpose |
|---|---|
| `ADMIN_API_KEY` | Admin login / API bearer key; mandatory in production |
| `RAG_DATA_DIR` | Admin SQLite database and all client tenant data |
| `RAG_KNOWLEDGE_DIR` | Legacy single-tenant knowledge directory |
| `RAG_LLM_PROVIDER` / `LLM_PROVIDER_TYPE` | Global model provider |
| `RAG_LLM_MODEL` / `LLM_MODEL` | Global model name |
| `OPENAI_API_KEY` / `LLM_API_KEY` | Provider credential (depending on provider) |
| `RAG_API_BASE` / `LLM_BASE_URL` | OpenAI-compatible base URL |
| `LLM_TIMEOUT_MS` | Global LLM request timeout in milliseconds (default 30000) |
| `LLM_MAX_RETRIES` | OpenAI-compatible request retries (default 2; capped at 8) |
| `QDRANT_URL` | Optional remote Qdrant URL; local storage remains available as fallback |
| `PORT` | Hosting port; the web server uses the platform-provided port |
| `ATTACHAI_SECURE_LEGACY_API` | Explicit switch for legacy-route authentication in development |

Some variables from broader Node/Supabase deployments (`NODE_VERSION`, `DATABASE_PROVIDER`, `STORAGE_PROVIDER`, `SUPABASE_*`, `TTS_API_KEY`, notification settings, and related values) are retained as documented compatibility placeholders in `.env.example`; the current Python platform does **not** automatically connect to Supabase Postgres/Storage/pgvector or provide text-to-speech/notification features. The implemented default persistence is SQLite plus local tenant files/vectors (and the optional Qdrant adapter). Do not assume Supabase values are active until an adapter is configured.

## Security and operational notes

- The raw admin key and raw client keys are not stored in the tenant registry; client keys are stored as SHA-256 hashes. Keys are high entropy and intended to be unguessable. A raw client key is displayed only at creation/rotation.
- Widget domain checks are useful access control, but browser origins are not a substitute for authentication on private server APIs. Never rely on domain checks to protect an API secret embedded in JavaScript.
- The dashboard is served by the same backend to avoid requiring a separate frontend build. All admin data requests still require a valid bearer key.
- Uploaded documents are parsed by the existing document loaders. Treat files as untrusted, review them before indexing, and only upload material you are allowed to process.
- Use HTTPS on public deployments, rotate any credentials that were exposed, and limit access to service logs/backups.
- Client deletion removes that tenant's local workspace as well as its registry row. Back up tenant data before deleting a production client.
- `RAG_DATA_DIR` must be on persistent storage for Render/containers; otherwise, tenant registry and conversation history may be lost across infrastructure changes.

## Tests and verification

Run:

```bash
python -m pytest -q
python -m compileall -q advanced_rag main.py web.py
```

Tests cover the original RAG and memory flows, plus admin authentication, client creation, key rotation, domain enforcement, tenant knowledge separation, document upload, ingestion, widget endpoints, and API contract basics.
