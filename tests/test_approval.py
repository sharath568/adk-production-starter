import pytest
from google.genai import types

from conftest import call, calls, say, tool_results


def approval(fc, confirmed: bool) -> types.Content:
    return types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=fc.id, name="adk_request_confirmation", response={"confirmed": confirmed}))])


@pytest.mark.asyncio
async def test_ticket_waits_for_human_approval_then_runs(harness):
    h = harness([
        call("transfer_to_agent", agent_name="ops_agent"),
        call("create_incident_ticket", service="orders-api", severity="sev2", summary="5xx since 14:05"),
        say("Ticket created."),
    ])
    events = await h.send("open a SEV2 for orders-api")

    request = calls(events, "adk_request_confirmation")
    assert request, "ADK should pause and ask for confirmation"
    assert "last_ticket" not in await h.state()  # nothing happened yet

    events = await h.send(approval(request[0], confirmed=True))
    ticket = tool_results(events, "create_incident_ticket")[-1]
    assert ticket["ticket_id"].startswith("INC-") and ticket["severity"] == "SEV2"
    assert (await h.state())["last_ticket"]["ticket_id"] == ticket["ticket_id"]


@pytest.mark.asyncio
async def test_rejected_ticket_is_never_created(harness):
    h = harness([
        call("transfer_to_agent", agent_name="ops_agent"),
        call("create_incident_ticket", service="orders-api", severity="SEV3", summary="minor"),
        say("OK, I won't open it."),
    ])
    events = await h.send("open a ticket")
    request = calls(events, "adk_request_confirmation")[0]
    await h.send(approval(request, confirmed=False))
    assert "last_ticket" not in await h.state()
