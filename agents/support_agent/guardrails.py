"""Guardrail callbacks. They run in code, before and after every tool call, whatever the model decides.

Prompts ask the model to behave. Callbacks make sure it does.
"""

from __future__ import annotations

import re
from typing import Any

from google.adk.tools import BaseTool, ToolContext

from . import config

SEVERITIES = {"SEV1", "SEV2", "SEV3"}
_SECRET = re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[:=]\s*\S+")
_COUNTER = "temp:tool_calls"  # temp: state is scoped to the current invocation and never persisted


def before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """Return a dict to skip the tool and hand that dict back to the model as the result."""
    calls = tool_context.state.get(_COUNTER, 0) + 1
    tool_context.state[_COUNTER] = calls
    if calls > config.MAX_TOOL_CALLS_PER_TURN:
        return {"error": "tool call limit reached for this turn; summarize what you have"}

    service = args.get("service")
    if service is not None and service not in config.ALLOWED_SERVICES:
        return {"error": f"service '{service}' is not in the allowlist", "allowed": sorted(config.ALLOWED_SERVICES)}

    if tool.name == "create_incident_ticket":
        sev = str(args.get("severity", "")).upper()
        if sev not in SEVERITIES:
            return {"error": f"severity must be one of {sorted(SEVERITIES)}"}
        args["severity"] = sev  # normalize in place; the tool sees the cleaned value
    return None


def after_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict) -> dict | None:
    """Redact anything that looks like a credential before it reaches the model or the logs."""
    text = str(tool_response)
    if _SECRET.search(text):
        return _redact(tool_response)
    return None


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str):
        return _SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", obj)
    return obj
