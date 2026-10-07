"""A small multi-agent support assistant, built the way you'd want to run it in production.

    coordinator (cheap model, no tools: it only routes)
      ├── knowledge_agent  (docs and runbooks, read-only)
      └── ops_agent        (live status + deploys; write actions need human approval)

Why split it up at all? Each specialist gets a short instruction and only the tools it needs.
Smaller tool lists mean fewer wrong tool calls, and you can test, swap and price each agent
separately. The coordinator stays cheap because routing doesn't need a big model.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from google.adk.models import BaseLlm

from . import config
from .guardrails import after_tool, before_tool
from .observability import after_model, after_tool_log, before_model
from .tools.knowledge import search_docs
from .tools.ops import create_incident_ticket_tool, get_service_status, list_recent_deploys

KNOWLEDGE_INSTRUCTION = """You answer questions using the search_docs tool. Always call it before answering.
- Answer only from what the tool returns. Cite the source, e.g. (deploys.md#Rollback).
- If grounded is false or nothing relevant comes back, say you couldn't find it in the docs.
- Keep it short: steps as a numbered list, commands in backticks.
- If the user needs live status or wants an action taken, transfer to ops_agent."""

OPS_INSTRUCTION = """You help with live operations.
- For "is X down / slow / ok", call get_service_status. If it isn't healthy, also call
  list_recent_deploys and point out any deploy shortly before the problem started.
- Only open a ticket when the user asks for one. Pick SEV1 if customers can't place orders,
  SEV2 for degraded with a workaround, SEV3 otherwise. A human approves tickets before they're created.
- Report numbers exactly as the tools return them. Never invent a status.
- For how-to or policy questions, transfer to knowledge_agent."""

COORDINATOR_INSTRUCTION = """You are the front door of an internal engineering support assistant.
Route every request to exactly one specialist:
- knowledge_agent: how do I / what is our policy / what does this error mean.
- ops_agent: is something down or slow, what changed, open an incident.
If the request is unclear, ask one short clarifying question. Don't answer questions yourself."""

# Applied to every agent that has tools.
TOOL_CALLBACKS = dict(
    before_model_callback=before_model,
    after_model_callback=after_model,
    before_tool_callback=before_tool,
    # Order matters: the first callback that returns a value wins. Log first, then redact.
    after_tool_callback=[after_tool_log, after_tool],
)


def build_root_agent(
    router_model: str | BaseLlm = config.ROUTER_MODEL,
    specialist_model: str | BaseLlm = config.SPECIALIST_MODEL,
) -> LlmAgent:
    """Factory, so tests can inject a scripted model and each environment can pick its models."""
    knowledge_agent = LlmAgent(
        name="knowledge_agent",
        model=specialist_model,
        description="Answers how-to and policy questions from internal runbooks: backups, "
        "restores, deploys, rollbacks, incident process, error codes, credentials.",
        instruction=KNOWLEDGE_INSTRUCTION,
        tools=[search_docs],
        **TOOL_CALLBACKS,
    )
    ops_agent = LlmAgent(
        name="ops_agent",
        model=specialist_model,
        description="Checks live service health and recent deploys, and opens incident tickets.",
        instruction=OPS_INSTRUCTION,
        tools=[get_service_status, list_recent_deploys, create_incident_ticket_tool],
        **TOOL_CALLBACKS,
    )
    return LlmAgent(
        name="coordinator",
        model=router_model,
        description="Routes support requests to the right specialist.",
        instruction=COORDINATOR_INSTRUCTION,
        sub_agents=[knowledge_agent, ops_agent],
        before_model_callback=before_model,
        after_model_callback=after_model,
    )


def build_app(root: LlmAgent | None = None) -> App:
    # Context caching matters for multi-agent setups: every transfer swaps the system instruction
    # and tool list, so without a cache the whole prompt prefix is re-sent at full price each hop.
    return App(
        name="support_agent",
        root_agent=root or build_root_agent(),
        context_cache_config=ContextCacheConfig(),
    )


root_agent = build_root_agent()
app = build_app(root_agent)
