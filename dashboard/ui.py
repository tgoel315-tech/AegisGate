"""
Minimal visual layer. Palette is strictly #0F1B3D (navy), #FFFFFF (white) and
#FF3D8B (pink); every other shade is one of those three at reduced opacity.
"""
import base64
import html
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

NAVY, WHITE, PINK = "#0F1B3D", "#FFFFFF", "#FF3D8B"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
:root { --navy:#0F1B3D; --white:#FFFFFF; --pink:#FF3D8B;
        --w70:rgba(255,255,255,.70); --w50:rgba(255,255,255,.50); --w12:rgba(255,255,255,.12);
        --w06:rgba(255,255,255,.06); --p15:rgba(255,61,139,.15); }
html, body, [class*="css"], .stMarkdown, .stButton button { font-family:'Plus Jakarta Sans',sans-serif; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stDecoration"] { display:none; }
.block-container { padding-top:1.1rem; padding-bottom:1rem; max-width:1600px; }
[data-testid="stSidebar"] { background:var(--navy); border-right:1px solid var(--w12); }
[data-testid="stSidebar"] .stMarkdown p, [data-testid="stSidebar"] .stMarkdown li { font-size:.8rem; line-height:1.45; }
hr { border-color:var(--w12) !important; }

/* buttons */
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button, [data-testid="stFormSubmitButton"] button, [data-testid="stPopover"] button {
  background:transparent; color:var(--white); border:1px solid var(--w12); border-radius:8px;
  font-weight:600; font-size:.78rem; letter-spacing:.02em; padding:.32rem .8rem; min-height:0; }
[data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover, [data-testid="stPopover"] button:hover {
  border-color:var(--pink); color:var(--pink); background:transparent; }
button[kind="primary"], button[kind="primaryFormSubmit"] { background:var(--pink) !important; border-color:var(--pink) !important; color:var(--navy) !important; }
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover { opacity:.9; }
[data-testid="stDownloadButton"] button { border-color:var(--pink); color:var(--pink); padding:.15rem .55rem; font-size:.7rem; }
[data-testid="stDownloadButton"] button:hover { background:var(--pink); color:var(--navy); }

/* tabs */
[data-baseweb="tab-list"] { gap:1.2rem; border-bottom:1px solid var(--w12); }
[data-baseweb="tab"] { font-size:.74rem; font-weight:700; letter-spacing:.12em; color:var(--w50); padding:0 0 .5rem 0; }
[data-baseweb="tab"][aria-selected="true"] { color:var(--white); }
[data-baseweb="tab-highlight"] { background:var(--pink); }
[data-baseweb="tab-border"] { display:none; }

/* layout primitives */
.ag-label { font-size:.66rem; font-weight:700; letter-spacing:.16em; color:var(--w50); text-transform:uppercase; }
.ag-mono  { font-family:'JetBrains Mono',monospace; }
.ag-card  { border:1px solid var(--w12); border-radius:14px; padding:14px 16px; }
.ag-pill  { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--w12); border-radius:999px;
            padding:3px 10px; font-size:.68rem; font-weight:700; letter-spacing:.1em; white-space:nowrap; }
.ag-pill.pink { border-color:var(--pink); color:var(--pink); }
.ag-pill.solid { background:var(--pink); border-color:var(--pink); color:var(--navy); }
.ag-dot { width:7px; height:7px; border-radius:50%; background:var(--white); display:inline-block; }
.ag-dot.pink { background:var(--pink); box-shadow:0 0 0 3px var(--p15); animation:agpulse 1.4s infinite; }
.ag-dot.dim  { background:var(--w50); }
@keyframes agpulse { 50% { box-shadow:0 0 0 6px rgba(255,61,139,0); } }

/* header */
.ag-header { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; padding:2px 0 14px;
             border-bottom:1px solid var(--w12); margin-bottom:14px; }
.ag-header .left, .ag-header .right { display:flex; gap:10px; align-items:center; }
.ag-header .right { justify-content:flex-end; }
.ag-title { text-align:center; }
.ag-title .h { font-size:1.55rem; line-height:1.2; font-weight:800; letter-spacing:.32em; margin:0; padding:0; color:var(--white); }
.ag-title span { font-size:.6rem; letter-spacing:.24em; color:var(--w50); font-weight:600; }
.ag-title b { color:var(--pink); }

/* KPI strip */
.ag-kpis { display:grid; grid-template-columns:repeat(6,1fr); gap:0; border:1px solid var(--w12); border-radius:14px;
           margin-bottom:16px; }
.ag-kpi { padding:10px 16px; border-right:1px solid var(--w12); }
.ag-kpi:last-child { border-right:none; }
.ag-kpi .v { font-size:1.35rem; font-weight:800; line-height:1.25; }
.ag-kpi .s { font-size:.66rem; color:var(--w50); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ag-kpi .v.pink { color:var(--pink); }

/* camera */
.ag-cam-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
.ag-video { position:relative; border:1px solid var(--w12); border-radius:14px; overflow:hidden; background:#0b1430;
            aspect-ratio:4/3; max-height:470px; width:100%; }
.ag-video img { width:100%; height:100%; object-fit:contain; display:block; }
.ag-banner { margin-top:8px; border-radius:10px; padding:8px 12px; background:var(--pink); color:var(--navy);
             font-weight:800; font-size:.78rem; letter-spacing:.06em; }
.ag-zones { display:flex; justify-content:space-between; margin-top:8px; font-size:.64rem; letter-spacing:.12em;
            color:var(--w50); font-weight:700; }
.ag-zones .mid { color:var(--pink); }

/* alert capture */
.ag-strip { display:flex; gap:12px; overflow-x:auto; padding-bottom:6px; scroll-snap-type:x mandatory; }
.ag-strip::-webkit-scrollbar { height:6px; } .ag-strip::-webkit-scrollbar-thumb { background:var(--w12); border-radius:6px; }
.ag-shot { flex:0 0 210px; scroll-snap-align:start; border:1px solid var(--w12); border-radius:12px; overflow:hidden; }
.ag-shot img { width:100%; height:128px; object-fit:cover; display:block; background:#0b1430; }
.ag-shot .meta { padding:8px 10px; font-size:.7rem; }
.ag-shot .meta .t { font-weight:700; font-size:.74rem; }
.ag-shot.crit { border-color:var(--pink); }
.ag-empty { color:var(--w50); font-size:.78rem; padding:26px 0; text-align:center; border:1px dashed var(--w12); border-radius:12px; }

/* feed */
.ag-row { display:grid; grid-template-columns:58px 64px 1fr; gap:10px; align-items:start; padding:9px 2px;
          border-bottom:1px solid var(--w06); font-size:.78rem; }
.ag-row .tm { color:var(--w50); font-family:'JetBrains Mono',monospace; font-size:.7rem; padding-top:2px; }
.ag-row .ttl { font-weight:600; }
.ag-row .dt { color:var(--w50); font-size:.7rem; margin-top:1px; }
.ag-tag { display:inline-block; text-align:center; border:1px solid var(--w12); border-radius:6px; padding:1px 0; width:58px;
          font-size:.6rem; font-weight:700; letter-spacing:.1em; color:var(--w70); }
.ag-tag.CRITICAL { background:var(--pink); border-color:var(--pink); color:var(--navy); }
.ag-tag.HIGH { border-color:var(--pink); color:var(--pink); }
.ag-tag.MEDIUM { border-color:var(--white); color:var(--white); }
.ag-inc { border-left:2px solid var(--pink); padding-left:8px; margin-left:-10px; }

/* entry/exit table */
.ag-table { width:100%; border-collapse:collapse; font-size:.78rem; }
.ag-table th { text-align:left; font-size:.62rem; letter-spacing:.14em; color:var(--w50); font-weight:700;
               padding:8px 6px; border-bottom:1px solid var(--w12); }
.ag-table td { padding:9px 6px; border-bottom:1px solid var(--w06); }
.ag-table td.m { font-family:'JetBrains Mono',monospace; font-size:.72rem; color:var(--w70); }

/* footer */
.ag-foot { border-top:1px solid var(--w12); margin-top:14px; padding-top:12px; }

/* risk bar */
.ag-bar { height:4px; background:var(--w12); border-radius:4px; margin-top:6px; overflow:hidden; }
.ag-bar > div { height:100%; background:var(--pink); }
</style>
"""


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


class Clock:
    def __init__(self, tz: str):
        try:
            self.tz = ZoneInfo(tz)
        except Exception:
            self.tz = None

    def fmt(self, ts: Optional[float], f: str = "%H:%M:%S") -> str:
        if not ts:
            return "--:--:--"
        return datetime.fromtimestamp(ts, self.tz).strftime(f)


def data_uri(jpeg: Optional[bytes]) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode() if jpeg else ""


def header(gate: Optional[dict], linked: bool, clock: Clock, now: float) -> str:
    status = (gate or {}).get("status", "OFFLINE")
    alarm = status in ("BREACH", "HELD OPEN")
    door = ((gate or {}).get("door") or {}).get("state", "UNKNOWN")
    online = gate is not None
    return f"""
<div class="ag-header">
  <div class="left">
    <span class="ag-pill"><span class="ag-dot {'dim' if not online else ''}"></span>{'SENTRY ONLINE' if online else 'BACKEND OFFLINE'}</span>
    <span class="ag-pill {'solid' if alarm else ''}">GATE · {esc(status)}</span>
    <span class="ag-pill {'pink' if door == 'OPEN' else ''}">DOOR · {esc(door)}</span>
  </div>
  <div class="ag-title"><div class="h">AEGIS<b>GATE</b></div><span>EDGE-AI ACCESS SENTRY &amp; TAILGATING MONITOR</span></div>
  <div class="right">
    <span class="ag-pill ag-mono">{clock.fmt(now)} {esc(clock.tz.key if clock.tz else '')}</span>
    <span class="ag-pill {'pink' if not linked else ''}"><span class="ag-dot {'pink' if not linked else ''}"></span>{'LIVE LINK' if linked else 'RECONNECTING'}</span>
  </div>
</div>"""


def kpis(gate: Optional[dict], clock: Clock) -> str:
    g = gate or {}
    c = g.get("counts") or {}
    v = g.get("vision") or {}
    r = g.get("risk") or {"score": 0, "severity": "LOW"}
    b = g.get("last_badge") or {}
    s = g.get("session")
    people = v.get("unique_people")
    badge_line = (f"{esc(b.get('holder_name'))} · {clock.fmt(b.get('time'))}" if b else "No taps yet")
    session_line = (f"{s['in_count']}/{s['allowed']} in · {max(0, s['remaining_s']):.0f}s left" if s else "No open session")
    door = g.get("door") or {}
    door_line = (f"open {door['open_for_s']:.0f}s" if door.get("open_for_s") is not None else
                 ("close events supported" if door.get("close_events_supported") else "contact sensor"))
    return f"""
<div class="ag-kpis">
  <div class="ag-kpi"><div class="ag-label">Risk score</div>
     <div class="v {'pink' if r['score'] >= 50 else ''}">{r['score']}<span class="ag-label" style="margin-left:8px">{esc(r['severity'])}</span></div>
     <div class="ag-bar"><div style="width:{r['score']}%"></div></div></div>
  <div class="ag-kpi"><div class="ag-label">Crossings in / out</div>
     <div class="v">{c.get('in', 0)} <span style="color:var(--w50)">/</span> {c.get('out', 0)}</div>
     <div class="s">{c.get('inside', 0)} authorised inside</div></div>
  <div class="ag-kpi"><div class="ag-label">Unique people</div>
     <div class="v">{people if people is not None else c.get('unique_crossers', 0)}</div>
     <div class="s">{esc(v.get('detector') or 'tracks that crossed')}</div></div>
  <div class="ag-kpi"><div class="ag-label">Last RFID</div>
     <div class="v {'pink' if b and not b.get('authorized') else ''}" style="font-size:1rem;padding:5px 0 3px">{'GRANTED' if b.get('authorized') else ('REJECTED' if b else '—')}</div>
     <div class="s">{badge_line}</div></div>
  <div class="ag-kpi"><div class="ag-label">Access session</div>
     <div class="v" style="font-size:1rem;padding:5px 0 3px">{'OPEN' if s else 'IDLE'}</div>
     <div class="s">{esc(s['holder']) + ' · ' if s else ''}{session_line}</div></div>
  <div class="ag-kpi"><div class="ag-label">Door sensor</div>
     <div class="v {'pink' if door.get('state') == 'OPEN' else ''}" style="font-size:1rem;padding:5px 0 3px">{esc(door.get('state', '—'))}</div>
     <div class="s">{door_line}</div></div>
</div>"""


def camera_head(gate: Optional[dict]) -> str:
    v = (gate or {}).get("vision") or {}
    online = v.get("online")
    fps = f"{v['fps']:.0f} FPS" if v.get("fps") else "— FPS"
    return f"""
<div class="ag-cam-head">
  <div style="display:flex;gap:10px;align-items:center">
    <span class="ag-pill {'pink' if online else ''}"><span class="ag-dot {'pink' if online else 'dim'}"></span>{'LIVE' if online else 'NO SIGNAL'}</span>
    <span class="ag-label">CCTV MON-01 · Chokepoint tripwire</span>
  </div>
  <div style="display:flex;gap:8px"><span class="ag-pill">{v.get('active_tracks') or 0} TRACKED</span><span class="ag-pill ag-mono">{fps}</span></div>
</div>"""


def breach_banner(gate: Optional[dict], incidents: list) -> str:
    if not gate or gate.get("status") not in ("BREACH", "HELD OPEN") or not incidents:
        return ""
    inc = incidents[0]
    return (f'<div class="ag-banner">ALARM · {esc(inc["title"]).upper()} · RISK {inc["risk"]["score"]} '
            f'— {esc(inc["message"])}</div>')


def zones() -> str:
    return ('<div class="ag-zones"><span>◀ PUBLIC CORRIDOR</span><span class="mid">| TRIPWIRE |</span>'
            '<span>RESTRICTED INTERIOR ▶</span></div>')


def alert_strip(incidents: list, images: dict, clock: Clock) -> str:
    cards = []
    for inc in incidents:
        snap = (inc.get("snapshots") or [None])[-1]
        img = images.get(snap)
        crit = inc["risk"]["severity"] in ("CRITICAL", "HIGH")
        cards.append(f"""
<div class="ag-shot {'crit' if crit else ''}">
  {'<img src="' + img + '"/>' if img else '<div style="height:128px;background:#0b1430"></div>'}
  <div class="meta"><div class="t">{esc(inc['title'])}</div>
    <div style="display:flex;justify-content:space-between;margin-top:4px">
      <span class="ag-mono" style="color:var(--w50)">{clock.fmt(inc['created_at'])}</span>
      <span class="ag-tag {inc['risk']['severity']}" style="width:auto;padding:1px 6px">{inc['risk']['score']} {SEV_SHORT.get(inc['risk']['severity'], '')}</span>
    </div></div>
</div>""")
    if not cards:
        return '<div class="ag-empty">No breaches detected. Perimeter secure.</div>'
    return '<div class="ag-strip">' + "".join(cards) + "</div>"


SEV_SHORT = {"CRITICAL": "CRIT", "HIGH": "HIGH", "MEDIUM": "MED", "LOW": "LOW"}
TAGS = {"BADGE": "RFID", "CROSSING": "CAM", "DOOR": "DOOR", "ENTRY": "ENTRY", "SYSTEM": "SYS"}


def feed_row(item: dict, clock: Clock) -> str:
    sev = item.get("severity") or ""
    tag = SEV_SHORT.get(sev, sev) if item["kind"] == "INCIDENT" else TAGS.get(item["kind"], item["kind"][:5])
    tag_cls = sev if item["kind"] == "INCIDENT" or sev in ("HIGH", "CRITICAL") else ""
    return f"""
<div class="ag-row {'ag-inc' if item['kind'] == 'INCIDENT' else ''}">
  <div class="tm">{clock.fmt(item['ts'])}</div>
  <div><span class="ag-tag {tag_cls}">{esc(tag)}</span></div>
  <div><div class="ttl">{esc(item['title'])}</div><div class="dt">{esc(item.get('detail'))}</div></div>
</div>"""


def records_table(records: list, clock: Clock) -> str:
    rows = []
    n = len(records)
    for i, r in enumerate(records):
        inside = r["status"] == "INSIDE"
        rows.append(f"""<tr><td class="m">{n - i:03d}</td>
<td><span class="ag-dot {'' if inside else 'dim'}" style="margin-right:8px"></span>{esc(r.get('holder') or 'Unknown')}</td>
<td class="m">{clock.fmt(r['time_in'])}</td><td class="m">{clock.fmt(r.get('time_out'))}</td></tr>""")
    if not rows:
        return '<div class="ag-empty">No entries yet.</div>'
    return ('<table class="ag-table"><thead><tr><th>SERIAL</th><th>NAME</th><th>TIME IN</th><th>TIME OUT</th>'
            '</tr></thead><tbody>' + "".join(rows) + "</tbody></table>")
