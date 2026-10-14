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

## What's in v0.3

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
| Regressions | 43 offline tests with a scripted model: routing, tools, guardrails, approvals, sessions, MCP, tool and prompt contracts | `tests/` |
| Model quality | Three-layer evals: offline tests, `adk eval` evalsets run N times with gates, a pinned judge model; plus 9 deliberate regressions to prove each layer earns its place | `evals/`, `judge/`, `tools/regress.py` |
| Off-topic requests | Coordinator scope rule: decline in one sentence, don't transfer (found while writing the refusal evals) | `agent.py` |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                      # offline, no credentials, ~10 seconds

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

That proves the wiring. It can't tell you whether Gemini makes the right moves. That's what the evals are for.

## Evals: three layers, each with a gate

```
 make test     L1  scripted model + real tools/callbacks            every push, free, ~5 s
 make eval     L2  adk evalsets x N runs -> pass rate per suite      nightly, Gemini, ~cents
 make judge    L3  pinned judge model + versioned rubric             weekly / before release
 make regress  break the agent 9 ways on purpose; which layer noticed?
```

**Layer 2** uses ADK's own evalsets (`evals/<suite>/<suite>.evalset.json`, built from the readable `evals/cases.yaml`) and ADK's `LocalEvalService`, so the same files work with `adk eval` and `adk web`. The runner adds what one `adk eval` doesn't: every case runs `--runs` times, results are pass rates with flaky cases listed, each suite has a gate (`evals/gate.yaml`), and the run stops at a cost cap (`EVAL_COST_CAP_USD`, default $0.50 per process).

Each suite gets the trajectory rule that fits it:

| Suite | Cases | Trajectory rule | Why |
|---|---|---|---|
| `knowledge` | 9 | `IN_ORDER`, args ignored | the agent writes its own search query |
| `ops` | 4 | `IN_ORDER`, args compared | right specialist, right service name |
| `ops_triage` | 3 | `IN_ORDER`, args ignored | an unhealthy service must get a deploy check (`limit=` varies) |
| `approvals` | 3 | `IN_ORDER`, args ignored, no response check | must end in `adk_request_confirmation`: paused, no answer yet |
| `refusals` | 4 | `EXACT`, empty | any tool call fails |
| `data` | 4 | `IN_ORDER` | only when `MCP_DB_URL` is set |

Three things learned while wiring this up, all checked against ADK 2.11:

- In a multi-agent app, **`transfer_to_agent` is part of the trajectory**, so routing is tested by the same metric as tool use.
- **`IN_ORDER` allows extra calls between the expected ones, but compares arguments with plain equality.** `list_recent_deploys(service=...)` and `list_recent_deploys(service=..., limit=3)` don't match. That's why `ops_triage` exists.
- **An approval-gated tool shows up as two calls:** the tool, then `adk_request_confirmation`, and the turn ends with no final text. Response-match metrics are meaningless there, so that suite doesn't use one.

`tests/test_eval_pipeline.py` runs every evalset through `LocalEvalService` offline with a scripted "golden" model that plays each case perfectly. If that passes, the evalsets, configs and real tools agree. A red nightly run then means the *model* changed behaviour, not that the harness is broken.

**Layer 3** (`judge/run_judge.py`) scores the layer 2 transcripts against `judge/rubric.yaml`: grounded, cites the source, no false action, correct outcome (including ticket severity), scope, no secrets. The judge model is pinned and the rubric is versioned. Calibrate it against your own labels before you gate on it: `make labels`, label 30 rows, then `make calibrate` for agreement and Cohen's kappa. The judge setup comes from the companion repo [adk-eval-harness](https://github.com/sharath568/adk-eval-harness), where a cheaper judge turned out to be cheap because it was lenient.

**Regressions** (`agents/support_agent/regressions.py`) are switches, not patches: `AGENT_REGRESSION=drop_scope_rule make eval`. Layer 1 so far, offline:

| Regression | What changed | L1 |
|---|---|---|
| `drop_grounding_rule` | knowledge prompt loses "answer only from what the tool returns, cite the source" | **caught** (prompt contract) |
| `soften_grounding_rule` | rules all still there, plus "if the docs are thin, fill in from general best practice" | missed |
| `drop_scope_rule` | coordinator loses the out-of-scope rule | **caught** (prompt contract) |
| `drop_deploy_check` | ops prompt loses "if it isn't healthy, also call list_recent_deploys" | **caught** (prompt contract) |
| `vague_tool_docs` | every tool description becomes "Tool." | **caught** (tool contract) |
| `no_service_allowlist` | allowlist check deleted from `before_tool` | **caught** |
| `approval_off` | `require_confirmation` dropped from the ticket tool | **caught** (4 tests) |
| `no_secret_redaction` | `after_tool` redaction deleted | **caught** |
| `router_old_model` | router swapped to an older, smaller model | missed (the model is scripted) |

The prompt-contract tests (`tests/test_contracts.py`) catch a *deleted* rule in milliseconds. They can't catch a rule that's still there but undermined (`soften_grounding_rule`), or a model that stops following it. Those two rows are the case for layers 2 and 3. Run `make regress` with Gemini credentials to fill in their columns.

```bash
export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=your-project GOOGLE_CLOUD_LOCATION=global
make eval RUNS=3      # layer 2, writes runs/<stamp>-baseline/
make judge            # layer 3 on the latest run
make regress          # all three layers x 9 regressions, writes runs/regressions.md (resumes if interrupted)
```

CI: `.github/workflows/ci.yml` runs layer 1 on every push. `.github/workflows/evals.yml` runs layer 2 nightly and layer 3 on Mondays, through Workload Identity Federation. It's skipped until you set the repository variables `GCP_WIF_PROVIDER`, `GCP_SERVICE_ACCOUNT` and `GCP_PROJECT_ID`, so forks stay green.

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
| v0.2 | MCP tools with least-privilege database access | Safe database access for Gemini agents through MCP |
| **v0.3** | Three-layer evals (scripted model, `adk eval` x N with gates, judge), contract tests, injected regressions | Testing ADK agents |
| v0.4 | Text-to-SQL tool with guardrails | Text-to-SQL with Gemini |
| v0.5 | Async human-in-the-loop approvals via Pub/Sub | Human-in-the-loop approvals for ADK agents |
| v0.6 | Cost and latency controls | Cutting Gemini cost and latency |
| v1.0 | Terraform, Cloud Trace, reference architecture | Enterprise agent platform on Google Cloud |

## License

Apache-2.0
