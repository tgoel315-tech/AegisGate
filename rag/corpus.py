"""
Builds the retrieval corpus:
  * knowledge/*.md      SOPs and system documentation, split by heading
  * live incidents      pulled from the backend, one document per incident
  * stats               one summary document (counts per type, highest risk)
"""
import re
from collections import Counter
from datetime import datetime
from typing import List, Tuple

import requests

from . import config
from .retriever import Doc


def _t(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown"


def load_knowledge() -> List[Doc]:
    docs = []
    for path in sorted(config.KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parts = re.split(r"\n(?=## )", text)
        title = parts[0].splitlines()[0].lstrip("# ").strip() if parts else path.stem
        for i, part in enumerate(parts):
            heading = part.splitlines()[0].lstrip("# ").strip() if part.strip() else ""
            docs.append(Doc(f"{path.stem}#{i}", f"{title} — {part.strip()}", "knowledge",
                            {"file": path.name, "heading": heading}))
    return docs


def incident_text(inc: dict, redact: bool) -> str:
    badge = inc.get("badge") or {}
    holder = badge.get("holder_name")
    who = (badge.get("badge_id") or "unknown badge") if redact or not holder else \
        f"{holder} (badge {badge.get('badge_id') or '—'})"
    risk = inc.get("risk") or {}
    lines = [
        f"Incident {inc['id']} type {inc['type']} ({inc.get('title', '')}) at gate {inc.get('gate_id')}.",
        f"Detected {_t(inc.get('created_at'))}, last updated {_t(inc.get('updated_at'))}.",
        f"Risk score {risk.get('score')} severity {risk.get('severity')}.",
        f"Summary: {inc.get('message', '')}",
    ]
    if badge:
        lines.append(f"Badge: {who}, tapped {_t(badge.get('time'))}, "
                     f"{'authorised' if badge.get('authorized') else 'rejected'}.")
    for c in inc.get("crossings", []):
        lines.append(f"Camera track {c['track_id']} crossed {c.get('direction', 'IN')} at {_t(c['ts'])} — "
                     f"{'authorised' if c.get('authorized') else 'not authorised'}.")
    door = inc.get("door") or {}
    if door.get("opened_at"):
        lines.append(f"Door opened {_t(door['opened_at'])}, closed {_t(door.get('closed_at'))}, "
                     f"open {door.get('open_duration_s', 'n/a')} s.")
    if inc.get("extra_persons"):
        lines.append(f"Extra persons beyond the badge allowance: {inc['extra_persons']}.")
    for b in risk.get("breakdown", []):
        lines.append(f"Risk factor {b['factor']}: +{b['points']} because {b['reason']}.")
    lines.append(f"Evidence snapshots preserved: {len(inc.get('snapshots', []))}. "
                 f"PDF report available for {inc['id']}.")
    return " ".join(lines)


def load_incidents() -> Tuple[List[Doc], str]:
    try:
        r = requests.get(f"{config.BACKEND_URL}/api/incidents", params={"limit": config.MAX_INCIDENTS},
                         headers={"ngrok-skip-browser-warning": "1"}, timeout=6)
        r.raise_for_status()
        incidents = r.json()
    except Exception as exc:
        return [], f"backend unreachable ({exc.__class__.__name__})"

    docs = [Doc(inc["id"], incident_text(inc, config.REDACT_NAMES), "incident",
                {"type": inc["type"], "score": inc["risk"]["score"], "created_at": inc["created_at"]})
            for inc in incidents]
    if incidents:
        by_type = Counter(i["type"] for i in incidents)
        top = max(incidents, key=lambda i: i["risk"]["score"])
        latest = max(incidents, key=lambda i: i["created_at"])
        stats = (f"Incident statistics overview totals count how many: {len(incidents)} incidents on record "
                 f"between {_t(min(i['created_at'] for i in incidents))} and {_t(latest['created_at'])}. "
                 + " ".join(f"{t}: {n}." for t, n in by_type.most_common())
                 + f" Highest risk: {top['id']} ({top['type']}) score {top['risk']['score']}."
                 + f" Most recent: {latest['id']} ({latest['type']}) at {_t(latest['created_at'])}.")
        docs.append(Doc("stats", stats, "stats"))
    return docs, f"{len(incidents)} incidents loaded"
