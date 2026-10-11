"""One structured log line per model call and per tool call.

Cloud Logging parses JSON on stdout into jsonPayload, so these become queryable fields:
which agent, which model, latency, tokens, which tool, whether a guardrail blocked it.
Cloud Trace via OpenTelemetry comes in a later version of this repo.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool, ToolContext

from .tools.database import is_error

log = logging.getLogger("agent")
if not log.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False

_T0 = "temp:model_t0"


def _emit(**fields: Any) -> None:
    log.info(json.dumps(fields, default=str))


def before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    callback_context.state[_T0] = time.perf_counter()
    return None


def after_model(callback_context: CallbackContext, llm_response: LlmResponse) -> None:
    t0 = callback_context.state.get(_T0)
    usage = llm_response.usage_metadata
    parts = llm_response.content.parts if llm_response.content else []
    _emit(
        event="model_call",
        agent=callback_context.agent_name,
        invocation_id=callback_context.invocation_id,
        latency_ms=round((time.perf_counter() - t0) * 1000) if t0 else None,
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        cached_tokens=getattr(usage, "cached_content_token_count", None),
        function_calls=[p.function_call.name for p in parts if p.function_call],
    )
    return None


def after_tool_log(tool: BaseTool, args: dict, tool_context: ToolContext, tool_response: dict) -> None:
    _emit(
        event="tool_call",
        agent=tool_context.agent_name,
        tool=tool.name,
        arg_keys=sorted(args),  # keys only: argument values can contain user data
        session_id=tool_context.session.id,  # joins with the MCP server's audit log
        blocked=is_error(tool_response),
    )
    return None
