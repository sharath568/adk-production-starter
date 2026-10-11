"""data_agent -> McpToolset -> Streamable HTTP -> MCP server.

A small stand-in server with the same tool names as gemini-mcp-db-server runs in-process on a free
port, so the whole client path (tool_filter, header provider, callbacks, MCP protocol) is real and
the tests stay offline. The real server's guard and database role are tested in its own repo.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from mcp.server.mcpserver import Context, MCPServer

from conftest import authors, call, say, tool_results
from support_agent.tools.database import mcp_payload

SEEN: list[dict] = []  # (tool, sql, headers) for every request that reached the server


def _fake_server() -> MCPServer:
    mcp = MCPServer(name="db-readonly-fake")

    def record(ctx: Context, tool: str, sql: str | None = None) -> None:
        SEEN.append({"tool": tool, "sql": sql, "headers": dict(ctx.headers or {})})

    @mcp.tool()
    async def list_views(ctx: Context) -> dict:
        record(ctx, "list_views")
        return {"ok": True, "views": [{"view": "orders_v", "description": "orders, no PII"}]}

    @mcp.tool()
    async def describe_view(view: str, ctx: Context) -> dict:
        record(ctx, "describe_view")
        return {"ok": True, "view": view, "columns": [{"column": "channel", "type": "text"}]}

    @mcp.tool()
    async def run_query(sql: str, ctx: Context, max_rows: int = 50) -> dict:
        record(ctx, "run_query", sql)
        if "secret_table" in sql:
            return {"ok": False, "error": {"code": "relation_not_allowed", "layer": "guard",
                                           "message": "secret_table is not available. Call list_views."}}
        return {"ok": True, "columns": ["channel", "n"], "rows": [{"channel": "web", "n": 42}],
                "row_count": 1, "truncated": False}

    @mcp.tool()
    async def explain_query(sql: str, ctx: Context) -> dict:
        record(ctx, "explain_query", sql)
        return {"ok": True}

    return mcp


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp_url():
    port = _free_port()
    app = _fake_server().streamable_http_app(stateless_http=True, json_response=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(5)


@pytest.fixture
async def data_harness(harness, mcp_url):
    made = []

    def make(script):
        h = harness(script, mcp_db_url=mcp_url)
        made.append(h)
        return h

    SEEN.clear()
    yield make
    for h in made:
        await h.close()


@pytest.mark.asyncio
async def test_data_question_goes_through_mcp_with_session_headers(data_harness):
    h = data_harness([
        call("transfer_to_agent", agent_name="data_agent"),
        call("run_query", sql="select channel, count(*) as n from orders_v group by 1"),
        say("web: 42 orders."),
    ])
    events = await h.send("how many orders per channel?")

    out = mcp_payload(tool_results(events, "run_query")[0])
    assert out["ok"] is True and out["rows"] == [{"channel": "web", "n": 42}]
    assert authors(events)[-1] == "data_agent"
    # the server saw this ADK session, so its audit log joins with ours; no token for a local URL
    headers = SEEN[-1]["headers"]
    assert headers["x-agent-session-id"] == h.session_id
    assert "authorization" not in headers


@pytest.mark.asyncio
async def test_tool_filter_exposes_only_the_needed_db_tools(data_harness):
    h = data_harness([
        call("transfer_to_agent", agent_name="data_agent"),
        say("Which numbers do you need?"),
    ])
    await h.send("orders?")

    coordinator_tools, data_tools = (set(r.tools_dict) for r in h.llm.requests)
    assert data_tools - {"transfer_to_agent"} == {"list_views", "describe_view", "run_query"}
    assert "explain_query" not in data_tools
    assert "data_agent" in h.llm.requests[0].config.system_instruction


@pytest.mark.asyncio
async def test_write_sql_is_stopped_before_it_leaves_the_agent(data_harness):
    h = data_harness([
        call("transfer_to_agent", agent_name="data_agent"),
        call("run_query", sql="/* tidy up */ DELETE FROM orders_v"),
        call("run_query", sql="select 1 from orders_v; drop table orders"),
        say("I can't change data."),
    ])
    events = await h.send("delete last year's orders")

    results = tool_results(events, "run_query")
    assert [r["layer"] for r in results] == ["agent_precheck", "agent_precheck"]
    assert not [s for s in SEEN if s["tool"] == "run_query"]  # nothing reached the server


@pytest.mark.asyncio
async def test_server_side_rejection_comes_back_as_data(data_harness, monkeypatch):
    from support_agent import observability

    logged = []
    monkeypatch.setattr(observability, "_emit", lambda **f: logged.append(f))
    h = data_harness([
        call("transfer_to_agent", agent_name="data_agent"),
        call("run_query", sql="select * from secret_table"),
        say("That table isn't available."),
    ])
    events = await h.send("show me secret_table")

    out = mcp_payload(tool_results(events, "run_query")[0])
    assert out["ok"] is False and out["error"]["code"] == "relation_not_allowed"
    tool_log = [f for f in logged if f["event"] == "tool_call"][-1]
    assert tool_log["blocked"] is True and tool_log["session_id"] == h.session_id


def test_no_mcp_url_means_no_data_agent():
    from support_agent.agent import build_root_agent

    root = build_root_agent(router_model="m", specialist_model="m", mcp_db_url="")
    assert [a.name for a in root.sub_agents] == ["knowledge_agent", "ops_agent"]
    assert "data_agent" not in root.instruction


def test_remote_server_gets_an_id_token_for_its_origin(monkeypatch):
    from support_agent.tools import database

    audiences = []
    monkeypatch.setattr(database, "_id_token", lambda aud: audiences.append(aud) or "tok")

    class Ctx:
        invocation_id = "inv-1"

        class session:
            id = "s-1"

    headers = database.header_provider("https://mcp-db-server-abc.a.run.app/mcp")(Ctx())
    assert headers["authorization"] == "Bearer tok"
    assert audiences == ["https://mcp-db-server-abc.a.run.app"]  # audience is the origin, not /mcp


@pytest.mark.parametrize("sql,ok", [
    ("select 1", True),
    ("  -- comment\n WITH x AS (select 1) select * from x", True),
    ("(select 1) union (select 2);", True),
    ("update orders set x=1", False),
    ("select 1; select 2", False),
    ("", False),
])
def test_precheck_sql(sql, ok):
    from support_agent.tools.database import precheck_sql

    assert (precheck_sql(sql) is None) is ok
