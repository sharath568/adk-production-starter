# Changelog

## v0.2.0 (October 2026)

- `data_agent`: read-only business data through [gemini-mcp-db-server](https://github.com/sharath568/gemini-mcp-db-server)
  with `McpToolset` over Streamable HTTP. Enabled by `MCP_DB_URL`; off by default.
- Header provider: Google ID token for private Cloud Run (cached), plus `x-agent-session-id` /
  `x-agent-invocation-id` so the server's audit log joins with the agent's logs
- `tool_filter`: the model sees `list_views`, `describe_view`, `run_query` only
- `before_tool` precheck rejects non-SELECT and stacked SQL before the request leaves the process
- Tool log lines carry `session_id`; `blocked` understands MCP `ok=false` results
- Coordinator routes are built from the specialists that exist
- 12 new offline tests against an in-process MCP server (27 total)
- `deploy.sh`: `MCP_DB_SERVICE` sets `MCP_DB_URL` and grants `run.invoker` on that service only

## v0.1.0 (October 2026)

- Coordinator + knowledge_agent + ops_agent built with ADK 2.11
- Guardrail callbacks: service allowlist, severity validation, per-turn tool budget, secret redaction
- `create_incident_ticket` requires human confirmation (`FunctionTool(require_confirmation=True)`)
- Tenant taken from session state; knowledge tool calls the vertex-alloydb-rag service with an ID token
- `DatabaseSessionService` (SQLite locally, Postgres/AlloyDB on Cloud Run)
- Structured JSON logs for model and tool calls
- 15 offline tests with a scripted model; GitHub Actions CI
- Cloud Run deploy script
