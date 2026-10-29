# Orbit AI — Python backend release

Orbit AI is a multi-tenant AI assistant service with an administration dashboard, browser widget, tenant-specific knowledge, conversation history, leads, and provider adapters. This release moves the application backend to **Python/FastAPI** and integrates hybrid RAG directly into the request path. The prebuilt React/Vite dashboard and browser widget remain as web assets; Node.js is not required to run the backend.

## What is included

- `orbit_ai/`: FastAPI routes, tenant/key checks, SQLite or Supabase metadata repository, local/Qdrant/Supabase vector adapters, local/Supabase storage, embedding and LLM provider adapters, notification adapters, knowledge ingestion, hybrid retrieval, grounding checks, and persistent conversations.
- `public/`: retained prebuilt admin dashboard, demo page, and embeddable `widget.js`.
- `dashboard/`: React/Vite dashboard source and its frontend lockfile/tooling for future rebuilds.
- `supabase/migrations/0001_initial.sql` through `0003_atomic_domain_replacement.sql`: Supabase schema, private storage bucket, vector matching RPC, tenant RLS policies, and atomic domain-allowlist replacement RPC.
- `tests/`: Python unit and API/integration regression suite.
- `scripts/backup.py` and `scripts/restore.py`: local data backup and restore helpers.
- `docs/`: architecture, original inventories, variable mapping, migration notes, and verification ledger/report.

## Local setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and replace `ADMIN_API_KEY` with a new random secret (at least 24 characters for production). The default `LLM_PROVIDER_TYPE=local`, `EMBEDDING_PROVIDER=local`, `DATABASE_PROVIDER=sqlite`, `STORAGE_PROVIDER=local`, and `VECTOR_PROVIDER=local` configuration runs without external credentials.

```bash
uvicorn orbit_ai.app:app --host 0.0.0.0 --port 3000
```

Open `http://localhost:3000/admin/`. Health endpoints are `GET /health`, `GET /ready`, and `GET /metrics`. OpenAPI docs are available at `/docs` outside production mode.

## Running tests

```bash
python -m compileall -q orbit_ai tests
python -m pytest -q
```

The local tests use temporary SQLite databases, deterministic local embeddings, a local vector file, and a local/extractive answer provider. They do not prove that an externally configured OpenAI-compatible LLM, Supabase, Qdrant, or SMTP server is reachable; see `docs/VERIFICATION_REPORT.md`.

## Environment configuration

The provided `.env.example` preserves all contract-required environment names. `REPOSITORY_PROVIDER` takes precedence over `DATABASE_PROVIDER`; `ALLOWED_ORIGINS` takes precedence when non-empty, with `CORS_ORIGINS` as a compatibility alias. `NODE_ENV` remains as a compatibility-mode selector, while `NODE_VERSION` is retained but does not select or configure Python. See `docs/ENVIRONMENT_MATRIX.md` for the status of each variable, including retained-but-unused names.

Do not paste real secrets into reports or commit `.env`. The default admin key is for local development only; production startup rejects it.

## Providers and indexing

- **Metadata**: `sqlite` is the default and persists to `${DATA_DIR}/metadata.sqlite`. `supabase` uses PostgREST and requires the checked-in migration to have been applied.
- **Storage**: `local` stores files below `${DATA_DIR}/objects/<tenant-id>/`; `supabase` stores tenant-prefixed objects in the configured private bucket.
- **Embeddings**: `local` produces deterministic 128-dimensional embeddings. `openai` uses the OpenAI-compatible embeddings endpoint configured by `OPENAI_*`.
- **Vector retrieval**: `local`, `qdrant`, or `supabase`. Qdrant creates/verifies the collection dimension before modifying existing source vectors. The checked-in Supabase migration defines `vector(128)` and a corresponding `match_knowledge_vectors` RPC. If changing dimensions, plan and verify a schema/index migration and reindex; do not merely change the environment value.
- **Chat**: `local` selects extractive answers from retrieved evidence; `openai-compatible` calls the configured chat completions endpoint and validates the answer before returning it.
- **Notifications**: `outbox` durably queues a local JSON record (it does not send email by itself), `smtp` attempts email delivery, and `supabase` inserts a pending record into the configured outbox table. The Supabase outbox requires a separately operated worker to deliver queued items unless your existing deployment already provides one.

Hybrid RAG performs exact/keyword/BM25 candidate retrieval, rank fusion, deduplication, deterministic reranking, bounded evidence selection, contextual/multilingual follow-up handling, and conservative grounding checks. It emits citation metadata only for retrieved chunks. Source documents are treated as untrusted facts, not instructions.

## Preserving existing frontend assets

The backend serves the existing compiled admin files and `/widget.js` directly from `public/`. Node.js is not needed for runtime. To rebuild the frontend intentionally, use the maintained `dashboard/` package and Vite configuration; its configured output directory is `public/admin/`. Build tooling dependencies are separate from the Python service runtime.

## Data backups and restores

Stop the service before restore operations. Back up local state with:

```bash
python scripts/backup.py --data-dir ./data --output ./orbit-backup.zip
```

Restore only a trusted backup to a stopped instance:

```bash
python scripts/restore.py ./orbit-backup.zip --data-dir ./data
```

Restore refuses to overwrite a non-empty data directory unless `--force` is specified. With `--force`, it first makes a timestamped copy of the pre-restore directory. SQLite integrity is checked before files are copied. Backups can contain customer data and must be handled as sensitive operational artifacts; do not put them in the source ZIP or commit them.

## Supabase migration and rollback

1. Back up the current production database and knowledge files first.
2. Review and apply the migrations in order through an operator-controlled process: `0001_initial.sql`, `0002_restrict_audit_logs.sql`, then `0003_atomic_domain_replacement.sql`. The application does not apply migrations automatically at startup. Migration `0003` adds the `replace_client_domains` RPC used to atomically update tenant domain allowlists; until it is applied the adapter uses a compensating REST fallback, which is not a true database transaction.
3. Confirm the project uses the same table names and the configured outbox table.
4. Confirm pgvector dimensions and RPC function signature match the selected embedding model. The included migration is 128-dimensional.
5. Test create/read/update/delete, tenant-bound history, knowledge upload/search/rebuild, and notifications in a non-production project.
6. For rollback, stop the app, restore the database and storage backup, restore the matching vector index, and redeploy the prior application version. Do not change dimensions in place without a tested backup/rollback procedure.

The Supabase/Qdrant/OpenAI/SMTP adapters are implemented but the external credentials and services were unavailable in the test environment, so their real connectivity is not claimed by this report. See `docs/AUDIT_REPORT.md` for the independent audit, and `docs/AUDIT_VERIFICATION_LEDGER.md` for actual final commands and statuses.

## Deployment

The included `Dockerfile` runs Uvicorn under a non-root user in a Python image and retains built assets. `docker-compose.yml` provides a persistent data volume and starts a bundled Qdrant service alongside the app (the app can still use `VECTOR_PROVIDER=local`). Copy `.env.example` to `.env`, set secrets outside version control, then run:

```bash
docker compose up --build -d
```

For a local-only vector provider, Qdrant is not required even if the Compose service is started. In production, terminate TLS at a trusted reverse proxy, set `ALLOWED_ORIGINS` to the intended admin origins, use a strong admin key, protect/backup persistent volumes, and verify `/ready` against the actual configured providers. A process-local rate limiter is included; use infrastructure-level limits as well for multi-replica deployments.

## API compatibility

Core existing admin and public routes are retained under `/admin/*` and `/v1/*`, and `/health`, `/ready`, and `/metrics` remain. Public API calls use `X-API-Key` and an allowed `Origin`; admin calls use `X-Admin-API-Key`. For full route/feature details and known verification limits, read `docs/ARCHITECTURE.md` and `docs/VERIFICATION_REPORT.md`.
