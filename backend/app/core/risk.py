"""
Feature 1 — transparent, rule-based risk scoring (0-100). No ML, no LLM.

Every incident score is a sum of named factors. Each factor carries the points
it added and a plain-English reason, stored with the incident and printed in
the PDF so anyone can audit the number.

Incident score = base points for the incident type
               + extra-person points (tailgating / group unauthorised entry)
               + context points (forced door, rejected badges, held door, repeats)
               (clamped to 100)

Gate score     = highest time-decayed incident score in the risk window
               + 20 % of the other decayed scores   (clamped to 100)
               Decay is linear from 100 % (now) to 0 % (end of RISK_WINDOW_S).

Severity bands: 0-24 LOW · 25-49 MEDIUM · 50-74 HIGH · 75-100 CRITICAL
"""
from dataclasses import dataclass
from typing import List

BASE_POINTS = {
    "UNAUTHORIZED_BADGE": (15, "Badge was rejected (not on the authorised list)"),
    "DOOR_HELD_OPEN": (25, "Door stayed open beyond the allowed time"),
    "TAILGATING": (45, "More people entered than the badge authorised"),
    "UNAUTHORIZED_ENTRY": (55, "Person entered with no authorised access session"),
    "FORCED_DOOR": (60, "Door opened with no authorised badge tap in the last 6 s"),
}

RULES_TABLE = [
    {"factor": f"Base: {k.replace('_', ' ').title()}", "points": v[0], "rule": v[1]}
    for k, v in BASE_POINTS.items()
] + [
    {"factor": "Each additional extra person", "points": "+15 (max +30)",
     "rule": "Tailgating or unauthorised entry by a group"},
    {"factor": "Door forced in the last 60 s", "points": "+15",
     "rule": "Added to non-door incidents that coincide with a forced door"},
    {"factor": "Rejected badge attempts (last 5 min)", "points": "+10 each (max +20)",
     "rule": "Repeated card probing before the incident"},
    {"factor": "Door currently held open", "points": "+10",
     "rule": "Added to people incidents while the door is held"},
    {"factor": "Repeat incidents (last 10 min)", "points": "+5 each (max +15)",
     "rule": "Other incidents at the same gate"},
    {"factor": "Held-open overrun", "points": "+5 per 15 s over (max +20)",
     "rule": "Only for door-held-open incidents"},
]


def severity_for(score: int) -> str:
    if score >= 75:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


@dataclass
class RiskContext:
    door_forced_recent: bool = False
    denied_taps_recent: int = 0
    door_held_now: bool = False
    other_incidents_recent: int = 0
    held_open_threshold_s: float = 10.0


def score_incident(inc: dict, ctx: RiskContext) -> dict:
    breakdown: List[dict] = []

    def add(factor: str, points: int, reason: str) -> None:
        if points:
            breakdown.append({"factor": factor, "points": int(points), "reason": reason})

    itype = inc["type"]
    base, why = BASE_POINTS.get(itype, (10, "Security event"))
    add("Base", base, why)

    if itype == "TAILGATING":
        extra = int(inc.get("extra_persons", 1))
        if extra > 1:
            add("Extra persons", min(30, 15 * (extra - 1)),
                f"{extra} unauthorised people followed one badge tap")
    if itype == "UNAUTHORIZED_ENTRY":
        n = len([c for c in inc.get("crossings", []) if c.get("direction") == "IN"])
        if n > 1:
            add("Group entry", min(30, 15 * (n - 1)), f"{n} people entered without authorisation")
    if itype == "DOOR_HELD_OPEN":
        dur = float((inc.get("door") or {}).get("open_duration_s") or 0)
        over = max(0.0, dur - ctx.held_open_threshold_s)
        add("Held-open overrun", min(20, 5 * int(over // 15)),
            f"Door open {dur:.0f} s ({over:.0f} s over the limit)")

    if ctx.door_forced_recent and itype != "FORCED_DOOR":
        add("Forced door nearby", 15, "The door was forced open within the last 60 s")
    if ctx.denied_taps_recent and itype != "UNAUTHORIZED_BADGE":
        add("Rejected badges", min(20, 10 * ctx.denied_taps_recent),
            f"{ctx.denied_taps_recent} rejected badge attempt(s) in the last 5 min")
    if ctx.door_held_now and itype in ("TAILGATING", "UNAUTHORIZED_ENTRY"):
        add("Door held open", 10, "The door was being held open during the entry")
    if ctx.other_incidents_recent:
        add("Repeat activity", min(15, 5 * ctx.other_incidents_recent),
            f"{ctx.other_incidents_recent} other incident(s) at this gate in the last 10 min")

    score = max(0, min(100, sum(b["points"] for b in breakdown)))
    return {"score": score, "severity": severity_for(score), "breakdown": breakdown}


def gate_risk(incidents: List[dict], now: float, window_s: float) -> dict:
    decayed = []
    for inc in incidents:
        age = now - float(inc.get("updated_at") or inc["created_at"])
        if age < 0 or age > window_s:
            continue
        weight = 1.0 - age / window_s
        decayed.append((inc["risk"]["score"] * weight, inc, weight))
    if not decayed:
        return {"score": 0, "severity": "LOW",
                "breakdown": [{"factor": "No recent incidents", "points": 0,
                               "reason": f"Nothing in the last {int(window_s // 60)} min"}]}
    decayed.sort(key=lambda d: d[0], reverse=True)
    top, rest = decayed[0], decayed[1:]
    score = top[0] + 0.2 * sum(d[0] for d in rest)
    breakdown = [{"factor": top[1]["type"].replace("_", " ").title(), "points": round(top[0]),
                  "reason": f"Highest incident ({top[1]['risk']['score']} pts x {top[2]:.0%} recency)"}]
    if rest:
        breakdown.append({"factor": "Other incidents", "points": round(0.2 * sum(d[0] for d in rest)),
                          "reason": f"20 % of {len(rest)} other decayed incident score(s)"})
    score = int(round(min(100.0, score)))
    return {"score": score, "severity": severity_for(score), "breakdown": breakdown}
