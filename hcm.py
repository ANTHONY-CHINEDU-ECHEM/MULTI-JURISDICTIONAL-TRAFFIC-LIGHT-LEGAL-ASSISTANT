"""Engineering equations.

Signalized lane group performance follows the Highway Capacity Manual (HCM)
lane group method in the simplified form used for planning level HCS style
exports: adjusted saturation flow, capacity, volume to capacity ratio, uniform
plus incremental control delay, level of service and a back of queue estimate.

Clearance intervals follow the Institute of Transportation Engineers kinematic
formulation:

    yellow = t + v / (2a + 2Gg)
    red clearance = (W + L) / v

where t is perception reaction time (s), v approach speed (ft/s), a
deceleration (ft/s2), G approach grade as a decimal (downhill negative), g
gravitational acceleration, W intersection width (ft) and L vehicle length (ft).
"""

import numpy as np

from .config import KINEMATICS
from .utils import sub, vneg, vsub

BASE_SATURATION_FLOW = 1900.0
LOST_TIME_PER_PHASE_S = 4.0
ANALYSIS_PERIOD_H = 0.25
LOS_THRESHOLDS = ((10.0, "A"), (20.0, "B"), (35.0, "C"), (55.0, "D"), (80.0, "E"))


def signed_grade(grade_pct, direction):
    """Convert an absolute grade and an uphill/downhill label to a signed decimal."""
    grade = np.asarray(grade_pct, dtype=float) / 100.0
    downhill = np.asarray(direction) == "downhill"
    return np.where(downhill, vneg(grade), grade)


def ite_yellow(speed_mph, grade_pct, direction, reaction_s=None, decel_ftps2=None):
    """ITE kinematic yellow change interval in seconds."""
    t = KINEMATICS.default_perception_reaction_s if reaction_s is None else reaction_s
    a = KINEMATICS.default_deceleration_ftps2 if decel_ftps2 is None else decel_ftps2
    v = np.asarray(speed_mph, dtype=float) * KINEMATICS.mph_to_ftps
    g = signed_grade(grade_pct, direction)
    return t + v / (2.0 * a + 2.0 * g * KINEMATICS.gravity_ftps2)


def ite_red_clearance(speed_mph, width_ft, vehicle_length_ft=None):
    """ITE red clearance interval in seconds."""
    length = KINEMATICS.vehicle_length_ft if vehicle_length_ft is None else vehicle_length_ft
    v = np.asarray(speed_mph, dtype=float) * KINEMATICS.mph_to_ftps
    return (np.asarray(width_ft, dtype=float) + length) / v


def stopping_distance_ft(speed_mph, grade_decimal, reaction_s, decel_ftps2):
    """Distance needed to stop comfortably from the onset of yellow."""
    v = speed_mph * KINEMATICS.mph_to_ftps
    effective = decel_ftps2 + grade_decimal * KINEMATICS.gravity_ftps2
    return v * reaction_s + (v * v) / (2.0 * max(effective, 1.0))


def adjusted_saturation_flow(num_lanes, lane_width_ft, heavy_pct, grade_pct, direction, movement_kind, cbd):
    """HCM adjusted saturation flow rate (veh/h) for a lane group."""
    f_w = 1.0 + vsub(np.asarray(lane_width_ft, dtype=float), 12.0) / 30.0
    f_hv = 100.0 / (100.0 + np.asarray(heavy_pct, dtype=float))
    f_g = vsub(1.0, signed_grade(grade_pct, direction) * 100.0 / 200.0)
    f_a = np.where(np.asarray(cbd, dtype=bool), 0.90, 1.0)
    kind = np.asarray(movement_kind)
    f_turn = np.where(kind == "left", 0.95, np.where(kind == "through_right", 0.97, 1.0))
    return BASE_SATURATION_FLOW * np.asarray(num_lanes, dtype=float) * f_w * f_hv * f_g * f_a * f_turn


def effective_green(green_s, yellow_s, red_clearance_s):
    total = np.asarray(green_s, dtype=float) + np.asarray(yellow_s, dtype=float) + np.asarray(red_clearance_s, dtype=float)
    return np.maximum(vsub(total, LOST_TIME_PER_PHASE_S), 1.0)


def control_delay(cycle_s, g_eff, capacity, vc, k=0.5):
    """Uniform (d1) plus incremental (d2) delay in seconds per vehicle."""
    cycle_s = np.asarray(cycle_s, dtype=float)
    ratio = g_eff / cycle_s
    x_capped = np.minimum(vc, 1.0)
    d1 = 0.5 * cycle_s * np.square(vsub(1.0, ratio)) / np.maximum(vsub(1.0, x_capped * ratio), 0.0001)
    xm1 = vsub(vc, 1.0)
    term = np.sqrt(np.square(xm1) + (8.0 * k * vc) / np.maximum(capacity * ANALYSIS_PERIOD_H, 1.0))
    d2 = 900.0 * ANALYSIS_PERIOD_H * (xm1 + term)
    return d1 + np.maximum(d2, 0.0)


def level_of_service(delay_s, vc):
    """HCM signalized LOS; any lane group with v/c above 1.0 is LOS F."""
    out = []
    for d, x in zip(np.asarray(delay_s, dtype=float), np.asarray(vc, dtype=float)):
        if x > 1.0:
            out.append("F")
            continue
        grade = "F"
        for limit, letter in LOS_THRESHOLDS:
            if d <= limit:
                grade = letter
                break
        out.append(grade)
    return np.array(out)


def back_of_queue_ft(flow_vph, cycle_s, g_eff, vc, num_lanes, spacing_ft=25.0):
    """Planning level 95th percentile back of queue per lane in feet."""
    arrivals_per_s = np.asarray(flow_vph, dtype=float) / 3600.0
    red = vsub(np.asarray(cycle_s, dtype=float), g_eff)
    uniform = arrivals_per_s * red / np.maximum(vsub(1.0, np.minimum(vc, 0.98) * g_eff / cycle_s), 0.02)
    overflow = np.maximum(vsub(vc, 1.0), 0.0) * np.asarray(flow_vph, dtype=float) * ANALYSIS_PERIOD_H
    per_lane = (uniform + overflow) / np.maximum(np.asarray(num_lanes, dtype=float), 1.0)
    return per_lane * 1.65 * spacing_ft


def clearing_distance_ft(speed_mph, displayed_yellow_s):
    """Distance a vehicle travels during the displayed yellow at constant speed."""
    return speed_mph * KINEMATICS.mph_to_ftps * displayed_yellow_s


def dilemma_zone(speed_mph, distance_at_onset_ft, displayed_yellow_s, grade_decimal, reaction_s, decel_ftps2):
    """Classify the vehicle position at yellow onset.

    Returns a dict with can_stop, can_reach_stop_line_on_yellow and trapped
    (a Type I dilemma zone: neither stopping nor legally entering is possible).
    """
    stop_needed = stopping_distance_ft(speed_mph, grade_decimal, reaction_s, decel_ftps2)
    reach = clearing_distance_ft(speed_mph, displayed_yellow_s)
    can_stop = distance_at_onset_ft >= stop_needed
    can_enter = distance_at_onset_ft <= reach
    return {
        "stopping_distance_ft": round(float(stop_needed), 1),
        "yellow_travel_distance_ft": round(float(reach), 1),
        "can_stop": bool(can_stop),
        "can_reach_stop_line_on_yellow": bool(can_enter),
        "trapped_in_dilemma_zone": bool((not can_stop) and (not can_enter)),
        "dilemma_zone_length_ft": round(max(0.0, float(sub(stop_needed, reach))), 1),
    }
