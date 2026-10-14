"""Layer 3: score layer 2 transcripts against judge/rubric.yaml with a pinned judge model.

    python judge/run_judge.py                    # the latest runs/*/transcripts.jsonl
    python judge/run_judge.py runs/<dir>         # a specific run
    python judge/run_judge.py --model gemini-3.5-flash-lite --out judge-lite   # compare judges

Each criterion gets pass / fail / na with a one-line reason; a transcript passes if nothing fails.
Writes <out>.jsonl and <out>.md next to the transcripts. Exit 1 if the pass rate is under
judge_min_pass_rate in evals/gate.yaml, or the cost cap is hit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
os.environ.setdefault("EVAL_COST_CAP_USD", "0.50")

from support_agent import usage  # noqa: E402

RUBRIC = yaml.safe_load((ROOT / "judge/rubric.yaml").read_text())
PROMPT_VERSION = f"rubric-v{RUBRIC['version']}"

SCHEMA = {
    "type": "object",
    "properties": {"criteria": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "verdict": {"type": "string", "enum": ["pass", "fail", "na"]},
                       "reason": {"type": "string"}},
        "required": ["id", "verdict", "reason"]}}},
    "required": ["criteria"],
}


def judge_prompt(t: dict) -> str:
    crit = "\n".join(f"- {c['id']}: {c['check']}" for c in RUBRIC["criteria"])
    steps = json.dumps([{"call": c, "result": r} for c, r in
                        zip(t["tool_calls"], t["tool_results"] + [None] * len(t["tool_calls"]))], default=str)
    return f"""You grade one reply from an internal engineering support assistant (runbooks, service health,
deploys, incidents). Judge only what is in front of you. Tool results are the ground truth; the
reference answer was written by the test author as a hint and may be worded differently or be less complete.

User message: {t['question']}
Tool calls and results, in order (transfer_to_agent is routing between the assistant's own specialists):
{steps}
Paused for human approval: {t.get('paused_for_approval', False)}
Assistant's answer: {t['answer'] or '(no answer yet: the run is paused)'}
Reference answer (hint only): {t['reference']}

Grade each criterion as pass, fail or na, with one short sentence of reason:
{crit}"""


async def grade(client, t: dict, sem: asyncio.Semaphore) -> dict:
    from google.genai import errors, types

    async with sem:
        for attempt in range(5):
            try:  # with a timeout: in the companion repo one judge request once hung for 15 minutes
                r = await asyncio.wait_for(client.aio.models.generate_content(
                    model=RUBRIC["judge_model"], contents=judge_prompt(t),
                    config=types.GenerateContentConfig(
                        temperature=RUBRIC["temperature"],
                        thinking_config=types.ThinkingConfig(thinking_level=RUBRIC.get("thinking_level", "low").upper()),
                        response_mime_type="application/json", response_json_schema=SCHEMA)), timeout=90)
                break
            except errors.APIError as e:
                if e.code not in (429, 500, 503) or attempt == 4:
                    raise
                await asyncio.sleep(5 * (attempt + 1))
            except asyncio.TimeoutError:
                if attempt == 4:
                    raise
    usage.record(r.usage_metadata, model=RUBRIC["judge_model"])
    verdicts = {c["id"]: c for c in json.loads(r.text)["criteria"]}
    missing = [c["id"] for c in RUBRIC["criteria"] if c["id"] not in verdicts]
    return {"suite": t["suite"], "case": t["case"], "run": t["run"], "prompt_version": PROMPT_VERSION,
            "judge_model": RUBRIC["judge_model"], "criteria": verdicts, "missing": missing,
            "passed": not missing and all(v["verdict"] != "fail" for v in verdicts.values())}


def report(results: list[dict], run_dir: Path, gate: float) -> tuple[str, bool]:
    rate = sum(r["passed"] for r in results) / len(results)
    by_suite: dict[str, list[bool]] = defaultdict(list)
    fails: Counter = Counter()
    for r in results:
        by_suite[r["suite"]].append(r["passed"])
        fails.update(k for k, v in r["criteria"].items() if v["verdict"] == "fail")
    lines = [f"# Layer 3: judge ({PROMPT_VERSION}, `{RUBRIC['judge_model']}`)", "",
             f"{run_dir.name}: {len(results)} transcripts, pass rate {rate:.0%} (gate {gate:.0%}), "
             f"judge cost ${usage.TALLY.usd():.4f}", "", "| suite | pass rate |", "|---|---|"]
    lines += [f"| {s} | {sum(v) / len(v):.0%} |" for s, v in by_suite.items()]
    lines += ["", "| criterion | fails |", "|---|---|"]
    lines += [f"| {c['id']} | {fails.get(c['id'], 0)} |" for c in RUBRIC["criteria"]]
    lines += ["", "Failures:", ""]
    for r in results:
        for k, v in r["criteria"].items():
            if v["verdict"] == "fail":
                lines.append(f"- {r['suite']}/{r['case']} run {r['run']}, {k}: {v['reason']}")
    return "\n".join(lines) + "\n", rate >= gate


async def main(argv: list[str] | None = None, client=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--model", help="override the rubric's judge model (for judge comparisons)")
    ap.add_argument("--out", default="judge", help="output name: <out>.jsonl and <out>.md")
    a = ap.parse_args(argv)
    if a.model:
        RUBRIC["judge_model"] = a.model
    run_dir = Path(a.run_dir) if a.run_dir else max((ROOT / "runs").glob("*/transcripts.jsonl")).parent
    transcripts = [json.loads(line) for line in (run_dir / "transcripts.jsonl").read_text().splitlines()]
    gate = yaml.safe_load((ROOT / "evals/gate.yaml").read_text())["judge_min_pass_rate"]

    if client is None:
        from google import genai
        client = genai.Client()
    sem = asyncio.Semaphore(a.concurrency)
    try:
        results = await asyncio.gather(*(grade(client, t, sem) for t in transcripts))
    except usage.BudgetExceeded as e:
        print(f"STOPPED: {e}")
        return 1
    with (run_dir / f"{a.out}.jsonl").open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    text, ok = report(results, run_dir, gate)
    (run_dir / f"{a.out}.md").write_text(text)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
