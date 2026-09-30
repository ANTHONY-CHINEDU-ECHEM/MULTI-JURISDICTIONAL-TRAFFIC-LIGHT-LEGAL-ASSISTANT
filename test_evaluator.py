import pandas as pd

from trafficlegal import config
from trafficlegal.benchmark import verdict_benchmark


def crashes():
    return pd.read_csv(config.RAW_DIR / "crash_events.csv")


def test_verdict_accuracy_on_labelled_scenarios(assistant):
    report = verdict_benchmark(assistant.evaluator)
    assert report["accuracy"] >= 0.97


def test_red_clearance_omission_is_flagged(assistant):
    frame = crashes()
    cid = frame[frame["truth_deviation_kind"] == "RED_CLEARANCE_OMITTED"]["crash_id"].iloc[0]
    result = assistant.evaluator.evaluate(cid)
    status = {c["check_id"]: c["status"] for c in result["checks"]}
    assert status["RED_CLEARANCE_CONSISTENCY"] == "FAIL"
    cited = [e["citation"] for e in result["evidence"]["RED_CLEARANCE_CONSISTENCY"]]
    assert any("4F.17" in c and "Paragraph 09" in c for c in cited)


def test_detector_fault_reports_repair_window(assistant):
    frame = crashes()
    cid = frame[frame["scenario_truth"] == "DETECTOR_FAULT"]["crash_id"].iloc[0]
    result = assistant.evaluator.evaluate(cid)
    check = next(c for c in result["checks"] if c["check_id"] == "DETECTOR_STATUS")
    assert check["status"] == "FAIL" and "repair limit" in check["detail"]


def test_memo_is_dash_free(assistant):
    from trafficlegal.utils import contains_dash

    cid = crashes()["crash_id"].iloc[0]
    out = assistant.crash_report(cid, save_report=False)
    assert not contains_dash(out["answer_markdown"])
