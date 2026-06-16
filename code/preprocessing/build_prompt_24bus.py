"""
build_prompt_24bus.py
Read bus_model.json and generate an LLM prompt describing the heatwave scenario.
Output: output/scenario_prompt.txt
The LLM is not given branch topology (no information on which lines connect which buses).
"""

import json
from pathlib import Path

INPUT  = Path(__file__).parent / "output/bus_model.json"
OUTPUT = Path(__file__).parent / "output/scenario_prompt.txt"


def build_prompt(model: dict) -> str:
    buses     = model["buses"]
    branches  = model["branches"]
    peak      = model["peak_timestep"]

    # Find overloaded branches
    overloaded = [
        b for b in branches
        if abs(b["F_base_MW"]) > b["cont_rating"]
    ]

    # Buses with sheddable DG
    sheddable = {
        bus_id: info
        for bus_id, info in buses.items()
        if info["DG_capacity_MW"] > 0
    }

    lines = []

    lines.append("You are a power grid emergency operator managing a 24-bus transmission system (RTS-GMLC Area 1) during an extreme heatwave.")
    lines.append("")
    lines.append("## Scenario")
    lines.append(f"Timestamp: {peak['Year']}-{peak['Month']:02d}-{peak['Day']:02d}, interval {peak['Period']} (14:00 local time, peak solar and load).")
    lines.append("Load has increased by 40% due to heatwave conditions.")
    lines.append("Two generators are offline for maintenance: 123_STEAM_3 (350 MW) and 115_STEAM_3 (155 MW).")
    lines.append("")
    lines.append("## Thermal Generator Status")
    lines.append("Each generator shows: bus, type, current output (MW_inj), min (PMin_MW), max (PMax_MW), ramp rate (MW/min).")
    lines.append("")
    thermal_types = {"CT", "STEAM", "CC", "NUCLEAR"}
    for g in model["generators"]:
        if g["unit_type"] in thermal_types:
            lines.append(
                f"  - {g['gen_uid']} @ bus {g['bus_id']} [{g['unit_type']}]: "
                f"MW_inj={g['MW_inj']:.0f}, PMin={g['PMin_MW']:.0f}, PMax={g['PMax_MW']:.0f}, ramp={g['ramp_rate']:.1f} MW/min"
            )
    lines.append("")
    lines.append("## Overloaded Transmission Lines")
    lines.append("The following lines exceed their continuous rating and will trigger automatic relay trips if not resolved:")
    lines.append("")
    if overloaded:
        for b in overloaded:
            flow = b["F_base_MW"]
            lines.append(f"  - Line {b['uid']}: flow = {flow:.1f} MW, limit = {b['cont_rating']:.0f} MW (overload = {abs(flow) - b['cont_rating']:.1f} MW)")
    else:
        lines.append("  (No overloaded lines at baseline)")
    lines.append("")
    lines.append("## Available DG Shedding Actions")
    lines.append("You may reduce (shed) distributed generation at the following buses.")
    lines.append("Each bus shows: current generation (MW) and maximum sheddable capacity (MW).")
    lines.append("You CANNOT shed more than the DG capacity at each bus.")
    lines.append("")
    for bus_id, info in sheddable.items():
        lines.append(f"  - Bus {bus_id}: MW_gen = {info['MW_gen']:.1f} MW, DG_capacity = {info['DG_capacity_MW']:.1f} MW")
    lines.append("")
    lines.append("## Available Thermal Reduction Actions")
    lines.append("You may reduce thermal generator output down to PMin. Each generator shows current output and minimum.")
    lines.append("")
    thermal_types = {"CT", "STEAM", "CC"}
    for g in model["generators"]:
        if g["unit_type"] in thermal_types:
            headroom = g["MW_inj"] - g["PMin_MW"]
            if headroom > 0:
                lines.append(
                    f"  - {g['gen_uid']} @ bus {g['bus_id']} [{g['unit_type']}]: "
                    f"current={g['MW_inj']:.0f} MW, PMin={g['PMin_MW']:.0f} MW, "
                    f"max_reduction={headroom:.0f} MW"
                )
    lines.append("")
    lines.append("## Instructions")
    lines.append("Generate a minimal action schedule to resolve all overloads.")
    lines.append("You may combine both action types in the same schedule.")
    lines.append("Output ONLY a JSON list of actions, no explanation. Two action formats:")
    lines.append("")
    lines.append('```json')
    lines.append('[')
    lines.append('  {"t": <seconds>, "type": "gen_reduce", "gen_uid": "<uid>", "target_MW": <mw>},')
    lines.append('  {"t": <seconds>, "type": "dg_shed",    "bus": <bus_id>,    "shed_MW": <mw>},')
    lines.append('  ...')
    lines.append(']')
    lines.append('```')
    lines.append("")
    lines.append("Rules:")
    lines.append("  - gen_reduce: target_MW must be >= PMin and <= current output of that generator")
    lines.append("  - dg_shed: shed_MW must be > 0 and <= DG_capacity of that bus")
    lines.append("  - t >= 0 (seconds from now)")
    lines.append("  - Use the minimum number of actions needed")
    lines.append("  - Prefer gen_reduce for thermal generators when the overload is on a line fed by that generator")

    return "\n".join(lines)


def main():
    with open(INPUT) as f:
        model = json.load(f)

    prompt = build_prompt(model)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(prompt)

    print(prompt)
    print(f"\nSaved to {OUTPUT}")


if __name__ == "__main__":
    main()
