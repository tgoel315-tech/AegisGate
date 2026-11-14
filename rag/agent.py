"""
AegisGate incident RAG agent — deployable on Maritime.

Endpoints
  GET  /health   Maritime health check
  POST /chat     Maritime chat contract: {"message": "...", "source": "..."} -> {"response": "..."}
  POST /ask      Dashboard API: {"question": "..."} -> answer + sources + Prune receipt

Retrieval: BM25 over SOP docs + live incidents from the backend.
Generation: LLM via the Prune gateway (falls back to quoting the top records if no key).
The agent is read-only and advisory: it explains incidents, it never makes access decisions.
"""
import time
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import config
from .corpus import load_incidents, load_knowledge
from .llm import generate
from .retriever import BM25

app = FastAPI(title="AegisGate RAG agent", version="1.0.0")
_knowledge = load_knowledge()
_cache = {"at": 0.0, "index": None, "status": ""}


def _index(max_age_s: float = 10.0) -> BM25:
    if _cache["index"] is None or time.time() - _cache["at"] > max_age_s:
        incidents, status = load_incidents()
        _cache.update(index=BM25(_knowledge + incidents), at=time.time(), status=status)
    return _cache["index"]


_TYPE_WORDS = {
    "TAILGATING": ("tailgat", "piggyback", "followed"),
    "UNAUTHORIZED_ENTRY": ("unauthori", "intru", "without badge", "no badge"),
    "FORCED_DOOR": ("forced", "force"),
    "DOOR_HELD_OPEN": ("held", "propped", "left open"),
    "UNAUTHORIZED_BADGE": ("reject", "denied", "invalid badge", "unknown badge"),
}


def _rank(question: str, hits: list) -> list:
    """Boost incidents of the type the question names, then mix knowledge and records
    so the answer sees both the procedure and the actual evidence."""
    q = question.lower()
    wanted = {t for t, words in _TYPE_WORDS.items() if any(w in q for w in words)}
    rescored = sorted(((s * (2.0 if d.meta.get("type") in wanted else 1.0), d) for s, d in hits),
                      key=lambda x: x[0], reverse=True)
    knowledge = [h for h in rescored if h[1].source == "knowledge"][:3]
    records = [h for h in rescored if h[1].source != "knowledge"]
    picked = (records[: max(2, config.TOP_K - len(knowledge))] + knowledge)[: config.TOP_K]
    return sorted(picked, key=lambda x: x[0], reverse=True)


def answer(question: str) -> dict:
    question = (question or "").strip()[:1000]
    if not question:
        return {"answer": "Ask me about an incident, a badge, a time window or how the risk score works.",
                "sources": [], "mode": "none"}
    hits = _rank(question, _index().search(question, k=40))
    # Questions about totals should always see the stats document.
    if any(w in question.lower() for w in ("how many", "count", "total", "today", "latest", "highest")):
        stats = [d for d in _index().docs if d.id == "stats"]
        if stats and all(h[1].id != "stats" for h in hits):
            hits = [(0.0, stats[0])] + hits[: config.TOP_K - 1]
    context = "\n\n".join(f"[{d.id}] {d.text}" for _, d in hits) or "(no matching records)"
    text, info = generate(question, context)
    if text is None:
        if hits:
            text = "Most relevant records:\n\n" + "\n\n".join(
                f"[{d.id}] {d.text[:420]}{'…' if len(d.text) > 420 else ''}" for _, d in hits[:3])
        else:
            text = "I couldn't find any matching incident or procedure."
    return {"answer": text,
            "sources": [{"id": d.id, "source": d.source, **d.meta} for _, d in hits],
            "corpus": _cache["status"], **info}


class AskIn(BaseModel):
    question: str


class ChatIn(BaseModel):
    message: str
    source: Optional[str] = None


def _auth(token: Optional[str]) -> None:
    if config.AGENT_TOKEN and token != config.AGENT_TOKEN:
        raise HTTPException(401, "Missing or wrong X-Agent-Token")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(body: AskIn, x_agent_token: Optional[str] = Header(default=None)):
    _auth(x_agent_token)
    return answer(body.question)


@app.post("/chat")
def chat(body: ChatIn, x_agent_token: Optional[str] = Header(default=None)):
    _auth(x_agent_token)
    result = answer(body.message)
    return {"response": result["answer"], "sources": result["sources"], "mode": result.get("mode")}
