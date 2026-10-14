"""Deliberate regressions, switched on with AGENT_REGRESSION=<name>.

Each one is a realistic mistake: a rule dropped while editing a prompt, a lazy tool description, a
deleted guardrail, a model swap. `tools/regress.py` turns each one on and records which test layer
notices. They're read at agent-build time, so a test process or eval run picks them up from its env.
"""

from __future__ import annotations

import os

REGRESSIONS = {
    "drop_grounding_rule": "knowledge prompt loses 'answer only from what the tool returns, cite the source'",
    "soften_grounding_rule": "knowledge prompt keeps its rules but adds 'if the docs are thin, use general knowledge'",
    "drop_scope_rule": "coordinator prompt loses the out-of-scope rule",
    "drop_deploy_check": "ops prompt loses 'if it isn't healthy, also call list_recent_deploys'",
    "vague_tool_docs": "every tool description becomes 'Tool.'",
    "no_service_allowlist": "the service allowlist check is deleted from before_tool",
    "approval_off": "create_incident_ticket no longer requires human confirmation",
    "no_secret_redaction": "the after_tool credential redaction is deleted",
    "router_old_model": "router model swapped to an older, smaller one",
}


def active() -> str:
    name = os.getenv("AGENT_REGRESSION", "").strip()
    if name and name not in REGRESSIONS:
        raise ValueError(f"unknown AGENT_REGRESSION {name!r}; one of {sorted(REGRESSIONS)}")
    return name


def on(name: str) -> bool:
    return active() == name
