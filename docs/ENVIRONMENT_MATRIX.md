# Environment variable compatibility matrix

All contract-required names are retained in `.env.example`. “Unused/legacy-compatible” means the name is preserved to avoid silently breaking deployment templates, not that a runtime effect is claimed.

| Variable | Original purpose / compatibility | Python mapping and current status |
|---|---|---|
| `ADMIN_API_KEY` | Admin API authentication | Used by constant-time `X-Admin-API-Key` checks. Production rejects the local default and keys shorter than 24 characters. **Required in production.** |
| `ALLOWED_ORIGINS` | Supplied contract's allowlist name | Used for admin CORS; comma-separated exact origins. If blank, `CORS_ORIGINS` is used as an alias. |
| `DATABASE_PROVIDER` | Metadata repository selection | Used; supports `sqlite` and `supabase`. Default `sqlite`. |
| `LLM_API_KEY` | LLM secret | Used for `LLM_API_KEY_ENV=LLM_API_KEY`. Secret value is not logged. |
| `LLM_BASE_URL` | LLM endpoint | Used for OpenAI-compatible provider; URL is validated and credentials/query/fragment disallowed. Falls back to `OPENAI_BASE_URL` only for the legacy provider configuration path. |
| `LLM_MAX_RETRIES` | LLM transient retry count | Used by OpenAI-compatible adapter; default 2. |
| `LLM_MODEL` | LLM model/deployment name | Used for non-local providers; required with base URL and API key when external LLM selected. |
| `LLM_PROVIDER_NAME` | Human-facing/provider label | Used in adapter health/status. |
| `LLM_PROVIDER_TYPE` | Selects local or OpenAI-compatible LLM | Used; `local`, `openai-compatible`, and legacy `openai` alias. |
| `LLM_TIMEOUT_MS` | Provider timeout | Used for LLM calls and embedding requests. Minimum 100 ms. |
| `NODE_ENV` | Original runtime mode | Retained for compatibility; controls production security settings and docs visibility. It does not run Node. |
| `NODE_VERSION` | Legacy runtime metadata | Retained and displayed as legacy metadata only; **not** a Python version selector. |
| `NOTIFICATION_PROVIDER` | Notification adapter | Used; `outbox`, `smtp`, `supabase`. Default local outbox. |
| `ORBIT_RAG_DIAGNOSTICS` | Opt-in RAG diagnostics | Used as a Boolean gate for bounded/reduced query diagnostics. Default off. |
| `ORBIT_TEMP_DEBUG_CLIENT_ID` | Contract-required legacy debug name | Retained and parsed but not used for behavior; no special-tenant debug path was found in inspected original TS source. |
| `ORBIT_TEMP_DEBUG_GOUSTO` | Contract-required legacy debug name (spelling preserved) | Retained and parsed but unused; no special-tenant debug path was found in inspected original TS source. |
| `ORBIT_TEMP_DEBUG_LLM_INPUT` | Contract-required legacy debug name | Retained and parsed but unused; not wired to request/LLM logging. |
| `ORBIT_TEMP_DEBUG_PUREGYM` | Contract-required legacy debug name | Retained and parsed but unused; no special-tenant debug path was found in inspected original TS source. |
| `PORT` | HTTP port | Used by Uvicorn/container runtime and validated to 1–65535. Default 3000. |
| `STORAGE_PROVIDER` | Knowledge storage adapter | Used; `local` or `supabase`. |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase backend key | Used for selected Supabase providers; secret is not logged. Prefer a protected service-role key for backend operations. |
| `SUPABASE_STORAGE_BUCKET` | Private Supabase Storage bucket | Used; defaults to `knowledge`. The checked-in migration creates a private `knowledge` bucket. |
| `SUPABASE_URL` | Supabase project URL | Used by repository, storage, vector and notification adapters. Required when a Supabase adapter is selected. |
| `SUPABASE_VECTOR_DIMENSIONS` | Vector schema dimension | Used as a runtime dimension guard. The included SQL schema/RPC is fixed at 128 dimensions; changing this variable alone does not migrate the database. |
| `TTS_API_KEY` | Contract-required integration name | Retained and parsed but unused: inspected Orbit source did not contain an active TTS feature path to migrate. |
| `VECTOR_PROVIDER` | Vector retrieval adapter | Used; `local`, `qdrant`, or `supabase`. Default local. |

## Original/operational variables retained in addition to contract list

| Variable | Mapping / status |
|---|---|
| `HOST` | Uvicorn bind host; default `0.0.0.0`. |
| `DATA_DIR` | Root for SQLite DB, local vectors, uploaded objects, and local notification outbox. |
| `PUBLIC_BASE_URL` | Used to generate widget embed URLs; default localhost URL. |
| `CORS_ORIGINS` | Compatibility alias for `ALLOWED_ORIGINS`, used when `ALLOWED_ORIGINS` is blank. |
| `REPOSITORY_PROVIDER` | Original alias; if non-empty, takes precedence over `DATABASE_PROVIDER`. |
| `EMBEDDING_PROVIDER` | Used; `local` or `openai`. |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS` | Used by the OpenAI-compatible embedding adapter. Dimensions default to 1536 for non-Supabase storage, or the configured Supabase vector dimension when Supabase vectors are selected; dimensions are passed to `text-embedding-3-*` models and validated against Supabase schema. Legacy aliases `EMBEDDING_API_KEY` and `EMBEDDING_MODEL` remain supported where applicable. |
| `QDRANT_URL`, `QDRANT_API_KEY` | Used by Qdrant adapter; external reachability not verified. |
| `SUPABASE_ANON_KEY` | Retained because it appears in legacy environment templates. | Parsed for compatibility but **not used by any server adapter**. Server-side Supabase providers require `SUPABASE_SERVICE_ROLE_KEY`; no anon-key fallback is implemented. |
| `SUPABASE_OUTBOX_TABLE` | Original configurable notification table; used and SQL identifier validated. Defaults to `notifications`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Used by SMTP notification adapter; actual SMTP delivery not verified. |
| `LLM_API_KEY_ENV`, `LLM_RETRY_BASE_MS`, `LLM_TEMPERATURE`, `LLM_TOP_P`, `LLM_MAX_TOKENS`, `LLM_CHAT_PATH`, `LLM_HEALTH_PATH`, `LLM_AUTH_HEADER_NAME`, `LLM_AUTH_SCHEME`, `LLM_HEADERS`, `LLM_QUERY_PARAMS` | Used by the OpenAI-compatible LLM adapter for custom secret-name selection, bounded retries, model sampling, paths, authentication and non-secret headers/query parameters. Header/query secret injection is rejected. |
| `LLM_STREAM` | Preserved legacy/configuration name. | Parsed but **not consumed by the LLM adapter**. The public SSE endpoint emits events for a fully generated and grounding-checked answer; it does not stream provider tokens live. |

## Migration notes

- The initial config template lists every environment name in the engineering contract and adds variables needed to preserve original adapters.
- No secret values are provided. Do not commit `.env` files.
- Supabase vector storage needs matching schema + RPC dimensions. The included migration is `vector(128)` and should be reviewed against an existing project before applying.
- The four `ORBIT_TEMP_DEBUG_*` variables, `TTS_API_KEY`, `SUPABASE_ANON_KEY`, and `LLM_STREAM` are deliberately retained, but currently have no active effect rather than being repurposed without evidence. `LLM_STREAM` does not control live token generation in this release.
