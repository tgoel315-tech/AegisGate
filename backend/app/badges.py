"""
Authorised badge list. Replace or extend with the real card UIDs Alok's reader prints.
A tap is authorised if its badge_id is listed here (or, if AUTHORIZE_BY_HOLDER_NAME
is on, if the hardware supplied a holder_name).
"""
from typing import Optional

BADGES = {
    "E2806892": {"name": "Dr. Sarah Connor", "role": "Head of Cyber Security"},
    "A4109823": {"name": "Alex Vance", "role": "Lead Infrastructure Architect"},
    "B9302184": {"name": "Elena Rostova", "role": "Senior Cloud Engineer"},
    "C1045921": {"name": "Marcus Brody", "role": "Director of R&D"},
    "D8823190": {"name": "David Chen", "role": "Network Defense Specialist"},
}

_EMPTY_NAMES = {"", "unknown", "none", "null", "n/a", "-"}


def lookup(badge_id: Optional[str]) -> Optional[dict]:
    if not badge_id:
        return None
    return BADGES.get(str(badge_id).strip().upper())


def clean_holder(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    name = str(name).strip()
    return None if name.lower() in _EMPTY_NAMES else name
