"""The layer 2 pipeline, offline: ADK's LocalEvalService runs every evalset case against the real
agent, tools and callbacks, with a scripted "golden" model that plays each case the way a good model
should. If this passes, the evalsets, test configs, runner and real tools agree with each other, so a
failing nightly run means the *model* changed behaviour, not that the harness is broken.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import AsyncGenerator

import pytest
import yaml
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

from conftest import call, say

ROOT = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((ROOT / "evals/cases.yaml").read_text())
OFFLINE_SUITES = ["knowledge", "ops", "ops_triage", "approvals", "refusals"]

_spec = importlib.util.spec_from_file_location("run_evals", ROOT / "evals/run_evals.py")
run_evals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_evals)

OWNER = {"search_docs": "knowledge_agent", "get_service_status": "ops_agent", "list_recent_deploys": "ops_agent",
         "create_incident_ticket": "ops_agent", "run_query": "data_agent"}


def golden_moves(case: dict) -> list[types.Part]:
    """The ideal model turns for a case, derived from its expected tools and reference answer."""
    names = [n for n, _ in case["tools"] if n != "adk_request_confirmation"]
    service = (re.findall(r"\b([a-z]+-(?:api|database))\b", case["ask"]) or ["orders-api"])[0]
    moves = []
    for i, name in enumerate(names):
        if name == "transfer_to_agent":
            nxt = next((n for n in names[i + 1:] if n in OWNER), None)
            moves.append(call("transfer_to_agent", agent_name=OWNER.get(nxt, "ops_agent")))
        elif name == "search_docs":
            moves.append(call("search_docs", question=case["ask"]))
        elif name in ("get_service_status", "list_recent_deploys"):
            moves.append(call(name, service=service))
        elif name == "create_incident_ticket":
            sev = re.search(r"SEV\d", case["reference"]).group(0)
            moves.append(call(name, service=service, severity=sev, summary=case["ask"][:80]))
    return moves + [say(case["reference"])]


class GoldenLlm(BaseLlm):
    """Looks up the case by the user's question and plays its next move. Stateless across cases,
    so LocalEvalService can run cases in parallel."""

    moves: dict = {}

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents
        question = "".join(p.text or "" for p in contents[0].parts)
        script = self.moves[question]
        # Moves already made: this agent's own calls, plus other agents' calls, which ADK passes to a
        # sub-agent as quoted "For context: [coordinator] called tool ..." text rather than model turns.
        own = sum(1 for c in contents if c.role == "model" for p in c.parts if p.function_call)
        quoted = sum((p.text or "").count("] called tool `") for c in contents if c.role == "user" for p in c.parts)
        step = own + quoted
        yield LlmResponse(content=types.Content(role="model", parts=[script[min(step, len(script) - 1)]]))


def golden_agent():
    from support_agent.agent import build_root_agent

    moves = {c["ask"]: golden_moves(c) for s in OFFLINE_SUITES for c in CASES[s]}
    llm = GoldenLlm(model="golden", moves=moves)
    return build_root_agent(router_model=llm, specialist_model=llm, mcp_db_url="")


@pytest.mark.asyncio
@pytest.mark.parametrize("suite", OFFLINE_SUITES)
async def test_golden_model_passes_every_case(suite):
    rows, transcripts = await run_evals.run_suite(suite, runs=1, parallelism=2, root_agent=golden_agent())
    failed = [(r["case"], r["tools"], r["metrics"]) for r in rows if not r["passed"]]
    assert not failed, failed
    assert len(rows) == len(CASES[suite])
    if suite == "approvals":
        assert all(t["paused_for_approval"] for t in transcripts)


@pytest.mark.asyncio
async def test_approval_regression_fails_the_approvals_suite(monkeypatch):
    monkeypatch.setenv("AGENT_REGRESSION", "approval_off")
    rows, _ = await run_evals.run_suite("approvals", runs=1, parallelism=2, root_agent=golden_agent())
    assert not any(r["passed"] for r in rows)  # the write ran with no pause: every case fails


@pytest.mark.asyncio
async def test_allowlist_regression_changes_tool_results(monkeypatch):
    monkeypatch.setenv("AGENT_REGRESSION", "no_service_allowlist")
    _, transcripts = await run_evals.run_suite("ops", runs=1, parallelism=2, root_agent=golden_agent())
    result = next(t for t in transcripts if t["case"] == "not_allowlisted")["tool_results"]
    assert "allowlist" not in str(result)  # the guardrail is gone; the trajectory alone wouldn't show it


def test_summary_applies_gates():
    gate = {"min_pass_rate": {"refusals": 1.0}}
    rows = [{"suite": "refusals", "case": "a", "run": 1, "passed": True, "metrics": {}, "tools": []},
            {"suite": "refusals", "case": "a", "run": 2, "passed": False, "metrics": {}, "tools": ["search_docs"]}]
    text, ok = run_evals.summarize(rows, 2, gate, 1.0, "t")
    assert not ok and "| refusals | 1 | 50% | 100% | 1 | FAIL |" in text
