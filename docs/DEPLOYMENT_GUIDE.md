# Deployment guide

## Python process

Install Python 3.11+, create a virtual environment, install `requirements.txt`, create `.env` from `.env.example`, and configure `ADMIN_API_KEY`. Start with:

```bash
uvicorn orbit_ai.app:app --host "${HOST:-0.0.0.0}" --port "${PORT:-3000}"
```

For production, set `NODE_ENV=production`, use a strong unique admin key, configure exact admin origins in `ALLOWED_ORIGINS`, protect the data volume, and configure any external service deliberately. The app serves static assets under `/admin/` and `/widget.js` without requiring a Node runtime.

## Docker Compose

```bash
cp .env.example .env
# Edit .env first, especially ADMIN_API_KEY and provider selections.
docker compose up --build -d
```

The image uses Python 3.12, Uvicorn, a non-root user and a persistent `/app/data` volume. The Compose file includes a Qdrant service, but the app uses the configured `VECTOR_PROVIDER`. If external Qdrant isn't desired, use `VECTOR_PROVIDER=local` or configure the external service before selecting it. The Compose setup was not built in the current test environment; run it in a Docker-enabled release environment before deployment.

## Health / observability

- `GET /health`: application and provider check results. A successful HTTP response means the health handler ran; inspect every provider's `connected` field.
- `GET /ready`: returns 503 if any configured provider health check is not connected.
- `GET /metrics`: Prometheus-style request counts/latency summary.
- `GET /admin/health`: same provider health under the admin key.

Avoid logging API keys, raw credentials, customer data, full LLM payloads or document contents. `ORBIT_RAG_DIAGNOSTICS=1` opts into redacted retrieval counters; it is off by default.

## Storage and backup

For local operation, the service writes the SQLite repository, JSON vectors, uploaded files and outbox below `DATA_DIR`. Back these up as sensitive data. `scripts/backup.py` uses SQLite's backup API; `scripts/restore.py` must be run with the service stopped and checks archive paths and database integrity. Before any database or vector migration, create a separate verified external backup as well.

## Supabase

Apply the checked-in migration manually against a non-production project first. It provisions metadata tables, RLS policies, a private storage bucket, notification table/view, `knowledge_vectors vector(128)`, and `match_knowledge_vectors`. Ensure server-side access uses an appropriate service-role credential held only in server configuration. Validate all reads/writes, tenant-isolation policies, Storage operations, vector RPC and outbox health checks before cutover.

## Frontend rebuild

The committed dashboard source/lockfile is under `dashboard/`. The Vite output path is `public/admin/`, which the Python backend serves. Runtime does not require Node. Rebuilding dashboard assets requires installing its frontend dependencies with npm; this was not verified in the offline current environment because the npm package cache did not contain the required packages.

## Multi-instance / security notes

The included rate limiter is process-local; use your edge proxy/API gateway for shared rate limiting. Terminate TLS, configure restrictive CORS/origins, protect backups/volumes, and review the exact `/ready` results after deployment. Do not expose debug endpoints or secrets. External integration claims must be based on a live test in the target deployment environment.
