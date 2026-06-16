"""
build_bus_model.py
Compute PTDF matrix and P_inj baseline at heatwave peak.
Output: output/bus_model.json
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path

# --- Paths ---
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/RTS-GMLC/RTS_Data"
SRC  = DATA / "SourceData"
TS   = DATA / "timeseries_data_files"
OUT  = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

# --- Heatwave peak timestep ---
PEAK = dict(Year=2020, Month=7, Day=16, Period=169)

# --- Maintenance: unavailable generators ---
MAINTENANCE = {"123_STEAM_3", "115_STEAM_3"}

# --- Slack bus ---
SLACK_BUS = 123


def load_area1():
    bus = pd.read_csv(SRC / "bus.csv")
    bus = bus[bus["Area"] == 1].copy()
    return bus


def load_branches_area1(bus_ids):
    branch = pd.read_csv(SRC / "branch.csv")
    branch = branch[
        branch["From Bus"].isin(bus_ids) &
        branch["To Bus"].isin(bus_ids)
    ].copy()
    return branch


def load_gen_area1(bus_ids):
    gen = pd.read_csv(SRC / "gen.csv")
    gen = gen[gen["Bus ID"].isin(bus_ids)].copy()
    gen = gen[gen["Unit Type"] != "SYNC_COND"].copy()
    gen = gen[~gen["GEN UID"].isin(MAINTENANCE)].copy()
    return gen


def get_peak_row(path):
    df = pd.read_csv(path)
    row = df[
        (df["Year"]   == PEAK["Year"])   &
        (df["Month"]  == PEAK["Month"])  &
        (df["Day"]    == PEAK["Day"])    &
        (df["Period"] == PEAK["Period"])
    ]
    return row.drop(columns=["Year", "Month", "Day", "Period"]).squeeze()


def build_B_matrix(bus_ids, branch):
    n = len(bus_ids)
    idx = {b: i for i, b in enumerate(bus_ids)}
    B = np.zeros((n, n))
    for _, row in branch.iterrows():
        i = idx[row["From Bus"]]
        j = idx[row["To Bus"]]
        b = 1.0 / row["X"]
        B[i, i] += b
        B[j, j] += b
        B[i, j] -= b
        B[j, i] -= b
    return B


def build_PTDF(bus_ids, branch, B):
    slack_idx = bus_ids.index(SLACK_BUS)
    # remove slack bus row and column
    rows = [i for i in range(len(bus_ids)) if i != slack_idx]
    B_red = B[np.ix_(rows, rows)]
    X_red = np.linalg.inv(B_red)

    # expand X back to full size (slack bus = 0)
    n = len(bus_ids)
    X = np.zeros((n, n))
    for ii, i in enumerate(rows):
        for jj, j in enumerate(rows):
            X[i, j] = X_red[ii, jj]

    # compute PTDF (38 x 24)
    n_branch = len(branch)
    PTDF = np.zeros((n_branch, n))
    idx = {b: i for i, b in enumerate(bus_ids)}
    for ell, (_, row) in enumerate(branch.iterrows()):
        i = idx[row["From Bus"]]
        j = idx[row["To Bus"]]
        x_l = row["X"]
        for n_idx in range(n):
            PTDF[ell, n_idx] = (X[i, n_idx] - X[j, n_idx]) / x_l

    return PTDF


def compute_MW_gen_per_bus(gen, bus_ids):
    """
    Compute total MW_gen at each bus at heatwave peak.
    Thermal (CT/STEAM/CC/NUCLEAR): use MW Inj from gen.csv
    PV/RTPV/WIND/HYDRO: use timeseries at PEAK
    """
    # timeseries
    pv    = get_peak_row(TS / "PV/REAL_TIME_pv.csv")
    rtpv  = get_peak_row(TS / "RTPV/REAL_TIME_rtpv.csv")
    wind  = get_peak_row(TS / "WIND/REAL_TIME_wind.csv")
    hydro = get_peak_row(TS / "Hydro/REAL_TIME_hydro.csv")
    ts_all = pd.concat([pv, rtpv, wind, hydro])

    MW_gen = {b: 0.0 for b in bus_ids}

    for _, row in gen.iterrows():
        bus = row["Bus ID"]
        uid = row["GEN UID"]
        unit_type = row["Unit Type"]

        if unit_type in ("CT", "STEAM", "CC", "NUCLEAR"):
            MW_gen[bus] += row["MW Inj"]
        else:
            # PV, RTPV, WIND, HYDRO: read from timeseries
            if uid in ts_all.index:
                MW_gen[bus] += float(ts_all[uid])

    return MW_gen


def compute_DG_capacity_per_bus(gen, bus_ids):
    """
    DG capacity = total PMax of PV + RTPV + HYDRO + WIND per bus.
    This is the maximum sheddable capacity at each bus.
    """
    dg_types = {"PV", "RTPV", "HYDRO", "WIND"}
    dg = gen[gen["Unit Type"].isin(dg_types)]
    dg_cap = dg.groupby("Bus ID")["PMax MW"].sum()
    return {b: float(dg_cap.get(b, 0.0)) for b in bus_ids}


def main():
    # --- Load data ---
    bus    = load_area1()
    bus_ids = sorted(bus["Bus ID"].tolist())
    branch = load_branches_area1(set(bus_ids))
    gen    = load_gen_area1(set(bus_ids))

    # --- B matrix and PTDF ---
    B    = build_B_matrix(bus_ids, branch)
    PTDF = build_PTDF(bus_ids, branch, B)

    # --- P_inj baseline ---
    MW_load = bus.set_index("Bus ID")["MW Load"].to_dict()
    MW_gen  = compute_MW_gen_per_bus(gen, bus_ids)

    P_inj = {}
    for b in bus_ids:
        load_heatwave = MW_load[b] * 1.4
        P_inj[b] = MW_gen[b] - load_heatwave

    # --- F_base = PTDF × P_inj ---
    P_inj_vec = np.array([P_inj[b] for b in bus_ids])
    F_base_vec = PTDF @ P_inj_vec

    # --- DG capacity per bus ---
    dg_cap = compute_DG_capacity_per_bus(gen, bus_ids)

    # --- Output ---
    bus_model = {
        "peak_timestep": PEAK,
        "slack_bus": SLACK_BUS,
        "bus_ids": bus_ids,
        "branches": [
            {
                "uid": row["UID"],
                "from_bus": int(row["From Bus"]),
                "to_bus": int(row["To Bus"]),
                "x": float(row["X"]),
                "cont_rating": float(row["Cont Rating"]),
                "F_base_MW": float(F_base_vec[i]),
            }
            for i, (_, row) in enumerate(branch.iterrows())
        ],
        "buses": {
            str(b): {
                "MW_load_heatwave": round(MW_load[b] * 1.4, 3),
                "MW_gen": round(MW_gen[b], 3),
                "P_inj": round(P_inj[b], 3),
                "DG_capacity_MW": round(dg_cap[b], 3),
            }
            for b in bus_ids
        },
        "PTDF": {
            branch.iloc[i]["UID"]: {
                str(bus_ids[j]): round(float(PTDF[i, j]), 6)
                for j in range(len(bus_ids))
            }
            for i in range(len(branch))
        },
        "generators": [
            {
                "gen_uid": row["GEN UID"],
                "bus_id": int(row["Bus ID"]),
                "unit_type": row["Unit Type"],
                "MW_inj": float(row["MW Inj"]),
                "PMax_MW": float(row["PMax MW"]),
                "PMin_MW": float(row["PMin MW"]),
                "ramp_rate": float(row["Ramp Rate MW/Min"]),
            }
            for _, row in gen.iterrows()
        ],
    }

    out_path = OUT / "bus_model.json"
    with open(out_path, "w") as f:
        json.dump(bus_model, f, indent=2)

    print(f"bus_model.json saved to {out_path}")
    print(f"  Buses: {len(bus_ids)}")
    print(f"  Branches: {len(branch)}")
    print(f"  Generators: {len(gen)}")
    print(f"  PTDF shape: {PTDF.shape}")
    print(f"\nF_base summary (MW):")
    for i, (_, row) in enumerate(branch.iterrows()):
        flag = " *** OVERLOAD ***" if abs(F_base_vec[i]) > row["Cont Rating"] else ""
        print(f"  {row['UID']:8s}: {F_base_vec[i]:8.1f} MW  (limit {row['Cont Rating']:.0f} MW){flag}")


if __name__ == "__main__":
    main()
