import numpy as np
import pytest

from trafficlegal import hcm
from trafficlegal.jurisdictions import governing_requirements


def test_ite_yellow_level_45_mph():
    assert hcm.ite_yellow(45, 0, "uphill") == pytest.approx(1.0 + 45 * 1.467 / 20.0, rel=0.000001)


def test_downhill_grade_lengthens_yellow():
    level = float(hcm.ite_yellow(50, 0, "uphill"))
    downhill = float(hcm.ite_yellow(50, 4, "downhill"))
    uphill = float(hcm.ite_yellow(50, 4, "uphill"))
    assert downhill > level > uphill


def test_red_clearance_equation():
    assert float(hcm.ite_red_clearance(40, 80)) == pytest.approx((80 + 20) / (40 * 1.467), rel=0.000001)


def test_level_of_service_thresholds():
    grades = hcm.level_of_service(np.array([5, 15, 30, 50, 70, 90, 12]), np.array([0.5] * 6 + [1.1]))
    assert list(grades) == ["A", "B", "C", "D", "E", "F", "F"]


def test_dilemma_zone_trapped_when_yellow_short():
    zone = hcm.dilemma_zone(50, 250, 3.0, 0.0, 1.0, 10.0)
    assert zone["trapped_in_dilemma_zone"]
    zone_ok = hcm.dilemma_zone(50, 250, 5.0, 0.0, 1.0, 10.0)
    assert not zone_ok["trapped_in_dilemma_zone"]


def test_strictest_layer_governs_in_northgate_high_speed():
    req = governing_requirements("NGT", 45, 48, "through_right", 0, "uphill", 80)
    assert req["yellow_layers"]["local_high_speed_minimum"] == 4.0
    assert req["required_yellow_s"] == max(req["yellow_layers"].values())


def test_cedar_falls_speed_adjustment_raises_clearance_speed():
    base = governing_requirements("RIV", 45, 50, "through_right", 0, "uphill", 80)
    adjusted = governing_requirements("CDF", 45, 50, "through_right", 0, "uphill", 80)
    assert adjusted["clearance_speed_mph"] == base["clearance_speed_mph"] + 5
