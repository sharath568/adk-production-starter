"""Contracts the model depends on but no tool test exercises: tool descriptions and prompt rules.

These run in milliseconds. They catch a deleted rule or a lazy docstring. They can't tell whether the
model *follows* a rule; that's what the evals (layer 2) and the judge (layer 3) are for.
"""

import pytest
from google.adk.tools import FunctionTool

from support_agent.agent import build_root_agent

# Clauses whose removal changed behaviour in evals. Edit a rule? Update it here on purpose.
REQUIRED = {
    "coordinator": ["Out of scope:", "don't transfer"],
    "knowledge_agent": ["Answer only from what the tool returns", "Cite the source", "couldn't find it in the docs"],
    "ops_agent": ["call get_service_status", "also call\n  list_recent_deploys", "Only open a ticket when the user asks",
                  "SEV1 if customers can't place orders"],
}


def _agents():
    root = build_root_agent(router_model="scripted", specialist_model="scripted", mcp_db_url="")
    return {root.name: root, **{a.name: a for a in root.sub_agents}}


@pytest.mark.parametrize("agent,clauses", REQUIRED.items())
def test_prompt_keeps_required_rules(agent, clauses):
    instruction = _agents()[agent].instruction
    missing = [c for c in clauses if c not in instruction]
    assert not missing, f"{agent} instruction lost: {missing}"


def test_every_tool_has_a_useful_description():
    for agent in _agents().values():
        for tool in agent.tools:
            t = tool if isinstance(tool, FunctionTool) else FunctionTool(tool)
            decl = t._get_declaration()  # what the model actually sees
            assert len(decl.description or "") >= 40, f"{agent.name}.{decl.name}: description too thin"
            params = [p for p in (decl.parameters.properties or {}) if p != "tool_context"] if decl.parameters else []
            for p in params:
                assert p in decl.description, f"{agent.name}.{decl.name}: argument '{p}' isn't documented"


def test_writes_require_approval():
    ops = _agents()["ops_agent"]
    ticket = next(t for t in ops.tools if getattr(t, "name", "") == "create_incident_ticket")
    assert ticket._require_confirmation is True
