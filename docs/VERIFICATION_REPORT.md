# Verification report — independently audited release

**Current release candidate:** `Orbit-AI-Final-Audited.zip`  
**Decision:** Conditionally verified for local use; external production acceptance remains incomplete.

This report supersedes earlier test counts and packaging statements in the original `Orbit-AI-Final.zip` delivery. The audited archive and extracted contents are the final source of truth. Detailed confirmed defects/fixes are in `docs/AUDIT_REPORT.md`; the complete command/status ledger is in `docs/AUDIT_VERIFICATION_LEDGER.md`.

## Latest working-tree evidence

- `python -m pytest -q`: **55 passed** in the latest displayed working-tree run, with no warnings.
- `python -m compileall -q orbit_ai scripts tests`: passed after the provider/config/test updates preceding packaging.
- `python -m pip install --no-deps --no-build-isolation -e .`: editable package build and installation succeeded.
- Standalone Uvicorn smoke test using a fresh temporary `DATA_DIR`: `GET /health` = 200, `GET /ready` = 200/ready true, `GET /admin/` = 200, `GET /widget.js` = 200, and authenticated `POST /admin/auth/validate` = 200.
- Untouched Advanced RAG reference suite: **24 passed** in a separate run.

These local tests use local providers or test doubles. They do not prove external provider connectivity.

## Known failed/blocked/not-run checks

| Check | Status | Observed reason |
|---|---|---|
| `python -m pip check` | **FAIL** | Shared environment conflict: MoviePy 2.2.1 requires Pillow below 12; environment has Pillow 12.3.0. Neither is declared as Orbit runtime dependency. |
| Dashboard npm install/build and browser E2E | **BLOCKED** | `npm ci --offline --ignore-scripts --no-audit --no-fund` failed `ENOTCACHED` for `zod@3.25.76`; network package install was unavailable/timed out. |
| Docker image/Compose build | **BLOCKED** | Docker CLI not installed. |
| SQL migration execution/live Supabase | **BLOCKED** | `psql` unavailable and no Supabase endpoint/service-role credential supplied. |
| Live Qdrant, hosted LLM/embeddings, SMTP | **BLOCKED** | No configured external services/credentials in this environment. Mock adapter tests are not live integration proof. |
| Ruff lint | **NOT RUN** | Ruff declared in dev requirements but not installed; offline package access unavailable. |
| Production-scale concurrency and destructive restore drill | **NOT RUN** | Requires a controlled staging dataset and environment; not attempted against real user data. |

## Acceptance

The final archive's ZIP integrity, required contents, cache/database/secret exclusion, clean extraction, compile check, test suite, and editable package installation must all pass in the clean extracted copy before calling the package validated. See the audit ledger for the final observed package results. Do not describe this release as bug-free or fully production verified.
