"""Measure the judge against a human before trusting it.

    python tools/calibrate_judge.py export [runs/<dir> ...] --n 30   # writes labels/to_label.csv
    # open the CSV, put pass or fail in human_verdict for every row (judge verdicts are not in the file)
    python tools/calibrate_judge.py score labels/to_label.csv         # agreement + Cohen's kappa

Ported from the companion adk-eval-harness repo. Export samples transcripts that already have a judge verdict, mixing passes and fails, from one or
more runs (regression runs make good material: they contain real failures).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["key", "suite", "case", "question", "tools", "answer", "human_verdict", "notes"]


def _load(run_dir: Path) -> list[tuple[dict, dict]]:
    tr = {f"{run_dir.name}|{t['suite']}|{t['case']}|{t['run']}": t
          for t in map(json.loads, (run_dir / "transcripts.jsonl").read_text().splitlines())}
    jd = {f"{run_dir.name}|{j['suite']}|{j['case']}|{j['run']}": j
          for j in map(json.loads, (run_dir / "judge.jsonl").read_text().splitlines())}
    return [(k, tr[k], jd[k]) for k in tr if k in jd]


def export(run_dirs: list[Path], n: int, seed: int) -> None:
    rows = [x for d in run_dirs for x in _load(d)]
    rng = random.Random(seed)
    fails = [r for r in rows if not r[2]["passed"]]
    passes = [r for r in rows if r[2]["passed"]]
    k = min(len(fails), n // 2)  # oversample failures: a judge that says "pass" to everything is 90% accurate
    pick = rng.sample(fails, k) + rng.sample(passes, min(len(passes), n - k))
    rng.shuffle(pick)
    out = ROOT / "labels/to_label.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for key, t, _ in pick:
            tools = "; ".join(f"{c['name']}({json.dumps(c['args'])}) -> {json.dumps(r['response'], default=str)[:300]}"
                              for c, r in zip(t["tool_calls"], t["tool_results"]))
            w.writerow({"key": key, "suite": t["suite"], "case": t["case"], "question": t["question"],
                        "tools": tools, "answer": t["answer"], "human_verdict": "", "notes": ""})
    print(f"wrote {len(pick)} rows to {out.relative_to(ROOT)} ({k} judged fail, {len(pick) - k} judged pass)")


def kappa(pairs: list[tuple[bool, bool]]) -> float:
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def score(path: Path) -> None:
    labelled = [r for r in csv.DictReader(path.open()) if r["human_verdict"].strip().lower() in ("pass", "fail")]
    if not labelled:
        raise SystemExit(f"no rows with human_verdict pass/fail in {path}")
    judged: dict[str, dict] = {}
    for d in {r["key"].split("|")[0] for r in labelled}:
        judged.update({k: j for k, _, j in _load(ROOT / "runs" / d)})
    pairs = [(r["human_verdict"].strip().lower() == "pass", judged[r["key"]]["passed"]) for r in labelled]
    agree = sum(h == j for h, j in pairs) / len(pairs)
    print(f"{len(pairs)} labelled answers: agreement {agree:.0%}, Cohen's kappa {kappa(pairs):.2f}")
    print(f"  human pass / judge fail: {sum(h and not j for h, j in pairs)}  (judge too strict)")
    print(f"  human fail / judge pass: {sum(j and not h for h, j in pairs)}  (judge too lenient: the dangerous one)")
    for r, (h, j) in zip(labelled, pairs):
        if h != j:
            reasons = {k: v["reason"] for k, v in judged[r["key"]]["criteria"].items() if v["verdict"] == "fail"}
            print(f"  - {r['key']}: human {'pass' if h else 'fail'}, judge {'pass' if j else 'fail'} {reasons or ''}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("run_dirs", nargs="*")
    e.add_argument("--n", type=int, default=30)
    e.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("score")
    s.add_argument("csv")
    a = ap.parse_args()
    if a.cmd == "export":
        dirs = [Path(d) for d in a.run_dirs] or [p.parent for p in sorted((ROOT / "runs").glob("*/judge.jsonl"))]
        export(dirs, a.n, a.seed)
    else:
        score(Path(a.csv))
