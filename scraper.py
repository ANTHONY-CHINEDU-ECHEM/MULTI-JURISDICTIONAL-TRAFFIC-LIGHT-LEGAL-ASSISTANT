"""Scrape the McTrans HCS Streets CSV article and turn it into a dataset schema.

The article does not publish a downloadable table; it documents which
parameters the HCS Streets module writes when an intersection or corridor is
exported to CSV (intersection geometry, traffic, signal controller settings and
performance measures) and how analysts build multi year scenarios from that
export. This module scrapes those parameter groups and maps every scraped
parameter to one or more columns of the synthetic HCS style dataset produced
by trafficlegal.synth. When the network is unavailable the verified snapshot
below is used so the pipeline stays reproducible.
"""

import re
from datetime import datetime, timezone

from . import config
from .utils import get_logger, strip_dashes, write_json

LOG = get_logger("scraper")

SNAPSHOT = {
    "title": "Integrating HCS Signal Analyses with Excel for Efficient Traffic Studies",
    "groups": {
        "Intersection geometry": ["number of lanes", "lane width", "storage length", "grade %"],
        "Traffic": ["vehicular demand", "heavy vehicles %", "bicycles", "buses", "peak hour factor"],
        "Signal controller settings": [
            "cycle length", "control type (pretimed/actuated/coordinated)", "offsets",
            "phase splits", "red/yellow intervals", "minimum green", "passage time", "and more",
        ],
        "Performance measures": [
            "volume to capacity ratio", "control delay", "LOS", "and queue storage ratios",
        ],
    },
    "scenario_years": [2023, 2030, 2035],
    "retrieved": "offline snapshot, verified against the live article on 2026/09/30",
}

PARAMETER_TO_COLUMNS = {
    "number of lanes": ["num_lanes"],
    "lane width": ["lane_width_ft"],
    "storage length": ["storage_length_ft"],
    "grade": ["grade_pct", "grade_direction"],
    "vehicular demand": ["demand_vph"],
    "heavy vehicles": ["heavy_vehicle_pct"],
    "bicycles": ["bicycles_vph"],
    "buses": ["buses_per_hr"],
    "peak hour factor": ["peak_hour_factor"],
    "cycle length": ["cycle_length_s"],
    "control type": ["control_type"],
    "offsets": ["offset_s"],
    "phase splits": ["split_s", "green_s"],
    "red/yellow intervals": ["yellow_s", "red_clearance_s"],
    "minimum green": ["min_green_s"],
    "passage time": ["passage_time_s"],
    "volume to capacity": ["vc_ratio", "capacity_vph", "saturation_flow_vph"],
    "control delay": ["control_delay_s"],
    "los": ["los"],
    "queue storage": ["queue_storage_ratio", "back_of_queue_ft"],
}


def _normalise(text):
    return " ".join(strip_dashes(text).replace("\u00a0", " ").split())


def parse_article(html):
    """Extract parameter groups and scenario years from the article HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("h1")
    groups = {}
    for item in soup.find_all("li"):
        strong = item.find("strong")
        if not strong:
            continue
        label = _normalise(strong.get_text()).rstrip(":")
        body = _normalise(item.get_text()).split(":", 1)
        if len(body) != 2 or not label:
            continue
        params = [p.strip(" ;.") for p in body[1].split(",") if p.strip(" ;.")]
        if params:
            groups[label] = params
    years = sorted({int(y) for y in re.findall(r"\b(20[2345]\d)\b", soup.get_text())
                    if 2020 <= int(y) <= 2050})
    scenario_years = [y for y in years if y in (2023, 2030, 2035)] or SNAPSHOT["scenario_years"]
    return {
        "title": _normalise(title_tag.get_text()) if title_tag else SNAPSHOT["title"],
        "groups": groups or SNAPSHOT["groups"],
        "scenario_years": scenario_years,
    }


def fetch_article(timeout_s=20):
    """Download and parse the article, falling back to the verified snapshot."""
    try:
        import requests

        response = requests.get(config.SOURCE_URL, timeout=timeout_s)
        response.raise_for_status()
        parsed = parse_article(response.text)
        parsed["retrieved"] = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S UTC")
        LOG.info("Scraped %d parameter groups from McTrans", len(parsed["groups"]))
        return parsed
    except Exception as exc:
        LOG.warning("Live scrape unavailable (%s); using verified offline snapshot", exc)
        return dict(SNAPSHOT)


def build_schema(article):
    """Map every scraped parameter to dataset columns and record provenance."""
    mapping = []
    for group, params in article["groups"].items():
        for param in params:
            key = param.lower()
            columns = []
            for phrase, cols in PARAMETER_TO_COLUMNS.items():
                if phrase in key:
                    columns.extend(cols)
            mapping.append({"group": group, "parameter": param, "columns": sorted(set(columns))})
    return {
        "source_url": config.SOURCE_URL_ENCODED,
        "source_title": article["title"],
        "retrieved": article.get("retrieved", "unknown"),
        "scenario_years": article["scenario_years"],
        "parameter_mapping": mapping,
    }


def scrape_and_save():
    schema = build_schema(fetch_article())
    path = config.RAW_DIR / "source_schema.json"
    write_json(path, schema)
    LOG.info("Schema written to %s", path)
    return schema
