"""Ops tools backed by a fake status API (data/status.json).

Swap the _load_* functions for Cloud Monitoring and Cloud Run Admin API calls in a real setup.
The tool signatures, docstrings and return shapes are what matter to the agent, and they stay the same.
"""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path

from google.adk.tools import FunctionTool, ToolContext

STATUS_FILE = Path(__file__).resolve().parents[3] / "data" / "status.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(STATUS_FILE.read_text())


def get_service_status(service: str) -> dict:
    """Get the current health of a service: status, error rate, p95 latency and since when.

    Args:
        service: Service name, for example "orders-api".
    """
    s = _data()["services"].get(service)
    if s is None:
        return {"error": f"unknown service '{service}'", "known": sorted(_data()["services"])}
    return {"service": service, **s}


def list_recent_deploys(service: str, limit: int = 3) -> dict:
    """List the most recent deploys of a service, newest first. Use it to correlate incidents with changes.

    Args:
        service: Service name, for example "orders-api".
        limit: How many deploys to return (1-10).
    """
    limit = max(1, min(int(limit), 10))
    deploys = sorted(
        (d for d in _data()["deploys"] if d["service"] == service), key=lambda d: d["at"], reverse=True
    )
    return {"service": service, "deploys": deploys[:limit]}


def create_incident_ticket(service: str, severity: str, summary: str, tool_context: ToolContext) -> dict:
    """Open an incident ticket. Requires a human to approve before it runs.

    Args:
        service: Affected service.
        severity: One of SEV1, SEV2, SEV3.
        summary: One or two sentences: what's wrong and since when.
    """
    ticket = {"ticket_id": f"INC-{uuid.uuid4().hex[:6].upper()}", "service": service,
              "severity": severity, "summary": summary}
    tool_context.state["last_ticket"] = ticket
    return ticket


# Write actions go through a human. ADK pauses the run and emits an adk_request_confirmation
# call; the client approves or rejects it, and only then does the function execute.
create_incident_ticket_tool = FunctionTool(create_incident_ticket, require_confirmation=True)
