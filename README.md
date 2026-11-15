# AegisGate: Edge-AI anti-tailgating sentry

One RFID tap should let in one person. AegisGate watches the doorway with a laptop
webcam, ties every person crossing to the badge tap and door sensor, scores the risk,
keeps the evidence, and shows it all live on a Streamlit SOC dashboard.

```
 ESP32-S3 (Alok, restricted)        Laptop webcam (Abhinav)
  RFID + door contact                YOLOv8n + ByteTrack + tripwire
        │ POST /api/event/hardware          │ POST /api/event/vision   (one per track, IN/OUT)
        │ {"event":"BADGE_TAP"...}          │ POST /api/vision/frame   (preview ~5 fps)
        ▼                                   ▼
 ┌──────────────────── FastAPI backend (Tanvi) ─────────────────────┐
 │ adapters ─▶ correlator ─▶ risk engine ─▶ incidents + PDF reports  │
 │ SQLite / Supabase · snapshots on disk · WebSocket /ws            │
 └──────────────┬──────────────────────────────────┬────────────────┘
                │ WS push + REST                    │ GET /api/incidents
                ▼                                   ▼
   Streamlit dashboard (Amandeep)  ◀──  built-in RAG assistant
   live feed · PDFs · evidence          BM25 retrieval + LLM (Grok / Groq)
```

> **Quick start for the demo:** see [`docs/CONNECT_EVERYTHING.md`](docs/CONNECT_EVERYTHING.md)
> (one Streamlit dashboard + ESP32 + webcam).

## Folders and owners

| Folder | Owner | What it is |
|---|---|---|
| `hardware/` | Alok | Restricted script kept **verbatim** in `restricted/`, its derived interface (`README.md`) and an ESP32 simulator |
| `vision/` | Abhinav | ML module: YOLOv8n person detector + ByteTrack tracker, direction-aware tripwire, backend client |
| `backend/` | Tanvi | FastAPI: hardware/vision adapters, correlator, rule-based risk, evidence store, PDF reports, WebSocket |
| `dashboard/` | Amandeep | Streamlit SOC dashboard (theme `#0F1B3D` / `#FFFFFF` / `#FF3D8B`) |
| `rag/` | team | Incident assistant: retrieval over incidents + SOPs, LLM via your **Grok/Groq** key, runs inside the dashboard |
| `tests/` | team | The five demo scenarios + tripwire tests (`pytest -q`) |

## The four features

1. **Dynamic risk scoring (0-100, rule-based).** `backend/app/core/risk.py`. Every incident stores each factor, its points and the reason. Base points: rejected badge 15, held open 25, tailgating 45, unauthorised entry 55, forced door 60. Context points are added for extra people, nearby forced doors, rejected badges, a held door and repeat incidents. Bands: LOW <25, MEDIUM <50, HIGH <75, CRITICAL. The dashboard sidebar shows the full rule table.
2. **Direction-aware tracking.** `vision/tripwire.py`. A track must be seen clearly on one side (12 % of the frame from the line, shown as grey dashed lines), then clearly on the other side for 2 frames, before it counts. Standing or swaying near the line never counts. A 3 s per-track cooldown applies, and the backend also drops repeats of the same (track, direction).

   **Track numbers** (1, 21, 34…) are ByteTrack IDs: a counter, not an identity. A new number is used whenever the tracker starts a new track (including brief false detections) or loses a person for too long. That's why there are gaps. `vision/aegis_bytetrack.yaml` reduces this. "Unique people" only counts tracks that lived at least 5 frames.
3. **Door sensor correlation.** `backend/app/core/correlator.py`. An authorised tap opens an 8 s session for one person (plus 3 s grace for late camera events). A door opening without an authorised tap in the last 6 s is a forced door (same rule as the restricted script). A door open past 10 s is held open.
4. **Evidence reports.** Each incident keeps timestamps, badge, session, every crossing with its snapshot, door times and the risk breakdown. **PDF download lives in the right-hand live feed only.**

## How the backend correlates the three sources

| Situation | Result |
|---|---|
| Authorised tap → 1 inbound crossing within the window | Authorised entry (row in entry/exit log) |
| Authorised tap → 2+ distinct inbound tracks | `TAILGATING` (one incident per tap, updated per extra person) |
| Inbound crossing, no session (after a 2 s wait for late badge events) | `UNAUTHORIZED_ENTRY` |
| `DOOR_OPEN` with no authorised tap in the last 6 s | `FORCED_DOOR` |
| Door open longer than `HELD_OPEN_THRESHOLD_S` | `DOOR_HELD_OPEN` (duration filled in on close) |
| Badge not on the list | `UNAUTHORIZED_BADGE` (low score, raises later incidents' risk) |
| Outbound crossing | OUT count; closes the oldest open entry record |

---

## Setup on Windows (VS Code)

**Install once:** Python **3.11** (python.org, tick *Add to PATH*), Git, VS Code with the Python extension.

```bat
git clone https://github.com/tgoel315-tech/AegisGate.git
cd AegisGate
scripts\setup_windows.bat
```
That creates `.venv`, installs everything and copies `backend\.env` and `.streamlit\secrets.toml`
from their examples. In VS Code: *Ctrl+Shift+P → Python: Select Interpreter → .venv*.
The first run of the vision module downloads `yolov8n.pt` (about 6 MB) automatically.

### Run (four terminals, or `scripts\start_all.bat`)

```bat
.venv\Scripts\activate
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000     :: 1 backend   http://localhost:8000/docs
python -m rag.start                                         :: 2 RAG agent http://localhost:8100
python -m vision.main --camera 0                            :: 3 webcam tracker (preview window)
streamlit run dashboard/app.py                              :: 4 dashboard http://localhost:8501
```

Vision options: `--camera 1` (USB camera), `--orientation horizontal`, `--position 0.4`, `--arm 0.15`,
`--invert` (swap IN/OUT), `--no-mirror`, `--source video.mp4`, `--classic` (no PyTorch).
Keys in the preview: `a`/`d` move the line, `o` vertical/horizontal, `r` reverse direction,
`m` mirror, `c` clear, `q` quit.

**ESP32:** the firmware must POST to `http://<laptop-LAN-IP>:8000/api/event/hardware`. Keep the
laptop and the ESP32 on the same Wi-Fi and allow Python through Windows Firewall when asked.
No firmware change is needed.

### Test

```bat
pytest -q                                   :: 20 tests incl. all 5 required scenarios
python hardware\simulator.py tap --badge E2806892 --name "Dr. Sarah Connor"
python hardware\simulator.py door-open
```
Or use the **Judge controller** buttons at the bottom of the dashboard: Normal entry, Tailgating,
Unauthorised, Forced door, Held open (plus Manual events and Reset).
Live demo: tap a real card, then walk two people across the line in front of the webcam.

---

## External services

| Service | Needed for | Required? |
|---|---|---|
| **LLM key**: xAI Grok (`xai-…`) or Groq (`gsk_…`) | The incident assistant's answers | Recommended. Without a key the assistant quotes the top matching records |
| **ngrok** | A public HTTPS address for the laptop backend, so Streamlit Cloud can read it | Only when the dashboard runs on Streamlit Cloud |
| **Streamlit Community Cloud** | Hosting the dashboard | Yes, to host the dashboard |
| **Supabase** | Cloud Postgres instead of local SQLite | Optional |

Prune (`prune_…` keys) and Maritime (the repo-root `Dockerfile`) are still supported but **not
needed**. The assistant runs inside the Streamlit app.

### LLM key (Grok or Groq)
1. Check the key: `python scripts\test_llm_key.py <your-key>`. It prints the provider, the model it
   picked and a test reply. "Key REJECTED" usually means credits or billing aren't set up on the console.
2. Local: put `LLM_API_KEY = "<your-key>"` in `.streamlit\secrets.toml`, then restart Streamlit.
3. Streamlit Cloud: App → Settings → **Secrets** → add the same line → Save.
4. Ask something in the sidebar. It should say *"LLM · <model> via xAI Grok"* (or *Groq*).

The provider is detected from the key prefix, and the model is picked from what your key can use.
To force a model, set `LLM_MODEL`. Never commit the key, because `secrets.toml` is git-ignored.

### ngrok and Streamlit Cloud
See [`docs/CONNECT_EVERYTHING.md`](docs/CONNECT_EVERYTHING.md) for the full step-by-step,
including the ESP32 hardware connection.

### Supabase (optional)
1. supabase.com → New project → note the database password.
2. Project Settings → Database → Connection string → **Session pooler** → copy it.
3. In `backend\.env`: `DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@<host>:5432/postgres`

---

## Hardware interface limitations (see `hardware/README.md`)
* The restricted script sends no **door-closed** event, so held-open detection switches on once a
  `DOOR_CLOSE` arrives (or when you set `HELD_OPEN_REQUIRES_CLOSE_EVENT=false`).
* There is no command channel back to the ESP32, so AegisGate **cannot** drive the buzzer, LEDs or lock.
* ESP32 uptime timestamps are replaced by server time. Only one gate is supported (`gate-01`).

The camera only tracks and counts movement. It never identifies people. The RAG assistant is
advisory and read-only. Every access and risk decision comes from the rule engine.
