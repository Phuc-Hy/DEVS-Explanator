import json
from pathlib import Path

TRACE_PATH  = Path(__file__).parent.parent / "layer_2/output/simulation_trace.json"
OUT_PATH    = Path(__file__).parent / "output"
OUT_PATH.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Constraint predicates  (each returns True if the event is a violation)
# ---------------------------------------------------------------------------

def kappa_relay_trip(event):
    return event.get("event") == "RELAY_TRIP"


def kappa_blackout(event):
    return event.get("event") == "BLACKOUT"


CONSTRAINTS = [kappa_relay_trip, kappa_blackout]


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

def check(trace):
    violations = []
    for event in trace:
        for kappa in CONSTRAINTS:
            if kappa(event):
                violations.append(event)
                break  # avoid duplicate entries for the same event
    verdict = "invalid" if violations else "valid"
    return verdict, violations


def run():
    trace = json.loads(TRACE_PATH.read_text())
    verdict, violations = check(trace)

    result = {
        "verdict": verdict,
        "violations": violations,
    }

    out = OUT_PATH / "verdict.json"
    out.write_text(json.dumps(result, indent=2))

    print(f"Verdict: {verdict.upper()}")
    if violations:
        print(f"Violations ({len(violations)}):")
        for v in violations:
            print(f"  {v}")
    else:
        print("No constraint violations detected.")
    print(f"\nVerdict saved -> {out}")


if __name__ == "__main__":
    run()
