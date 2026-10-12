# adk-production-starter

A starter kit for running **multi-agent systems built with Google's Agent Development Kit (ADK)** in production on Google Cloud. It's small enough to read in one sitting, with the parts that tutorials skip: guardrails in code, human approval for write actions, persistent sessions, structured logs, offline tests, and a Cloud Run deploy.

Companion code for *"Building your first multi-agent system with ADK, the production way"*. It grows release by release. See the [roadmap](#roadmap).

```
                    ┌──────────────────────────────┐
  user ──► Cloud Run│ coordinator  (flash-lite)    │  routes only, no tools
                    └──┬─────────────┬──────────┬──┘
                       │             │          │
       ┌───────────────▼─┐  ┌────────▼─────────────────┐  ┌▼──────────────────────┐
       │ knowledge_agent │  │ ops_agent                │  │ data_agent (v0.2)     │
       │  search_docs ───┼► │  get_service_status      │  │  list_views           │
       │  (RAG service)  │  │  list_recent_deploys     │  │  describe_view        │
       └─────────────────┘  │  create_incident_ticket ⏸│  │  run_query            │
                            └──────────────────────────┘  └──────────┬────────────┘
                                         ⏸ = human approval          │ MCP + ID token
                                                                     ▼
                                       gemini-mcp-db-server (private Cloud Run, read-only role)
   every tool call ─► before_tool guardrails ─► tool ─► log ─► redact
   sessions ─► Postgres (AlloyDB / Cloud SQL) via DatabaseSessionService
```

## What's in v0.2

| Production concern | How it's handled | Where |
|---|---|---|
| Wrong tool calls | Each specialist sees only its own tools; coordinator has none | `agents/support_agent/agent.py` |
| Cost | Cheap model routes, stronger model does the work; context cache across transfers | `agent.py`, `config.py` |
| Bad arguments | `before_tool_callback`: service allowlist, severity validation, normalization | `guardrails.py` |
| Runaway loops | Per-turn tool-call budget in `temp:` state | `guardrails.py` |
| Leaking secrets | `after_tool_callback` redacts credential-looking strings | `guardrails.py` |
| Risky writes | `FunctionTool(require_confirmation=True)`: ADK pauses until a human approves | `tools/ops.py` |
| Cross-tenant data | Tenant read from session state, never a tool argument the model fills | `tools/knowledge.py` |
| Downstream outages | Tool errors returned as data so the agent can explain, not crash | `tools/knowledge.py` |
| Instances restarting | `DatabaseSessionService` on Postgres; any instance can resume any session | `server.py` |
| Observability | One JSON log line per model call (latency, tokens, cache hits) and tool call | `observability.py` |
| Database access | `data_agent` reads business data through a read-only MCP server; it never holds a DB credential | `tools/database.py` |
| Who's calling the DB | ID token for the private MCP service; session id in headers joins the server's audit log with ours | `tools/database.py` |
| Too many tools | `McpToolset(tool_filter=...)`: the model sees 3 of the server's 4 tools | `tools/database.py`, `config.py` |
| Destructive SQL | Agent-side precheck (SELECT only, one statement) before the request leaves; the server's guard and DB role are the real control | `guardrails.py` |
| Regressions | 27 offline tests with a scripted model: routing, tools, guardrails, approvals, sessions, MCP | `tests/` |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                      # offline, no credentials, ~2 seconds

# Talk to it with Gemini on Vertex AI
gcloud auth application-default login
cp .env.example .env && set -a && source .env && set +a
adk web agents                 # dev UI on http://localhost:8000
```

With the database server running locally ([gemini-mcp-db-server](https://github.com/sharath568/gemini-mcp-db-server): `make db serve`), set `MCP_DB_URL=http://127.0.0.1:8080/mcp` to add the data_agent.

Try: *"how many orders per channel?"* (data_agent, if enabled), *"is orders-api ok?"*, *"how do I roll back a deploy?"*, *"open a SEV2 for orders-api"* (watch it pause for approval), *"check prod-database"* (watch the guardrail).

## Testing agents without calling a model

`tests/conftest.py` has a `ScriptedLlm`: a `BaseLlm` that replays a fixed list of model turns and records every request. Tests script what the model "decides" and assert on what the system *does*, which is the part you own:

```python
h = harness([
    call("transfer_to_agent", agent_name="ops_agent"),
    call("get_service_status", service="prod-database"),   # not allowed
    say("I can only check orders-api, payments-api and inventory-api."),
])
events = await h.send("check prod-database")
assert "not in the allowlist" in tool_results(events, "get_service_status")[0]["error"]
```

Model quality is tested separately with evals (coming in v0.3).

## Deploy to Cloud Run

```bash
PROJECT_ID=my-project \
SESSION_DB_URL='postgresql+asyncpg://postgres:PASS@10.x.x.x:5432/postgres' \
RAG_SERVICE=rag-api \
MCP_DB_SERVICE=mcp-db-server \
./deploy/deploy.sh
```

Private service, its own least-privilege service account, session DB URL in Secret Manager, Direct VPC egress to the database, `roles/run.invoker` on the RAG and MCP database services and nothing broader. Pair it with [vertex-alloydb-rag](https://github.com/sharath568/vertex-alloydb-rag) for hybrid search on AlloyDB.

## Troubleshooting

**`Error on session runner task: unhandled errors in a TaskGroup (1 sub-exception)`** in the logs, but the answer is fine.
One HTTP connection to the MCP server was dropped (the sub-exception is an `httpx` `ReadError`). It happens through `gcloud run services proxy` and around Cloud Run cold starts. The MCP client fails its whole session on any transport error; ADK logs this warning, opens a new session and retries once, so a single drop costs a few hundred ms and nothing else.

If it fails twice in a row, ADK drops the toolset for that turn and the model sees `Tool 'list_views' not found`. If you see that, look at the network path (proxy, VPC egress, the server's instance limits), not the agent.

## Roadmap

| Version | Adds | Article |
|---|---|---|
| v0.1 | Multi-agent core, guardrails, approvals, DB sessions, tests, Cloud Run | ADK multi-agent, the production way |
| **v0.2** | MCP tools with least-privilege database access | Safe database access for Gemini agents through MCP |
| v0.3 | Evaluation harness (trajectory + response) in CI | Testing ADK agents |
| v0.4 | Text-to-SQL tool with guardrails | Text-to-SQL with Gemini |
| v0.5 | Async human-in-the-loop approvals via Pub/Sub | Human-in-the-loop approvals for ADK agents |
| v0.6 | Cost and latency controls | Cutting Gemini cost and latency |
| v1.0 | Terraform, Cloud Trace, reference architecture | Enterprise agent platform on Google Cloud |

## License

Apache-2.0
