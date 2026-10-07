# adk-production-starter

A starter kit for running **multi-agent systems built with Google's Agent Development Kit (ADK)** in production on Google Cloud. It's small enough to read in one sitting, with the parts that tutorials skip: guardrails in code, human approval for write actions, persistent sessions, structured logs, offline tests, and a Cloud Run deploy.

Companion code for *"Building your first multi-agent system with ADK, the production way"*. It grows release by release. See the [roadmap](#roadmap).

```
                    ┌──────────────────────────────┐
  user ──► Cloud Run│ coordinator  (flash-lite)    │  routes only, no tools
                    └───────┬──────────────┬───────┘
                            │              │
              ┌─────────────▼───┐   ┌──────▼──────────────────────┐
              │ knowledge_agent │   │ ops_agent                    │
              │  search_docs ───┼─► │  get_service_status          │
              │  (RAG service)  │   │  list_recent_deploys         │
              └─────────────────┘   │  create_incident_ticket ⏸    │ ⏸ = human approval
                                    └──────────────────────────────┘
   every tool call ─► before_tool guardrails ─► tool ─► log ─► redact
   sessions ─► Postgres (AlloyDB / Cloud SQL) via DatabaseSessionService
```

## What's in v0.1

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
| Regressions | 15 offline tests with a scripted model: routing, tools, guardrails, approvals, sessions | `tests/` |

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

Try: *"is orders-api ok?"*, *"how do I roll back a deploy?"*, *"open a SEV2 for orders-api"* (watch it pause for approval), *"check prod-database"* (watch the guardrail).

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
./deploy/deploy.sh
```

Private service, its own least-privilege service account, session DB URL in Secret Manager, Direct VPC egress to the database, `roles/run.invoker` on the RAG service and nothing broader. Pair it with [vertex-alloydb-rag](https://github.com/sharath568/vertex-alloydb-rag) for hybrid search on AlloyDB.

## Roadmap

| Version | Adds | Article |
|---|---|---|
| **v0.1** | Multi-agent core, guardrails, approvals, DB sessions, tests, Cloud Run | ADK multi-agent, the production way |
| v0.2 | MCP tools with least-privilege database access | Safe database access for Gemini agents through MCP |
| v0.3 | Evaluation harness (trajectory + response) in CI | Testing ADK agents |
| v0.4 | Text-to-SQL tool with guardrails | Text-to-SQL with Gemini |
| v0.5 | Async human-in-the-loop approvals via Pub/Sub | Human-in-the-loop approvals for ADK agents |
| v0.6 | Cost and latency controls | Cutting Gemini cost and latency |
| v1.0 | Terraform, Cloud Trace, reference architecture | Enterprise agent platform on Google Cloud |

## License

Apache-2.0
