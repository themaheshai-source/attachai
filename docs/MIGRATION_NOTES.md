# Migration notes: Node.js/TypeScript backend → Python/FastAPI

## Scope completed in this source tree

The prior Fastify backend was replaced with a FastAPI application under `orbit_ai/`. The React/Vite dashboard source and existing static dashboard/widget assets were retained. The Python app does not proxy to or launch a Node server.

| Original concern | Python replacement | Compatibility / limitation |
|---|---|---|
| Fastify server/routes/middleware | `orbit_ai/app.py` | Preserves core `/admin/*`, `/v1/*`, `/health`, `/ready`, and `/metrics` contracts. Public chat streaming returns SSE token + done events after grounding validation. |
| Zod request schemas | Pydantic v2 models in `orbit_ai/models.py` | Unknown request fields are rejected. Request validation errors use JSON error envelopes. |
| Env parser (`DATABASE_PROVIDER`, `REPOSITORY_PROVIDER`, `CORS_ORIGINS`, `OPENAI_*`, LLM variables) | `orbit_ai/config.py` | `REPOSITORY_PROVIDER` takes precedence. A non-empty `ALLOWED_ORIGINS` is canonical; blank `ALLOWED_ORIGINS` falls back to `CORS_ORIGINS`. Legacy `NODE_VERSION`, temp debug names and `TTS_API_KEY` remain but do not select Python runtime or create unsupported features. |
| Local SQLite metadata | `SQLiteRepository` in `orbit_ai/db.py` | Uses the original data-dir `metadata.sqlite` path and creates missing compatibility columns. Data is not deleted or reset. |
| Supabase metadata | PostgREST `SupabaseRepository` | Requires schema deployment; real project not available for verification. |
| Local / Supabase storage | `LocalStorage`, `SupabaseStorage` | Tenant-prefixed private paths; local files are written atomically with restrictive permissions. Supabase credentials/project not verified. |
| Local / Qdrant / Supabase vectors | `LocalVector`, `QdrantVector`, `SupabaseVector` | Explicit tenant filtering; dimension changes are rejected before replacement/deletion. Supabase migration is fixed at 128 dimensions. |
| Embedding provider | `LocalEmbedding`, `OpenAIEmbedding` | Local deterministic 128-dimensional embedding is default. External embedding calls not verified. |
| LLM provider | `LocalLLM`, `OpenAICompatibleLLM` | External requests have bounded timeout/retry handling; response shape/empty output is validated. External provider not verified. |
| Original advanced RAG / grounding services | `orbit_ai/rag.py`, `orbit_ai/chat.py` plus the reference query-understanding service | Hybrid exact/keyword/BM25 retrieval, rank fusion, reranking, bounded context, evidence decisions, multilingual follow-up variants and grounding correction are in the real chat path. Formal claim-level entailment is not implemented; the conservative deterministic checks are not proof of every answer claim. |
| Session/conversation repository | persistent conversation/message operations | SQLite persistence across app recreation is tested; tenant filter on every history lookup. Supabase behavior not remotely verified. |
| TypeScript backup/restore scripts | `scripts/backup.py`, `scripts/restore.py` | Local backup handles SQLite with SQLite's backup API; restore checks ZIP paths, symlinks and SQLite integrity and preserves pre-restore copies when overwriting. Stop the service before restore. |
| Node backend runtime Dockerfile | Python 3.12 image, Uvicorn | The backend runtime no longer requires Node. Node remains a dashboard build-time dependency only. Docker image itself was not built in this environment. |

## Data compatibility and cutover

1. Back up the existing `DATA_DIR`, including `metadata.sqlite`, `vectors.json`, `objects/`, and `outbox/` (or the corresponding external provider data). Use the existing source system's supported backup process as well when external databases are involved.
2. Point `DATA_DIR` at the prior data directory only after testing against a copy. The Python repository intentionally preserves the original SQLite database path and schema names, adds absent legacy columns safely, and does not create a blank replacement DB over an existing one.
3. Keep the same embedding model/provider/dimension while reusing existing vectors. The local deterministic provider is designed as a local fallback, not a semantic match to an arbitrary external embedding model. If a provider/model changes, reindex from the original knowledge files into a new compatible index first.
4. If using Supabase, review and apply `supabase/migrations/0001_initial.sql`, `0002_restrict_audit_logs.sql`, and `0003_atomic_domain_replacement.sql` in order against a backed-up non-production project. Migration 0003 introduces an atomic `replace_client_domains` RPC. The included vector schema is 128 dimensions; modify the table type and RPC signature together for another dimension and verify before cutover.
5. Deploy the Python backend and test all widget/admin flows against the new API origin. Keep the old deployment available for rollback until local, data, external provider, and browser end-to-end acceptance are complete.
6. For rollback, stop the new app, restore data and the compatible vector index/database snapshot, restore the previous environment/deployment, and smoke-test the previous backend. Do not run production schema migrations or destructive vector reindexing without a separately approved production change.

## Known behavior decisions

- Conversation list/detail endpoints were added in Python because the dashboard calls them and the repository supports tenant-scoped conversation retrieval.
- The Python streaming route emits the buffered final answer after grounding checks, matching the original buffering behavior rather than exposing tokens before validation.
- The `ORBIT_TEMP_DEBUG_*` variables and `TTS_API_KEY` are intentionally retained but unused because no corresponding active implementation was found in the inspected original code. They were not repurposed.
- `SUPABASE_OUTBOX_TABLE` remains configurable and is validated as a SQL identifier. The local file outbox queues notifications but does not send them; a delivery consumer is needed unless SMTP is selected.
- Process-local rate limiting is compatible with a single instance but does not coordinate across replicas; place a trusted proxy/API gateway limit in front of multi-replica deployments.
