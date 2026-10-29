# Production readiness assessment — conditional / not fully verified

> **Post-release audit:** This assessment is superseded by [`AUDIT_REPORT.md`](AUDIT_REPORT.md) and [`AUDIT_VERIFICATION_LEDGER.md`](AUDIT_VERIFICATION_LEDGER.md), which independently rechecked the original delivered ZIP and document additional fixes and verification blockers.

## Verified locally

- Python/FastAPI backend starts in-process via the test client.
- Local SQLite schema and repositories persist tenant, knowledge metadata, conversations and messages across app recreation.
- Public key and exact-Origin checks reject invalid credentials/origins.
- Tenant-scoped knowledge upload, local indexing, hybrid retrieval, grounding and source metadata work in the exercised path.
- SSE sends token and done events after the grounded response is computed.
- Admin/dashboard static bundle and browser widget are served.
- Vector dimension changes are preflighted before replacing a local vector source; local data files are written atomically with restrictive permissions.
- All Python tests in `tests/` pass in the current local environment (see `VERIFICATION_REPORT.md`).

## Not verified / prerequisites before production

- Actual Supabase and Qdrant connections, schema/RLS behavior, private Storage upload/download/delete, vector search and outbox write.
- Actual external embeddings and chat LLM authentication, model compatibility, rate-limit behavior and provider quality.
- SMTP connection and delivery.
- Docker image build/runtime and a clean production deployment.
- Dashboard asset rebuild and browser-level end-to-end tests; the built asset bundle is retained but npm dependencies were unavailable offline.
- The complete original TypeScript test suite; dependency installation failed because npm's offline cache did not contain a required package.
- Comprehensive destructive migration/rollback against a production-sized dataset or all existing historical schemas.

## Known limitations

- The deterministic local embedding provider is a development/offline provider; it is not semantically equivalent to hosted embeddings. Keep embeddings/index dimensions consistent.
- Supabase SQL migration is fixed to `vector(128)`. Alternate dimensions require a matching SQL type/RPC migration and a complete reindex.
- The local notification outbox records messages but does not send them. Use a delivery worker or SMTP/Supabase provider and prove delivery in staging.
- The SMTP health check verifies configuration, not SMTP connectivity/delivery.
- Grounding validation uses conservative source/numeric/negation/qualification heuristics plus a corrective retry; it does not formally prove every answer claim.
- Rate limiting is process-local and requires edge infrastructure for horizontal scale.

**Release decision:** not a fully externally verified production release. The local Python release can be packaged and exercised, but production cutover should wait for the blocked provider, Docker, frontend build and rollback checks to pass in a credentialed staging environment.
