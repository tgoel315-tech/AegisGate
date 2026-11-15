"""
LLM call for the incident assistant. Works with any OpenAI-compatible provider:
xAI Grok, Groq, Prune or OpenAI. The provider is detected from the key (see config.py).
"""
from typing import Optional, Tuple

from . import config

SYSTEM_PROMPT = """You are the AegisGate SOC incident assistant for an access-controlled door.
Rules:
- Answer ONLY from the CONTEXT blocks. If the answer is not there, say you don't have that record.
- You are advisory. You never decide access, never change risk scores and cannot control the door,
  buzzer, LEDs or lock. Risk scores come from AegisGate's rule engine; explain them using the listed factors.
- The camera tracks movement only; never claim it identified a person.
- Cite sources in square brackets using the block ids, e.g. [INC-20261114-3FE987] or [sop_tailgating#2].
- Be brief and concrete: times, counts, badge ids, scores."""

_state = {"client": None, "model": None}


def _client():
    if _state["client"] is None:
        from openai import OpenAI
        headers = {}
        if config.LLM_PROVIDER == "prune":
            headers = {"X-Prune-Feature-Id": config.PRUNE_FEATURE_ID, "X-Prune-Workload": "aegisgate"}
        _state["client"] = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY,
                                  default_headers=headers or None, timeout=30)
    return _state["client"]


def pick_model() -> str:
    """Use LLM_MODEL if set; otherwise the first preferred model this key can access."""
    if config.LLM_MODEL:
        return config.LLM_MODEL
    if _state["model"]:
        return _state["model"]
    preferred = config.PREFERRED_MODELS.get(config.LLM_PROVIDER, [])
    try:
        available = [m.id for m in _client().models.list().data]
    except Exception:
        available = []
    choice = next((m for m in preferred if m in available), None)
    if not choice and available:            # nothing on our list: take a small chat model if we can spot one
        text = [m for m in available if not any(x in m for x in ("image", "vision", "imagine", "whisper",
                                                                  "tts", "embed", "guard", "video"))]
        choice = next((m for m in text if any(x in m for x in ("mini", "fast", "instant"))), None) or \
            (text[0] if text else available[0])
    _state["model"] = choice or (preferred[0] if preferred else "gpt-4o-mini")
    return _state["model"]


def status() -> dict:
    return {"provider": config.LLM_LABEL or None, "configured": bool(config.LLM_API_KEY),
            "base_url": config.LLM_BASE_URL or None}


def generate(question: str, context: str) -> Tuple[Optional[str], dict]:
    """Returns (answer or None, info). None means 'use the extractive fallback'."""
    if not config.LLM_API_KEY:
        return None, {"mode": "extractive", "reason": "no LLM key set"}
    model = pick_model()
    try:
        resp = _client().chat.completions.with_raw_response.create(
            model=model,
            temperature=0.1,
            max_tokens=600,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"}],
        )
        completion = resp.parse()
        text = (completion.choices[0].message.content or "").strip()
        if not text:
            return None, {"mode": "extractive", "reason": f"{config.LLM_LABEL} returned an empty answer"}
        return text, {"mode": "llm", "model": model, "provider": config.LLM_LABEL,
                      "receipt": completion.model_dump().get("prune_metadata")}
    except Exception as exc:
        detail = str(getattr(exc, "message", "") or exc)[:160]
        return None, {"mode": "extractive", "provider": config.LLM_LABEL, "model": model,
                      "reason": f"{config.LLM_LABEL} call failed: {exc.__class__.__name__}: {detail}"}
