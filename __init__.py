"""Multi Jurisdictional Traffic Light Incident Legal Assistant.

A hybrid structured and unstructured retrieval augmented generation system that
joins crash telemetry and signal controller logs (SQLite) with a hierarchical
index of regulatory manuals (MUTCD, state DOT policy, local municipal code and
NEMA TS 2 hardware specifications) to evaluate whether the yellow change and
red clearance intervals met legal and engineering requirements at the exact
millisecond a vehicle entered the intersection.
"""

__version__ = "1.0.0"
