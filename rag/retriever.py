"""
Dependency-free BM25 retriever. Small corpus (SOPs + a few hundred incidents),
so this is instant and needs no embedding API calls.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List

_TOKEN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_STOP = set("a an and are as at be by for from has have in is it of on or that the this to was were "
            "with what when which who why how did does do any all".split())


def tokenize(text: str) -> List[str]:
    toks = []
    for t in _TOKEN.findall(text.lower()):
        if t in _STOP:
            continue
        toks.append(t)
        if "-" in t or "_" in t:                     # also index the parts of INC-2026..., held_open
            toks.extend(p for p in re.split(r"[-_]", t) if p and p not in _STOP)
    return toks


@dataclass
class Doc:
    id: str
    text: str
    source: str                  # "knowledge" | "incident" | "stats"
    meta: dict = field(default_factory=dict)


class BM25:
    def __init__(self, docs: List[Doc], k1: float = 1.4, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tfs = [Counter(tokenize(d.text)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = (sum(self.lens) / len(self.lens)) if docs else 0
        df = Counter(t for tf in self.tfs for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 6) -> List[tuple]:
        q = tokenize(query)
        scored = []
        for i, tf in enumerate(self.tfs):
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avg or 1)))
            if s > 0:
                scored.append((s, self.docs[i]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]
