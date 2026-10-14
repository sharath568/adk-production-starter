"""The judge runner, offline: a fake Gemini client returns canned verdicts."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_judge", ROOT / "judge/run_judge.py")
run_judge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_judge)

IDS = [c["id"] for c in run_judge.RUBRIC["criteria"]]


class FakeClient:
    def __init__(self, fail_case: str):
        self.fail_case, self.prompts = fail_case, []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._gen))

    async def _gen(self, model, contents, config):
        self.prompts.append(contents)
        bad = self.fail_case in contents
        crit = [{"id": i, "verdict": "fail" if bad and i == "grounded" else "pass", "reason": "r"} for i in IDS]
        meta = SimpleNamespace(prompt_token_count=1000, candidates_token_count=100, thoughts_token_count=0)
        return SimpleNamespace(text=json.dumps({"criteria": crit}), usage_metadata=meta)


def _transcript(case, question):
    return {"suite": "knowledge", "case": case, "run": 1, "question": question, "tool_calls": [],
            "tool_results": [], "answer": "a", "reference": "r", "paused_for_approval": False}


def test_judge_scores_reports_and_gates(tmp_path):
    rows = [_transcript(f"c{i}", f"question {i}") for i in range(9)] + [_transcript("bad", "MAKE-ME-FAIL")]
    (tmp_path / "transcripts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    client = FakeClient("MAKE-ME-FAIL")
    code = asyncio.run(run_judge.main([str(tmp_path)], client=client))
    assert code == 0  # 90% >= 85% gate
    md = (tmp_path / "judge.md").read_text()
    assert "pass rate 90%" in md and "knowledge/bad run 1, grounded" in md
    assert all("Tool results are the ground truth" in p for p in client.prompts)
