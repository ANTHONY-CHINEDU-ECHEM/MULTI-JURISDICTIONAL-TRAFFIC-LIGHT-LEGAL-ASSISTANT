"""Central configuration for paths, engineering constants and retrieval settings.

Every value here can be overridden with an environment variable of the same
name prefixed with TRAFFICLEGAL_, for example TRAFFICLEGAL_DATA_DIR.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_path(name, default):
    value = os.environ.get("TRAFFICLEGAL_" + name)
    return Path(value) if value else default


def _env_float(name, default):
    value = os.environ.get("TRAFFICLEGAL_" + name)
    return float(value) if value else default


DATA_DIR = _env_path("DATA_DIR", ROOT / "data")
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
KNOWLEDGE_DIR = _env_path("KNOWLEDGE_DIR", ROOT / "knowledge")
ARTIFACT_DIR = _env_path("ARTIFACT_DIR", ROOT / "artifacts")
DB_PATH = ARTIFACT_DIR / "signal_store.sqlite"
INDEX_PATH = ARTIFACT_DIR / "knowledge_index.json"
TEXT_CACHE_DIR = ARTIFACT_DIR / "text_cache"
REPORT_DIR = ARTIFACT_DIR / "reports"

HYPHEN = chr(45)
"""The ASCII hyphen. The repository style forbids writing this character
literally anywhere in source, data or documentation, so any external string
that genuinely requires it (a URL slug, for example) is assembled here."""

SOURCE_SLUG_WORDS = [
    "integrate", "hcs", "signal", "analyses", "with", "excel",
    "for", "efficient", "traffic", "studies",
]
SOURCE_URL = "https://mctrans.ce.ufl.edu/" + HYPHEN.join(SOURCE_SLUG_WORDS) + "/"
"""McTrans article describing the HCS Streets CSV export schema (used for live requests)."""
SOURCE_URL_ENCODED = "https://mctrans.ce.ufl.edu/" + "%2D".join(SOURCE_SLUG_WORDS) + "/"
"""The same address with each hyphen percent encoded (RFC 3986 equivalent), used wherever the URL is written to disk."""


@dataclass(frozen=True)
class Kinematics:
    """Constants for the ITE kinematic yellow change and red clearance equations."""

    gravity_ftps2: float = 32.2
    default_perception_reaction_s: float = 1.0
    default_deceleration_ftps2: float = 10.0
    vehicle_length_ft: float = 20.0
    mph_to_ftps: float = 1.467


@dataclass(frozen=True)
class Tolerances:
    """Tolerances used when comparing logged durations with requirements."""

    timing_resolution_s: float = 0.1
    consistency_tolerance_ms: int = 50
    requirement_tolerance_s: float = 0.05
    mutcd_yellow_min_s: float = 3.0
    mutcd_yellow_max_s: float = 6.0
    mutcd_red_clearance_max_s: float = 6.0
    speed_uncertainty_mph: float = 1.0
    mmu_min_yellow_threshold_s: float = _env_float("MMU_MIN_YELLOW_S", 2.7)


@dataclass(frozen=True)
class RetrievalSettings:
    """Hierarchical retrieval depth at each tier of the index."""

    sections_per_tier: int = 6
    paragraphs_per_query: int = 8
    section_blend_weight: float = 1.0
    bm25_k1: float = 1.4
    bm25_b: float = 0.72
    provision_weights: dict = field(default_factory=lambda: {
        "Standard": 1.25,
        "Clause": 1.25,
        "Guidance": 1.12,
        "Option": 1.0,
        "Support": 0.92,
        "Specification": 1.1,
        "Text": 1.0,
    })


KINEMATICS = Kinematics()
TOLERANCES = Tolerances()
RETRIEVAL = RetrievalSettings()

LLM_MODEL = os.environ.get("TRAFFICLEGAL_LLM_MODEL", "")
LLM_ENABLED = bool(LLM_MODEL) and bool(os.environ.get("ANTHROPIC_API_KEY"))

for _directory in (RAW_DIR, PROCESSED_DIR, ARTIFACT_DIR, TEXT_CACHE_DIR, REPORT_DIR):
    _directory.mkdir(parents=True, exist_ok=True)
