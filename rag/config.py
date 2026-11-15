import os
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = RAG_DIR / "knowledge"

# Local convenience: read rag/.env if present (Maritime injects real env vars instead).
_env = RAG_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ---------------------------------------------------------------- LLM provider
# Paste ONE key; the provider is detected from its prefix:
#   xai-...    -> xAI Grok    https://api.x.ai/v1
#   gsk_...    -> Groq        https://api.groq.com/openai/v1
#   prune_...  -> Prune       https://api.withprune.com/v1   (gateway in front of OpenAI etc.)
#   sk-...     -> OpenAI      https://api.openai.com/v1
# Accepted variable names: LLM_API_KEY, GROK_API_KEY, XAI_API_KEY, GROQ_API_KEY, PRUNE_API_KEY.
PROVIDERS = {
    "xai":    {"prefix": "xai-",   "base_url": "https://api.x.ai/v1",            "label": "xAI Grok"},
    "groq":   {"prefix": "gsk_",   "base_url": "https://api.groq.com/openai/v1", "label": "Groq"},
    "prune":  {"prefix": "prune_", "base_url": "https://api.withprune.com/v1",   "label": "Prune"},
    "openai": {"prefix": "sk-",    "base_url": "https://api.openai.com/v1",      "label": "OpenAI"},
}
# Preferred models, best first. The first one your key can actually use is chosen
# automatically (checked against the provider's /models list). Override with LLM_MODEL.
PREFERRED_MODELS = {
    "xai": ["grok-4.1-fast", "grok-4-fast", "grok-3-mini", "grok-3", "grok-4"],
    "groq": ["openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"],
    "prune": ["gpt-4o-mini"],
    "openai": ["gpt-4o-mini"],
}


def _first_env(*names: str) -> str:
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return v
    return ""


LLM_API_KEY = _first_env("LLM_API_KEY", "GROK_API_KEY", "XAI_API_KEY", "GROQ_API_KEY", "PRUNE_API_KEY",
                         "OPENAI_API_KEY")


def _detect(key: str) -> str:
    forced = os.getenv("LLM_PROVIDER", "").strip().lower()
    if forced in PROVIDERS:
        return forced
    for name, p in PROVIDERS.items():
        if key.startswith(p["prefix"]):
            return name
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    return "xai" if (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")) else "openai"


LLM_PROVIDER = _detect(LLM_API_KEY) if LLM_API_KEY else ""
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or (PROVIDERS[LLM_PROVIDER]["base_url"] if LLM_PROVIDER else "")
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("PRUNE_MODEL", "")      # empty = auto-pick
LLM_LABEL = PROVIDERS.get(LLM_PROVIDER, {}).get("label", "")
PRUNE_FEATURE_ID = os.getenv("PRUNE_FEATURE_ID", "aegisgate_incident_rag")

# Where to read live incidents from (local backend, or its public ngrok URL when
# this agent runs on Maritime).
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

TOP_K = int(os.getenv("RAG_TOP_K", "6"))
MAX_INCIDENTS = int(os.getenv("RAG_MAX_INCIDENTS", "200"))
# Replace badge-holder names with badge ids before anything is sent to the LLM.
REDACT_NAMES = os.getenv("RAG_REDACT_NAMES", "false").lower() in ("1", "true", "yes")
# Optional shared secret the dashboard sends as X-Agent-Token.
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
