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
   Streamlit dashboard (Amandeep)        RAG agent on Maritime
   live feed · PDFs · evidence    ◀────  BM25 retrieval + LLM via Prune
```

## Folders and owners

| Folder | Owner | What it is |
|---|---|---|
| `hardware/` | Alok | Restricted script kept **verbatim** in `restricted/`, its derived interface (`README.md`) and an ESP32 simulator |
| `vision/` | Abhinav | ML module: YOLOv8n person detector + ByteTrack tracker, direction-aware tripwire, backend client |
| `backend/` | Tanvi | FastAPI: hardware/vision adapters, correlator, rule-based risk, evidence store, PDF reports, WebSocket |
| `dashboard/` | Amandeep | Streamlit SOC dashboard (theme `#0F1B3D` / `#FFFFFF` / `#FF3D8B`) |
| `rag/` | team | Incident assistant: retrieval over incidents + SOPs, LLM via **Prune**, deployable on **Maritime** |
| `tests/` | team | The five demo scenarios + tripwire tests (`pytest -q`) |

## The four features

1. **Dynamic risk scoring (0-100, rule-based).** `backend/app/core/risk.py`. Every incident stores each factor, its points and the reason. Base points: rejected badge 15, held open 25, tailgating 45, unauthorised entry 55, forced door 60. Context points are added for extra people, nearby forced doors, rejected badges, a held door and repeat incidents. Bands: LOW <25, MEDIUM <50, HIGH <75, CRITICAL. The dashboard sidebar shows the full rule table.
2. **Direction-aware tracking.** `vision/tripwire.py`. Each track id keeps a stable side of the line. A crossing counts only after the person is confirmed on the other side, outside a dead band, and a per-track cooldown applies. The backend also drops repeats of the same (track, direction).
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

Vision options: `--camera 1` (USB camera), `--orientation horizontal`, `--position 0.4`,
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

## External services: what you need and how to set them up

| Service | Needed for | Required? |
|---|---|---|
| **Prune** | LLM calls from the RAG agent (cost control, key vault, Shield) | Yes for LLM answers (without it the agent quotes the top records) |
| **Maritime** | Hosting the RAG agent | Yes for the hackathon requirement |
| **ngrok** | Giving the laptop backend a public HTTPS URL for Streamlit Cloud + Maritime | Only when the dashboard / agent run in the cloud |
| **Streamlit Community Cloud** | Hosting the dashboard | Yes, to "host the dash on Streamlit" |
| **Supabase** | Cloud Postgres instead of local SQLite | Optional |

The backend must run on the laptop because the ESP32 and the webcam are there.

### 1. Prune (LLM gateway)
1. Activate your free Prune Pro month at withprune.com and open the dashboard.
2. **Connect → Providers**: add your OpenAI key (it stays in Prune's vault).
3. **API Keys**: create a key (starts with `prune_`).
4. Put it in `rag\.env` (copy `rag\.env.example`): `PRUNE_API_KEY=prune_...`
   Model defaults to `gpt-4o-mini` (`PRUNE_MODEL`). Restart `python -m rag.start`.
5. Check: ask a question in the dashboard sidebar. It should say *"LLM · gpt-4o-mini via Prune"*.
   Every call carries `X-Prune-Feature-Id: aegisgate_incident_rag`, so it shows up grouped in Prune.

### 2. ngrok (public URL for the backend)
1. Sign up at ngrok.com, copy your authtoken, then: `ngrok config add-authtoken <TOKEN>`
2. Claim your free static domain (Dashboard → Domains).
3. Run alongside the backend: `ngrok http 8000 --url=<your-name>.ngrok-free.app`
   (older ngrok versions use `--domain=` instead of `--url=`).
4. Set `CONTROL_TOKEN=<some long random string>` in `backend\.env` so strangers can't trigger
   the demo or reset endpoints. The ESP32 endpoint stays open because the restricted firmware
   can't send headers.

### 3. Maritime (host the RAG agent)
The repo-root `Dockerfile` builds only `rag/`, binds `$PORT`, and serves `/health` and `/chat`
(Maritime's contract) plus `/ask`.
1. Sign up at maritime.sh with participant code **VIHAANX** (3 months of Scale free).
2. Install the CLI (needs Node 18+): `npm install -g maritime-cli`, then `maritime login`.
3. Push this repo to GitHub, then:
   ```bat
   maritime create aegisgate-rag --repo https://github.com/tgoel315-tech/AegisGate
   maritime env set aegisgate-rag PRUNE_API_KEY=prune_...
   maritime env set aegisgate-rag BACKEND_URL=https://<your-name>.ngrok-free.app
   maritime env set aegisgate-rag AGENT_TOKEN=<random string>
   maritime deploy aegisgate-rag -w
   maritime chat aegisgate-rag "how many incidents today?"
   ```
4. Make the URL public with `maritime agents url visibility <agent_id> public` and copy it.
   If a flag differs in your CLI version, run `maritime guide --json` or see maritime.sh/docs/cli.

### 4. Streamlit Community Cloud (host the dashboard)
1. share.streamlit.io → *Create app* → repo `tgoel315-tech/AegisGate`, branch `main`,
   **main file `dashboard/app.py`**. Under *Advanced settings* pick Python 3.11.
2. *Advanced settings → Secrets*, paste:
   ```toml
   BACKEND_URL = "https://<your-name>.ngrok-free.app"
   RAG_URL = "https://<your-maritime-agent-url>"
   CONTROL_TOKEN = "<same as backend .env>"
   AGENT_TOKEN = "<same as on Maritime>"
   CAMERA_MODE = "auto"
   TIMEZONE = "Asia/Kolkata"
   ```
3. Deploy. The theme comes from `.streamlit/config.toml`. With a remote backend the camera panel
   polls one frame per second. Locally it streams MJPEG.

### 5. Supabase (optional)
1. supabase.com → New project → note the database password.
2. Project Settings → Database → Connection string → **Session pooler** → copy it.
3. In `backend\.env`: `DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@<host>:5432/postgres`
   Tables are created automatically on startup. Snapshots stay on the laptop disk.

---

## Hardware interface limitations (see `hardware/README.md`)
* The restricted script sends no **door-closed** event, so held-open detection switches on once a
  `DOOR_CLOSE` arrives (or when you set `HELD_OPEN_REQUIRES_CLOSE_EVENT=false`).
* There is no command channel back to the ESP32, so AegisGate **cannot** drive the buzzer, LEDs or lock.
* ESP32 uptime timestamps are replaced by server time. Only one gate is supported (`gate-01`).

The camera only tracks and counts movement. It never identifies people. The RAG assistant is
advisory and read-only. Every access and risk decision comes from the rule engine.
