"""Dependency free Okapi BM25 with a small traffic engineering thesaurus."""

import math
import re
from collections import Counter

from .config import RETRIEVAL
from .utils import neg, sub

NEG1 = neg(1)
NEG3 = neg(3)

TOKEN = re.compile(r"[^\W_]+(?:\.[^\W_]+)*", re.ASCII)
STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the this to was were
will with which when where who what shall should may can than then there these those such any all not no
into per""".split())
SYNONYMS = {
    "amber": ["yellow"],
    "yellow": ["change"],
    "allred": ["red", "clearance"],
    "clearance": ["red"],
    "loop": ["detector", "detection"],
    "detector": ["detection", "loop"],
    "mmu": ["malfunction", "management", "monitor"],
    "conflict": ["monitor", "malfunction"],
    "timing": ["interval", "duration"],
    "preempt": ["preemption"],
    "firetruck": ["preemption", "emergency"],
    "ped": ["pedestrian"],
    "crosswalk": ["pedestrian"],
    "liability": ["responsibility", "maintenance"],
    "maintenance": ["responsibility", "repair"],
    "controller": ["controller", "unit", "cabinet"],
    "flash": ["flashing"],
    "many": ["number"],
    "fya": ["flashing", "yellow", "arrow"],
}


def stem(token):
    """Light plural stemmer: keeps section identifiers and short tokens intact."""
    if len(token) <= 4 or not token.isalpha():
        return token
    if token.endswith("ies"):
        return token[:len(token) + NEG3] + "y"
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:len(token) + NEG1]
    return token


def tokenize(text, expand=False):
    tokens = [stem(t) for t in TOKEN.findall(text.lower().replace("all red", "allred")) if t not in STOPWORDS]
    if expand:
        extra = []
        for t in tokens:
            extra.extend(SYNONYMS.get(t, []))
        tokens = tokens + extra
    return tokens


class BM25:
    def __init__(self, documents, k1=None, b=None):
        self.k1 = RETRIEVAL.bm25_k1 if k1 is None else k1
        self.b = RETRIEVAL.bm25_b if b is None else b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df = Counter()
        for c in self.docs:
            df.update(c.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1.0 + (sub(n, f) + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query_tokens, index):
        doc = self.docs[index]
        norm = self.k1 * (sub(1.0, self.b) + self.b * self.lengths[index] / self.avg)
        total = 0.0
        for t in query_tokens:
            tf = doc.get(t)
            if tf:
                total += self.idf.get(t, 0.0) * tf * (self.k1 + 1.0) / (tf + norm)
        return total

    def top(self, query, k=10, candidates=None, expand=True):
        tokens = tokenize(query, expand=expand)
        pool = range(len(self.docs)) if candidates is None else candidates
        scored = [(self.score(tokens, i), i) for i in pool]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: s[0], reverse=True)
        return scored[:k]
