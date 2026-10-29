# Orbit AI — independent audit test report

This report reflects checks run against the audited working tree, not the previous release report.

## Local automated tests

- **Orbit AI Python suite:** `python -m pytest -q` — **55 passed** in the latest working-tree run; the final clean-archive result is recorded in the ledger.
- **Python compilation:** `python -m compileall -q orbit_ai scripts tests` — run again on the final extracted archive before delivery.
- **Advanced RAG reference suite:** `python -m pytest -q` from the original `advanced_rag` directory — **24 passed** in an independent baseline run. This checks the reference project separately; it is not proof that external Orbit integrations are operational.

The Orbit tests cover local API workflows, authentication and tenant separation, conversation continuity, summaries/greetings, local hybrid retrieval and evidence, grounding, hostile retrieved content placement, upload filename canonicalization, index replacement failure behavior, vector-dimension compatibility, CORS origin/port normalization, CSV formula neutralization, payload limits, rate-limit memory bounds, configuration validation, OpenAI embedding request dimensions via a fake HTTP response, provider health parsing, SMTP headers via a fake client, Supabase exact counts/pagination/RPC fallback via fake responses, Qdrant schema validation via fake responses, restore archive safety, and cleanup retry behavior.

## External and frontend verification limits

- Live OpenAI-compatible chat/embedding calls: **BLOCKED** — no external credential/service configured for this audit. Fake HTTP adapter tests are not live integration tests.
- Live Supabase/Postgres SQL/RPC/Storage: **BLOCKED** — no project URL/service-role key or database CLI/service available. SQL migrations have not been applied to a real database.
- Live Qdrant: **BLOCKED** — no running Qdrant service/credentials; schema and request logic are tested with fake HTTP responses.
- Live SMTP or delivery worker: **BLOCKED** — no SMTP server or configured delivery worker. The local file outbox only queues notifications.
- Dashboard production build/browser E2E: **BLOCKED** — `npm ci --offline --ignore-scripts --no-audit --no-fund` fails with `ENOTCACHED` for `zod@3.25.76`; network installation is unavailable/timed out in this environment.
- Docker image build/run: **BLOCKED** — Docker CLI is not installed.
- Lint: **NOT RUN** — Ruff is declared in `requirements-dev.txt`, but the executable/package is not installed and package installation is not available offline.
- `python -m pip check`: **FAIL (ambient environment conflict)** — reports `moviepy 2.2.1` requires `Pillow<12.0,>=9.2.0`, but the shared environment has Pillow 12.3.0. Neither MoviePy nor Pillow is an Orbit runtime dependency in `requirements.txt`; this is not evidence of an Orbit dependency-resolution failure.

See `docs/AUDIT_REPORT.md` and `docs/AUDIT_VERIFICATION_LEDGER.md` for findings, fixes, commands, and final archive validation.
