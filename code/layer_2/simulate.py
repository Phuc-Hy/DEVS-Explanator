import sys
import json
from pathlib import Path

LAYER2_DIR = Path(__file__).parent
sys.path.insert(0, str(LAYER2_DIR))
sys.path.insert(0, "/Users/phuc_hy/PhD/research_paper/explanator/PythonPDEVS/src")

from pypdevs.simulator import Simulator
from coupled_model import GridModel24

BUS_MODEL_PATH    = LAYER2_DIR.parent / "preprocessing/output/bus_model.json"
ACTION_SCHED_PATH = LAYER2_DIR.parent / "layer_1/output/action_schedule.json"
OUT_DIR           = LAYER2_DIR / "output"
OUT_DIR.mkdir(exist_ok=True)

CONTROLLABLE = {"CT", "STEAM", "CC", "PV", "RTPV", "HYDRO", "WIND"}


def generate_topology(bus_data):
    topology = []
    branches = bus_data["branches"]
    bus_ids  = bus_data["bus_ids"]
    gens     = bus_data["generators"]

    for g in gens:
        if g["unit_type"] in CONTROLLABLE:
            topology.append({
                "from":        g["gen_uid"],
                "to":          f"B{g['bus_id']}",
                "cause_event": "GEN_REDUCE",
                "mechanism":   (
                    f"{g['unit_type']} output change at bus {g['bus_id']}: "
                    f"ΔP propagates via PTDF to all branches"
                ),
            })

    for bus_id in bus_ids:
        for branch in branches:
            base = {
                "from": f"B{bus_id}",
                "to":   branch["uid"],
                "mechanism": (
                    f"PTDF[{branch['uid']},{bus_id}]: "
                    f"injection change at bus {bus_id} shifts flow on "
                    f"{branch['uid']} ({branch['from_bus']}→{branch['to_bus']})"
                ),
            }
            topology.append({**base, "cause_event": "SHED"})
            topology.append({**base, "cause_event": "GEN_EFFECT"})

    for branch in branches:
        topology.append({
            "from":        branch["uid"],
            "to":          f"B{branch['to_bus']}",
            "cause_event": "RELAY_TRIP",
            "mechanism":   (
                f"cascade: trip of {branch['uid']} isolates bus {branch['to_bus']}"
            ),
        })

    return topology


def run():
    bus_data = json.loads(BUS_MODEL_PATH.read_text())
    actions  = json.loads(ACTION_SCHED_PATH.read_text())

    grid = GridModel24(bus_data, actions)
    sim  = Simulator(grid)
    sim.setClassicDEVS()
    sim.simulate()

    trace = list(grid.trace_collector.state.events)

    trace_path = OUT_DIR / "simulation_trace.json"
    trace_path.write_text(json.dumps(trace, indent=2))

    topology      = generate_topology(bus_data)
    topology_path = OUT_DIR / "topology.json"
    topology_path.write_text(json.dumps(topology, indent=2))

    print(f"Simulation complete: {len(trace)} event(s) logged.")
    for evt in sorted(trace, key=lambda e: e["t"]):
        if evt["event"] == "GEN_REDUCE":
            detail = f"  {evt['unit_type']}  {evt['p_before']:.0f}→{evt['p_after']:.0f} MW  (Δ={evt['delta_mw']:.1f})"
        elif evt["event"] == "SHED":
            detail = f"  shed_mw={evt['shed_mw']}"
        elif evt["event"] == "GEN_EFFECT":
            detail = f"  gen_delta_mw={evt['gen_delta_mw']}"
        elif evt["event"] == "RELAY_TRIP":
            detail = f"  flow={evt['flow_mw']} MW  limit={evt['cont_rating']} MW"
        else:
            detail = ""
        print(f"  t={evt['t']}s  {evt['model']}:{evt['event']}{detail}")

    print(f"\nTrace    -> {trace_path}")
    print(f"Topology -> {topology_path}")


if __name__ == "__main__":
    run()
