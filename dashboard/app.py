"""
AegisGate SOC dashboard (owner: Amandeep) — Streamlit.

    streamlit run dashboard/app.py

Layout (same positions as the original HTML dashboard):
    header ............ sentry + gate status | AEGISGATE | clock + live link
    KPI strip ......... risk · in/out · unique people · last RFID · session · door
    left column ....... live camera  ▸  alert capture (evidence snapshots)
    right column ...... LIVE FEED of every record (PDF reports here only) | entry/exit log
    footer ............ judge controller (demo scenarios)
    sidebar ........... incident assistant (RAG via Prune/Maritime) + risk rules
"""
import time

import streamlit as st

import services as svc
import ui

st.set_page_config(page_title="AegisGate · SOC", page_icon="🛡️", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)

cfg = svc.settings()
link = svc.live_link(cfg.ws_url)
clock = ui.Clock(cfg.timezone)


def state():
    return svc.dashboard_state(cfg.backend_url, link.version, int(time.time() // 2))


# ------------------------------------------------------------------ header + KPIs
@st.fragment(run_every=1)
def header_panel():
    data = state()
    gate = data["gate"] if data else None
    st.markdown(ui.header(gate, link.connected, clock, time.time()), unsafe_allow_html=True)
    st.markdown(ui.kpis(gate, clock), unsafe_allow_html=True)


header_panel()
left, right = st.columns([1.55, 1], gap="large")


# ------------------------------------------------------------------ camera
@st.fragment(run_every=1)
def camera_status():
    data = state()
    st.markdown(ui.camera_head(data["gate"] if data else None), unsafe_allow_html=True)


@st.fragment(run_every=1)
def camera_polled():
    img = svc.frame_bytes(cfg.backend_url)
    st.markdown(f'<div class="ag-video"><img src="{ui.data_uri(img)}"/></div>', unsafe_allow_html=True)


@st.fragment(run_every=1)
def camera_banner():
    data = state()
    if data:
        st.markdown(ui.breach_banner(data["gate"], data["incidents"]) + ui.zones(), unsafe_allow_html=True)


with left:
    camera_status()
    stream = cfg.camera_mode == "mjpeg" or (cfg.camera_mode == "auto" and cfg.backend_is_local)
    if stream:   # smooth stream straight from the backend; the browser must reach BACKEND_URL
        st.markdown(f'<div class="ag-video"><img src="{cfg.backend_url}/api/video_feed"/></div>',
                    unsafe_allow_html=True)
    else:        # works anywhere (Streamlit Cloud + ngrok): server fetches a frame each second
        camera_polled()
    camera_banner()

    @st.fragment(run_every=1)
    def alert_capture():
        data = state()
        incidents = [i for i in (data or {}).get("incidents", []) if i["type"] != "UNAUTHORIZED_BADGE"][:12]
        images = {}
        for inc in incidents:
            snap = (inc.get("snapshots") or [None])[-1]
            if snap:
                images[snap] = ui.data_uri(svc.snapshot_bytes(cfg.backend_url, snap))
        st.markdown(f"""<div style="display:flex;justify-content:space-between;align-items:baseline;margin:18px 0 8px">
            <span class="ag-label" style="color:#fff;font-size:.74rem">Alert capture</span>
            <span class="ag-pill {'pink' if incidents else ''}">{len(incidents)} INCIDENTS</span></div>""",
                    unsafe_allow_html=True)
        st.markdown(ui.alert_strip(incidents, images, clock), unsafe_allow_html=True)

    alert_capture()


# ------------------------------------------------------------------ live feed (right)
FILTERS = {"All": None, "Incidents": {"INCIDENT"}, "Access": {"BADGE", "ENTRY"},
           "Camera": {"CROSSING"}, "Door": {"DOOR"}}

with right:
    @st.fragment(run_every=1)
    def live_feed():
        data = state()
        st.markdown('<div class="ag-label" style="color:#fff;font-size:.74rem;margin-bottom:4px">Real-time feed</div>',
                    unsafe_allow_html=True)
        tab_feed, tab_log = st.tabs(["LIVE FEED", "ENTRY / EXIT LOG"])
        if not data:
            tab_feed.markdown(f'<div class="ag-empty">Backend unreachable at {ui.esc(cfg.backend_url)}</div>',
                              unsafe_allow_html=True)
            return
        with tab_feed:
            choice = st.segmented_control("Filter", list(FILTERS), default="All", key="feed_filter",
                                          label_visibility="collapsed") or "All"
            kinds = FILTERS[choice]
            items = [f for f in data["feed"] if not kinds or f["kind"] in kinds]
            box = st.container(height=560, border=False)
            with box:
                if not items:
                    st.markdown('<div class="ag-empty">Nothing yet.</div>', unsafe_allow_html=True)
                buffer = []
                for item in items:
                    if item["kind"] != "INCIDENT" or not item.get("incident_id"):
                        buffer.append(ui.feed_row(item, clock))
                        continue
                    if buffer:
                        st.markdown("".join(buffer), unsafe_allow_html=True)
                        buffer = []
                    c1, c2 = st.columns([4, 1], vertical_alignment="center")
                    c1.markdown(ui.feed_row(item, clock), unsafe_allow_html=True)
                    c2.download_button(
                        "PDF", data=svc.pdf_loader(cfg.backend_url, item["incident_id"], item.get("updated_at", 0)),
                        file_name=f"{item['incident_id']}.pdf", mime="application/pdf",
                        key=f"pdf_{item['incident_id']}", on_click="ignore", width="stretch",
                        help="Download the evidence report (PDF)")
                if buffer:
                    st.markdown("".join(buffer), unsafe_allow_html=True)
        with tab_log:
            g = data["gate"]["counts"]
            st.markdown(f'<span class="ag-pill">ACTIVE INSIDE · {g.get("inside", 0)}</span>',
                        unsafe_allow_html=True)
            with st.container(height=560, border=False):
                st.markdown(ui.records_table(data["records"], clock), unsafe_allow_html=True)

    live_feed()


# ------------------------------------------------------------------ judge controller (footer)
st.markdown('<div class="ag-foot"><span class="ag-label">Judge controller · run a scenario</span></div>',
            unsafe_allow_html=True)
SCENARIOS = [("Normal entry", "normal"), ("Tailgating", "tailgating"), ("Unauthorised", "unauthorized"),
             ("Forced door", "forced"), ("Held open", "held_open")]
cols = st.columns([1, 1, 1, 1, 1, 0.9, 0.7], gap="small")
for col, (label, name) in zip(cols, SCENARIOS):
    if col.button(label, key=f"sc_{name}", use_container_width=True):
        ok, err = svc.post(cfg, f"/api/demo/scenario/{name}")
        st.toast(f"{label} scenario started" if ok else f"Failed: {err}")
with cols[5].popover("Manual", use_container_width=True):
    for label, kind in [("Tap valid badge", "tap"), ("Tap unknown badge", "tap_unknown"), ("Person IN", "in"),
                        ("Person OUT", "out"), ("Door open", "door_open"), ("Door close", "door_close")]:
        if st.button(label, key=f"ev_{kind}", use_container_width=True):
            ok, err = svc.post(cfg, f"/api/demo/event/{kind}")
            st.toast(f"Sent: {label}" if ok else f"Failed: {err}")
if cols[6].button("Reset", key="reset", use_container_width=True):
    ok, err = svc.post(cfg, "/api/demo/reset")
    st.toast("All records cleared" if ok else f"Failed: {err}")


# ------------------------------------------------------------------ sidebar: assistant
with st.sidebar:
    st.markdown('<div class="ag-label" style="color:#fff;font-size:.8rem">Incident assistant</div>'
                '<div style="color:rgba(255,255,255,.5);font-size:.72rem;margin:4px 0 12px">RAG over incidents + SOPs · '
                'LLM via Prune · hosted on Maritime. Advisory only: it never decides access.</div>',
                unsafe_allow_html=True)
    history = st.session_state.setdefault("chat", [])
    with st.form("ask", clear_on_submit=True, border=False):
        q = st.text_input("Question", placeholder="Why was the last tailgating incident high risk?",
                          label_visibility="collapsed")
        sent = st.form_submit_button("Ask", use_container_width=True, type="primary")
    if sent and q.strip():
        with st.spinner("Retrieving evidence…"):
            history.insert(0, (q, svc.ask_agent(cfg, q)))
    for question, res in history[:6]:
        st.markdown(f"**{ui.esc(question)}**")
        st.markdown(res.get("answer", ""))
        mode = res.get("mode")
        note = {"llm": f"LLM · {res.get('model', '')} via Prune",
                "extractive": f"No LLM ({res.get('reason', '')}) · top matching records",
                "error": "Assistant unreachable"}.get(mode, mode or "")
        srcs = " ".join(f"`{s['id']}`" for s in res.get("sources", [])[:6])
        st.caption(f"{note}  \n{srcs}")
        st.divider()

    with st.expander("How the risk score works"):
        rules = svc.risk_rules(cfg.backend_url)
        if rules:
            st.dataframe(rules["rules"], hide_index=True, use_container_width=True)
            st.caption(" · ".join(f"{k} {v}" for k, v in rules["severity_bands"].items()))
    st.caption(f"Backend `{cfg.backend_url}`  \nWebSocket {'connected' if link.connected else 'down: ' + str(link.error)}"
               f"  \nAgent `{cfg.rag_url}`")
