"""Offline test harness: a scripted model stands in for Gemini, so routing, tools, guardrails
and approvals are tested deterministically, with no API calls and no flakiness."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncGenerator

import pytest
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# ADK's MCP client otherwise probes Google credentials for mTLS on each connection (slow off-GCP).
os.environ.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT))


class ScriptedLlm(BaseLlm):
    """Replays a list of model turns. Records every request so tests can inspect what the model saw."""

    script: list = []
    requests: list = []

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        if not self.script:
            raise AssertionError("model called more times than scripted")
        yield LlmResponse(content=types.Content(role="model", parts=[self.script.pop(0)]))


def call(name: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def say(text: str) -> types.Part:
    return types.Part(text=text)


class Harness:
    def __init__(self, script: list[types.Part], state: dict | None = None, mcp_db_url: str = ""):
        from support_agent.agent import build_app, build_root_agent

        self.llm = ScriptedLlm(model="scripted", script=list(script), requests=[])
        self.app = build_app(build_root_agent(router_model=self.llm, specialist_model=self.llm,
                                                     mcp_db_url=mcp_db_url))
        self.sessions = InMemorySessionService()
        self.runner = Runner(app=self.app, session_service=self.sessions)
        self.initial_state = state or {"tenant": "default"}
        self.session_id: str | None = None
        self.events: list = []

    async def send(self, message: types.Content | str) -> list:
        if self.session_id is None:
            s = await self.sessions.create_session(app_name=self.app.name, user_id="u1", state=self.initial_state)
            self.session_id = s.id
        if isinstance(message, str):
            message = types.Content(role="user", parts=[types.Part(text=message)])
        out = []
        async for e in self.runner.run_async(user_id="u1", session_id=self.session_id, new_message=message):
            out.append(e)
        self.events += out
        return out

    async def close(self) -> None:
        await self.runner.close()  # closes MCP sessions too

    async def state(self) -> dict:
        s = await self.sessions.get_session(app_name=self.app.name, user_id="u1", session_id=self.session_id)
        return dict(s.state)


def tool_results(events, name: str) -> list[dict]:
    return [p.function_response.response for e in events if e.content for p in e.content.parts
            if p.function_response and p.function_response.name == name]


def calls(events, name: str) -> list:
    return [p.function_call for e in events if e.content for p in e.content.parts
            if p.function_call and p.function_call.name == name]


def authors(events) -> list[str]:
    return [e.author for e in events if e.content and any(p.text for p in e.content.parts)]


@pytest.fixture
def harness():
    return Harness
