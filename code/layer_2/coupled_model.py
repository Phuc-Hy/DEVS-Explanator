import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/Users/phuc_hy/PhD/research_paper/explanator/PythonPDEVS/src")

from pypdevs.DEVS import CoupledDEVS
from atomic_models import ActionScheduler, GeneratorModel, BusModel, BranchModel, TraceCollector

CONTROLLABLE = {"CT", "STEAM", "CC", "PV", "RTPV", "HYDRO", "WIND"}


class GridModel24(CoupledDEVS):

    def __init__(self, bus_data, actions):
        CoupledDEVS.__init__(self, "GridModel24")

        self.Y = self.addOutPort("Y")

        ptdf_raw = bus_data["PTDF"]
        ptdf_per_bus = {bus_id: {} for bus_id in bus_data["bus_ids"]}
        for branch_uid, bus_vals in ptdf_raw.items():
            for bus_id_str, val in bus_vals.items():
                bus_id = int(bus_id_str)
                if bus_id in ptdf_per_bus:
                    ptdf_per_bus[bus_id][branch_uid] = val

        buses_info    = bus_data["buses"]
        branches_info = bus_data["branches"]
        gens_info     = bus_data["generators"]

        self.scheduler = self.addSubModel(ActionScheduler(actions))

        self.trace_collector = self.addSubModel(TraceCollector())

        self.bus_models = {}
        for bus_id in bus_data["bus_ids"]:
            info  = buses_info[str(bus_id)]
            model = BusModel(
                bus_id         = bus_id,
                ptdf_row       = ptdf_per_bus[bus_id],
                dg_capacity_mw = info["DG_capacity_MW"],
            )
            self.bus_models[bus_id] = self.addSubModel(model)

        self.gen_models = {}
        for g in gens_info:
            unit_type = g["unit_type"]
            if unit_type in CONTROLLABLE:
                model = GeneratorModel(
                    gen_uid              = g["gen_uid"],
                    bus_id               = g["bus_id"],
                    unit_type            = unit_type,
                    p_cur                = g["MW_inj"],
                    p_min                = g["PMin_MW"],
                    p_max                = g["PMax_MW"],
                    ramp_rate_mw_per_min = g["ramp_rate"],
                )
                self.gen_models[g["gen_uid"]] = self.addSubModel(model)
                self.connectPorts(self.scheduler.out_shed, model.in_cmd)
                bus_id = g["bus_id"]
                if bus_id in self.bus_models:
                    self.connectPorts(model.out_p_delta, self.bus_models[bus_id].in_gen_delta)
                self.connectPorts(model.out_trace, self.trace_collector.in_trace)

        self.branch_models = {}
        for b in branches_info:
            model = BranchModel(
                uid         = b["uid"],
                from_bus    = b["from_bus"],
                to_bus      = b["to_bus"],
                f_base_mw   = b["F_base_MW"],
                cont_rating = b["cont_rating"],
            )
            self.branch_models[b["uid"]] = self.addSubModel(model)

        for bus_model in self.bus_models.values():
            self.connectPorts(self.scheduler.out_shed, bus_model.in_shed)
            self.connectPorts(bus_model.out_trace, self.trace_collector.in_trace)

        for bus_model in self.bus_models.values():
            for branch_model in self.branch_models.values():
                self.connectPorts(bus_model.out_power_delta, branch_model.in_power_delta)

        for branch_model in self.branch_models.values():
            to_bus_id = branch_model.state.to_bus
            if to_bus_id in self.bus_models:
                self.connectPorts(branch_model.out_relay_trip, self.bus_models[to_bus_id].in_relay_trip)
            self.connectPorts(branch_model.out_trace, self.trace_collector.in_trace)

        self.connectPorts(self.trace_collector.out_exec_trace, self.Y)
