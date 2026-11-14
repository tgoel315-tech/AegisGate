"""
LLM calls go through Prune (https://www.withprune.com), an OpenAI-compatible
gateway: it trims cost, keeps the provider key in its vault, blocks risky
requests (Shield) and returns a signed receipt (`prune_metadata`) on every call.
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


def _client():
    from openai import OpenAI
    return OpenAI(base_url=config.PRUNE_BASE_URL, api_key=config.PRUNE_API_KEY,
                  default_headers={"X-Prune-Feature-Id": config.PRUNE_FEATURE_ID,
                                   "X-Prune-Workload": "aegisgate"})


def generate(question: str, context: str) -> Tuple[Optional[str], dict]:
    """Returns (answer or None, info). None means 'use the extractive fallback'."""
    if not config.PRUNE_API_KEY:
        return None, {"mode": "extractive", "reason": "PRUNE_API_KEY not set"}
    try:
        resp = _client().chat.completions.with_raw_response.create(
            model=config.PRUNE_MODEL,
            temperature=0.1,
            max_tokens=450,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"}],
        )
        completion = resp.parse()
        receipt = completion.model_dump().get("prune_metadata")
        return completion.choices[0].message.content, {
            "mode": "llm", "model": config.PRUNE_MODEL, "gateway": "prune", "receipt": receipt,
            "pipeline": resp.headers.get("x-prune-pipeline-label")}
    except Exception as exc:
        shield = None
        response = getattr(exc, "response", None)
        if response is not None:
            shield = response.headers.get("x-prune-shield-code")
        return None, {"mode": "extractive", "reason": f"LLM call failed: {exc.__class__.__name__}",
                      "shield_code": shield}
