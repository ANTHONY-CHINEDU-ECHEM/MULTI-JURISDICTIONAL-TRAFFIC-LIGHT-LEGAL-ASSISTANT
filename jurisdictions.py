"""Jurisdiction registry and governing requirement logic.

The two states and six municipalities below are fictional. They exist so the
multi jurisdictional reasoning (federal floor, state policy, local ordinance)
can be demonstrated and tested end to end without misrepresenting the law of
any real state or city. Replace them with real state DOT manuals and municipal
code by dropping documents into knowledge/state and knowledge/local and
editing data/raw/jurisdiction_policy.csv.
"""

from dataclasses import asdict, dataclass

from .config import KINEMATICS, TOLERANCES
from .utils import sub


@dataclass(frozen=True)
class StatePolicy:
    state_code: str
    state_name: str
    agency: str
    manual_title: str
    speed_basis: str
    reaction_time_s: float
    deceleration_ftps2: float
    min_yellow_s: float
    min_red_clearance_s: float
    red_clearance_method: str


@dataclass(frozen=True)
class LocalPolicy:
    jurisdiction_code: str
    jurisdiction_name: str
    state_code: str
    ordinance_title: str
    speed_adjust_mph: float
    min_yellow_s: float
    min_red_clearance_s: float
    high_speed_threshold_mph: float
    high_speed_min_yellow_s: float
    detector_repair_hours: float
    log_retention_days: int


STATES = {
    "AV": StatePolicy(
        "AV", "State of Avalon", "Avalon Department of Transportation",
        "Avalon DOT Traffic Signal Timing Policy Manual", "posted",
        1.0, 10.0, 3.0, 1.0, "ITE",
    ),
    "KS": StatePolicy(
        "KS", "State of Kestrel", "Kestrel Department of Transportation",
        "Kestrel DOT Signal Operations Directive", "85th",
        1.0, 10.0, 3.5, 0.5, "MINIMUM_ONLY",
    ),
}

LOCALS = {
    "RIV": LocalPolicy("RIV", "City of Riverbend", "AV", "Riverbend Municipal Code Title 12 Traffic Signals", 0.0, 3.5, 1.0, 99.0, 0.0, 48.0, 365),
    "HBP": LocalPolicy("HBP", "Town of Harbor Point", "AV", "Harbor Point Town Ordinance 7 Signal Operations", 0.0, 3.0, 1.5, 99.0, 0.0, 72.0, 180),
    "CDF": LocalPolicy("CDF", "City of Cedar Falls", "AV", "Cedar Falls Municipal Code Chapter 9 Signalized Intersections", 5.0, 3.0, 1.0, 99.0, 0.0, 24.0, 730),
    "NGT": LocalPolicy("NGT", "City of Northgate", "KS", "Northgate Municipal Code Article 14 Signal Timing", 0.0, 3.5, 1.0, 45.0, 4.0, 48.0, 365),
    "MLB": LocalPolicy("MLB", "Village of Millbrook", "KS", "Millbrook Village Code Part 6 Traffic Control", 0.0, 3.5, 1.0, 99.0, 0.0, 48.0, 365),
    "STB": LocalPolicy("STB", "City of Stonebridge", "KS", "Stonebridge Municipal Code Title 10 Signals", 0.0, 3.5, 1.2, 50.0, 4.5, 24.0, 540),
}


def state_for(local_code):
    return STATES[LOCALS[local_code].state_code]


def clearance_speed(state, local, posted_mph, speed85_mph, movement_kind):
    """Speed the governing policy tells engineers to time clearance intervals with."""
    base = speed85_mph if state.speed_basis == "85th" else posted_mph
    base = base + local.speed_adjust_mph
    if movement_kind == "left":
        base = max(20.0, sub(base, 10.0))
    return float(base)


def governing_requirements(local_code, posted_mph, speed85_mph, movement_kind, grade_pct, grade_direction, width_ft):
    """Combine federal, state and local rules into the governing minimums.

    The strictest applicable value governs: MUTCD guidance sets the federal
    floor of 3 seconds for yellow, the state policy fixes the kinematic method
    and its own minimums, and the local ordinance may add further minimums.
    Returns a dict with each layer and the governing values so reports can
    explain which authority controls.
    """
    from .hcm import ite_red_clearance, ite_yellow

    local = LOCALS[local_code]
    state = STATES[local.state_code]
    speed = clearance_speed(state, local, posted_mph, speed85_mph, movement_kind)
    kinematic_yellow = float(ite_yellow(speed, grade_pct, grade_direction, state.reaction_time_s, state.deceleration_ftps2))
    kinematic_red = float(ite_red_clearance(speed, width_ft, KINEMATICS.vehicle_length_ft))

    yellow_layers = {
        "federal_mutcd_guidance_min": TOLERANCES.mutcd_yellow_min_s,
        "state_kinematic": round(kinematic_yellow, 2),
        "state_minimum": state.min_yellow_s,
        "local_minimum": local.min_yellow_s,
    }
    if posted_mph >= local.high_speed_threshold_mph:
        yellow_layers["local_high_speed_minimum"] = local.high_speed_min_yellow_s

    red_layers = {"state_minimum": state.min_red_clearance_s, "local_minimum": local.min_red_clearance_s}
    if state.red_clearance_method == "ITE":
        red_layers["state_kinematic"] = round(min(kinematic_red, TOLERANCES.mutcd_red_clearance_max_s), 2)

    governing_yellow_source = _sources_at_max(yellow_layers)
    governing_red_source = _sources_at_max(red_layers)
    return {
        "clearance_speed_mph": round(speed, 1),
        "reaction_time_s": state.reaction_time_s,
        "deceleration_ftps2": state.deceleration_ftps2,
        "yellow_layers": yellow_layers,
        "red_clearance_layers": red_layers,
        "required_yellow_s": round(min(max(yellow_layers.values()), TOLERANCES.mutcd_yellow_max_s), 2),
        "required_red_clearance_s": round(max(red_layers.values()), 2),
        "governing_yellow_source": governing_yellow_source,
        "governing_red_clearance_source": governing_red_source,
    }


def _sources_at_max(layers):
    """Name every layer that ties for the governing (maximum) value."""
    top = max(layers.values())
    return " and ".join(k for k, v in layers.items() if v == top)


def policy_rows():
    rows = []
    for local in LOCALS.values():
        row = asdict(local)
        state = asdict(STATES[local.state_code])
        row.update({(k if k.startswith("state_") else "state_" + k): v for k, v in state.items() if k != "state_code"})
        rows.append(row)
    return rows
