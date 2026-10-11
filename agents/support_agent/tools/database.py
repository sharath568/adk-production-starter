"""Database tools over MCP: the data_agent reads business data through gemini-mcp-db-server.

The agent never holds a database credential. It talks MCP (Streamable HTTP) to a private Cloud Run
service that owns the policy: SQL guard, read-only transaction, statement timeout, row cap, and a
Postgres role with SELECT on a few views only. This side adds three things:

- Identity: a Google ID token for the MCP service (the agent's service account has run.invoker).
- Attribution: the ADK session and invocation ids go in headers, so the server's audit log can be
  joined with this agent's logs.
- Least exposure: tool_filter hands the model only the tools it needs.

Server: https://github.com/sharath568/gemini-mcp-db-server
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlparse

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from .. import config

_tokens: dict[str, tuple[str, float]] = {}  # audience -> (token, expires_at)
# First keyword of the statement, after leading comments and parentheses.
_LEAD = re.compile(r"^(?:\s|--[^\n]*\n|/\*.*?\*/|\()*(\w+)", re.S)


def _is_local(url: str) -> bool:
    return urlparse(url).hostname in {"127.0.0.1", "localhost", "::1"}


def _audience(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _id_token(audience: str) -> str:
    """Google-signed ID token for a Cloud Run service. Cached; they're valid for an hour."""
    token, expires = _tokens.get(audience, ("", 0.0))
    if token and time.time() < expires:
        return token
    import google.auth.transport.requests
    import google.oauth2.id_token

    token = google.oauth2.id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    _tokens[audience] = (token, time.time() + 45 * 60)
    return token


def header_provider(url: str):
    """Headers for every MCP request: who is calling (ID token) and which agent session (audit)."""

    def headers(ctx: ReadonlyContext) -> dict[str, str]:
        h = {"x-agent-session-id": ctx.session.id, "x-agent-invocation-id": ctx.invocation_id}
        if not _is_local(url):
            h["authorization"] = f"Bearer {_id_token(_audience(url))}"
        return h

    return headers


def build_db_toolset(url: str) -> McpToolset:
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=url, timeout=30),
        # The server also offers explain_query. Left out: a shorter tool list means fewer wrong calls.
        tool_filter=list(config.DB_TOOLS),
        header_provider=header_provider(url),
    )


def precheck_sql(sql: str) -> str | None:
    """Cheap agent-side check, run before the request leaves the process. Returns an error or None.

    This is not the control. The server's parser, read-only transaction and database role are.
    It just saves a round trip for the obvious cases and gives the model a fast, clear error.
    """
    m = _LEAD.match(sql or "")
    if not m or m.group(1).lower() not in {"select", "with"}:
        return "only a single read-only SELECT is allowed; the database cannot be changed from here"
    if ";" in sql.strip().rstrip(";"):
        return "send one statement at a time (no ';' inside the query)"
    return None


def mcp_payload(tool_response: Any) -> dict | None:
    """The server's JSON result from an MCP tool response. ADK passes it on as a text content block."""
    if not isinstance(tool_response, dict):
        return None
    if isinstance(tool_response.get("structuredContent"), dict):
        return tool_response["structuredContent"]
    for block in tool_response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                body = json.loads(block["text"])
            except (KeyError, ValueError):
                return None
            return body if isinstance(body, dict) else None
    return None


def is_error(tool_response: Any) -> bool:
    """True for local tool errors ({"error": ...}) and MCP results the server marked ok=false."""
    if not isinstance(tool_response, dict):
        return False
    if "error" in tool_response or tool_response.get("isError"):
        return True
    payload = mcp_payload(tool_response)
    return payload is not None and payload.get("ok") is False
