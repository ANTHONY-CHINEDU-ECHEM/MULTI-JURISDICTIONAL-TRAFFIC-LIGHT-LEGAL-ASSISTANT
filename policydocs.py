"""Write the fictional state DOT manuals and municipal ordinances.

Each document is generated from the same policy objects the evaluator uses,
so the numbers quoted by the retriever always agree with the numbers applied
by the rule engine. The documents follow the MUTCD provision layout (a section
heading, then Standard, Guidance, Option or Support blocks with numbered
paragraphs) so one hierarchical parser serves federal, state and local text.
"""

from . import config
from .jurisdictions import LOCALS, STATES

NOTICE = ("Notice: SYNTHETIC DEMONSTRATION DOCUMENT. This jurisdiction and its provisions are fictional and exist "
          "only to exercise the multi jurisdictional reasoning of this software. It is not the law of any real "
          "state or municipality.")


def _block(kind, number, text):
    return kind + ":\n" + str(number).zfill(2) + "\n" + text + "\n"


def state_document(state):
    basis = ("the posted speed limit of the approach" if state.speed_basis == "posted"
             else "the measured 85th percentile approach speed")
    red_text = ("The red clearance interval shall be computed with the ITE kinematic red clearance equation, "
                "R = (W + L) / v, using the width from the stop line to the far side of the last conflicting lane, "
                "a design vehicle length of 20 feet and the clearance speed defined in Clause 3.2, and shall not be "
                "less than " + str(state.min_red_clearance_s) + " seconds."
                if state.red_clearance_method == "ITE"
                else "The red clearance interval shall not be less than " + str(state.min_red_clearance_s)
                + " seconds. Engineers may use the ITE kinematic red clearance equation as guidance.")
    sections = [
        ("Clause 3.1 Applicability and Relationship to the MUTCD", [
            _block("Standard", 1, "This manual adopts the Manual on Uniform Traffic Control Devices, 11th Edition, as "
                   "the standard for traffic control devices on all public roads in the " + state.state_name + ". Where "
                   "this manual is more restrictive than the MUTCD, this manual governs. No provision of this manual "
                   "relaxes a MUTCD Standard."),
            _block("Support", 2, "Local agencies may adopt requirements that are more restrictive than this manual "
                   "by ordinance. The most restrictive applicable requirement governs a signalized location."),
        ]),
        ("Clause 3.2 Yellow Change Interval", [
            _block("Standard", 1, "The yellow change interval shall be computed with the ITE kinematic equation "
                   "Y = t + v / (2a + 2Gg) using a perception reaction time t of " + str(state.reaction_time_s)
                   + " seconds, a deceleration rate a of " + str(state.deceleration_ftps2) + " feet per second squared, "
                   "the approach grade G as a decimal (negative for downgrade), and a clearance speed v equal to "
                   + basis + ". For protected left turn movements the clearance speed shall be 10 mph below the "
                   "through clearance speed but not less than 20 mph."),
            _block("Standard", 2, "The yellow change interval shall not be less than " + str(state.min_yellow_s)
                   + " seconds and shall be rounded up to the nearest 0.1 second supported by the controller unit."),
            _block("Guidance", 3, "Yellow change intervals longer than 6 seconds should be avoided; where the kinematic "
                   "value exceeds 6 seconds, advance warning and dilemma zone detection should be considered."),
        ]),
        ("Clause 3.3 Red Clearance Interval", [
            _block("Standard", 1, red_text),
        ]),
        ("Clause 3.4 Consistency of Clearance Intervals", [
            _block("Standard", 1, "The displayed yellow change interval shall equal the programmed value in every cycle "
                   "of a timing plan. The red clearance interval shall not be shortened or omitted on a cycle by cycle "
                   "basis except as permitted by MUTCD Section 4F.17."),
            _block("Standard", 2, "Any deviation between displayed and programmed clearance intervals recorded in the "
                   "controller high resolution event log shall be treated as an equipment malfunction and reported "
                   "to the signal maintenance supervisor within 24 hours."),
        ]),
        ("Clause 3.5 Controller Assemblies and Malfunction Management", [
            _block("Standard", 1, "Controller assemblies shall conform to NEMA TS 2 or the ATC standards. Minimum yellow "
                   "change interval monitoring in the malfunction management unit shall be enabled on every vehicle "
                   "channel."),
            _block("Guidance", 2, "Malfunction management unit logs should be downloaded after every reported crash at "
                   "a signalized location and preserved with the controller event log."),
        ]),
        ("Clause 3.6 Vehicle Detection", [
            _block("Standard", 1, "Detector failures reported by controller diagnostics, including open loop, shorted "
                   "loop, excessive inductance change and watchdog failure, shall place the affected phase on "
                   "maximum recall until repaired."),
            _block("Guidance", 2, "Advance detection providing dilemma zone protection should be restored as soon as "
                   "practical, because maximum recall removes green extension for vehicles approaching at speed."),
        ]),
    ]
    return _render(state.manual_title, state.state_name + " (tier: STATE)", sections)


def local_document(local):
    state = STATES[local.state_code]
    sections = [
        ("Section 1.01 Adoption of State Policy", [
            _block("Standard", 1, "The " + local.jurisdiction_name + " adopts the " + state.manual_title + " for all "
                   "traffic control signals under municipal jurisdiction. Where this ordinance is more restrictive, "
                   "this ordinance governs."),
        ]),
        ("Section 1.02 Minimum Yellow Change Interval", [
            _block("Standard", 1, "No yellow change interval at a municipal signal shall be less than "
                   + str(local.min_yellow_s) + " seconds, regardless of the value produced by the state equation."),
        ]),
        ("Section 1.03 Minimum Red Clearance Interval", [
            _block("Standard", 1, "Every signal phase shall display a red clearance interval of not less than "
                   + str(local.min_red_clearance_s) + " seconds before a conflicting movement is released."),
        ]),
    ]
    if local.high_speed_threshold_mph < 90:
        sections.append(("Section 1.04 High Speed Approaches", [
            _block("Standard", 1, "On approaches with a posted speed limit of " + str(int(local.high_speed_threshold_mph))
                   + " mph or greater the yellow change interval shall be not less than "
                   + str(local.high_speed_min_yellow_s) + " seconds."),
        ]))
    if local.speed_adjust_mph > 0:
        sections.append(("Section 1.05 Clearance Speed", [
            _block("Standard", 1, "For the purpose of clearance interval calculations the clearance speed shall be the "
                   "speed required by state policy increased by " + str(int(local.speed_adjust_mph)) + " mph."),
        ]))
    sections.append(("Section 1.06 Detector Repair", [
        _block("Standard", 1, "A vehicle detector failure at a municipal signal shall be repaired within "
               + str(int(local.detector_repair_hours)) + " hours of detection by controller diagnostics or report."),
        _block("Support", 2, "Failure to repair within this period is evidence that the municipality had notice of a "
               "defective condition."),
    ]))
    sections.append(("Section 1.07 Signal Records", [
        _block("Standard", 1, "Controller event logs, detector fault logs and malfunction management unit logs shall be "
               "retained for not less than " + str(local.log_retention_days) + " days and shall be preserved without "
               "alteration after notice of a crash or claim."),
    ]))
    return _render(local.ordinance_title, local.jurisdiction_name + ", " + state.state_name + " (tier: LOCAL)", sections)


def _render(title, jurisdiction_line, sections):
    lines = ["# " + title, "", "Jurisdiction: " + jurisdiction_line, "", NOTICE, ""]
    for heading, blocks in sections:
        lines.append("## " + heading)
        lines.append("")
        for block in blocks:
            lines.append(block)
    return "\n".join(lines)


def write_policy_documents():
    written = []
    for state in STATES.values():
        path = config.KNOWLEDGE_DIR / "state" / (state.state_code.lower() + "_dot_signal_policy.md")
        path.write_text(state_document(state), encoding="utf8")
        written.append(path)
    for local in LOCALS.values():
        path = config.KNOWLEDGE_DIR / "local" / (local.jurisdiction_code.lower() + "_municipal_code.md")
        path.write_text(local_document(local), encoding="utf8")
        written.append(path)
    return written
