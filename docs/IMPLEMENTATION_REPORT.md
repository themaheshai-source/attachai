# Orbit AI — implementation report

> **Independent audit update:** The earlier implementation summary is supplemented and corrected by [`AUDIT_REPORT.md`](AUDIT_REPORT.md) and [`AUDIT_VERIFICATION_LEDGER.md`](AUDIT_VERIFICATION_LEDGER.md). Those files list defects found in the actual delivered ZIP, fixes and regression tests, package hygiene corrections, and the current blocked checks. Their evidence and current test counts supersede any earlier completion wording.

## Executive result

Orbit AI's application backend has been migrated to a Python/FastAPI service in `orbit_ai/`. It does not proxy requests to, launch, or depend on the legacy Node backend. The React/Vite dashboard source, existing compiled admin assets, and browser widget were preserved. The relevant query-understanding component from Advanced RAG is integrated in Orbit's real chat and retrieval path; the reference project is not started as a second server.

**Result status:** locally verified for the implemented Python flows; external production acceptance remains conditional. See `VERIFICATION_REPORT.md` for exact commands, observations, and blocked items.

## Original architecture and source audit

`orbit-ai-main.zip` contains a Fastify/TypeScript API, React/Vite administration dashboard, public widget, tenant-aware chat, document ingestion, local metadata/vector support, optional Qdrant and Supabase adapters, LLM/embedding configuration, notifications, and TypeScript tests. The original app already had retrieval and grounding components; the migration carries the relevant behavior to Python rather than copying a second, disconnected RAG app.

`advanced_rag-upgraded(1).zip` contains a Python RAG package with query understanding, language-aware handling, retrieval/ranking, ingestion/context/answering and tests. Its untouched test suite passed 24 tests. The reusable `QueryUnderstandingService` was integrated in offline, no-remote-call mode for contextual query resolution and variants, while Orbit's own adapters, tenant contract and data layout remain authoritative.

The pre-edit inventories record 93 Orbit files and 44 Advanced RAG files. Both archives were inspected before modifying production code and were left unchanged.

## Source change inventory

- **Added:** the Python package under `orbit_ai/` (FastAPI routes, configuration, security, repositories, provider adapters, ingestion, hybrid retrieval, chat orchestration and integrated query understanding); `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`; Python tests under `tests/`; safe local backup/restore tools under `scripts/`; and the architecture, environment, migration, implementation and verification documents under `docs/`.
- **Replaced or rewritten:** root `README.md`, `.env.example`, `.gitignore`, `Dockerfile`, `docker-compose.yml`, packaging/runtime configuration and the migration-related documentation to describe the Python runtime accurately.
- **Preserved:** `dashboard/` React/Vite source and package lock, `public/admin/` prebuilt dashboard assets, `public/widget.js`, `public/demo.html`, and the Supabase migration/schema source. These web assets remain compatible static resources and do not execute application backend logic in Node.
- **Removed from the release:** the active root TypeScript/Fastify backend (`src/`), root Node package manifest/lock and TypeScript compiler configuration, legacy root TypeScript tests and backup entry points, and obsolete generated/audit/report artifacts that described the previous runtime. The separate `dashboard/package.json` and `dashboard/package-lock.json` remain for intentionally rebuilding the frontend. This removal was made only after inspecting route usage, dashboard API calls and deployment references; the original uploaded ZIP remains untouched and is the rollback reference.

## Final architecture and request path

1. FastAPI middleware handles request sizes, CORS, security headers, and process-local rate limits.
2. Admin requests authenticate with the admin key. Public requests authenticate the tenant API key, tenant enabled state and configured `Origin`.
3. The application resolves the authorized tenant and persisted conversation history for the supplied session identifier.
4. Greetings/general conversation can bypass retrieval. Factual questions use tenant-filtered dense vector search plus exact, keyword and BM25 retrieval, reciprocal-rank fusion, deduplication, deterministic reranking and bounded evidence selection.
5. Short/follow-up/weakly supported questions use the integrated Advanced RAG-derived query-understanding component and multi-query retrieval where it improves evidence.
6. The LLM receives bounded, source-labelled tenant evidence as untrusted data. Local extractive mode supports offline operation; OpenAI-compatible chat and embedding adapters are configurable.
7. The answer is checked for numeric support, explicit negatives and qualification loss. Unsupported output gets one corrective attempt, then the tenant fallback message if it remains ungrounded. Conflicting amounts for a named topic and period are marked uncertain.
8. User/assistant messages and usage are persisted. Chat returns real retrieved chunk/source IDs; SSE is buffered until the final answer has passed grounding checks.

Detailed diagrams and API coverage are in `ARCHITECTURE.md`.

## Implementation map

| Path | Implementation |
|---|---|
| `orbit_ai/app.py` | FastAPI startup/shutdown, middleware, authentication dependencies, `/admin/*` and `/v1/*` compatibility routes, health/metrics and static assets |
| `orbit_ai/config.py` | Environment parsing, type/URL/identifier validation, provider settings, compatibility aliases |
| `orbit_ai/security.py` | Admin/API-key handling, constant-time verification, Origin/domain checks and path/name normalization |
| `orbit_ai/db.py` | SQLite repositories with compatibility-safe schema additions, persisted conversations/messages, tenant-safe lookups, Supabase PostgREST adapter |
| `orbit_ai/providers.py` | Deterministic local / OpenAI-compatible embeddings, local / Qdrant / Supabase vectors, local / Supabase storage, local / external chat LLMs, outbox / SMTP / Supabase notifications |
| `orbit_ai/knowledge.py` | TXT, Markdown, PDF, DOCX and CSV parsing, chunking, metadata, upload/list/delete/rebuild service |
| `orbit_ai/rag.py` | Exact/keyword/BM25 retrieval, RRF, deduplication, reranking, context selection, evidence decisions and grounding checks |
| `orbit_ai/chat.py` | Tenant-scoped orchestration, persisted sessions, query understanding, multi-query retrieval, fallback and corrective grounding |
| `orbit_ai/integrations/query_understanding.py` | Selected query-understanding source from Advanced RAG, connected to chat's follow-up path |
| `orbit_ai/models.py` | Typed/validated API request/response contracts |
| `supabase/migrations/0001_initial.sql` | Supabase tables, policies, private storage bucket, vector match function; 128-dimensional index contract |
| `scripts/backup.py`, `scripts/restore.py` | Local backup/restore helpers with safe archive checks and SQLite integrity validation |
| `dashboard/`, `public/` | Retained dashboard source, prebuilt dashboard assets and browser widget |
| `tests/` | Python unit and API integration regression tests |
| `docs/` | Inventories, architecture, environment matrix, migration notes, test report and verification ledger |

## Migration coverage and compatibility

The backend runtime is Python 3.11+ and uses FastAPI/Uvicorn. The Dockerfile targets Python 3.12. Core admin and public endpoint prefixes (`/admin/*`, `/v1/*`), public chat configuration, chat response fields, tenant API key and Origin checks, conversation IDs, lead flow, static dashboard and widget serving are retained to the extent defined by the inspected original routes. Conversation list/detail routes are also present because the dashboard invokes them.

The frontend is not rewritten in Python. Node.js remains a dashboard build-time requirement only; it is not needed to run the Python API. The existing prebuilt dashboard bundle and widget were verified through local HTTP requests, but a dashboard rebuild was blocked by the offline npm cache.

The SQLite repository keeps the existing `DATA_DIR/metadata.sqlite` layout and updates missing compatibility columns without resetting the database. The default embedding/vector schema is 128 dimensions. Reusing an existing vector index requires the same embedding provider/model/dimension; otherwise reindex from retained original knowledge after backup. Supabase migration execution was not performed against any live project.

## Environment-variable compatibility

The final `.env.example` preserves every name from the engineering contract, including `NODE_ENV`, `NODE_VERSION`, `TTS_API_KEY`, `ORBIT_TEMP_DEBUG_CLIENT_ID`, the original misspelling `ORBIT_TEMP_DEBUG_GOUSTO`, `ORBIT_TEMP_DEBUG_LLM_INPUT`, and `ORBIT_TEMP_DEBUG_PUREGYM`. They are not repurposed to imply uninspected behavior. The `ALLOWED_ORIGINS`/`CORS_ORIGINS` and `REPOSITORY_PROVIDER`/`DATABASE_PROVIDER` compatibility rules are documented and tested. See `ENVIRONMENT_MATRIX.md` for each variable's runtime status.

No production credentials are supplied in the archive. A strong `ADMIN_API_KEY` must be configured for production. The included Supabase SQL is 128-dimensional; merely changing `SUPABASE_VECTOR_DIMENSIONS` is not a schema migration.

## Verification and remaining constraints

The final local test suite covered tenant auth/Origin validation, upload-to-retrieval source attribution, cross-tenant isolation, conversations across application recreation, SSE, widget/static delivery, input validation, numeric grounding, conflicting prices and a Hinglish monthly-price follow-up. A separately started Uvicorn process returned successful health/readiness and served the dashboard and widget. Local backup/restore preserved the sample SQLite, vector, object and outbox files.

Not verified against live services: Supabase database/storage/vector/outbox, Qdrant, external embeddings/LLM, SMTP and production schema migration. Docker is not installed. The original TS test suite and dashboard build were blocked by the npm offline cache missing `zod@3.25.76`. A shared-environment `pip check` issue was observed for `moviepy` and Pillow; neither is an Orbit runtime dependency in `requirements.txt`.

The deterministic local embedding/answer providers are for local/offline behavior and are not equivalent to a hosted semantic model. Grounding checks are conservative heuristics and do not constitute formal claim-by-claim entailment proof. A production-ready declaration requires the blocked staging checks to pass. See `VERIFICATION_REPORT.md` for exact `PASS`, `FAIL`, `BLOCKED`, and `NOT RUN` statuses.

## Installation and run

```bash
python -m venv .venv
. .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and set a strong, unique ADMIN_API_KEY.
uvicorn orbit_ai.app:app --host 0.0.0.0 --port 3000
```

Open `http://localhost:3000/admin/`. Run local tests using `python -m compileall -q orbit_ai tests scripts` and `pytest -q`. See `DEPLOYMENT_GUIDE.md`, `PROVIDER_CONFIGURATION_GUIDE.md`, and `MIGRATION_NOTES.md` before a production cutover.
