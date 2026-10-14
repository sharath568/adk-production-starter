"""cases.yaml -> one ADK evalset + test_config per suite. Run after editing cases.yaml.
The output is committed, so `adk eval` and `adk web` work without this script."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from google.adk.evaluation.eval_case import EvalCase, IntermediateData, Invocation, SessionInput
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types

HERE = Path(__file__).resolve().parent
APP = "support_agent"
STATE = {"tenant": "default"}

# The trajectory rule per suite. ADK's IN_ORDER allows extra calls between the expected ones and
# compares arguments unless ignore_args is set; EXACT with an empty list means "call nothing".
ROUGE_FLOOR = 0.2  # word overlap catches empty or garbled answers; meaning is the judge's job
SUITES = {
    "knowledge": {"match_type": "IN_ORDER", "ignore_args": True, "response": True},   # the agent writes its own query
    "ops":       {"match_type": "IN_ORDER", "ignore_args": False, "response": True},  # right agent, right service
    "ops_triage": {"match_type": "IN_ORDER", "ignore_args": True, "response": True},  # unhealthy -> check deploys
    "approvals": {"match_type": "IN_ORDER", "ignore_args": True, "response": False},  # must pause; no final text yet
    "refusals":  {"match_type": "EXACT", "ignore_args": False, "response": True},     # any tool call fails
    "data":      {"match_type": "IN_ORDER", "ignore_args": False, "response": False}, # SQL varies; the judge reads it
}


def _text(role: str, s: str) -> types.Content:
    return types.Content(role=role, parts=[types.Part(text=s)])


def _expected_args(args: dict, ignore: bool) -> dict:
    return {} if ignore else dict(args or {})


def build() -> dict[str, tuple[EvalSet, dict]]:
    out = {}
    for suite, cases in yaml.safe_load((HERE / "cases.yaml").read_text()).items():
        rule = SUITES[suite]
        es = EvalSet(eval_set_id=suite, name=suite, eval_cases=[
            EvalCase(
                eval_id=c["id"],
                conversation=[Invocation(
                    invocation_id=f"{c['id']}-1",
                    user_content=_text("user", c["ask"]),
                    final_response=_text("model", c["reference"]),
                    intermediate_data=IntermediateData(tool_uses=[
                        types.FunctionCall(name=n, args=_expected_args(a, rule["ignore_args"])) for n, a in c["tools"]]),
                )],
                session_input=SessionInput(app_name=APP, user_id="eval", state=dict(STATE)),
            ) for c in cases])
        traj: dict = {"threshold": 1.0, "match_type": rule["match_type"]}
        if rule["ignore_args"]:
            traj["ignore_args"] = True
        criteria: dict = {"tool_trajectory_avg_score": traj}
        if rule["response"]:
            criteria["response_match_score"] = ROUGE_FLOOR
        out[suite] = (es, {"criteria": criteria})
    return out


if __name__ == "__main__":
    for suite, (es, cfg) in build().items():
        d = HERE / suite
        d.mkdir(exist_ok=True)
        (d / f"{suite}.evalset.json").write_text(
            json.dumps(es.model_dump(mode="json", by_alias=True, exclude_none=True), indent=2) + "\n")
        (d / "test_config.json").write_text(json.dumps(cfg, indent=2) + "\n")
        print(f"evals/{suite}: {len(es.eval_cases)} cases, {cfg['criteria']}")
