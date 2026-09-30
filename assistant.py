"""Question router for the legal assistant.

Routes
* HYBRID_CRASH: the question names a crash (CR00017). Structured logs and
  telemetry are evaluated and every finding is paired with authority.
* STRUCTURED_STATE: an intersection and a timestamp are named. The signal
  state at that millisecond is returned with the provisions that define
  what each indication means.
* INTERSECTION_PROFILE: an intersection is named without a time. Timing
  compliance from the HCS style table plus crash history.
* REGULATORY: anything else. Hierarchical retrieval across the manuals,
  optionally restricted to a jurisdiction named in the question.
"""

import re

from . import llm, memo
from .evaluator import CrashEvaluator
from .jurisdictions import LOCALS, STATES
from .retriever import HierarchicalRetriever
from .store import StructuredRetriever
from .utils import stamp_to_ms, strip_dashes

CRASH_ID = re.compile(r"\bCR\d{5}\b", re.IGNORECASE)
INTERSECTION_ID = re.compile(r"\bINT\d{4}\b", re.IGNORECASE)
STAMP = re.compile(r"\b\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,3})?\b")


class LegalAssistant:
    def __init__(self):
        self.db = StructuredRetriever()
        self.rag = HierarchicalRetriever()
        self.evaluator = CrashEvaluator(self.db, self.rag)

    def _jurisdiction_filter(self, question):
        lowered = question.lower()
        for local in LOCALS.values():
            short = local.jurisdiction_name.split(" of ", 1)[1].lower()
            if short in lowered:
                return local.state_code, local.jurisdiction_code
        for state in STATES.values():
            if state.state_name.split(" of ")[1].lower() in lowered:
                return state.state_code, None
        return None, None

    def ask(self, question, save_report=True):
        crash = CRASH_ID.search(question)
        if crash:
            return self.crash_report(crash.group(0).upper(), question, save_report)
        inter = INTERSECTION_ID.search(question)
        stamp = STAMP.search(question)
        if inter and stamp:
            return self.state_at(inter.group(0).upper(), stamp.group(0), question)
        if inter:
            return self.intersection_profile(inter.group(0).upper(), question)
        return self.regulatory(question)

    def crash_report(self, crash_id, question=None, save_report=True):
        result = self.evaluator.evaluate(crash_id)
        narrative = llm.narrate(result, question)
        paths = memo.save(result, narrative) if save_report else (None, None)
        return {"route": "HYBRID_CRASH", "result": result, "narrative": narrative,
                "answer_markdown": memo.render_markdown(result, narrative),
                "report_paths": [str(p) for p in paths if p]}

    def state_at(self, intersection_id, stamp, question):
        epoch = stamp_to_ms(stamp)
        rows = self.db.state_at(intersection_id, epoch)
        inter = self.db.intersection(intersection_id)
        evidence = self.rag.retrieve("meaning of steady circular green yellow red signal indication",
                                     tiers=("FEDERAL",), k=4)
        lines = ["# Signal State at " + stamp + " for " + intersection_id, ""]
        if not rows:
            lines.append("No controller log interval covers that millisecond. Logs are retained around crash windows only.")
        for r in rows:
            lines.append("* Phase " + str(r["nema_phase"]) + " (" + r["movement"] + "): " + r["interval_type"]
                         + " from " + r["start_stamp"] + " to " + r["end_stamp"] + ", displayed "
                         + str(r["displayed_duration_ms"]) + " ms of " + str(r["programmed_duration_ms"]) + " ms programmed.")
        lines += ["", "Phases not listed were resting in red.", "", "## Meaning of Indications", ""]
        lines += ["* " + strip_dashes(e.cite()) + ": " + strip_dashes(e.text[:300]) for e in evidence]
        return {"route": "STRUCTURED_STATE", "intersection": inter, "rows": rows,
                "evidence": [e.as_dict() for e in evidence], "answer_markdown": "\n".join(lines)}

    def intersection_profile(self, intersection_id, question):
        inter = self.db.intersection(intersection_id)
        if not inter:
            return {"route": "INTERSECTION_PROFILE", "answer_markdown": "Unknown intersection " + intersection_id}
        rows = [r for r in self.db.hcs_rows(intersection_id, 2023) if r["timing_plan_id"] == 1]
        crashes = self.db.crashes(50, intersection_id)
        lines = ["# " + inter["intersection_name"] + " (" + intersection_id + ")", "",
                 inter["jurisdiction_name"] + ", " + STATES[inter["state_code"]].state_name + ". "
                 + inter["control_type"] + " control on a " + inter["controller_standard"] + " controller. Timing practice "
                 + inter["timing_practice"].replace("_", " ").lower() + ".", "", "## Clearance Timing, 2023 AM Peak Plan", ""]
        for r in rows:
            flag = " **Shortfall " + str(r["yellow_shortfall_s"]) + " s**" if r["yellow_shortfall_s"] > 0 else ""
            lines.append("* Phase " + str(r["nema_phase"]) + " " + r["movement"] + ": yellow " + str(r["yellow_s"])
                         + " s against " + str(r["required_yellow_s"]) + " s required, red clearance "
                         + str(r["red_clearance_s"]) + " s against " + str(r["required_red_clearance_s"])
                         + " s, LOS " + r["los"] + flag)
        lines += ["", "## Crash History", ""]
        lines += ["* " + c["crash_id"] + " " + c["crash_stamp"] + " " + c["crash_type"].lower() + " crash, phase "
                  + str(c["subject_phase"]) for c in crashes] or ["* No crashes on file."]
        return {"route": "INTERSECTION_PROFILE", "intersection": inter, "timing": rows, "crashes": crashes,
                "answer_markdown": "\n".join(lines)}

    def regulatory(self, question):
        state_code, jurisdiction_code = self._jurisdiction_filter(question)
        tiers = ("FEDERAL", "STATE", "LOCAL", "HARDWARE") if state_code else ("FEDERAL", "HARDWARE")
        evidence = self.rag.retrieve(question, tiers=tiers, state_code=state_code,
                                     jurisdiction_code=jurisdiction_code, k=6)
        generated = llm.answer_general(question, evidence)
        lines = ["# " + strip_dashes(question), ""]
        if generated:
            lines += [generated, ""]
        ranking = {"Standard": 0, "Clause": 0, "Guidance": 1, "Specification": 2, "Option": 3, "Support": 4}
        lines += ["## Most Relevant Provisions", ""]
        by_score = sorted(evidence, key=lambda x: x.score, reverse=True)
        for e in sorted(by_score, key=lambda x: ranking.get(x.provision, 5)):
            lines.append("* **" + e.provision + "** " + strip_dashes(e.cite()) + ": " + strip_dashes(e.text[:500]))
        if not evidence:
            lines.append("No matching provision was found in the knowledge base.")
        return {"route": "REGULATORY", "evidence": [e.as_dict() for e in evidence],
                "answer_markdown": "\n".join(lines)}
