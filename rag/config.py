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

# Prune = OpenAI-compatible gateway. Your OpenAI (or other provider) key stays in the
# Prune vault; this service only ever holds the Prune key.
PRUNE_API_KEY = os.getenv("PRUNE_API_KEY", "")
PRUNE_BASE_URL = os.getenv("PRUNE_BASE_URL", "https://api.withprune.com/v1")
PRUNE_MODEL = os.getenv("PRUNE_MODEL", "gpt-4o-mini")
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
