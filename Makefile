.PHONY: test web api eval judge regress regress-l1 evalsets labels calibrate eval-cli
RUNS ?= 3

test:       ; pytest -q                                   # layer 1: offline, scripted model
web:        ; adk web agents                              # ADK dev UI at http://localhost:8000
api:        ; ADK_WEB=false python server.py

evalsets:   ; python evals/build_evalsets.py              # after editing evals/cases.yaml
eval:       ; python evals/run_evals.py --runs $(RUNS)    # layer 2: Gemini, gates in evals/gate.yaml
judge:      ; python judge/run_judge.py                   # layer 3: judge the latest layer 2 run
regress:    ; python tools/regress.py --runs 2            # 9 regressions x 3 layers
regress-l1: ; python tools/regress.py --skip-evals        # layer 1 column only, offline
labels:     ; python tools/calibrate_judge.py export --n 30
calibrate:  ; python tools/calibrate_judge.py score labels/to_label.csv

# The stock ADK CLI on one suite, for comparison with the runner
eval-cli:
	adk eval agents/support_agent evals/ops/ops.evalset.json --config_file_path evals/ops/test_config.json
