"""Hierarchical retrieval: route by authority tier, rank sections, then paragraphs.

Level 1 (routing) restricts the corpus to the tiers a question needs and to the
state and municipality that own the intersection, so a Kestrel crash is never
argued with Avalon policy. Level 2 ranks sections within each tier with BM25
over heading and body. Level 3 ranks paragraphs only inside the winning
sections, weights them by provision type (a Standard outranks Support text)
and blends in the parent section score. Results are diversified so each
requested tier contributes evidence.
"""

import re
from dataclasses import dataclass

from .bm25 import BM25
from .config import RETRIEVAL
from .ingest import load_index
from .utils import UPPER_CLASS, sub

SECTION_REF = re.compile(r"\b(\d{1,2}" + UPPER_CLASS + r"\.\d{2})\b")
TIER_ORDER = ("FEDERAL", "STATE", "LOCAL", "HARDWARE")


@dataclass
class Evidence:
    doc_id: str
    tier: str
    citation: str
    section_id: str
    section_title: str
    para_no: str
    provision: str
    page: str
    text: str
    score: float

    def cite(self):
        parts = [self.citation]
        if self.tier == "FEDERAL":
            parts.append("Section " + self.section_id + " (" + self.section_title + ")")
        elif self.tier == "HARDWARE":
            parts.append(("" if self.section_id.startswith("Section") else "Section ") + self.section_id
                         + " (" + self.section_title + ")")
        else:
            parts.append(self.section_id + " (" + self.section_title + ")")
        parts.append("Paragraph " + self.para_no)
        parts.append(self.provision)
        if self.page:
            parts.append("page " + self.page)
        return ", ".join(parts)

    def as_dict(self):
        return {"citation": self.cite(), "tier": self.tier, "provision": self.provision,
                "section_id": self.section_id, "page": self.page, "score": round(self.score, 3),
                "text": self.text}


class HierarchicalRetriever:
    def __init__(self, documents=None):
        self.documents = documents if documents is not None else load_index()
        self.sections, self.paragraphs = [], []
        for doc in self.documents:
            for s_idx, section in enumerate(doc["sections"]):
                sec_pos = len(self.sections)
                self.sections.append({"doc": doc, "section": section, "paragraph_ids": []})
                for para in section["paragraphs"]:
                    self.sections[sec_pos]["paragraph_ids"].append(len(self.paragraphs))
                    self.paragraphs.append({"doc": doc, "section": section, "para": para, "sec_pos": sec_pos})
        self.section_index = BM25([
            (s["section"]["title"] + " ") * 3 + s["section"]["section_id"] + " "
            + " ".join(p["text"] for p in s["section"]["paragraphs"])[:5000]
            for s in self.sections
        ])
        self.paragraph_index = BM25([
            p["section"]["title"] + " " + p["section"]["section_id"] + " " + p["para"]["text"]
            for p in self.paragraphs
        ])

    def _eligible(self, doc, tiers, state_code, jurisdiction_code):
        if tiers and doc["tier"] not in tiers:
            return False
        if doc["tier"] == "STATE" and state_code and doc["state_code"] != state_code:
            return False
        if doc["tier"] == "LOCAL" and jurisdiction_code and doc["jurisdiction_code"] != jurisdiction_code:
            return False
        return True

    def retrieve(self, query, tiers=None, state_code=None, jurisdiction_code=None, k=None, per_tier_floor=1):
        k = k or RETRIEVAL.paragraphs_per_query
        tiers = tuple(tiers) if tiers else TIER_ORDER
        explicit = set(SECTION_REF.findall(query))
        chosen = {}
        for tier in tiers:
            candidates = [i for i, s in enumerate(self.sections)
                          if s["doc"]["tier"] == tier and self._eligible(s["doc"], tiers, state_code, jurisdiction_code)]
            if not candidates:
                continue
            ranked = self.section_index.top(query, RETRIEVAL.sections_per_tier, candidates)
            if ranked:
                best = ranked[0][0]
                floor = min(r[0] for r in ranked) if len(ranked) > 1 else 0.0
                spread = max(sub(best, floor), 0.000001)
                for score, idx in ranked:
                    chosen[idx] = 0.25 + 0.75 * sub(score, floor) / spread
            for idx in candidates:
                if self.sections[idx]["section"]["section_id"] in explicit:
                    chosen[idx] = 1.5
        if not chosen:
            return []
        para_candidates = [pid for sec in chosen for pid in self.sections[sec]["paragraph_ids"]]
        ranked = self.paragraph_index.top(query, len(para_candidates), para_candidates)
        top_score = ranked[0][0] if ranked else 1.0
        results = []
        for score, pid in ranked:
            p = self.paragraphs[pid]
            weight = RETRIEVAL.provision_weights.get(p["para"]["provision"], 1.0)
            blended = (score / top_score) * weight + RETRIEVAL.section_blend_weight * chosen.get(p["sec_pos"], 0.0)
            results.append(self._evidence(p, blended))
        results.sort(key=lambda e: e.score, reverse=True)
        return self._diversify(results, tiers, k, per_tier_floor)

    def _evidence(self, p, score):
        doc, section, para = p["doc"], p["section"], p["para"]
        return Evidence(doc["doc_id"], doc["tier"], doc["citation"], section["section_id"], section["title"],
                        para["para_no"], para["provision"], para["page"], para["text"], score)

    @staticmethod
    def _diversify(results, tiers, k, floor):
        picked, seen = [], set()
        for tier in tiers:
            for ev in [r for r in results if r.tier == tier][:floor]:
                picked.append(ev)
                seen.add(id(ev))
        for ev in results:
            if len(picked) >= k:
                break
            if id(ev) not in seen:
                picked.append(ev)
                seen.add(id(ev))
        picked.sort(key=lambda e: e.score, reverse=True)
        return picked[:max(k, len([t for t in tiers]))]

    def section(self, doc_id, section_id):
        for s in self.sections:
            if s["doc"]["doc_id"] == doc_id and s["section"]["section_id"] == section_id:
                return s["section"]
        return None

    def paragraph(self, doc_id, section_id, para_no):
        section = self.section(doc_id, section_id)
        if not section:
            return None
        for para in section["paragraphs"]:
            if para["para_no"] == para_no:
                doc = next(d for d in self.documents if d["doc_id"] == doc_id)
                return Evidence(doc_id, doc["tier"], doc["citation"], section_id, section["title"], para_no,
                                para["provision"], para["page"], para["text"], 1.0)
        return None
