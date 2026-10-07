import pytest

from conftest import authors, call, say, tool_results


@pytest.mark.asyncio
async def test_status_question_routes_to_ops_and_correlates_deploys(harness):
    h = harness([
        call("transfer_to_agent", agent_name="ops_agent"),
        call("get_service_status", service="orders-api"),
        call("list_recent_deploys", service="orders-api", limit=2),
        say("orders-api is degraded since 14:05; deploy orders-api-00042 went out at 14:00."),
    ])
    events = await h.send("is orders-api ok?")

    assert tool_results(events, "get_service_status")[0]["status"] == "degraded"
    assert tool_results(events, "list_recent_deploys")[0]["deploys"][0]["revision"] == "orders-api-00042"
    assert authors(events)[-1] == "ops_agent"


@pytest.mark.asyncio
async def test_specialists_only_see_their_own_tools(harness):
    h = harness([
        call("transfer_to_agent", agent_name="knowledge_agent"),
        call("search_docs", question="how do I roll back a deploy"),
        say("Send traffic to the previous revision (deploys.md#Rollback)."),
    ])
    await h.send("how do I roll back?")

    coordinator_tools, knowledge_tools, _ = (set(r.tools_dict) for r in h.llm.requests)
    assert coordinator_tools == {"transfer_to_agent"}
    assert "search_docs" in knowledge_tools
    assert not knowledge_tools & {"get_service_status", "create_incident_ticket"}


@pytest.mark.asyncio
async def test_knowledge_agent_finds_rollback_runbook(harness):
    h = harness([
        call("transfer_to_agent", agent_name="knowledge_agent"),
        call("search_docs", question="roll back a Cloud Run deploy"),
        say("..."),
    ])
    events = await h.send("how do I roll back a cloud run deploy?")
    result = tool_results(events, "search_docs")[0]
    assert result["grounded"] and result["passages"][0]["source"] == "deploys.md#Rollback"
