import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR        = Path(__file__).parent
SCENARIO_PROMPT = BASE_DIR / "preprocessing/output/scenario_prompt.txt"
VERDICT_PATH    = BASE_DIR / "layer_3/output/verdict.json"
CRITIQUE_PATH   = BASE_DIR / "layer_5/output/critique.json"
ACTION_SCHED    = BASE_DIR / "layer_1/output/action_schedule.json"
CAUSAL_GRAPH    = BASE_DIR / "layer_4/output/causal_graph.json"
TRACE_PATH      = BASE_DIR / "layer_2/output/simulation_trace.json"
FINAL_OUT       = BASE_DIR / "layer_5/output/final_result.json"
ITER_DIR        = BASE_DIR / "iterations"

N_MAX = 3


def run_layer(script: Path):
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script.name} exited with code {result.returncode}")


def append_feedback(base_prompt: str, critique: dict) -> str:
    lines = [base_prompt, "\n\n=== FEEDBACK FROM PREVIOUS ATTEMPT ==="]
    lines.append(critique["summary"])
    for item in critique.get("critique_items", []):
        v = item["violation"]
        lines.append(f"\nViolation: {v['event']} on {v['model']} at t={v['timestamp']}")
        for step in item["causal_chain"]:
            lines.append(f"  {step}")
        lines.append(f"Correction: {item['correction']}")
    lines.append("=== END FEEDBACK ===\n")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-existing-schedule", action="store_true",
                        help="Skip policy_generator.py in iteration 1 and use existing action_schedule.json")
    args = parser.parse_args()

    original_prompt = SCENARIO_PROMPT.read_text()
    best_policy     = None
    best_violations = None
    current_prompt  = original_prompt

    try:
        for iteration in range(N_MAX):
            print(f"\n{'='*50}")
            print(f"Iteration {iteration + 1}/{N_MAX}")
            print(f"{'='*50}")

            SCENARIO_PROMPT.write_text(current_prompt)

            if args.use_existing_schedule and iteration == 0:
                print("Iteration 1: using existing action_schedule.json (skipping policy_generator.py)")
            else:
                run_layer(BASE_DIR / "layer_1/policy_generator.py")
            run_layer(BASE_DIR / "layer_2/simulate.py")
            run_layer(BASE_DIR / "layer_3/checker.py")

            verdict    = json.loads(VERDICT_PATH.read_text())
            violations = verdict["violations"]

            if best_violations is None or len(violations) < len(best_violations):
                best_violations = violations
                best_policy     = json.loads(ACTION_SCHED.read_text())

            snap = ITER_DIR / f"iter_{iteration + 1}"
            snap.mkdir(parents=True, exist_ok=True)
            (snap / "action_schedule.json").write_text(ACTION_SCHED.read_text())
            (snap / "verdict.json").write_text(VERDICT_PATH.read_text())

            if verdict["verdict"] == "valid":
                print(f"\nPolicy valid after {iteration + 1} iteration(s).")
                FINAL_OUT.write_text(json.dumps({
                    "verdict":    "valid",
                    "iterations": iteration + 1,
                    "policy":     best_policy,
                }, indent=2))
                return

            run_layer(BASE_DIR / "layer_4/extractor.py")
            run_layer(BASE_DIR / "layer_5/feedback.py")
            (snap / "causal_graph.json").write_text(CAUSAL_GRAPH.read_text())
            (snap / "critique.json").write_text(CRITIQUE_PATH.read_text())

            critique       = json.loads(CRITIQUE_PATH.read_text())
            current_prompt = append_feedback(original_prompt, critique)

            if iteration < N_MAX - 1:
                print("Waiting 60s before next iteration...")
                time.sleep(120)

        print(f"\nN_MAX={N_MAX} reached without valid policy.")
        print(f"Best policy had {len(best_violations)} violation(s). Flagged as UnresolvedViolation.")

        ACTION_SCHED.write_text(json.dumps(best_policy, indent=2))
        FINAL_OUT.write_text(json.dumps({
            "verdict":    "UnresolvedViolation",
            "iterations": N_MAX,
            "policy":     best_policy,
            "violations": best_violations,
        }, indent=2))

    finally:
        SCENARIO_PROMPT.write_text(original_prompt)


if __name__ == "__main__":
    main()
