# Changelog

## v0.3.0 (October 2026)

- Three-layer evals, ported from [adk-eval-harness](https://github.com/sharath568/adk-eval-harness):
  - `evals/cases.yaml` -> ADK evalsets for six suites (knowledge, ops, ops_triage, approvals, refusals,
    data), each with its own trajectory rule and a pass-rate gate in `evals/gate.yaml`
  - `evals/run_evals.py`: `LocalEvalService` x N runs, pass rates, flaky cases, transcripts, cost cap
  - `judge/run_judge.py` + `judge/rubric.yaml` (v1, pinned `gemini-3.5-flash`, thinking low);
    `tools/calibrate_judge.py` for agreement and Cohen's kappa against your labels
  - `tools/regress.py` + `regressions.py`: 9 deliberate regressions, results resumable per regression
- Coordinator scope rule: off-topic requests are declined without a transfer (missing before; found
  while writing the refusal cases)
- `usage.py`: token and cost tally from `after_model`; raises only when `EVAL_COST_CAP_USD` is set
- New offline tests (43 total): tool and prompt contracts, the eval pipeline with a scripted golden
  model, evalset/cases sync, the judge runner with a fake client
- `evals.yml`: nightly layer 2, weekly layer 3 via Workload Identity Federation; skipped without it

## v0.2.1 (October 2026)

- Gemini location defaults to `global`: Gemini 3.5 returns 404 NOT_FOUND from `us-central1`.
  `deploy.sh` takes `GEMINI_LOCATION` separately from the Cloud Run `REGION`.
- Checked live: coordinator -> data_agent -> MCP server on Cloud Run -> Cloud SQL, Gemini 3.5 Flash-Lite.
  Four questions (count, 3-way join revenue, delete request, injected row) took 17 model calls, about $0.009.

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
