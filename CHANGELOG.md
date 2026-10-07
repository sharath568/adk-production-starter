# Changelog

## v0.1.0 (October 2026)

- Coordinator + knowledge_agent + ops_agent built with ADK 2.11
- Guardrail callbacks: service allowlist, severity validation, per-turn tool budget, secret redaction
- `create_incident_ticket` requires human confirmation (`FunctionTool(require_confirmation=True)`)
- Tenant taken from session state; knowledge tool calls the vertex-alloydb-rag service with an ID token
- `DatabaseSessionService` (SQLite locally, Postgres/AlloyDB on Cloud Run)
- Structured JSON logs for model and tool calls
- 15 offline tests with a scripted model; GitHub Actions CI
- Cloud Run deploy script
