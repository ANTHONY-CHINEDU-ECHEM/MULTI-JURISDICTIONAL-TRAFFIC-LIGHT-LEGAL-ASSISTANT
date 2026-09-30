import pandas as pd

from trafficlegal import config


def load(name):
    return pd.read_csv(config.RAW_DIR / (name + ".csv"))


def test_primary_dataset_meets_size_requirement():
    hcs = load("hcs_streets_export")
    assert len(hcs) >= 15000 and hcs.shape[1] >= 16


def test_numeric_columns_are_non_negative():
    for name in ("hcs_streets_export", "signal_event_log", "crash_events", "detector_faults", "mmu_events"):
        frame = load(name)
        numeric = frame.select_dtypes("number")
        assert (numeric.fillna(0) >= 0).all().all(), name


def test_scenario_years_follow_the_source_article():
    assert sorted(load("hcs_streets_export")["scenario_year"].unique()) == [2023, 2030, 2035]


def test_event_log_intervals_are_contiguous_per_ring():
    log = load("signal_event_log")
    window = log[log["window_id"] == log["window_id"].iloc[0]]
    for _, ring in window.groupby("ring"):
        ring = ring.sort_values("start_epoch_ms")
        starts = ring["start_epoch_ms"].tolist()[1:]
        ends = ring["end_epoch_ms"].tolist()[:len(starts)]
        assert all(s >= e for s, e in zip(starts, ends))


def test_only_crash_cycles_deviate_from_programmed_yellow():
    log = load("signal_event_log")
    yellow = log[log["interval_type"] == "YELLOW"]
    deviating = yellow[yellow["displayed_duration_ms"] != yellow["programmed_duration_ms"]]
    crashes = load("crash_events").set_index("crash_id")
    assert set(deviating["window_id"]).issubset(set(crashes[crashes["truth_deviation_kind"] == "YELLOW_TRUNCATED"].index))
