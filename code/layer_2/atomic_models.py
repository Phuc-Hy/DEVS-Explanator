import sys
sys.path.insert(0, "/Users/phuc_hy/PhD/research_paper/explanator/PythonPDEVS/src")

from pypdevs.DEVS import AtomicDEVS
from pypdevs.infinity import INFINITY


class ActionSchedulerState:
    def __init__(self, actions):
        self.actions = sorted(actions, key=lambda a: a["t"])
        self.index = 0
        self.abs_time = 0.0


class ActionScheduler(AtomicDEVS):

    def __lt__(self, other):
        return self.name < other.name

    def __init__(self, actions):
        AtomicDEVS.__init__(self, "ActionScheduler")
        self.state = ActionSchedulerState(actions)
        self.out_shed = self.addOutPort("out_shed")

    def timeAdvance(self):
        s = self.state
        if s.index < len(s.actions):
            return s.actions[s.index]["t"] - s.abs_time
        return INFINITY

    def outputFnc(self):
        return {self.out_shed: self.state.actions[self.state.index]}

    def intTransition(self):
        s = self.state
        s.abs_time = s.actions[s.index]["t"]
        s.index += 1
        return s

    def extTransition(self, inputs):
        return self.state


class GeneratorState:
    def __init__(self, gen_uid, bus_id, unit_type, p_cur, p_min, p_max, ramp_rate_mw_per_min):
        self.gen_uid            = gen_uid
        self.bus_id             = bus_id
        self.unit_type          = unit_type
        self.P_cur              = p_cur
        self.P_min              = p_min
        self.P_max              = p_max
        self.ramp_rate_mw_per_s = ramp_rate_mw_per_min / 60.0
        self.phase              = "normal"
        self.pending_delta      = None
        self.ramp_time_s        = 0.0
        self.t_event            = 0.0


class GeneratorModel(AtomicDEVS):

    def __lt__(self, other):
        return self.name < other.name

    def __init__(self, gen_uid, bus_id, unit_type, p_cur, p_min, p_max, ramp_rate_mw_per_min):
        AtomicDEVS.__init__(self, gen_uid)
        self.state = GeneratorState(gen_uid, bus_id, unit_type, p_cur, p_min, p_max, ramp_rate_mw_per_min)
        self.in_cmd      = self.addInPort("in_cmd")
        self.out_p_delta = self.addOutPort("out_p_delta")
        self.out_trace   = self.addOutPort("out_trace")

    def timeAdvance(self):
        if self.state.pending_delta is not None:
            return self.state.ramp_time_s
        return INFINITY

    def outputFnc(self):
        s = self.state
        p_new = s.P_cur + s.pending_delta
        evt = {
            "t":           s.t_event,
            "model":       s.gen_uid,
            "event":       "GEN_REDUCE",
            "gen_uid":     s.gen_uid,
            "bus_id":      s.bus_id,
            "unit_type":   s.unit_type,
            "delta_mw":    round(s.pending_delta, 4),
            "p_before":    round(s.P_cur, 4),
            "p_after":     round(p_new, 4),
            "ramp_time_s": round(s.ramp_time_s, 1),
        }
        return {
            self.out_p_delta: {
                "t":        s.t_event,
                "gen_uid":  s.gen_uid,
                "bus_id":   s.bus_id,
                "delta_mw": s.pending_delta,
            },
            self.out_trace: evt,
        }

    def intTransition(self):
        s = self.state
        s.P_cur += s.pending_delta
        s.pending_delta = None
        s.phase = "normal"
        return s

    def extTransition(self, inputs):
        s = self.state
        if self.in_cmd in inputs:
            msg = inputs[self.in_cmd]
            action_type = msg.get("type", "dg_shed")
            if (action_type == "gen_reduce"
                    and msg.get("gen_uid") == s.gen_uid
                    and s.phase == "normal"):
                target = float(msg["target_MW"])
                target = max(s.P_min, min(s.P_max, target))
                delta = target - s.P_cur
                if delta != 0.0:
                    s.pending_delta = delta
                    ramp_time_s = abs(delta) / s.ramp_rate_mw_per_s if s.ramp_rate_mw_per_s > 0 else 0.0
                    s.ramp_time_s = ramp_time_s
                    s.t_event = float(msg["t"]) + ramp_time_s
                    s.phase = "adjusting"
        return s


class BusState:
    def __init__(self, bus_id, ptdf_row, dg_capacity_mw):
        self.bus_id         = bus_id
        self.ptdf_row       = ptdf_row
        self.dg_capacity_mw = dg_capacity_mw
        self.phase          = "normal"
        self.pending_event  = None
        self.pending_mw     = 0.0
        self.t_event        = 0.0


class BusModel(AtomicDEVS):

    def __lt__(self, other):
        return self.name < other.name

    def __init__(self, bus_id, ptdf_row, dg_capacity_mw):
        AtomicDEVS.__init__(self, f"B{bus_id}")
        self.state = BusState(bus_id, ptdf_row, dg_capacity_mw)
        self.in_shed         = self.addInPort("in_shed")
        self.in_gen_delta    = self.addInPort("in_gen_delta")
        self.in_relay_trip   = self.addInPort("in_relay_trip")
        self.out_power_delta = self.addOutPort("out_power_delta")
        self.out_trace       = self.addOutPort("out_trace")

    def timeAdvance(self):
        if self.state.pending_event is not None:
            return 0.0
        return INFINITY

    def outputFnc(self):
        s = self.state

        if s.pending_event in ("SHED", "GEN_EFFECT"):
            delta_flows = {
                uid: ptdf_val * s.pending_mw
                for uid, ptdf_val in s.ptdf_row.items()
            }
            if s.pending_event == "SHED":
                evt = {
                    "t":       s.t_event,
                    "model":   f"B{s.bus_id}",
                    "event":   "SHED",
                    "bus_id":  s.bus_id,
                    "shed_mw": -s.pending_mw,
                }
            else:
                evt = {
                    "t":            s.t_event,
                    "model":        f"B{s.bus_id}",
                    "event":        "GEN_EFFECT",
                    "bus_id":       s.bus_id,
                    "gen_delta_mw": round(s.pending_mw, 4),
                }
            return {
                self.out_power_delta: {"t": s.t_event, "deltas": delta_flows},
                self.out_trace:       evt,
            }

        if s.pending_event == "BLACKOUT":
            evt = {
                "t":      s.t_event,
                "model":  f"B{s.bus_id}",
                "event":  "BLACKOUT",
                "bus_id": s.bus_id,
            }
            return {
                self.out_trace: evt,
            }

        return {}

    def intTransition(self):
        self.state.pending_event = None
        return self.state

    def extTransition(self, inputs):
        s = self.state

        if self.in_relay_trip in inputs:
            msg = inputs[self.in_relay_trip]
            if s.phase != "blackout":
                s.pending_event = "BLACKOUT"
                s.t_event = float(msg["t"])
                s.phase = "blackout"

        elif self.in_gen_delta in inputs:
            msg = inputs[self.in_gen_delta]
            if s.phase != "blackout":
                s.pending_mw = float(msg["delta_mw"])
                s.pending_event = "GEN_EFFECT"
                s.t_event = float(msg["t"])

        elif self.in_shed in inputs:
            msg = inputs[self.in_shed]
            action_type = msg.get("type", "dg_shed")
            if (action_type == "dg_shed"
                    and int(msg["bus"]) == s.bus_id
                    and s.phase != "blackout"):
                shed_mw = min(float(msg["shed_MW"]), s.dg_capacity_mw)
                s.pending_mw = -shed_mw
                s.pending_event = "SHED"
                s.t_event = float(msg["t"])
                s.phase = "shedding"

        return s


class BranchState:
    def __init__(self, uid, from_bus, to_bus, f_base_mw, cont_rating):
        self.uid         = uid
        self.from_bus    = from_bus
        self.to_bus      = to_bus
        self.flow_mw     = f_base_mw
        self.cont_rating = cont_rating
        self.phase       = "energized"
        self.t_trip      = 0.0


class BranchModel(AtomicDEVS):

    def __lt__(self, other):
        return self.name < other.name

    def __init__(self, uid, from_bus, to_bus, f_base_mw, cont_rating):
        AtomicDEVS.__init__(self, uid)
        self.state = BranchState(uid, from_bus, to_bus, f_base_mw, cont_rating)
        self.in_power_delta = self.addInPort("in_power_delta")
        self.out_relay_trip = self.addOutPort("out_relay_trip")
        self.out_trace      = self.addOutPort("out_trace")

    def timeAdvance(self):
        if self.state.phase == "trip_pending":
            return 0.0
        return INFINITY

    def outputFnc(self):
        s = self.state
        evt = {
            "t":           s.t_trip,
            "model":       s.uid,
            "event":       "RELAY_TRIP",
            "branch_uid":  s.uid,
            "from_bus":    s.from_bus,
            "to_bus":      s.to_bus,
            "flow_mw":     round(s.flow_mw, 4),
            "cont_rating": s.cont_rating,
        }
        return {
            self.out_relay_trip: {"t": s.t_trip, "branch_uid": s.uid},
            self.out_trace:      evt,
        }

    def intTransition(self):
        self.state.phase = "tripped"
        return self.state

    def extTransition(self, inputs):
        s = self.state
        if self.in_power_delta in inputs and s.phase == "energized":
            msg = inputs[self.in_power_delta]
            delta = msg["deltas"].get(s.uid, 0.0)
            if delta != 0.0:
                s.flow_mw += delta
                if abs(s.flow_mw) > s.cont_rating:
                    s.phase = "trip_pending"
                    s.t_trip = float(msg["t"])
        return s


class TraceCollectorState:
    def __init__(self):
        self.events  = []
        self.pending = None


class TraceCollector(AtomicDEVS):

    def __lt__(self, other):
        return self.name < other.name

    def __init__(self):
        AtomicDEVS.__init__(self, "TraceCollector")
        self.state     = TraceCollectorState()
        self.in_trace  = self.addInPort("in_trace")
        self.out_exec_trace = self.addOutPort("out_exec_trace")

    def timeAdvance(self):
        if self.state.pending is not None:
            return 0.0
        return INFINITY

    def outputFnc(self):
        return {self.out_exec_trace: self.state.pending}

    def intTransition(self):
        self.state.pending = None
        return self.state

    def extTransition(self, inputs):
        if self.in_trace in inputs:
            evt = inputs[self.in_trace]
            self.state.events.append(evt)
            self.state.pending = evt
        return self.state
