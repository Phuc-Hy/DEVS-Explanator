
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).parents[1] / ".env")

PROMPT_FILE = Path(__file__).parents[1] / "preprocessing/output/scenario_prompt.txt"
OUT_RAW     = Path(__file__).parent / "output/policy_raw.txt"
OUT_JSON    = Path(__file__).parent / "output/action_schedule.json"

MODEL = "gemini-2.5-flash"


def parse_action_schedule(text: str) -> list:
    match = re.search(r"```json\s*(\[.*?\])\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"(\[.*?\])", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    raise ValueError("No JSON action schedule found in LLM response.")


def validate_actions(actions: list, bus_model: dict) -> list:
    buses = bus_model["buses"]
    gens  = {g["gen_uid"]: g for g in bus_model["generators"]}
    controllable = {"CT", "STEAM", "CC", "PV", "RTPV", "HYDRO", "WIND"}
    valid = []

    for a in actions:
        action_type = a.get("type", "dg_shed")

        if action_type == "dg_shed":
            bus_id = str(a.get("bus", ""))
            if bus_id not in buses:
                print(f"  [SKIP] dg_shed: bus {bus_id} not found in Area 1.")
                continue
            dg_cap = buses[bus_id]["DG_capacity_MW"]
            if dg_cap == 0:
                print(f"  [SKIP] dg_shed: bus {bus_id} has no DG capacity.")
                continue
            shed = a.get("shed_MW", 0)
            if shed <= 0 or shed > dg_cap:
                print(f"  [SKIP] dg_shed: bus {bus_id}: shed_MW={shed} out of range (0, {dg_cap}].")
                continue
            valid.append(a)

        elif action_type == "gen_reduce":
            gen_uid = a.get("gen_uid", "")
            if gen_uid not in gens:
                print(f"  [SKIP] gen_reduce: {gen_uid} not found in bus_model.")
                continue
            g = gens[gen_uid]
            if g["unit_type"] not in controllable:
                print(f"  [SKIP] gen_reduce: {gen_uid} is {g['unit_type']}, not controllable.")
                continue
            target = a.get("target_MW", -1)
            if target < g["PMin_MW"] or target > g["MW_inj"]:
                print(f"  [SKIP] gen_reduce: {gen_uid}: target_MW={target} out of [{g['PMin_MW']}, {g['MW_inj']}].")
                continue
            valid.append(a)

        else:
            print(f"  [SKIP] Unknown action type: {action_type}")

    return valid


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not found. Add GEMINI_API_KEY=... to code/.env")

    scenario_prompt = PROMPT_FILE.read_text()

    client = genai.Client(api_key=api_key)

    print(f"Sending prompt to {MODEL}...")
    response = client.models.generate_content(
        model=MODEL,
        contents=scenario_prompt,
    )
    policy_text = response.text

    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    OUT_RAW.write_text(policy_text)
    print(f"Raw response saved to {OUT_RAW}")

    print("\nParsing action schedule...")
    actions = parse_action_schedule(policy_text)
    print(f"Found {len(actions)} actions.")

    bus_model_path = Path(__file__).parents[1] / "preprocessing/output/bus_model.json"
    with open(bus_model_path) as f:
        bus_model = json.load(f)

    print("Validating actions...")
    valid_actions = validate_actions(actions, bus_model)
    print(f"Valid actions: {len(valid_actions)}/{len(actions)}")

    OUT_JSON.write_text(json.dumps(valid_actions, indent=2))
    print(f"\nAction schedule saved to {OUT_JSON}")

    print("\nAction schedule:")
    for a in valid_actions:
        action_type = a.get("type", "dg_shed")
        if action_type == "gen_reduce":
            print(f"  t={a['t']}s  gen_reduce  {a['gen_uid']} -> {a['target_MW']} MW")
        else:
            print(f"  t={a['t']}s  dg_shed     bus={a['bus']}  shed={a['shed_MW']} MW")


if __name__ == "__main__":
    main()
