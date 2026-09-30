"""Build the robust HCS style dataset and the incident telemetry it supports.

Stage one reproduces the HCS Streets CSV export described on the McTrans page:
one row per lane group, per analysis period, per scenario year (2023, 2030 and
2035, matching the traffic growth example on that page) with intersection
geometry, traffic, signal controller settings and HCM performance measures.

Stage two turns the 2023 timing plans into millisecond resolution controller
logs around each crash, together with detector faults, malfunction management
unit (MMU) events and crash telemetry. Every crash carries a hidden ground
truth label so the evaluator can be benchmarked objectively.
"""

import numpy as np
import pandas as pd

from . import config, hcm
from .jurisdictions import LOCALS, STATES, clearance_speed, governing_requirements, policy_rows
from .utils import get_logger, ms_to_stamp, round_up_to, sub, vsub

LOG = get_logger("synth")

PHASES = {
    1: {"movement": "WBL", "approach": "WB", "kind": "left", "ring": 1, "barrier": "A", "major": True},
    2: {"movement": "EBT", "approach": "EB", "kind": "through_right", "ring": 1, "barrier": "A", "major": True},
    3: {"movement": "NBL", "approach": "NB", "kind": "left", "ring": 1, "barrier": "B", "major": False},
    4: {"movement": "SBT", "approach": "SB", "kind": "through_right", "ring": 1, "barrier": "B", "major": False},
    5: {"movement": "EBL", "approach": "EB", "kind": "left", "ring": 2, "barrier": "A", "major": True},
    6: {"movement": "WBT", "approach": "WB", "kind": "through_right", "ring": 2, "barrier": "A", "major": True},
    7: {"movement": "SBL", "approach": "SB", "kind": "left", "ring": 2, "barrier": "B", "major": False},
    8: {"movement": "NBT", "approach": "NB", "kind": "through_right", "ring": 2, "barrier": "B", "major": False},
}
RING_ORDER = {1: [1, 2, 3, 4], 2: [5, 6, 7, 8]}
BARRIER_PAIRS = {"A": ((1, 2), (5, 6)), "B": ((3, 4), (7, 8))}
THROUGH_PAD = {("A", 1): 2, ("A", 2): 6, ("B", 1): 4, ("B", 2): 8}
SURFACE_BY_WEATHER = {"RAIN": "WET", "SNOW": "ICE"}
OPPOSING = {1: 2, 2: 1, 3: 4, 4: 3, 5: 6, 6: 5, 7: 8, 8: 7}

PERIODS = {
    "AM Peak": {"plan": 1, "cycles": [110, 120, 130], "factor": 1.00, "hours": (7, 8), "weekend": False},
    "Midday": {"plan": 2, "cycles": [80, 90, 100], "factor": 0.72, "hours": (11, 12), "weekend": False},
    "PM Peak": {"plan": 3, "cycles": [120, 130, 140], "factor": 1.12, "hours": (16, 17), "weekend": False},
    "Weekend": {"plan": 4, "cycles": [90, 100, 110], "factor": 0.66, "hours": (10, 15), "weekend": True},
}
DIRECTION_SKEW = {"AM Peak": {"EB": 1.12, "WB": 0.9, "NB": 1.08, "SB": 0.93},
                  "PM Peak": {"EB": 0.9, "WB": 1.12, "NB": 0.93, "SB": 1.08}}

STREETS_MAJOR = ["Main Street", "Commerce Boulevard", "Lakeview Avenue", "Industrial Parkway", "Market Street",
                 "Harbor Road", "Station Avenue", "University Drive", "Airport Boulevard", "Riverside Drive",
                 "Central Avenue", "Kingsway", "Meridian Road", "Oak Hill Parkway", "Veterans Highway"]
STREETS_MINOR = ["1st Street", "2nd Street", "3rd Avenue", "Elm Street", "Maple Avenue", "Cedar Lane",
                 "Park Road", "Mill Street", "School Street", "Church Street", "Pine Avenue", "Ash Road",
                 "Willow Way", "Birch Street", "Hillcrest Road", "Forest Avenue", "Walnut Street", "Grove Street"]
CONTROLLER_STANDARDS = ["NEMA TS2 Type 1", "NEMA TS2 Type 2", "ATC 5201"]
FAULT_CODES = ["OPEN_LOOP", "SHORTED_LOOP", "EXCESSIVE_INDUCTANCE_CHANGE", "WATCHDOG_FAILURE"]
HIRES_CODES = {"GREEN": (1, 7), "YELLOW": (8, 9), "RED_CLEARANCE": (10, 11)}
EPOCH_2024_MS = 1704067200000
DAY_MS = 86400000
HOUR_MS = 3600000
WINDOW_CYCLES = 8
CRASH_CYCLE = 5


def _choice(rng, items, p=None):
    return items[int(rng.choice(len(items), p=p))]


def build_intersections(rng, count):
    """Static intersection inventory and per phase geometry."""
    intersections, lane_groups = [], []
    local_codes = list(LOCALS)
    for idx in range(count):
        iid = "INT" + str(idx + 1).zfill(4)
        local = LOCALS[_choice(rng, local_codes)]
        control = _choice(rng, ["Pretimed", "Actuated", "Coordinated"], [0.2, 0.42, 0.38])
        practice = _choice(rng, ["ITE_KINEMATIC", "LEGACY_FLAT", "ITE_POSTED_ONLY"], [0.68, 0.2, 0.12])
        major_speed = float(_choice(rng, [35, 40, 45, 50, 55], [0.18, 0.24, 0.26, 0.2, 0.12]))
        minor_speed = float(_choice(rng, [25, 30, 35, 40], [0.2, 0.35, 0.3, 0.15]))
        major_lanes = int(_choice(rng, [1, 2, 3], [0.15, 0.6, 0.25]))
        minor_lanes = int(_choice(rng, [1, 2], [0.65, 0.35]))
        major_grade = float(_choice(rng, [0, 0, 1, 2, 3, 4, 5, 6]))
        minor_grade = float(_choice(rng, [0, 0, 0, 1, 2, 3, 4]))
        major_uphill_eb = bool(rng.random() < 0.5)
        minor_uphill_nb = bool(rng.random() < 0.5)
        width_crossing_minor = float(minor_lanes * 2 * 12 + 24 + int(rng.integers(0, 16)))
        width_crossing_major = float(major_lanes * 2 * 12 + 36 + int(rng.integers(0, 24)))
        cbd = bool(rng.random() < 0.22)
        name = _choice(rng, STREETS_MAJOR) + " and " + _choice(rng, STREETS_MINOR)
        intersections.append({
            "intersection_id": iid,
            "intersection_name": name,
            "corridor": name.split(" and ")[0],
            "state_code": local.state_code,
            "jurisdiction_code": local.jurisdiction_code,
            "jurisdiction_name": local.jurisdiction_name,
            "control_type": control,
            "controller_standard": _choice(rng, CONTROLLER_STANDARDS, [0.4, 0.35, 0.25]),
            "controller_id": "CTL" + str(idx + 1).zfill(4),
            "timing_practice": practice,
            "area_type": "CBD" if cbd else "Other",
            "major_posted_speed_mph": major_speed,
            "minor_posted_speed_mph": minor_speed,
            "annual_growth_rate": round(float(rng.uniform(0.005, 0.025)), 4),
        })
        for phase, meta in PHASES.items():
            major = meta["major"]
            posted = major_speed if major else minor_speed
            grade = major_grade if major else minor_grade
            uphill_ref = major_uphill_eb if major else minor_uphill_nb
            ref_dir = meta["approach"] in ("EB", "NB")
            uphill = uphill_ref if ref_dir else (not uphill_ref)
            left = meta["kind"] == "left"
            lanes = (int(_choice(rng, [1, 2], [0.75, 0.25])) if left else (major_lanes if major else minor_lanes))
            lane_groups.append({
                "intersection_id": iid,
                "nema_phase": phase,
                "movement": meta["movement"],
                "approach": meta["approach"],
                "lane_group_kind": meta["kind"],
                "ring": meta["ring"],
                "barrier": meta["barrier"],
                "num_lanes": lanes,
                "lane_width_ft": float(_choice(rng, [10.0, 10.5, 11.0, 11.5, 12.0], [0.08, 0.12, 0.3, 0.2, 0.3])),
                "storage_length_ft": float(rng.integers(120, 420)) if left else float(rng.integers(450, 1400)),
                "grade_pct": grade,
                "grade_direction": "level" if grade == 0 else ("uphill" if uphill else "downhill"),
                "intersection_width_ft": width_crossing_minor if major else width_crossing_major,
                "posted_speed_mph": posted,
                "speed_85th_mph": round(posted + max(0.0, float(rng.normal(5.0, 2.0))), 1),
                "heavy_vehicle_pct": round(float(rng.uniform(1.5, 12.0)), 1),
            })
    return pd.DataFrame(intersections), pd.DataFrame(lane_groups)


def program_clearances(inter, lanes, rng):
    """Programmed yellow and red clearance per lane group, by timing practice."""
    rows = []
    practice_of = inter.set_index("intersection_id")["timing_practice"].to_dict()
    local_of = inter.set_index("intersection_id")["jurisdiction_code"].to_dict()
    for lg in lanes.itertuples(index=False):
        local = LOCALS[local_of[lg.intersection_id]]
        state = STATES[local.state_code]
        practice = practice_of[lg.intersection_id]
        direction = "uphill" if lg.grade_direction == "level" else lg.grade_direction
        req = governing_requirements(local.jurisdiction_code, lg.posted_speed_mph, lg.speed_85th_mph,
                                     lg.lane_group_kind, lg.grade_pct, direction, lg.intersection_width_ft)
        speed = clearance_speed(state, local, lg.posted_speed_mph, lg.speed_85th_mph, lg.lane_group_kind)
        if practice == "ITE_KINEMATIC":
            yellow = round_up_to(req["required_yellow_s"], 0.1) + float(_choice(rng, [0.0, 0.0, 0.1, 0.2]))
            red = max(round_up_to(req["required_red_clearance_s"], 0.1),
                      round_up_to(float(hcm.ite_red_clearance(speed, lg.intersection_width_ft)), 0.1))
        elif practice == "ITE_POSTED_ONLY":
            posted_speed = lg.posted_speed_mph if lg.lane_group_kind != "left" else max(20.0, sub(lg.posted_speed_mph, 10.0))
            yellow = max(3.0, round_up_to(float(hcm.ite_yellow(posted_speed, lg.grade_pct, direction)), 0.1))
            red = max(0.5, round_up_to(float(hcm.ite_red_clearance(posted_speed, lg.intersection_width_ft)), 0.1))
        else:
            yellow = 3.0 if lg.lane_group_kind == "left" else 3.5
            red = 1.0
        rows.append({
            "yellow_s": round(min(yellow, 6.0), 1),
            "red_clearance_s": round(min(red, 6.0), 1),
            "clearance_speed_mph": req["clearance_speed_mph"],
            "required_yellow_s": req["required_yellow_s"],
            "required_red_clearance_s": req["required_red_clearance_s"],
        })
    return pd.concat([lanes.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _base_demand(rng, kind, major, lanes):
    if kind == "left":
        return float(rng.uniform(80, 280) if major else rng.uniform(30, 150))
    per_lane = rng.uniform(330, 540) if major else rng.uniform(180, 380)
    return float(per_lane * lanes)


def _allocate_splits(y, clear, min_green, nominal_cycle):
    """Allocate phase greens with a dual ring, two barrier structure."""
    y_a = max(y[1] + y[2], y[5] + y[6])
    y_b = max(y[3] + y[4], y[7] + y[8])
    lost_a = max(clear[1] + clear[2], clear[5] + clear[6])
    lost_b = max(clear[3] + clear[4], clear[7] + clear[8])
    available = max(sub(sub(nominal_cycle, lost_a), lost_b), 24.0)
    green_barrier = {"A": available * y_a / (y_a + y_b), "B": available * y_b / (y_a + y_b)}
    greens = {}
    for barrier, pairs in BARRIER_PAIRS.items():
        for (p, q) in pairs:
            share = max(green_barrier[barrier], min_green[p] + min_green[q])
            gp = max(min_green[p], round(share * y[p] / (y[p] + y[q])))
            gq = max(min_green[q], round(sub(share, gp)))
            greens[p], greens[q] = float(gp), float(gq)
        totals = {ring: sum(greens[ph] + clear[ph] for ph in pair) for ring, pair in zip((1, 2), pairs)}
        target = max(totals.values())
        for ring in (1, 2):
            pad_phase = THROUGH_PAD[(barrier, ring)]
            greens[pad_phase] = round(greens[pad_phase] + sub(target, totals[ring]), 1)
    cycle = sum(greens[p] + clear[p] for p in RING_ORDER[1])
    return greens, round(cycle, 1)


def build_hcs_table(inter, lanes, years, rng):
    """Lane group rows per scenario year and analysis period (HCS Streets CSV style)."""
    lanes = lanes.copy()
    lanes["base_demand_vph"] = [
        _base_demand(rng, r.lane_group_kind, PHASES[r.nema_phase]["major"], r.num_lanes)
        for r in lanes.itertuples(index=False)
    ]
    lanes["bicycles_vph"] = rng.integers(0, 45, len(lanes))
    lanes["buses_per_hr"] = np.where(lanes["lane_group_kind"] == "left", 0, rng.integers(0, 12, len(lanes)))
    lanes["peak_hour_factor"] = np.round(rng.uniform(0.85, 0.96, len(lanes)), 2)
    info = inter.set_index("intersection_id")
    cbd_flag = (info["area_type"] == "CBD").to_dict()
    lanes["sat_flow_vph"] = hcm.adjusted_saturation_flow(
        lanes["num_lanes"], lanes["lane_width_ft"], lanes["heavy_vehicle_pct"], lanes["grade_pct"],
        lanes["grade_direction"], lanes["lane_group_kind"], lanes["intersection_id"].map(cbd_flag))

    timing_rows = []
    for iid, group in lanes.groupby("intersection_id", sort=True):
        control = info.at[iid, "control_type"]
        g = group.set_index("nema_phase")
        clear = {p: float(g.at[p, "yellow_s"] + g.at[p, "red_clearance_s"]) for p in PHASES}
        min_green = {p: (5.0 if PHASES[p]["kind"] == "left" else (15.0 if PHASES[p]["major"] else 8.0)) for p in PHASES}
        for period, meta in PERIODS.items():
            skew = DIRECTION_SKEW.get(period, {})
            y = {}
            for p in PHASES:
                demand = g.at[p, "base_demand_vph"] * meta["factor"] * skew.get(PHASES[p]["approach"], 1.0)
                y[p] = max(demand / g.at[p, "peak_hour_factor"] / g.at[p, "sat_flow_vph"], 0.02)
            nominal = float(_choice(rng, meta["cycles"])) if control != "Pretimed" else 100.0
            greens, cycle = _allocate_splits(y, clear, min_green, nominal)
            offset = float(rng.integers(0, int(cycle))) if control == "Coordinated" else 0.0
            for p in PHASES:
                timing_rows.append({
                    "intersection_id": iid, "analysis_period": period, "timing_plan_id": meta["plan"],
                    "nema_phase": p, "cycle_length_s": cycle, "offset_s": offset,
                    "green_s": greens[p], "split_s": round(greens[p] + clear[p], 1),
                    "min_green_s": min_green[p],
                    "passage_time_s": 0.0 if control == "Pretimed" else float(_choice(rng, [2.0, 2.5, 3.0, 3.5])),
                })
    timing = pd.DataFrame(timing_rows)

    frames = []
    for year in years:
        for period, meta in PERIODS.items():
            part = lanes.copy()
            part["scenario_year"] = year
            part["analysis_period"] = period
            growth = part["intersection_id"].map(info["annual_growth_rate"])
            skew = DIRECTION_SKEW.get(period, {})
            direction_factor = part["approach"].map(lambda a: skew.get(a, 1.0))
            part["demand_vph"] = np.round(part["base_demand_vph"] * meta["factor"] * direction_factor
                                          * np.power(1.0 + growth, sub(year, years[0]))).astype(int)
            frames.append(part)
    table = pd.concat(frames, ignore_index=True)
    table = table.merge(timing, on=["intersection_id", "analysis_period", "nema_phase"], how="left")
    table = table.merge(inter, on="intersection_id", how="left")

    flow = table["demand_vph"] / table["peak_hour_factor"]
    g_eff = hcm.effective_green(table["green_s"], table["yellow_s"], table["red_clearance_s"])
    capacity = table["sat_flow_vph"] * g_eff / table["cycle_length_s"]
    vc = flow / capacity
    delay = hcm.control_delay(table["cycle_length_s"], g_eff, capacity, vc)
    queue = hcm.back_of_queue_ft(flow, table["cycle_length_s"], g_eff, vc, table["num_lanes"])

    table["saturation_flow_vph"] = np.round(table["sat_flow_vph"]).astype(int)
    table["capacity_vph"] = np.round(capacity).astype(int)
    table["vc_ratio"] = np.round(vc, 3)
    table["control_delay_s"] = np.round(delay, 1)
    table["los"] = hcm.level_of_service(delay, vc)
    table["back_of_queue_ft"] = np.round(queue, 1)
    table["queue_storage_ratio"] = np.round(queue / table["storage_length_ft"], 3)
    table["yellow_shortfall_s"] = np.round(np.maximum(vsub(table["required_yellow_s"], table["yellow_s"]), 0.0), 2)
    table["red_clearance_shortfall_s"] = np.round(
        np.maximum(vsub(table["required_red_clearance_s"], table["red_clearance_s"]), 0.0), 2)
    ordered = [
        "scenario_year", "analysis_period", "timing_plan_id", "state_code", "jurisdiction_code", "jurisdiction_name",
        "intersection_id", "intersection_name", "corridor", "area_type", "control_type", "controller_standard",
        "timing_practice", "nema_phase", "ring", "barrier", "movement", "approach", "lane_group_kind", "num_lanes",
        "lane_width_ft", "storage_length_ft", "grade_pct", "grade_direction", "intersection_width_ft",
        "posted_speed_mph", "speed_85th_mph", "clearance_speed_mph", "demand_vph", "heavy_vehicle_pct",
        "bicycles_vph", "buses_per_hr", "peak_hour_factor", "cycle_length_s", "offset_s", "split_s", "green_s",
        "yellow_s", "red_clearance_s", "min_green_s", "passage_time_s", "saturation_flow_vph", "capacity_vph",
        "vc_ratio", "control_delay_s", "los", "back_of_queue_ft", "queue_storage_ratio", "required_yellow_s",
        "required_red_clearance_s", "yellow_shortfall_s", "red_clearance_shortfall_s",
    ]
    table = table[ordered].sort_values(["scenario_year", "intersection_id", "timing_plan_id", "nema_phase"])
    return table.reset_index(drop=True), timing


def _timeline(plan, t0_ms, cycle_ms, deviation):
    """Interval rows for one window. deviation applies to the crash cycle only."""
    rows = []
    for k in range(WINDOW_CYCLES):
        start = t0_ms + k * cycle_ms
        dur = {p: [int(round(plan[p]["green_s"] * 1000)), int(round(plan[p]["yellow_s"] * 1000)),
                   int(round(plan[p]["red_clearance_s"] * 1000))] for p in PHASES}
        if deviation and k == CRASH_CYCLE:
            p = deviation["phase"]
            if deviation["kind"] == "YELLOW_TRUNCATED":
                dur[p][1] = sub(dur[p][1], deviation["cut_ms"])
                dur[p][2] = dur[p][2] + deviation["cut_ms"]
            elif deviation["kind"] == "RED_CLEARANCE_OMITTED":
                order = RING_ORDER[PHASES[p]["ring"]]
                nxt = order[order.index(p) + 1]
                dur[nxt][0] = dur[nxt][0] + dur[p][2]
                dur[p][2] = 0
        for ring, order in RING_ORDER.items():
            cursor = start
            barrier_start = {"A": start}
            for p in order:
                if PHASES[p]["barrier"] == "B" and "B" not in barrier_start:
                    ring1_a = sum(sum(dur[q]) for q in (1, 2))
                    ring2_a = sum(sum(dur[q]) for q in (5, 6))
                    barrier_start["B"] = start + max(ring1_a, ring2_a)
                    cursor = barrier_start["B"]
                for interval, length in zip(("GREEN", "YELLOW", "RED_CLEARANCE"), dur[p]):
                    prog = {"GREEN": plan[p]["green_s"], "YELLOW": plan[p]["yellow_s"],
                            "RED_CLEARANCE": plan[p]["red_clearance_s"]}[interval]
                    rows.append({"cycle_seq": k + 1, "ring": ring, "nema_phase": p, "interval_type": interval,
                                 "start_epoch_ms": cursor, "end_epoch_ms": cursor + length,
                                 "displayed_duration_ms": length, "programmed_duration_ms": int(round(prog * 1000))})
                    cursor = cursor + length
    return rows


def _pick_day(rng, weekend):
    while True:
        day = int(rng.integers(0, 731))
        weekday = day % 7  # 2024/01/01 was a Monday, so 5 and 6 are Saturday and Sunday
        if (weekday >= 5) == weekend:
            return EPOCH_2024_MS + day * DAY_MS


def _stopping(speed_mph, lg, policy):
    grade = 0.0 if lg["grade_direction"] == "level" else lg["grade_pct"] / 100.0
    if lg["grade_direction"] == "downhill":
        grade = sub(0.0, grade)
    return hcm.stopping_distance_ft(speed_mph, grade, policy.reaction_time_s, policy.deceleration_ftps2)


def build_incidents(inter, hcs, rng, crash_count):
    """Crash telemetry plus the controller, detector and MMU logs that surround it."""
    base = hcs[hcs["scenario_year"] == hcs["scenario_year"].min()]
    lanes = base.drop_duplicates(["intersection_id", "nema_phase"]).set_index(["intersection_id", "nema_phase"])
    plans = {(r.intersection_id, r.analysis_period): {} for r in base.itertuples(index=False)}
    for r in base.itertuples(index=False):
        plans[(r.intersection_id, r.analysis_period)][r.nema_phase] = {
            "green_s": r.green_s, "yellow_s": r.yellow_s, "red_clearance_s": r.red_clearance_s,
            "cycle_length_s": r.cycle_length_s, "timing_plan_id": r.timing_plan_id}
    info = inter.set_index("intersection_id")

    tol = 0.02
    pools = {
        "COMPLIANT_RED_ENTRY": [k for k, r in lanes.iterrows() if r["yellow_shortfall_s"] <= tol],
        "LAWFUL_ENTRY": [k for k, r in lanes.iterrows() if r["yellow_shortfall_s"] <= tol],
        "DESIGN_DEFICIENT": [k for k, r in lanes.iterrows() if r["yellow_shortfall_s"] >= 0.3],
        "CONTROLLER_DEVIATION": [k for k, r in lanes.iterrows() if r["yellow_shortfall_s"] <= tol and k[1] in (1, 2, 3, 5, 6, 7)],
        "DETECTOR_FAULT": [k for k, r in lanes.iterrows() if r["yellow_shortfall_s"] <= tol
                           and r["lane_group_kind"] == "through_right" and info.at[k[0], "control_type"] != "Pretimed"],
    }
    mix = {"COMPLIANT_RED_ENTRY": 0.34, "LAWFUL_ENTRY": 0.14, "DESIGN_DEFICIENT": 0.18,
           "CONTROLLER_DEVIATION": 0.18, "DETECTOR_FAULT": 0.16}
    names = list(mix)

    crashes, events, faults, mmu = [], [], [], []
    event_counter, fault_counter, mmu_counter = 1, 1, 1
    crash_times = {}
    attempts = 0
    while len(crashes) < crash_count and attempts < crash_count * 40:
        attempts += 1
        truth = _choice(rng, names, [mix[n] for n in names])
        pool = pools[truth]
        if not pool:
            continue
        iid, phase = pool[int(rng.integers(0, len(pool)))]
        lg = lanes.loc[(iid, phase)]
        local = LOCALS[info.at[iid, "jurisdiction_code"]]
        policy = STATES[local.state_code]
        period = _choice(rng, list(PERIODS))
        meta = PERIODS[period]
        plan = plans[(iid, period)]
        cycle_ms = int(round(plan[1]["cycle_length_s"] * 1000))
        day = _pick_day(rng, meta["weekend"])
        t0 = day + int(rng.integers(meta["hours"][0], meta["hours"][1] + 1)) * HOUR_MS + int(rng.integers(0, 45 * 60000))

        deviation = None
        if truth == "CONTROLLER_DEVIATION":
            if rng.random() < 0.6:
                cut = int(round(float(rng.uniform(0.6, 1.6)) * 1000))
                cut = min(cut, sub(int(round(plan[phase]["yellow_s"] * 1000)), 1600))
                if cut < 400:
                    continue
                deviation = {"phase": phase, "kind": "YELLOW_TRUNCATED", "cut_ms": cut}
            else:
                if plan[phase]["red_clearance_s"] < 0.8:
                    continue
                deviation = {"phase": phase, "kind": "RED_CLEARANCE_OMITTED", "cut_ms": int(round(plan[phase]["red_clearance_s"] * 1000))}

        timeline = _timeline(plan, t0, cycle_ms, deviation)
        mine = {row["interval_type"]: row for row in timeline if row["cycle_seq"] == CRASH_CYCLE + 1 and row["nema_phase"] == phase}
        onset = mine["YELLOW"]["start_epoch_ms"]
        yd_s = mine["YELLOW"]["displayed_duration_ms"] / 1000.0
        red_onset = mine["YELLOW"]["end_epoch_ms"]
        conflicting = RING_ORDER[PHASES[phase]["ring"]][(RING_ORDER[PHASES[phase]["ring"]].index(phase) + 1) % 4]

        crash_type = "ANGLE"
        if truth == "COMPLIANT_RED_ENTRY":
            v = max(20.0, lg["posted_speed_mph"] + float(rng.normal(3.0, 3.0)))
            after_red = max(float(rng.uniform(0.3, 3.0)), sub(5.8, yd_s))
            dist = v * 1.467 * (yd_s + after_red)
            if dist < _stopping(v, lg, policy) * 1.05:
                continue
            entry = red_onset + int(after_red * 1000)
        elif truth == "LAWFUL_ENTRY":
            v = max(20.0, lg["posted_speed_mph"] + float(rng.normal(2.0, 3.0)))
            if rng.random() < 0.35:
                entry = sub(onset, int(float(rng.uniform(0.5, 3.0)) * 1000))
            else:
                entry = onset + int(float(rng.uniform(0.2, max(0.3, sub(yd_s, 0.25)))) * 1000)
            crash_type = "LEFT_TURN"
            conflicting = OPPOSING[phase]
        elif truth in ("DESIGN_DEFICIENT", "CONTROLLER_DEVIATION") and not (
                deviation and deviation["kind"] == "RED_CLEARANCE_OMITTED"):
            v = lg["clearance_speed_mph"] + float(rng.uniform(0.0, 3.0))
            if lg["lane_group_kind"] == "left":
                v = lg["clearance_speed_mph"] + float(rng.uniform(0.0, 2.0))
            stop_need = _stopping(v, lg, policy)
            reach = v * 1.467 * yd_s
            if stop_need <= reach * 1.04:
                continue
            dist = reach + float(rng.uniform(0.25, 0.8)) * sub(stop_need, reach)
            entry = onset + int(dist / (v * 1.467) * 1000)
        elif truth == "CONTROLLER_DEVIATION":
            v = max(20.0, lg["posted_speed_mph"] + float(rng.normal(2.0, 2.5)))
            entry = red_onset + int(float(rng.uniform(0.1, 0.6)) * 1000)
        else:
            v = max(25.0, lg["posted_speed_mph"] + float(rng.normal(3.0, 2.5)))
            low = max(yd_s + 0.25, 2.7)
            if low >= 5.3:
                continue
            travel = float(rng.uniform(low, 5.3))
            entry = onset + int(travel * 1000)
            if entry <= red_onset:
                continue

        ref = sub(entry, int(rng.integers(4000, 6001)))
        fps = v * 1.467
        dist_ref = fps * ms_between_s(entry, ref)
        impact = entry + int((lg["intersection_width_ft"] * 0.5 + 10.0) / fps * 1000)
        crash_id = "CR" + str(len(crashes) + 1).zfill(5)

        detector_active_window = None
        if truth == "DETECTOR_FAULT":
            start = sub(impact, int(float(rng.uniform(30, 240)) * HOUR_MS))
            detected = start + int(float(rng.uniform(5, 90)) * 60000)
            cleared = impact + int(float(rng.uniform(3, 48)) * HOUR_MS)
            faults.append(_fault_row(fault_counter, iid, phase, start, detected, cleared, rng, "CONTROLLER_DIAGNOSTIC"))
            fault_counter += 1
            detector_active_window = (start, cleared)

        mmu_trip = None
        if deviation and deviation["kind"] == "YELLOW_TRUNCATED":
            if yd_s < config.TOLERANCES.mmu_min_yellow_threshold_s and rng.random() < 0.55:
                mmu_trip = red_onset
                mmu.append({"mmu_event_id": "MMU" + str(mmu_counter).zfill(6), "intersection_id": iid,
                            "event_epoch_ms": red_onset, "event_stamp": ms_to_stamp(red_onset),
                            "event_type": "MIN_YELLOW_CHANGE_FAULT", "channel": phase, "nema_phase": phase,
                            "measured_duration_ms": int(yd_s * 1000),
                            "threshold_ms": int(config.TOLERANCES.mmu_min_yellow_threshold_s * 1000),
                            "resulting_state": "FAULT_FLASH"})
                mmu_counter += 1

        for row in timeline:
            det = "N"
            if detector_active_window and row["nema_phase"] == phase:
                if row["end_epoch_ms"] > detector_active_window[0] and row["start_epoch_ms"] < detector_active_window[1]:
                    det = "Y"
            state = "FAULT_FLASH" if (mmu_trip and row["start_epoch_ms"] >= mmu_trip) else "NORMAL"
            start_code, end_code = HIRES_CODES[row["interval_type"]]
            events.append({
                "event_id": "EV" + str(event_counter).zfill(7), "window_id": crash_id, "intersection_id": iid,
                "controller_id": info.at[iid, "controller_id"], "timing_plan_id": plan[1]["timing_plan_id"],
                "cycle_seq": row["cycle_seq"], "ring": row["ring"], "nema_phase": row["nema_phase"],
                "movement": PHASES[row["nema_phase"]]["movement"], "interval_type": row["interval_type"],
                "hires_start_event_code": start_code, "hires_end_event_code": end_code,
                "start_epoch_ms": row["start_epoch_ms"], "end_epoch_ms": row["end_epoch_ms"],
                "start_stamp": ms_to_stamp(row["start_epoch_ms"]), "end_stamp": ms_to_stamp(row["end_epoch_ms"]),
                "displayed_duration_ms": row["displayed_duration_ms"],
                "programmed_duration_ms": row["programmed_duration_ms"],
                "detector_fault_active": det, "mmu_state": state,
            })
            event_counter += 1

        entry_recorded = entry + int(rng.integers(0, 41))
        weather = _choice(rng, ["CLEAR", "CLOUDY", "RAIN", "FOG", "SNOW"], [0.55, 0.2, 0.17, 0.04, 0.04])
        crashes.append({
            "crash_id": crash_id, "intersection_id": iid, "state_code": local.state_code,
            "jurisdiction_code": local.jurisdiction_code, "analysis_period": period,
            "crash_epoch_ms": impact, "crash_stamp": ms_to_stamp(impact), "crash_type": crash_type,
            "severity_kabco": _choice(rng, ["K", "A", "B", "C", "O"], [0.02, 0.08, 0.2, 0.3, 0.4]),
            "vehicles_involved": int(_choice(rng, [2, 2, 2, 3, 4])),
            "subject_phase": phase, "subject_movement": PHASES[phase]["movement"],
            "subject_approach": PHASES[phase]["approach"], "conflicting_phase": conflicting,
            "telemetry_source": _choice(rng, ["EVENT_DATA_RECORDER", "VIDEO_ANALYTICS", "CONNECTED_VEHICLE"], [0.5, 0.3, 0.2]),
            "telemetry_ref_epoch_ms": ref, "telemetry_ref_stamp": ms_to_stamp(ref),
            "speed_at_ref_mph": round(v + float(rng.normal(0.0, 0.6)), 1),
            "dist_to_stop_line_at_ref_ft": round(max(1.0, dist_ref + float(rng.normal(0.0, 1.5))), 1),
            "stop_line_entry_epoch_ms": entry_recorded, "stop_line_entry_stamp": ms_to_stamp(entry_recorded),
            "weather": weather,
            "lighting": "DAYLIGHT" if 7 <= ((ref % DAY_MS) // HOUR_MS) <= 18 else "DARK_LIGHTED",
            "surface": SURFACE_BY_WEATHER[weather] if weather in ("RAIN", "SNOW") else _choice(rng, ["DRY", "WET"], [0.93, 0.07]),
            "scenario_truth": truth,
            "truth_deviation_kind": deviation["kind"] if deviation else "NONE",
        })
        crash_times.setdefault(iid, []).append(impact)

    faults.extend(_background_faults(inter, crash_times, rng, fault_counter, 1400))
    mmu.extend(_background_mmu(inter, crash_times, rng, mmu_counter, 380))
    return pd.DataFrame(crashes), pd.DataFrame(events), pd.DataFrame(faults), pd.DataFrame(mmu)


def ms_between_s(later_ms, earlier_ms):
    return sub(later_ms, earlier_ms) / 1000.0


def _fault_row(counter, iid, phase, start, detected, cleared, rng, reporter):
    return {
        "fault_id": "DF" + str(counter).zfill(6), "intersection_id": iid,
        "detector_channel": phase * 2, "nema_phase": phase, "detector_function": "ADVANCE",
        "detector_type": "Inductive Loop", "fault_code": _choice(rng, FAULT_CODES),
        "fault_start_epoch_ms": start, "fault_detected_epoch_ms": detected, "fault_cleared_epoch_ms": cleared,
        "fault_start_stamp": ms_to_stamp(start), "fault_detected_stamp": ms_to_stamp(detected),
        "fault_cleared_stamp": ms_to_stamp(cleared), "fallback_mode": "MAX_RECALL",
        "work_order_id": "WO" + str(counter).zfill(6), "reported_by": reporter,
    }


def _far_from_crashes(iid, moment, crash_times, days=12):
    return all(abs(sub(moment, t)) > days * DAY_MS for t in crash_times.get(iid, []))


def _background_faults(inter, crash_times, rng, counter, count):
    rows, ids = [], inter["intersection_id"].tolist()
    while len(rows) < count:
        iid = ids[int(rng.integers(0, len(ids)))]
        start = EPOCH_2024_MS + int(rng.integers(0, 730)) * DAY_MS + int(rng.integers(0, 24)) * HOUR_MS
        if not _far_from_crashes(iid, start, crash_times):
            continue
        phase = int(rng.integers(1, 9))
        detected = start + int(float(rng.uniform(1, 240)) * 60000)
        cleared = detected + int(float(rng.uniform(1, 120)) * HOUR_MS)
        row = _fault_row(counter, iid, phase, start, detected, cleared, rng,
                         _choice(rng, ["CONTROLLER_DIAGNOSTIC", "FIELD_CREW", "PUBLIC_REPORT"], [0.7, 0.2, 0.1]))
        row["detector_function"] = _choice(rng, ["ADVANCE", "STOP_BAR"], [0.45, 0.55])
        row["detector_channel"] = phase * 2 if row["detector_function"] == "ADVANCE" else sub(phase * 2, 1)
        rows.append(row)
        counter += 1
    return rows


def _background_mmu(inter, crash_times, rng, counter, count):
    rows, ids = [], inter["intersection_id"].tolist()
    kinds = ["PORT1_TIMEOUT", "CONFLICT", "RED_FAIL", "VOLTAGE_MONITOR", "MIN_YELLOW_CHANGE_FAULT"]
    while len(rows) < count:
        iid = ids[int(rng.integers(0, len(ids)))]
        moment = EPOCH_2024_MS + int(rng.integers(0, 730)) * DAY_MS + int(rng.integers(0, DAY_MS))
        if not _far_from_crashes(iid, moment, crash_times):
            continue
        kind = _choice(rng, kinds, [0.3, 0.2, 0.25, 0.15, 0.1])
        phase = int(rng.integers(1, 9))
        rows.append({"mmu_event_id": "MMU" + str(counter).zfill(6), "intersection_id": iid,
                     "event_epoch_ms": moment, "event_stamp": ms_to_stamp(moment), "event_type": kind,
                     "channel": phase, "nema_phase": phase,
                     "measured_duration_ms": int(rng.integers(1800, 2690)) if kind == "MIN_YELLOW_CHANGE_FAULT" else 0,
                     "threshold_ms": int(config.TOLERANCES.mmu_min_yellow_threshold_s * 1000) if kind == "MIN_YELLOW_CHANGE_FAULT" else 0,
                     "resulting_state": "FAULT_FLASH"})
        counter += 1
    return rows


def generate(intersection_count=170, crash_count=520, seed=20260930, years=(2023, 2030, 2035)):
    """Generate and persist every dataset. Returns a dict of table name to row count."""
    rng = np.random.default_rng(seed)
    inter, lane_groups = build_intersections(rng, intersection_count)
    lane_groups = program_clearances(inter, lane_groups, rng)
    hcs, timing = build_hcs_table(inter, lane_groups, list(years), rng)
    crashes, events, faults, mmu = build_incidents(inter, hcs, rng, crash_count)

    geometry_cols = ["intersection_id", "nema_phase", "movement", "approach", "lane_group_kind", "ring", "barrier",
                     "num_lanes", "lane_width_ft", "storage_length_ft", "grade_pct", "grade_direction",
                     "intersection_width_ft", "posted_speed_mph", "speed_85th_mph", "heavy_vehicle_pct",
                     "yellow_s", "red_clearance_s"]
    outputs = {
        "hcs_streets_export": hcs,
        "intersections": inter,
        "lane_group_geometry": lane_groups[geometry_cols],
        "signal_timing_plans": timing.merge(lane_groups[["intersection_id", "nema_phase", "yellow_s", "red_clearance_s"]],
                                            on=["intersection_id", "nema_phase"]),
        "signal_event_log": events,
        "detector_faults": faults.sort_values("fault_start_epoch_ms").reset_index(drop=True),
        "mmu_events": mmu.sort_values("event_epoch_ms").reset_index(drop=True),
        "crash_events": crashes,
        "jurisdiction_policy": pd.DataFrame(policy_rows()),
    }
    counts = {}
    for name, frame in outputs.items():
        frame.to_csv(config.RAW_DIR / (name + ".csv"), index=False, float_format="%.4f", encoding="utf8")
        counts[name] = {"rows": int(len(frame)), "columns": int(frame.shape[1])}
        LOG.info("Wrote %s: %d rows x %d columns", name, len(frame), frame.shape[1])
    from .policydocs import write_policy_documents
    write_policy_documents()
    return counts


def export_excel(path=None):
    """Write the HCS style export plus summary sheets to an Excel workbook."""
    path = path or (config.PROCESSED_DIR / "hcs_streets_export.xlsx")
    hcs = pd.read_csv(config.RAW_DIR / "hcs_streets_export.csv")
    summary = (hcs.groupby(["scenario_year", "analysis_period"])
               .agg(lane_groups=("intersection_id", "size"), mean_delay_s=("control_delay_s", "mean"),
                    share_los_f=("los", lambda s: float((s == "F").mean())),
                    mean_vc=("vc_ratio", "mean"))
               .round(3).reset_index())
    deficits = hcs[(hcs["scenario_year"] == hcs["scenario_year"].min()) & (hcs["yellow_shortfall_s"] > 0)]
    deficits = deficits.drop_duplicates(["intersection_id", "nema_phase"])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        hcs.to_excel(writer, sheet_name="streets_export", index=False)
        summary.to_excel(writer, sheet_name="scenario_summary", index=False)
        deficits.to_excel(writer, sheet_name="clearance_deficits", index=False)
    LOG.info("Excel workbook written to %s", path)
    return path


def column_count_ok(frame, minimum_rows=15000, minimum_cols=16):
    return len(frame) >= minimum_rows and frame.shape[1] >= minimum_cols

