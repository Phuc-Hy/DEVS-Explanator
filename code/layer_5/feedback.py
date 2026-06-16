import json
from pathlib import Path

VERDICT_PATH      = Path(__file__).parent.parent / "layer_3/output/verdict.json"
CAUSAL_GRAPH_PATH = Path(__file__).parent.parent / "layer_4/output/causal_graph.json"
BUS_MODEL_PATH    = Path(__file__).parent.parent / "preprocessing/output/bus_model.json"
ACTION_SCHED_PATH = Path(__file__).parent.parent / "layer_1/output/action_schedule.json"
OUT_PATH          = Path(__file__).parent / "output"
OUT_PATH.mkdir(exist_ok=True)


def format_chain(causal_links, violation):
    link_map = {}
    for link in causal_links:
        ek = (link["effect"]["t"], link["effect"]["model"], link["effect"]["event"])
        link_map.setdefault(ek, []).append(link)

    def trace_back(node, depth=0):
        if depth > 20:
            return []
        ek = (node["t"], node["model"], node["event"])
        parents = link_map.get(ek, [])
        if not parents:
            return [node]
        chain = []
        for link in parents:
            chain.extend(trace_back(link["cause"], depth + 1))
        chain.append(node)
        return chain

    chain_nodes = trace_back(violation)
    steps = []
    for i in range(len(chain_nodes) - 1):
        src = chain_nodes[i]
        dst = chain_nodes[i + 1]
        src_ek = (src["t"], src["model"], src["event"])
        mechanism = next(
            (lk["mechanism"] for lk in causal_links
             if (lk["cause"]["t"], lk["cause"]["model"], lk["cause"]["event"]) == src_ek
             and (lk["effect"]["t"], lk["effect"]["model"], lk["effect"]["event"])
             == (dst["t"], dst["model"], dst["event"])),
            ""
        )
        steps.append(
            f"{src['model']}:{src['event']} --[{mechanism}]--> {dst['model']}:{dst['event']}"
        )
    return steps


def find_cause_event(causal_links, violation):
    for link in causal_links:
        if link["effect"] == violation:
            return link["cause"]
    return None


def analyze_relay_trip(violation, causal_links, bus_model, actions):
    branch_uid  = violation.get("model", violation.get("branch_uid"))
    flow_mw     = violation.get("flow_mw", 0.0)
    cont_rating = violation.get("cont_rating", 0.0)
    overload    = round(flow_mw - cont_rating, 4)

    ptdf = bus_model.get("PTDF", {}).get(branch_uid, {})
    branches = {b["uid"]: b for b in bus_model["branches"]}
    branch_info = branches.get(branch_uid, {})
    from_bus = branch_info.get("from_bus", "?")
    to_bus   = branch_info.get("to_bus", "?")

    cause = find_cause_event(causal_links, violation)

    lines = []

    if cause is not None:
        cause_model = cause["model"]
        cause_event = cause["event"]

        if cause_event == "SHED":
            bus_id     = cause.get("bus_id", cause_model.replace("B", ""))
            shed_mw    = cause.get("shed_mw", 0.0)
            ptdf_val   = ptdf.get(str(bus_id), 0.0)
            lines.append(
                f"Bus {bus_id} was shed by {shed_mw} MW at t={cause['t']} s. "
                f"This produced a flow change of {round(ptdf_val * (-shed_mw), 4)} MW on branch "
                f"{branch_uid} ({from_bus}->{to_bus}, rated {cont_rating} MW) "
                f"because PTDF[{branch_uid},{bus_id}] = {round(ptdf_val, 4)}: "
                f"the injection at bus {bus_id} has "
                + ("no" if abs(ptdf_val) < 1e-6 else "limited")
                + f" sensitivity to {branch_uid}."
            )

        elif cause_event == "GEN_REDUCE":
            gen_uid  = cause.get("gen_uid", cause_model)
            delta_mw = cause.get("delta_mw", 0.0)
            bus_id   = cause.get("bus_id", "?")
            ptdf_val = ptdf.get(str(bus_id), 0.0)
            lines.append(
                f"Generator {gen_uid} at bus {bus_id} was reduced by {abs(delta_mw)} MW "
                f"at t={cause['t']} s. "
                f"PTDF[{branch_uid},{bus_id}] = {round(ptdf_val, 4)}, "
                f"producing a flow change of {round(ptdf_val * delta_mw, 4)} MW on {branch_uid}."
            )

    lines.append(
        f"The pre-existing overload of {overload} MW remained unresolved and "
        f"{branch_uid} tripped at flow {flow_mw} MW > rating {cont_rating} MW."
    )

    nonzero = {
        bus_id: round(val, 4)
        for bus_id, val in ptdf.items()
        if abs(val) > 1e-6
    }
    if nonzero:
        best_bus = max(nonzero, key=lambda b: abs(nonzero[b]))
        best_ptdf = nonzero[best_bus]
        needed_mw = round(overload / abs(best_ptdf), 2)

        gens_at_bus = [
            g for g in bus_model["generators"]
            if str(g["bus_id"]) == str(best_bus)
        ]

        if gens_at_bus:
            g = gens_at_bus[0]
            lines.append(
                f"Root cause: corrective action targeted a bus with insufficient PTDF sensitivity to {branch_uid}. "
                f"The bus with highest PTDF sensitivity is bus {best_bus} "
                f"(PTDF[{branch_uid},{best_bus}] = {best_ptdf}). "
                f"Recommended correction: reduce {g['gen_uid']} by at least {needed_mw} MW "
                f"to bring {branch_uid} flow within its continuous rating of {cont_rating} MW."
            )
        else:
            lines.append(
                f"Root cause: no corrective action targeted the bus with highest PTDF sensitivity. "
                f"Bus {best_bus} has PTDF[{branch_uid},{best_bus}] = {best_ptdf}; "
                f"a reduction of at least {needed_mw} MW at that bus is needed."
            )
    else:
        lines.append(
            f"No bus has nonzero PTDF sensitivity to {branch_uid}. "
            f"Review the network topology and PTDF matrix."
        )

    return " ".join(lines)


def analyze_blackout(violation, causal_links, bus_model):
    bus_id = violation.get("bus_id", violation["model"].replace("B", ""))
    cause  = find_cause_event(causal_links, violation)

    if cause is not None and cause.get("event") == "RELAY_TRIP":
        branch_uid = cause.get("branch_uid", cause["model"])
        return (
            f"Bus {bus_id} lost supply at t={violation['t']} s due to trip of branch {branch_uid}. "
            f"Resolve the RELAY_TRIP violation on {branch_uid} to prevent this blackout."
        )
    return f"Bus {bus_id} entered blackout at t={violation['t']} s. Review causal chain for upstream violations."


def build_critique(verdict, causal_graph, bus_model, actions):
    violations   = verdict["violations"]
    causal_links = causal_graph["causal_links"]

    critique_items = []
    for v in violations:
        event_type = v["event"]
        chain      = format_chain(causal_links, v)

        if event_type == "RELAY_TRIP":
            correction = analyze_relay_trip(v, causal_links, bus_model, actions)
        elif event_type == "BLACKOUT":
            correction = analyze_blackout(v, causal_links, bus_model)
        else:
            correction = "Review policy manually."

        critique_items.append({
            "violation": {
                "event":     event_type,
                "model":     v["model"],
                "timestamp": v["t"],
            },
            "causal_chain": chain,
            "correction":   correction,
        })

    return {
        "verdict":        verdict["verdict"],
        "critique_items": critique_items,
        "summary": (
            f"The policy produced {len(violations)} violation(s). "
            "Please revise the action schedule according to the corrections below and resubmit."
        ),
    }


def run():
    verdict      = json.loads(VERDICT_PATH.read_text())
    causal_graph = json.loads(CAUSAL_GRAPH_PATH.read_text())
    bus_model    = json.loads(BUS_MODEL_PATH.read_text())
    actions      = json.loads(ACTION_SCHED_PATH.read_text())

    if verdict["verdict"] == "valid":
        result = {"verdict": "valid", "summary": "Policy is physically valid. No corrections needed."}
        print("Policy is valid. No feedback needed.")
    else:
        result = build_critique(verdict, causal_graph, bus_model, actions)
        print("=== Causal Critique ===")
        for item in result["critique_items"]:
            v = item["violation"]
            print(f"\nViolation: {v['event']} on {v['model']} at t={v['timestamp']}")
            print("Causal chain:")
            for step in item["causal_chain"]:
                print(f"  {step}")
            print(f"Correction: {item['correction']}")
        print(f"\nSummary: {result['summary']}")

    out = OUT_PATH / "critique.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"\nCritique saved -> {out}")


if __name__ == "__main__":
    run()
