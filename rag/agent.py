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
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import config
from .engine import answer

app = FastAPI(title="AegisGate RAG agent", version="1.0.0")


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
