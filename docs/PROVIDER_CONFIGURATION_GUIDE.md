# Provider configuration

See `.env.example` and `ENVIRONMENT_MATRIX.md` for the complete list and compatibility mapping. The defaults are intentionally local and do not require network credentials.

## Supported combinations

| Purpose | Environment variables | Notes |
|---|---|---|
| Metadata | `DATABASE_PROVIDER=sqlite` or `supabase`; optional legacy `REPOSITORY_PROVIDER` alias | `REPOSITORY_PROVIDER`, when non-empty, wins. Supabase requires the migration and service access. |
| Files | `STORAGE_PROVIDER=local` or `supabase`; `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET` | Supabase objects are under a safe tenant ID prefix and the bucket should remain private. |
| Embeddings | `EMBEDDING_PROVIDER=local` or `openai`; `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL` | Local produces 128 dimensions. External model calls weren't verified without credentials. |
| Vectors | `VECTOR_PROVIDER=local`, `qdrant`, or `supabase`; `QDRANT_URL`, `QDRANT_API_KEY`, `SUPABASE_VECTOR_DIMENSIONS` | A vector index's dimension is a schema contract. Reindex on a backup/new index rather than modifying a live collection in place. The included Supabase migration is vector(128). |
| Chat completion | `LLM_PROVIDER_TYPE=local` or `openai-compatible`; `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, optional `LLM_API_KEY_ENV` | External mode requires a base URL, model and referenced secret name. `LLM_TIMEOUT_MS`, `LLM_MAX_RETRIES` and `LLM_RETRY_BASE_MS` bound provider calls. |
| Notifications | `NOTIFICATION_PROVIDER=outbox`, `smtp` or `supabase` | SMTP connection/delivery and Supabase outbox writes require live credentials and must be tested in the deployment environment. |

## OpenAI-compatible LLM

Example configuration (replace URL/model/secret according to the selected vendor):

```dotenv
LLM_PROVIDER_TYPE=openai-compatible
LLM_PROVIDER_NAME=custom
LLM_BASE_URL=https://api.example.invalid/v1
LLM_MODEL=your-model-name
LLM_API_KEY_ENV=LLM_API_KEY
LLM_API_KEY=replace-with-secret
LLM_CHAT_PATH=/chat/completions
LLM_HEALTH_PATH=/models
LLM_TIMEOUT_MS=15000
LLM_MAX_RETRIES=2
LLM_RETRY_BASE_MS=250
LLM_TEMPERATURE=0
LLM_HEADERS={}
LLM_QUERY_PARAMS={}
```

The base URL cannot contain credentials, query string or fragment. `LLM_HEADERS` supports only non-secret extra headers and rejects auth/transport headers and header names that appear secret-bearing. Authentication is generated from the single configured key variable. Query parameters also reject secret-like names. Azure-style endpoints can set a custom chat path, health path, auth header name/scheme, and non-secret API-version query parameter.

## Provider test interpretation

`/health` and `/ready` exercise adapter health checks. A provider marked `connected` by a configuration-only check does not prove full business operations; for example, SMTP health verifies required settings rather than sending a real message. Use a controlled test tenant to verify actual document upload/retrieval, LLM generation, notification delivery and the configured database/storage provider before production. External providers were not reachable/credentialed during this project verification.
