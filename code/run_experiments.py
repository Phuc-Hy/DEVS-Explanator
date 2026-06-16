import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR     = Path(__file__).parent
FINAL_OUT    = BASE_DIR / "layer_5/output/final_result.json"
RESULTS_DIR  = BASE_DIR / "experiments/runs"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

N_RUNS        = 100
SLEEP_BETWEEN = 10


def run_once():
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "run_pipeline.py")],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout


def classify(final):
    verdict    = final["verdict"]
    iterations = final["iterations"]
    if verdict == "valid" and iterations == 1:
        return "no_hallucination"
    if verdict == "valid" and iterations > 1:
        return "correctable_hallucination"
    return "persistent_hallucination"


def main():
    existing = sorted(RESULTS_DIR.glob("run_*.json"))
    start_id = len(existing) + 1
    print(f"Found {len(existing)} existing runs. Starting from run {start_id}.")

    counts = {
        "no_hallucination":          0,
        "correctable_hallucination": 0,
        "persistent_hallucination":  0,
    }
    iter_dist  = {1: 0, 2: 0, 3: 0}
    all_results = []
    errors      = []

    for run_id in range(start_id, N_RUNS + 1):
        print(f"Run {run_id:3d}/{N_RUNS} ... ", end="", flush=True)

        returncode, stdout = run_once()

        if returncode != 0:
            print("ERROR")
            errors.append(run_id)
            continue

        final  = json.loads(FINAL_OUT.read_text())
        label  = classify(final)
        counts[label] += 1

        verdict    = final["verdict"]
        iterations = final["iterations"]
        if verdict == "valid":
            iter_dist[iterations] = iter_dist.get(iterations, 0) + 1

        iter1_schedule_path = BASE_DIR / "iterations/iter_1/action_schedule.json"
        iter1_schedule = json.loads(iter1_schedule_path.read_text()) if iter1_schedule_path.exists() else None

        run_result = {
            "run_id":              run_id,
            "verdict":             verdict,
            "iterations":          iterations,
            "label":               label,
            "policy":              final["policy"],
            "iter1_action_schedule": iter1_schedule,
        }
        if verdict == "UnresolvedViolation":
            run_result["violations"] = final.get("violations", [])

        (RESULTS_DIR / f"run_{run_id:03d}.json").write_text(
            json.dumps(run_result, indent=2)
        )
        all_results.append(run_result)
        policy = final["policy"]
        parts = []
        for a in policy:
            atype  = a.get("type", "dg_shed")
            target = a.get("gen_uid", f"bus{a.get('bus', '?')}")
            mw     = a.get("target_MW", a.get("shed_MW", "?"))
            parts.append(f"{atype}:{target}->{mw}MW")
        policy_str = ", ".join(parts) if parts else "empty"
        print(f"{label}  (iter={iterations})  [{policy_str}]")

        if run_id < N_RUNS:
            time.sleep(SLEEP_BETWEEN)

    total_done = len(all_results)
    hallucination_total = (
        counts["correctable_hallucination"] + counts["persistent_hallucination"]
    )

    summary = {
        "timestamp":   datetime.now().isoformat(),
        "n_runs":      N_RUNS,
        "completed":   total_done,
        "errors":      errors,
        "counts": counts,
        "hallucination_total": hallucination_total,
        "hallucination_rate":  round(hallucination_total / total_done, 4) if total_done else 0,
        "persistent_rate":     round(counts["persistent_hallucination"] / total_done, 4) if total_done else 0,
        "iter_distribution":   iter_dist,
        "all_results":         all_results,
    }

    summary_path = BASE_DIR / "experiments/summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*55}")
    print(f"EXPERIMENT COMPLETE  ({total_done} runs)")
    print(f"{'='*55}")
    print(f"  No hallucination      : {counts['no_hallucination']:4d}  ({counts['no_hallucination']/total_done*100:.1f}%)")
    print(f"  Correctable halluc.   : {counts['correctable_hallucination']:4d}  ({counts['correctable_hallucination']/total_done*100:.1f}%)")
    print(f"  Persistent halluc.    : {counts['persistent_hallucination']:4d}  ({counts['persistent_hallucination']/total_done*100:.1f}%)")
    print(f"  ─────────────────────────────────────────")
    print(f"  Hallucination rate    : {hallucination_total/total_done*100:.1f}%")
    print(f"  Persistent rate       : {counts['persistent_hallucination']/total_done*100:.1f}%")
    print(f"\n  Iteration distribution (valid runs):")
    for k, v in sorted(iter_dist.items()):
        print(f"    iter {k}: {v} run(s)")
    if errors:
        print(f"\n  Failed runs: {errors}")
    print(f"\n  Summary -> experiments/summary.json")
    print(f"  Per-run  -> experiments/runs/run_NNN.json")


if __name__ == "__main__":
    main()
