"""The committed evalsets are what `adk eval` runs, so they must match cases.yaml and the gates."""

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_evalsets", ROOT / "evals/build_evalsets.py")
build_evalsets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_evalsets)


def test_committed_evalsets_match_cases_yaml():
    for suite, (es, cfg) in build_evalsets.build().items():
        committed = json.loads((ROOT / f"evals/{suite}/{suite}.evalset.json").read_text())
        fresh = json.loads(json.dumps(es.model_dump(mode="json", by_alias=True, exclude_none=True)))
        assert committed == fresh, f"evals/{suite} is stale: run python evals/build_evalsets.py"
        assert json.loads((ROOT / f"evals/{suite}/test_config.json").read_text()) == cfg


def test_every_suite_has_a_gate_and_unique_ids():
    cases = yaml.safe_load((ROOT / "evals/cases.yaml").read_text())
    gates = yaml.safe_load((ROOT / "evals/gate.yaml").read_text())["min_pass_rate"]
    assert set(cases) == set(gates)
    ids = [c["id"] for suite in cases.values() for c in suite]
    assert len(ids) == len(set(ids))
