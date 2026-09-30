"""Render an evaluation as an engineering and legal analysis memorandum.

Two artifacts are written per crash:

* <crash_id>.json keeps every fact, check and evidence paragraph verbatim,
  which is the version to preserve for discovery or expert review.
* <crash_id>.md is the readable memorandum. Its prose is written without
  dash characters, and quoted excerpts are normalised to the same style
  (dashes rendered as spaces) unless TRAFFICLEGAL_VERBATIM_MEMO=1 is set.
"""

import os

from . import config
from .utils import strip_dashes, write_json

STATUS_WORD = {"PASS": "Met", "FAIL": "Not met", "INFO": "Finding", "NOT_APPLICABLE": "Not applicable"}
VERBATIM = os.environ.get("TRAFFICLEGAL_VERBATIM_MEMO") == "1"


def _q(text):
    return text if VERBATIM else strip_dashes(text)


def render_markdown(result, narrative=None):
    f = result["facts"]
    lines = [
        "# Signal Timing Incident Analysis: " + result["crash_id"],
        "",
        "**Verdict:** " + result["verdict"].replace("_", " ").title(),
        "",
        result["verdict_label"] + ". Confidence: " + result["confidence"].title() + ".",
        "",
    ]
    if result["verdict"] == "INDETERMINATE":
        lines += ["Reason: " + f.get("reason", "unknown"), ""]
        return "\n".join(lines)
    if narrative:
        lines += ["## Narrative Summary", "", _q(narrative), ""]
    lines += [
        "## Facts at the Moment of Entry",
        "",
        "* Location: " + f["intersection_name"] + " (" + f["intersection_id"] + "), " + f["jurisdiction"] + ".",
        "* Controller: " + f["controller"] + ", " + f["control_type"] + " operation, timing plan "
        + str(f["timing_plan_id"]) + ".",
        "* Subject movement: phase " + str(f["subject_phase"]) + " (" + f["subject_movement"] + "); conflicting phase "
        + str(f["conflicting_phase"]) + "; crash type " + f["crash_type"].replace("_", " ").lower() + ".",
        "* Yellow onset " + f["yellow_onset_stamp"] + ", red onset " + f["red_onset_stamp"] + ", stop line entry "
        + f["stop_line_entry_stamp"] + ", impact " + f["impact_stamp"] + ".",
        "* Indication at entry: " + f["indication_at_entry"] + (
            " (" + str(f["entry_after_red_onset_s"]) + " s after red onset)" if f["indication_at_entry"] != "GREEN"
            and f["indication_at_entry"] != "YELLOW" else "") + ".",
        "* Clearance intervals displayed in the crash cycle: yellow " + str(f["displayed_yellow_s"]) + " s (programmed "
        + str(f["programmed_yellow_s"]) + " s), red clearance " + str(f["displayed_red_clearance_s"]) + " s (programmed "
        + str(f["programmed_red_clearance_s"]) + " s).",
        "* Vehicle: " + str(f["speed_mph"]) + " mph, " + (
            "already past the stop line at yellow onset" if f["crossed_stop_line_before_yellow"]
            else str(f["distance_at_yellow_onset_ft"]) + " ft from the stop line at yellow onset ("
            + str(f["travel_time_at_yellow_onset_s"]) + " s of travel)") + "; telemetry from "
        + f["telemetry_source"].replace("_", " ").lower() + ".",
        "* Approach: posted " + str(f["posted_speed_mph"]) + " mph, 85th percentile " + str(f["speed_85th_mph"])
        + " mph, grade " + f["grade"] + ", crossing width " + str(f["intersection_width_ft"]) + " ft.",
        "* Conditions: weather " + f["weather"].lower() + ", surface " + f["surface"].lower() + ".",
        "",
        "## Governing Requirements by Authority Layer",
        "",
    ]
    req = result["requirements"]
    for layer, value in req["yellow_layers"].items():
        lines.append("* Yellow, " + layer.replace("_", " ") + ": " + str(value) + " s")
    lines.append("* Governing yellow: **" + str(req["required_yellow_s"]) + " s** from "
                 + req["governing_yellow_source"].replace("_", " ") + ", clearance speed "
                 + str(req["clearance_speed_mph"]) + " mph.")
    for layer, value in req["red_clearance_layers"].items():
        lines.append("* Red clearance, " + layer.replace("_", " ") + ": " + str(value) + " s")
    lines.append("* Governing red clearance: **" + str(req["required_red_clearance_s"]) + " s** from "
                 + req["governing_red_clearance_source"].replace("_", " ") + ".")
    lines += ["", "## Findings", ""]
    for check in result["checks"]:
        lines.append("### " + STATUS_WORD[check["status"]] + ": " + check["title"])
        lines.append("")
        lines.append(check["detail"])
        lines.append("")
        limit = 4 if check["status"] == "FAIL" else 2
        for ev in result["evidence"].get(check["check_id"], [])[:limit]:
            lines.append("> " + _q(ev["citation"]) + ": " + _q(ev["text"][:600]))
            lines.append(">")
        if result["evidence"].get(check["check_id"]):
            lines.pop()
            lines.append("")
    if result["evidence"].get("RECORDS"):
        lines += ["## Evidence Preservation", ""]
        for ev in result["evidence"]["RECORDS"][:3]:
            lines.append("* " + _q(ev["citation"]) + ": " + _q(ev["text"][:400]))
        lines.append("")
    lines += ["## Signal State Snapshot at Entry", ""]
    for s in result["signal_snapshot_at_entry"]:
        lines.append("* Phase " + str(s["phase"]) + ": " + s["interval"] + " since " + s["since"])
    lines += ["", "## Limitations", "", result["disclaimer"], ""]
    return "\n".join(lines)


def save(result, narrative=None):
    json_path = config.REPORT_DIR / (result["crash_id"] + ".json")
    md_path = config.REPORT_DIR / (result["crash_id"] + ".md")
    payload = dict(result)
    if narrative:
        payload["narrative"] = narrative
    write_json(json_path, payload)
    md_path.write_text(render_markdown(result, narrative), encoding="utf8")
    return md_path, json_path
