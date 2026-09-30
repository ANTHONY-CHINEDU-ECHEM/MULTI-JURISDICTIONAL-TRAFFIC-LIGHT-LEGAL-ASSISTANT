"""Objective benchmarks.

Verdict benchmark: every synthetic crash carries a hidden scenario label that
the evaluator never reads. Predicted verdicts are compared with the expected
verdict for that label, producing accuracy, per class precision and recall,
and a confusion matrix.

Retrieval benchmark: questions written in the language a claims analyst or
engineer would use, each with the section (or sections) a correct answer must
cite. Reports hit rate at 1 and 3 and mean reciprocal rank at section level.
"""

from collections import Counter, defaultdict

import pandas as pd

from . import config
from .evaluator import TRUTH_TO_VERDICT, CrashEvaluator
from .retriever import HierarchicalRetriever
from .utils import write_json

RETRIEVAL_CASES = [
    ("How long should the yellow change interval be at a signal?", "MUTCD11", {"4F.17"}),
    ("Can the red clearance interval be omitted or shortened cycle by cycle?", "MUTCD11", {"4F.17"}),
    ("Who is responsible for keeping a controller operating to its timing schedule?", "MUTCD11", {"4A.10"}),
    ("Transition into flashing mode initiated by a conflict monitor", "MUTCD11", {"4G.02", "4G.01"}),
    ("During preemption may the yellow change interval be shortened for an emergency vehicle?", "MUTCD11", {"4F.19", "4F.18"}),
    ("Meaning of a steady circular yellow signal indication to drivers", "MUTCD11", {"4A.03"}),
    ("Crash experience warrant for installing a traffic control signal", "MUTCD11", {"4C.08"}),
    ("How many signal faces are required on an approach?", "MUTCD11", {"4D.05"}),
    ("Yellow change and red clearance for bicycle signal faces", "MUTCD11", {"4H.11"}),
    ("Pedestrian signal head size design and illumination", "MUTCD11", {"4I.02"}),
    ("Protected permissive left turn indications in a separate signal face", "MUTCD11", {"4F.08", "4F.07"}),
    ("MMU minimum yellow change red clearance interval monitoring", "NEMA_TS2", {"4.4.5", "2.3.8"}),
    ("Loop detector unit environmental tests", "NEMA_TS2", {"2.8", "2.8.1"}),
    ("Flashing yellow arrow support in the malfunction management unit", "NEMA_TS2", {"4.6", "4.1.3", "4.6.2", "4.6.3"}),
    ("Port 1 timeout behaviour of the malfunction management unit", "NEMA_TS2", {"4.4.6", "2.3.9"}),
    ("Cabinet ventilation fan design", "NEMA_TS2", {"7.9", "7.9.1", "7.9.2"}),
]


def verdict_benchmark(evaluator=None):
    evaluator = evaluator or CrashEvaluator()
    crashes = pd.read_csv(config.RAW_DIR / "crash_events.csv")
    rows = []
    for crash in crashes.itertuples(index=False):
        result = evaluator.evaluate(crash.crash_id, with_evidence=False)
        rows.append({"crash_id": crash.crash_id, "expected": TRUTH_TO_VERDICT[crash.scenario_truth],
                     "predicted": result["verdict"], "confidence": result["confidence"]})
    frame = pd.DataFrame(rows)
    labels = sorted(set(frame["expected"]) | set(frame["predicted"]))
    per_class = {}
    for label in labels:
        tp = int(((frame.expected == label) & (frame.predicted == label)).sum())
        fp = int(((frame.expected != label) & (frame.predicted == label)).sum())
        fn = int(((frame.expected == label) & (frame.predicted != label)).sum())
        per_class[label] = {
            "support": int((frame.expected == label).sum()),
            "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        }
    confusion = defaultdict(Counter)
    for r in rows:
        confusion[r["expected"]][r["predicted"]] += 1
    errors = frame[frame.expected != frame.predicted]
    return {
        "crashes": len(frame),
        "accuracy": round(float((frame.expected == frame.predicted).mean()), 4),
        "per_class": per_class,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "misclassified": errors.to_dict(orient="records"),
        "high_confidence_share": round(float((frame.confidence == "HIGH").mean()), 4),
        "accuracy_by_confidence": {
            level: round(float((part.expected == part.predicted).mean()), 4)
            for level, part in frame.groupby("confidence")
        },
    }


def retrieval_benchmark(retriever=None):
    retriever = retriever or HierarchicalRetriever()
    hits1 = hits3 = 0
    rr_total = 0.0
    detail = []
    for question, doc_id, expected in RETRIEVAL_CASES:
        tier = "FEDERAL" if doc_id == "MUTCD11" else "HARDWARE"
        results = retriever.retrieve(question, tiers=(tier,), k=10, per_tier_floor=0)
        ranked_sections = []
        for ev in results:
            if ev.section_id not in ranked_sections:
                ranked_sections.append(ev.section_id)
        rank = next((i + 1 for i, s in enumerate(ranked_sections) if s in expected), None)
        hits1 += int(rank == 1)
        hits3 += int(rank is not None and rank <= 3)
        rr_total += (1.0 / rank) if rank else 0.0
        detail.append({"question": question, "expected": sorted(expected), "rank": rank,
                       "top_sections": ranked_sections[:3]})
    n = len(RETRIEVAL_CASES)
    return {"questions": n, "hit_at_1": round(hits1 / n, 4), "hit_at_3": round(hits3 / n, 4),
            "mrr": round(rr_total / n, 4), "detail": detail}


def run_all():
    report = {"verdicts": verdict_benchmark(), "retrieval": retrieval_benchmark()}
    write_json(config.ARTIFACT_DIR / "benchmark.json", report)
    return report
