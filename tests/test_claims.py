import pytest

from conftest import call, say, tool_results


def test_model_never_sees_tool_context_or_a_tenant_parameter():
    from google.adk.tools import FunctionTool
    from support_agent.tools.knowledge import search_docs

    decl = FunctionTool(search_docs)._get_declaration()
    params = set(decl.parameters.properties) if decl.parameters else set(decl.parameters_json_schema["properties"])
    assert params == {"question"}


@pytest.mark.asyncio
async def test_tool_budget_resets_every_turn(harness, monkeypatch):
    from support_agent import config

    monkeypatch.setattr(config, "MAX_TOOL_CALLS_PER_TURN", 2)
    status = lambda: call("get_service_status", service="orders-api")
    h = harness([
        call("transfer_to_agent", agent_name="ops_agent"), status(), status(), say("one"),
        status(), status(), say("two"),
    ])
    first = await h.send("check twice")
    second = await h.send("check twice again")
    assert not any("error" in r for r in tool_results(first, "get_service_status"))
    assert not any("error" in r for r in tool_results(second, "get_service_status"))
    assert not any(k.startswith("temp:") for k in await h.state())
