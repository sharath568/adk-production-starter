import pytest

from conftest import call, say, tool_results


@pytest.mark.asyncio
async def test_unknown_service_is_blocked_before_the_tool_runs(harness):
    h = harness([
        call("transfer_to_agent", agent_name="ops_agent"),
        call("get_service_status", service="prod-database"),
        say("I can only check orders-api, payments-api and inventory-api."),
    ])
    events = await h.send("check prod-database")
    result = tool_results(events, "get_service_status")[0]
    assert "not in the allowlist" in result["error"]


@pytest.mark.asyncio
async def test_tool_call_budget_stops_loops(harness, monkeypatch):
    from support_agent import config

    monkeypatch.setattr(config, "MAX_TOOL_CALLS_PER_TURN", 3)
    loop = [call("get_service_status", service="orders-api") for _ in range(4)]
    h = harness([call("transfer_to_agent", agent_name="ops_agent"), *loop, say("stopping")])
    events = await h.send("keep checking orders-api")
    results = tool_results(events, "get_service_status")
    assert [("error" in r) for r in results] == [False, False, False, True]


@pytest.mark.asyncio
async def test_severity_is_validated(harness):
    h = harness([
        call("transfer_to_agent", agent_name="ops_agent"),
        call("create_incident_ticket", service="orders-api", severity="URGENT!!", summary="x"),
        say("Severity must be SEV1-3."),
    ])
    events = await h.send("open a ticket")
    assert "severity must be one of" in tool_results(events, "create_incident_ticket")[0]["error"]


def test_secrets_are_redacted_from_tool_output():
    from support_agent.guardrails import after_tool

    class T:
        name = "search_docs"

    out = after_tool(T(), {}, None, {"passages": [{"text": "set password: hunter2 then restart"}]})
    assert out["passages"][0]["text"] == "set password=[REDACTED] then restart"
    assert after_tool(T(), {}, None, {"text": "nothing secret here"}) is None
