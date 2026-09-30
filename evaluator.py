"""Millisecond level clearance interval evaluation for a single crash.

The evaluator joins three kinds of evidence:

1. Structured facts from SQLite: the interval every phase displayed at the
   stop line entry millisecond, the programmed timing plan, the displayed
   durations in neighbouring cycles, detector faults and MMU events.
2. Engineering computation: the governing clearance requirements (federal,
   state and local layers) and the dilemma zone position of the vehicle at
   yellow onset, reconstructed from the telemetry reference point.
3. Unstructured authority: for every check, pinned citations to the
   provision that creates the duty plus hierarchical retrieval restricted to
   the jurisdiction that owns the intersection.

The output is a structured finding set with a verdict. It is decision
support for engineers and counsel, not a legal conclusion.
"""

from . import config
from .hcm import dilemma_zone
from .jurisdictions import LOCALS, STATES, governing_requirements
from .retriever import HierarchicalRetriever
from .store import StructuredRetriever
from .utils import gap, ms_between, ms_to_stamp, shortfall, sub, surplus

T = config.TOLERANCES
K = config.KINEMATICS

VERDICTS = {
    "CONTROLLER_TIMING_DEVIATION": "Displayed clearance timing deviated from the programmed timing plan in the crash cycle",
    "YELLOW_TIMING_BELOW_REQUIREMENT": "Programmed yellow change interval was below the governing requirement and the vehicle was trapped in a dilemma zone",
    "DETECTION_SYSTEM_FAULT": "An active detector fault removed dilemma zone protection while the vehicle was in the indecision zone",
    "NO_SIGNAL_DEFICIENCY_RED_ENTRY": "Clearance timing met every governing requirement; the vehicle entered on red after it could have stopped",
    "NO_SIGNAL_DEFICIENCY_LAWFUL_ENTRY": "Clearance timing met every governing requirement; the vehicle entered lawfully on green or yellow",
    "INDETERMINATE": "The logs do not cover the stop line entry time, so no timing finding can be made",
}
TRUTH_TO_VERDICT = {
    "COMPLIANT_RED_ENTRY": "NO_SIGNAL_DEFICIENCY_RED_ENTRY",
    "LAWFUL_ENTRY": "NO_SIGNAL_DEFICIENCY_LAWFUL_ENTRY",
    "DESIGN_DEFICIENT": "YELLOW_TIMING_BELOW_REQUIREMENT",
    "CONTROLLER_DEVIATION": "CONTROLLER_TIMING_DEVIATION",
    "DETECTOR_FAULT": "DETECTION_SYSTEM_FAULT",
}

PINS = {
    "MUTCD_YELLOW_RANGE": [("MUTCD11", "4F.17", "13")],
    "YELLOW_CONSISTENCY": [("MUTCD11", "4F.17", "08"), ("MUTCD11", "4F.17", "07"), ("STATE", "Clause 3.4", "01"),
                           ("STATE", "Clause 3.4", "02"), ("MUTCD11", "4A.10", "02")],
    "RED_CLEARANCE_CONSISTENCY": [("MUTCD11", "4F.17", "09"), ("MUTCD11", "4F.17", "10"), ("STATE", "Clause 3.4", "01")],
    "YELLOW_REQUIREMENT": [("MUTCD11", "4F.17", "03"), ("STATE", "Clause 3.2", "01"), ("STATE", "Clause 3.2", "02"),
                           ("LOCAL", "Section 1.02", "01"), ("LOCAL", "Section 1.04", "01"), ("LOCAL", "Section 1.05", "01"),
                           ("STATE", "Clause 3.1", "01")],
    "RED_CLEARANCE_REQUIREMENT": [("MUTCD11", "4F.17", "06"), ("MUTCD11", "4F.17", "05"), ("STATE", "Clause 3.3", "01"),
                                  ("LOCAL", "Section 1.03", "01")],
    "RED_CLEARANCE_MAXIMUM": [("MUTCD11", "4F.17", "13")],
    "DILEMMA_ZONE": [("MUTCD11", "4F.17", "01"), ("STATE", "Clause 3.2", "03")],
    "MMU_RESPONSE": [("NEMA_TS2", "4.4.5", "01"), ("NEMA_TS2", "2.3.8", "01"), ("STATE", "Clause 3.5", "01"),
                     ("MUTCD11", "4G.02", "01")],
    "DETECTOR_STATUS": [("STATE", "Clause 3.6", "01"), ("STATE", "Clause 3.6", "02"), ("LOCAL", "Section 1.06", "01"),
                        ("LOCAL", "Section 1.06", "02"), ("MUTCD11", "4A.10", "02"), ("NEMA_TS2", "6.5", "01")],
    "RECORDS": [("LOCAL", "Section 1.07", "01"), ("STATE", "Clause 3.5", "02")],
}
QUERIES = {
    "MUTCD_YELLOW_RANGE": "yellow change interval minimum 3 seconds maximum 6 seconds duration",
    "YELLOW_CONSISTENCY": "duration of yellow change interval shall not vary cycle by cycle same signal timing plan",
    "RED_CLEARANCE_CONSISTENCY": "red clearance interval shall not be decreased or omitted cycle by cycle",
    "YELLOW_REQUIREMENT": "yellow change interval duration determined engineering practices kinematic equation speed",
    "RED_CLEARANCE_REQUIREMENT": "red clearance interval duration engineering practices before conflicting movements released",
    "RED_CLEARANCE_MAXIMUM": "red clearance interval duration not exceeding 6 seconds",
    "DILEMMA_ZONE": "yellow change interval warn approaching traffic permission to proceed terminated stop",
    "MMU_RESPONSE": "malfunction management unit minimum yellow change red clearance interval monitoring",
    "DETECTOR_STATUS": "vehicle detector failure maintenance responsibility repair loop detector diagnostics",
    "RECORDS": "controller event logs retained preserved after crash",
}
INDECISION_ZONE_S = (2.5, 5.5)


class CrashEvaluator:
    def __init__(self, structured=None, retriever=None):
        self.db = structured or StructuredRetriever()
        self.rag = retriever or HierarchicalRetriever()

    def _resolve_doc(self, key, state_code, jurisdiction_code):
        if key == "STATE":
            return "STATE_" + state_code
        if key == "LOCAL":
            return "LOCAL_" + jurisdiction_code
        return key

    def evidence_for(self, check_id, state_code, jurisdiction_code, extra_query=""):
        items, seen = [], set()
        for doc_key, section_id, para_no in PINS.get(check_id, []):
            ev = self.rag.paragraph(self._resolve_doc(doc_key, state_code, jurisdiction_code), section_id, para_no)
            if ev:
                ev.score = 2.0
                items.append(ev)
                seen.add((ev.doc_id, ev.section_id, ev.para_no))
        query = (QUERIES.get(check_id, "") + " " + extra_query).strip()
        for ev in self.rag.retrieve(query, tiers=("FEDERAL", "STATE", "LOCAL", "HARDWARE"), state_code=state_code,
                                    jurisdiction_code=jurisdiction_code, k=4):
            key = (ev.doc_id, ev.section_id, ev.para_no)
            if key not in seen:
                items.append(ev)
                seen.add(key)
        return [e.as_dict() for e in items[:8]]

    def evaluate(self, crash_id, with_evidence=True):
        crash = self.db.crash(crash_id)
        if crash is None:
            raise KeyError("Unknown crash_id " + str(crash_id))
        iid, phase = crash["intersection_id"], int(crash["subject_phase"])
        inter = self.db.intersection(iid)
        lane = self.db.lane_group(iid, phase)
        local = LOCALS[crash["jurisdiction_code"]]
        state = STATES[local.state_code]
        window = crash_id
        entry = int(crash["stop_line_entry_epoch_ms"])

        yellows = self.db.phase_intervals(window, phase, "YELLOW")
        reds = self.db.phase_intervals(window, phase, "RED_CLEARANCE")
        if not yellows:
            return self._indeterminate(crash, "No controller log window was found for this crash")
        containing = self.db.interval_containing(window, phase, entry)
        indication = containing["interval_type"] if containing else "RED"
        if containing and containing["interval_type"] == "GREEN":
            relevant_yellow = next((y for y in yellows if y["start_epoch_ms"] >= containing["end_epoch_ms"]), yellows[len(yellows) // 2])
        else:
            relevant_yellow = self.db.last_interval_before(window, phase, "YELLOW", entry)
        if relevant_yellow is None:
            return self._indeterminate(crash, "Stop line entry precedes the logged window")
        cycle = relevant_yellow["cycle_seq"]
        relevant_red = next((r for r in reds if r["cycle_seq"] == cycle), None)
        onset = int(relevant_yellow["start_epoch_ms"])
        red_onset = int(relevant_yellow["end_epoch_ms"])
        displayed_yellow_s = relevant_yellow["displayed_duration_ms"] / 1000.0
        programmed_yellow_s = relevant_yellow["programmed_duration_ms"] / 1000.0
        displayed_red_s = (relevant_red["displayed_duration_ms"] / 1000.0) if relevant_red else 0.0
        programmed_red_s = (relevant_red["programmed_duration_ms"] / 1000.0) if relevant_red else 0.0

        grade_dir = "uphill" if lane["grade_direction"] == "level" else lane["grade_direction"]
        req = governing_requirements(local.jurisdiction_code, lane["posted_speed_mph"], lane["speed_85th_mph"],
                                     lane_kind(phase), lane["grade_pct"], grade_dir, lane["intersection_width_ft"])

        speed = float(crash["speed_at_ref_mph"])
        fps = speed * K.mph_to_ftps
        ref = int(crash["telemetry_ref_epoch_ms"])
        dist_ref = float(crash["dist_to_stop_line_at_ref_ft"])
        dist_onset = sub(dist_ref, fps * ms_between(onset, ref) / 1000.0)
        predicted_entry = ref + int(dist_ref / fps * 1000.0)
        telemetry_gap_ms = gap(predicted_entry, entry)
        travel_time_onset = dist_onset / fps if fps > 0 else 0.0
        grade_decimal = 0.0 if lane["grade_direction"] == "level" else lane["grade_pct"] / 100.0
        if lane["grade_direction"] == "downhill":
            grade_decimal = sub(0.0, grade_decimal)
        zone = dilemma_zone(speed, max(dist_onset, 0.0), displayed_yellow_s, grade_decimal,
                            state.reaction_time_s, state.deceleration_ftps2)
        entered_after_red = entry > red_onset
        zone["entered_after_red_onset_observed"] = bool(entered_after_red)
        zone["trapped_in_dilemma_zone"] = bool(dist_onset > 0 and not zone["can_stop"] and entered_after_red)
        flips = []
        for delta in (T.speed_uncertainty_mph, sub(0.0, T.speed_uncertainty_mph)):
            alt_speed = speed + delta
            alt_fps = alt_speed * K.mph_to_ftps
            alt_dist = sub(dist_ref, alt_fps * ms_between(onset, ref) / 1000.0)
            alt = dilemma_zone(alt_speed, max(alt_dist, 0.0), displayed_yellow_s, grade_decimal,
                               state.reaction_time_s, state.deceleration_ftps2)
            flips.append(alt["can_stop"] != zone["can_stop"])
        zone["sensitive_to_speed_uncertainty"] = bool(any(flips))

        other_yellows = [y["displayed_duration_ms"] for y in yellows if y["cycle_seq"] != cycle]
        other_reds = [r["displayed_duration_ms"] for r in reds if r["cycle_seq"] != cycle]
        yellow_deviation_ms = gap(relevant_yellow["displayed_duration_ms"], relevant_yellow["programmed_duration_ms"])
        red_deviation_ms = shortfall(programmed_red_s * 1000.0, displayed_red_s * 1000.0)
        yellow_cycle_spread_ms = sub(max(other_yellows + [relevant_yellow["displayed_duration_ms"]]),
                                     min(other_yellows + [relevant_yellow["displayed_duration_ms"]]))

        conflicting = int(crash["conflicting_phase"])
        conflict_green = next((g for g in self.db.phase_intervals(window, conflicting, "GREEN")
                               if g["start_epoch_ms"] >= red_onset), None)
        release_gap_s = (ms_between(conflict_green["start_epoch_ms"], red_onset) / 1000.0) if conflict_green else None

        faults = self.db.active_faults(iid, phase, entry)
        mmu = self.db.mmu_events(iid, sub(onset, 60000), red_onset + 600000)
        snapshot = self.db.state_at(iid, entry, window)

        checks = []

        def add(check_id, title, status, detail, measured=None, required=None):
            checks.append({"check_id": check_id, "title": title, "status": status, "detail": detail,
                           "measured": measured, "required": required})

        entry_after_red_s = ms_between(entry, red_onset) / 1000.0 if indication == "RED" or indication == "RED_CLEARANCE" else 0.0
        add("INDICATION_AT_ENTRY", "Signal indication at the stop line entry millisecond", "INFO",
            "Phase " + str(phase) + " (" + crash["subject_movement"] + ") was displaying " + indication
            + " at " + ms_to_stamp(entry) + ("" if indication in ("GREEN", "YELLOW")
                                              else ", " + fmt(entry_after_red_s) + " s after red onset") + ".",
            indication, "GREEN or YELLOW for lawful entry")

        in_range = T.mutcd_yellow_min_s <= programmed_yellow_s <= T.mutcd_yellow_max_s
        add("MUTCD_YELLOW_RANGE", "Programmed yellow within MUTCD guidance range", "PASS" if in_range else "FAIL",
            "Programmed yellow " + fmt(programmed_yellow_s) + " s against the 3 to 6 s Guidance range.",
            programmed_yellow_s, "3.0 to 6.0 s")

        consistent_y = yellow_deviation_ms <= T.consistency_tolerance_ms and yellow_cycle_spread_ms <= T.consistency_tolerance_ms
        add("YELLOW_CONSISTENCY", "Displayed yellow equals programmed yellow in every cycle of the plan",
            "PASS" if consistent_y else "FAIL",
            "Crash cycle displayed " + fmt(displayed_yellow_s) + " s versus programmed " + fmt(programmed_yellow_s)
            + " s; spread across " + str(len(yellows)) + " logged cycles is " + str(int(yellow_cycle_spread_ms)) + " ms.",
            displayed_yellow_s, programmed_yellow_s)

        consistent_r = red_deviation_ms <= T.consistency_tolerance_ms and all(
            r >= sub(int(programmed_red_s * 1000), T.consistency_tolerance_ms) for r in other_reds)
        add("RED_CLEARANCE_CONSISTENCY", "Red clearance not decreased or omitted in the crash cycle",
            "PASS" if consistent_r else "FAIL",
            "Crash cycle red clearance displayed " + fmt(displayed_red_s) + " s versus programmed "
            + fmt(programmed_red_s) + " s" + (" (omitted)" if displayed_red_s == 0 and programmed_red_s > 0 else "") + ".",
            displayed_red_s, programmed_red_s)

        y_short = shortfall(req["required_yellow_s"], programmed_yellow_s)
        y_ok = y_short <= T.requirement_tolerance_s
        add("YELLOW_REQUIREMENT", "Programmed yellow meets the governing federal, state and local requirement",
            "PASS" if y_ok else "FAIL",
            "Governing requirement " + fmt(req["required_yellow_s"]) + " s set by " + req["governing_yellow_source"]
            + " (clearance speed " + fmt(req["clearance_speed_mph"]) + " mph); programmed " + fmt(programmed_yellow_s)
            + " s, shortfall " + fmt(y_short) + " s.",
            programmed_yellow_s, req["required_yellow_s"])

        r_short = shortfall(req["required_red_clearance_s"], programmed_red_s)
        add("RED_CLEARANCE_REQUIREMENT", "Programmed red clearance meets the governing requirement",
            "PASS" if r_short <= T.requirement_tolerance_s else "FAIL",
            "Governing requirement " + fmt(req["required_red_clearance_s"]) + " s set by "
            + req["governing_red_clearance_source"] + "; programmed " + fmt(programmed_red_s) + " s.",
            programmed_red_s, req["required_red_clearance_s"])

        add("RED_CLEARANCE_MAXIMUM", "Red clearance does not exceed the 6 s MUTCD guidance",
            "PASS" if programmed_red_s <= T.mutcd_red_clearance_max_s else "FAIL",
            "Programmed red clearance " + fmt(programmed_red_s) + " s.", programmed_red_s, "6.0 s or less")

        if dist_onset <= 0:
            zone_status, zone_detail = "NOT_APPLICABLE", "The vehicle had already crossed the stop line when yellow began."
        else:
            zone_status = "FAIL" if zone["trapped_in_dilemma_zone"] else "PASS"
            zone_detail = ("At yellow onset the vehicle was " + fmt(dist_onset) + " ft from the stop line at "
                           + fmt(speed) + " mph. Stopping needed " + fmt(zone["stopping_distance_ft"])
                           + " ft; the displayed yellow allowed " + fmt(zone["yellow_travel_distance_ft"])
                           + " ft of travel. " + ("The vehicle could neither stop nor reach the stop line before red."
                                                   if zone["trapped_in_dilemma_zone"] else
                                                   ("The vehicle could stop comfortably." if zone["can_stop"]
                                                    else "The vehicle could reach the stop line during yellow."))
                           + (" This result changes within a speed uncertainty of " + fmt(T.speed_uncertainty_mph)
                              + " mph, so it is borderline." if zone["sensitive_to_speed_uncertainty"] else ""))
        add("DILEMMA_ZONE", "Type I dilemma zone at yellow onset", zone_status, zone_detail,
            round(max(dist_onset, 0.0), 1), zone["stopping_distance_ft"])

        in_indecision = INDECISION_ZONE_S[0] <= travel_time_onset <= INDECISION_ZONE_S[1]
        add("INDECISION_ZONE", "Type II indecision zone (2.5 to 5.5 s from the stop line at yellow onset)", "INFO",
            "Travel time to the stop line at yellow onset was " + fmt(max(travel_time_onset, 0.0)) + " s"
            + (", inside the indecision zone." if in_indecision else ", outside the indecision zone."),
            round(max(travel_time_onset, 0.0), 2), "2.5 to 5.5 s")

        below_mmu = displayed_yellow_s < T.mmu_min_yellow_threshold_s
        mmu_trip = [m for m in mmu if m["event_type"] == "MIN_YELLOW_CHANGE_FAULT" and int(m["nema_phase"]) == phase]
        if below_mmu:
            add("MMU_RESPONSE", "MMU minimum yellow change monitoring responded", "PASS" if mmu_trip else "FAIL",
                "Displayed yellow " + fmt(displayed_yellow_s) + " s is below the configured MMU threshold of "
                + fmt(T.mmu_min_yellow_threshold_s) + " s; " + ("the MMU logged MIN_YELLOW_CHANGE_FAULT and placed the "
                                                                 "intersection in flash." if mmu_trip else
                                                                 "no MMU fault was logged, indicating monitoring was "
                                                                 "disabled or the MMU failed to detect the short yellow."),
                displayed_yellow_s, T.mmu_min_yellow_threshold_s)
        else:
            add("MMU_RESPONSE", "MMU minimum yellow change monitoring responded", "NOT_APPLICABLE",
                "Displayed yellow was above the MMU minimum threshold, so no MMU trip was expected.",
                displayed_yellow_s, T.mmu_min_yellow_threshold_s)

        if faults:
            f = faults[0]
            hours_open = ms_between(entry, f["fault_detected_epoch_ms"]) / 3600000.0
            overdue = hours_open > local.detector_repair_hours
            add("DETECTOR_STATUS", "Detection serving the subject phase was healthy", "FAIL",
                f["fault_code"] + " on detector channel " + str(f["detector_channel"]) + " (" + f["detector_function"]
                + ") since " + f["fault_detected_stamp"] + "; fallback " + f["fallback_mode"] + ". The fault had been "
                "known for " + fmt(hours_open) + " h against a local repair limit of "
                + fmt(local.detector_repair_hours) + " h" + (", so the repair window was exceeded." if overdue else "."),
                round(hours_open, 1), local.detector_repair_hours)
        else:
            add("DETECTOR_STATUS", "Detection serving the subject phase was healthy", "PASS",
                "No detector fault was active on phase " + str(phase) + " at the entry millisecond.", 0, None)

        if release_gap_s is not None:
            add("CONFLICTING_RELEASE", "Time between subject red onset and conflicting green", "INFO",
                "Conflicting phase " + str(conflicting) + " received green " + fmt(release_gap_s)
                + " s after phase " + str(phase) + " turned red.", release_gap_s, programmed_red_s)

        add("TELEMETRY_CONSISTENCY", "Telemetry reconstruction agrees with the recorded stop line entry",
            "PASS" if telemetry_gap_ms <= 250 else "INFO",
            "Constant speed reconstruction predicts entry within " + str(int(telemetry_gap_ms)) + " ms of the recorded time.",
            int(telemetry_gap_ms), 250)

        status = {c["check_id"]: c["status"] for c in checks}
        deviation = status["YELLOW_CONSISTENCY"] == "FAIL" or status["RED_CLEARANCE_CONSISTENCY"] == "FAIL"
        if deviation and indication in ("RED", "RED_CLEARANCE", "YELLOW"):
            verdict = "CONTROLLER_TIMING_DEVIATION"
        elif status["YELLOW_REQUIREMENT"] == "FAIL" and status["DILEMMA_ZONE"] == "FAIL":
            verdict = "YELLOW_TIMING_BELOW_REQUIREMENT"
        elif faults and inter["control_type"] != "Pretimed" and in_indecision and indication != "GREEN":
            verdict = "DETECTION_SYSTEM_FAULT"
        elif indication in ("RED", "RED_CLEARANCE"):
            verdict = "NO_SIGNAL_DEFICIENCY_RED_ENTRY"
        else:
            verdict = "NO_SIGNAL_DEFICIENCY_LAWFUL_ENTRY"

        borderline = zone["sensitive_to_speed_uncertainty"] and dist_onset > 0 and indication != "GREEN"
        confidence = "HIGH" if telemetry_gap_ms <= 150 and not borderline else "MODERATE"

        evidence = {}
        if with_evidence:
            for check in checks:
                if check["check_id"] in PINS:
                    evidence[check["check_id"]] = self.evidence_for(check["check_id"], state.state_code,
                                                                    local.jurisdiction_code)
            evidence["RECORDS"] = self.evidence_for("RECORDS", state.state_code, local.jurisdiction_code)

        return {
            "crash_id": crash_id,
            "verdict": verdict,
            "verdict_label": VERDICTS[verdict],
            "confidence": confidence,
            "facts": {
                "intersection_id": iid, "intersection_name": inter["intersection_name"],
                "jurisdiction": local.jurisdiction_name + ", " + state.state_name,
                "controller": inter["controller_standard"] + " (" + inter["controller_id"] + ")",
                "control_type": inter["control_type"], "timing_plan_id": relevant_yellow["timing_plan_id"],
                "subject_phase": phase, "subject_movement": crash["subject_movement"],
                "conflicting_phase": conflicting, "crash_type": crash["crash_type"],
                "impact_stamp": crash["crash_stamp"], "stop_line_entry_stamp": ms_to_stamp(entry),
                "yellow_onset_stamp": ms_to_stamp(onset), "red_onset_stamp": ms_to_stamp(red_onset),
                "indication_at_entry": indication, "entry_after_red_onset_s": round(entry_after_red_s, 3),
                "displayed_yellow_s": displayed_yellow_s, "programmed_yellow_s": programmed_yellow_s,
                "displayed_red_clearance_s": displayed_red_s, "programmed_red_clearance_s": programmed_red_s,
                "speed_mph": speed, "distance_at_yellow_onset_ft": round(max(dist_onset, 0.0), 1),
                "crossed_stop_line_before_yellow": bool(dist_onset <= 0),
                "travel_time_at_yellow_onset_s": round(max(travel_time_onset, 0.0), 2),
                "posted_speed_mph": lane["posted_speed_mph"], "speed_85th_mph": lane["speed_85th_mph"],
                "grade": str(lane["grade_pct"]) + " percent " + lane["grade_direction"],
                "intersection_width_ft": lane["intersection_width_ft"],
                "telemetry_source": crash["telemetry_source"], "weather": crash["weather"], "surface": crash["surface"],
            },
            "requirements": req,
            "dilemma_zone": zone,
            "checks": checks,
            "signal_snapshot_at_entry": [{"phase": s["nema_phase"], "interval": s["interval_type"],
                                          "since": s["start_stamp"]} for s in snapshot],
            "detector_faults": faults,
            "mmu_events": mmu,
            "evidence": evidence,
            "surplus_yellow_s": round(surplus(req["required_yellow_s"], programmed_yellow_s), 2),
            "disclaimer": ("Engineering decision support only. Findings depend on log integrity and telemetry accuracy "
                           "and must be reviewed by a licensed professional engineer and counsel before any legal use."),
        }

    def _indeterminate(self, crash, reason):
        return {"crash_id": crash["crash_id"], "verdict": "INDETERMINATE", "verdict_label": VERDICTS["INDETERMINATE"],
                "confidence": "LOW", "facts": {"reason": reason}, "checks": [], "evidence": {}}


def lane_kind(phase):
    return "left" if int(phase) in (1, 3, 5, 7) else "through_right"


def fmt(value):
    if value is None:
        return "n/a"
    return ("%.2f" % float(value)).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
