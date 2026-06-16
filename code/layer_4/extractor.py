import json
from pathlib import Path

TRACE_PATH   = Path(__file__).parent.parent / "layer_2/output/simulation_trace.json"
TOPOLOGY_PATH = Path(__file__).parent.parent / "layer_2/output/topology.json"
VERDICT_PATH = Path(__file__).parent.parent / "layer_3/output/verdict.json"
OUT_PATH     = Path(__file__).parent / "output"
OUT_PATH.mkdir(exist_ok=True)

TAU_MAX = 7200  # causal horizon in simulation seconds (2 hours)


# ---------------------------------------------------------------------------
# Algorithm 1: DEVS Causal Explanation Extraction
# ---------------------------------------------------------------------------

def event_key(e):
    return (e["t"], e["model"], e["event"])


def extract(trace, violations, topology):
    # Timeline: sort full trace by timestamp
    timeline = sorted(trace, key=lambda e: e["t"])

    # Normalise: build canonical event map keyed by (t, model, event)
    canonical = {}
    for e in trace:
        canonical[event_key(e)] = e
    # Seed with violation events (prefer trace copy for identity consistency)
    nodes = {}
    for v in violations:
        k = event_key(v)
        obj = canonical.get(k, v)
        nodes[k] = obj

    edges = []
    visited_pairs = set()

    # Backward chaining (iterative until convergence)
    frontier = list(nodes.values())

    while frontier:
        next_frontier = []
        for effect in frontier:
            t_j = effect["t"]
            c_j = effect["model"]
            for candidate in trace:
                t_i = candidate["t"]
                c_i = candidate["model"]
                if t_i > t_j:
                    continue
                if t_j - t_i > TAU_MAX:
                    continue
                topo_entry = next(
                    (e for e in topology
                     if e["from"] == c_i and e["to"] == c_j
                     and candidate["event"] == e["cause_event"]),
                    None
                )
                if topo_entry is None:
                    continue
                pair = (event_key(candidate), event_key(effect))
                if pair in visited_pairs:
                    continue
                visited_pairs.add(pair)
                if event_key(candidate) not in nodes:
                    nodes[event_key(candidate)] = candidate
                    next_frontier.append(candidate)
                edges.append({"cause": candidate, "effect": effect, "mechanism": topo_entry["mechanism"]})
        frontier = next_frontier

    # Acyclicity check
    node_list = list(nodes.values())
    adj = {event_key(n): [] for n in node_list}
    for edge in edges:
        adj[event_key(edge["cause"])].append(event_key(edge["effect"]))

    if has_cycle(adj):
        raise RuntimeError("ModelingError: cycle detected in causal graph")

    return timeline, edges, list(nodes.values())


def has_cycle(adj):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}

    def dfs(u):
        color[u] = GRAY
        for v in adj.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(dfs(u) for u in adj if color[u] == WHITE)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    trace    = json.loads(TRACE_PATH.read_text())
    topology = json.loads(TOPOLOGY_PATH.read_text())
    verdict  = json.loads(VERDICT_PATH.read_text())

    if verdict["verdict"] == "valid":
        print("Policy is valid. No causal extraction needed.")
        return

    violations = verdict["violations"]
    timeline, edges, nodes = extract(trace, violations, topology)

    # Serialize causal links
    causal_links = [
        {
            "t_cause":   e["cause"]["t"],
            "cause":     e["cause"],
            "t_effect":  e["effect"]["t"],
            "effect":    e["effect"],
            "mechanism": e["mechanism"],
        }
        for e in edges
    ]

    result = {
        "timeline": timeline,
        "causal_links": causal_links,
        "violation_nodes": violations,
    }

    out = OUT_PATH / "causal_graph.json"
    out.write_text(json.dumps(result, indent=2))

    print("=== Causal Chain ===")
    for link in causal_links:
        print(f"  t={link['t_cause']}  {link['cause']['model']}:{link['cause']['event']}"
              f"  --[{link['mechanism']}]-->  "
              f"{link['effect']['model']}:{link['effect']['event']}  t={link['t_effect']}")
    print(f"\nCausal graph saved -> {out}")


if __name__ == "__main__":
    run()
