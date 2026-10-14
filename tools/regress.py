"""Break the agent on purpose and record which layer notices.

    python tools/regress.py --runs 2                           # every regression in regressions.py
    python tools/regress.py --only drop_scope_rule --runs 1
    python tools/regress.py --skip-evals                       # layer 1 only: offline, free, ~1 min

For each regression: layer 1 (pytest), layer 2 (run_evals.py against its gates), layer 3 (the judge
against its gate). A layer "catches" a regression when its gate fails. Results are saved per
regression in runs/regressions/, so an interrupted run resumes; the table goes to runs/regressions.md.
Each layer runs in its own process with AGENT_REGRESSION set, so the cost cap applies per layer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from support_agent.regressions import REGRESSIONS  # noqa: E402

PY = sys.executable
SUITES = ["knowledge", "ops", "ops_triage", "approvals", "refusals"]


def run(cmd: list[str], regression: str) -> tuple[int, str]:
    env = {**os.environ, "AGENT_REGRESSION": regression, "PYTHONWARNINGS": "ignore"}
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--skip-evals", action="store_true", help="layer 1 only")
    ap.add_argument("--skip-judge", action="store_true")
    ap.add_argument("--redo", action="store_true", help="rerun regressions that already have a result")
    a = ap.parse_args()
    names = a.only.split(",") if a.only else list(REGRESSIONS)
    saved = ROOT / "runs/regressions"
    saved.mkdir(parents=True, exist_ok=True)

    for name in names:
        f = saved / f"{name}.json"
        prev = json.loads(f.read_text()) if f.exists() else {}
        if prev and not a.redo and (a.skip_evals or prev.get("l2") is not None):
            print(f"{name}: already done, skipping (--redo to rerun)")
            continue
        t0 = time.perf_counter()
        l1, out1 = run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], name)
        res = {"name": name, "l1": l1 != 0,
               "l1_detail": (re.findall(r"(\d+ failed)", out1) or ["all passed"])[0],
               "l2": None, "rates": {}, "l3": None, "l3_rate": "-", "run_dir": None}
        if not a.skip_evals:
            l2, out2 = run([PY, "evals/run_evals.py", "--runs", str(a.runs), "--label", f"reg-{name}"], name)
            m = re.search(r"written to (runs/\S+)", out2)
            res.update(l2=l2 != 0, run_dir=m.group(1) if m else None,
                       rates=dict(re.findall(r"^\| (\w+) \| \d+ \| (\d+%)", out2, re.M)))
            if m and not a.skip_judge:
                l3, out3 = run([PY, "judge/run_judge.py", m.group(1)], name)
                res.update(l3=l3 != 0, l3_rate=(re.findall(r"pass rate (\d+%)", out3) or ["?"])[0])
        res["seconds"] = round(time.perf_counter() - t0)
        f.write_text(json.dumps(res))
        print(f"{name}: L1 {'caught' if res['l1'] else 'missed'} ({res['l1_detail']}), "
              f"L2 {'-' if res['l2'] is None else 'caught' if res['l2'] else 'missed'} {res['rates']}, "
              f"L3 {'-' if res['l3'] is None else 'caught' if res['l3'] else 'missed'} {res['l3_rate']}", flush=True)

    rows = [json.loads((saved / f"{n}.json").read_text()) for n in REGRESSIONS if (saved / f"{n}.json").exists()]
    mark = lambda caught: "-" if caught is None else ("**caught**" if caught else "missed")  # noqa: E731
    lines = ["# Injected regressions: which layer caught what", "",
             f"{a.runs} run(s) per eval case. A layer catches a regression when its gate fails.", "",
             f"| regression | what changed | L1 fake LLM | L2 adk eval ({' / '.join(SUITES)}) | L3 judge |",
             "|---|---|---|---|---|"]
    for r in rows:
        r2 = " / ".join(r["rates"].get(s, "-") for s in SUITES)
        l2 = "-" if r["l2"] is None else f"{mark(r['l2'])} ({r2})"
        l3 = "-" if r["l3"] is None else f"{mark(r['l3'])} ({r['l3_rate']})"
        lines.append(f"| `{r['name']}` | {REGRESSIONS[r['name']]} | {mark(r['l1'])} ({r['l1_detail']}) | {l2} | {l3} |")
    caught_any = sum(bool(r["l1"] or r["l2"] or r["l3"]) for r in rows)
    lines += ["", f"Caught by at least one layer: {caught_any}/{len(rows)}."]
    (ROOT / "runs/regressions.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
