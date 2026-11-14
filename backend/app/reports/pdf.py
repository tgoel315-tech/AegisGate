"""
Feature 4 — evidence-based incident report as a downloadable PDF.
Contains: summary, badge and session details, crossing timeline, door timings,
the full risk-score breakdown and every preserved camera snapshot.
"""
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

NAVY = colors.HexColor("#0F1B3D")
PINK = colors.HexColor("#FF3D8B")
WHITE = colors.HexColor("#FFFFFF")
MUTED = colors.HexColor("#5B6684")
RULE = colors.HexColor("#D9DCE5")


def _t(ts: Optional[float], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.fromtimestamp(ts).strftime(fmt) if ts else "—"


def _table(rows, widths, header=True):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                  ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY)]
    t.setStyle(TableStyle(style))
    return t


def build_incident_pdf(inc: dict, snapshot_dir: Path) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"AegisGate incident {inc['id']}", author="AegisGate")
    ss = getSampleStyleSheet()
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=11, spaceBefore=10,
                        spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["BodyText"], textColor=NAVY, fontSize=9, leading=12)
    big = ParagraphStyle("big", parent=body, leading=24)
    small = ParagraphStyle("small", parent=body, textColor=MUTED, fontSize=7.5)
    risk = inc.get("risk", {})
    story = []

    # Header band
    head = Table([[Paragraph('<font color="#FFFFFF" size="15"><b>AEGISGATE</b></font><br/>'
                             '<font color="#FFFFFF" size="8">Incident report · Edge-AI anti-tailgating sentry</font>',
                             body),
                   Paragraph(f'<para alignment="right"><font color="#FF3D8B" size="22"><b>{risk.get("score", 0)}'
                             f'</b></font><font color="#FFFFFF" size="8"><br/>RISK · {risk.get("severity", "")}'
                             '</font></para>', big)]],
                 colWidths=[120 * mm, 58 * mm])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
                              ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                              ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LINEBELOW", (0, 0), (-1, -1), 2.5, PINK)]))
    story += [head, Spacer(1, 8)]
    story.append(Paragraph(f"<b>{inc.get('title', inc['type'])}</b> — {inc.get('message', '')}", body))

    badge = inc.get("badge") or {}
    session = inc.get("session") or {}
    door = inc.get("door") or {}
    story.append(Paragraph("Summary", h2))
    story.append(_table([
        ["Incident ID", inc["id"], "Gate", inc.get("gate_id", "—")],
        ["Type", inc["type"], "Status", inc.get("status", "OPEN")],
        ["Detected", _t(inc.get("created_at")), "Last updated", _t(inc.get("updated_at"))],
        ["Badge ID", badge.get("badge_id") or "—", "Holder", badge.get("holder_name") or "—"],
        ["Badge tap", _t(badge.get("time")), "Authorised", {True: "Yes", False: "No"}.get(badge.get("authorized"), "—")],
        ["Access window", f"{_t(session.get('opened_at'), '%H:%M:%S')} → {_t(session.get('expires_at'), '%H:%M:%S')}"
         if session else "—", "Allowed / entered",
         f"{session.get('allowed', '—')} / {len([c for c in inc.get('crossings', []) if c.get('direction') == 'IN'])}"],
        ["Door opened", _t(door.get("opened_at")), "Door closed", _t(door.get("closed_at"))],
        ["Door open time", f"{door['open_duration_s']} s" if door.get("open_duration_s") is not None else "—",
         "Extra persons", str(inc.get("extra_persons") or 0)],
    ], [30 * mm, 59 * mm, 30 * mm, 59 * mm], header=False))

    story.append(Paragraph("Risk score breakdown", h2))
    rows = [["Factor", "Points", "Reason"]]
    rows += [[b["factor"], f"+{b['points']}", Paragraph(b["reason"], body)] for b in risk.get("breakdown", [])]
    rows.append(["Total (max 100)", str(risk.get("score", 0)), risk.get("severity", "")])
    t = _table(rows, [42 * mm, 18 * mm, 118 * mm])
    t.setStyle(TableStyle([("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                           ("TEXTCOLOR", (1, -1), (1, -1), PINK)]))
    story.append(t)

    story.append(Paragraph("Event timeline", h2))
    timeline = []
    if badge.get("time"):
        timeline.append((badge["time"], "RFID", f"Badge {badge.get('badge_id') or '—'} "
                                                f"({badge.get('holder_name') or 'unknown'}) — "
                                                f"{'authorised' if badge.get('authorized') else 'rejected'}"))
    if door.get("opened_at"):
        timeline.append((door["opened_at"], "Door", "Door opened" + ("" if door.get("authorized") is not False
                                                                     else " without authorisation")))
    for c in inc.get("crossings", []):
        timeline.append((c["ts"], "Camera", f"Track {c['track_id']} crossed {c.get('direction', 'IN')}"
                                            f" — {'authorised' if c.get('authorized') else 'NOT authorised'}"
                                            + (f" (conf {c['confidence']:.2f})" if c.get("confidence") else "")))
    if door.get("closed_at"):
        timeline.append((door["closed_at"], "Door", "Door closed"))
    timeline.append((inc["created_at"], "AegisGate", f"Incident {inc['type']} raised"))
    timeline.sort(key=lambda x: x[0])
    story.append(_table([["Time", "Source", "Event"]] + [[_t(ts, "%H:%M:%S.%f")[:-4], src, Paragraph(txt, body)]
                                                       for ts, src, txt in timeline],
                        [26 * mm, 22 * mm, 130 * mm]))

    snaps = [snapshot_dir / s for s in inc.get("snapshots", []) if (snapshot_dir / s).exists()]
    if snaps:
        cells = []
        for p in snaps[:6]:
            img = Image(str(p), width=86 * mm, height=86 * mm * 0.75, kind="proportional")
            cells.append([img, Paragraph(p.name, small)])
        grid = [[cells[i], cells[i + 1] if i + 1 < len(cells) else ""] for i in range(0, len(cells), 2)]
        g = Table(grid, colWidths=[89 * mm, 89 * mm], hAlign="LEFT")
        g.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(KeepTogether([Paragraph("Evidence snapshots", h2), g]))

    story += [Spacer(1, 10), Paragraph(
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by AegisGate. The risk score is rule-based "
        "and fully listed above. The camera tracks movement only — it does not identify people. "
        "No commands were sent to the door hardware.", small)]
    doc.build(story)
    return buf.getvalue()
