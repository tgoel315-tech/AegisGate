"""
Check that your LLM key works before using it in the dashboard.

    python scripts/test_llm_key.py xai-xxxxxxxx        (or gsk_..., prune_..., sk-...)
    python scripts/test_llm_key.py                     (reads LLM_API_KEY / GROK_API_KEY / ... from the env)

Prints the detected provider, the model it will use, and a one-line test reply.
"""
import os
import sys
from pathlib import Path

if len(sys.argv) > 1:
    os.environ["LLM_API_KEY"] = sys.argv[1].strip()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag import config, llm  # noqa: E402

if not config.LLM_API_KEY:
    sys.exit("No key found. Usage: python scripts/test_llm_key.py <your-key>")

print(f"Provider : {config.LLM_LABEL}  ({config.LLM_BASE_URL})")
try:
    models = [m.id for m in llm._client().models.list().data]
    print(f"Key OK   : {len(models)} models available")
except Exception as exc:
    if exc.__class__.__name__ in ("APIConnectionError", "APITimeoutError"):
        sys.exit(f"Could not reach {config.LLM_BASE_URL}: check your internet / firewall / VPN.")
    sys.exit(f"Key REJECTED: {exc.__class__.__name__}: {exc}\n"
             "Check the key was copied fully, and that billing/credits are enabled on the provider console.")
print(f"Model    : {llm.pick_model()}   (override with LLM_MODEL=...)")
text, info = llm.generate("Reply with exactly: AegisGate assistant online.", "(test)")
print(f"Reply    : {text or info.get('reason')}")
