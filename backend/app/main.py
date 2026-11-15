"""
AegisGate backend (owner: Tanvi).

Run from the repository root:
    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

Hardware contract is unchanged from the restricted script:
    POST /api/event/hardware   POST /api/event/vision   WS /ws
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .adapters.hardware import parse_hardware
from .adapters.vision import Crossing, parse_vision
from .config import settings
from .core.correlator import Correlator
from .core.frames import FrameStore, decode_b64_image
from .core.risk import RULES_TABLE
from .db import Store
from .reports.pdf import build_incident_pdf
from .ws import ConnectionManager



CONTROL_TOKEN = os.getenv("CONTROL_TOKEN", "")   # protects demo/reset when the API is public

store = Store(settings.database_url)
frames = FrameStore(settings.frame_stale_s)
engine = Correlator(settings, store, frames)
manager = ConnectionManager()


async def _publish(msgs):
    if msgs:
        await manager.broadcast_many(msgs, engine.version)


async def _ticker():
    last_people = None
    while True:
        await asyncio.sleep(0.5)
        try:
            await _publish(engine.tick())
            people = (frames.stats or {}).get("unique_people")
            if people != last_people and frames.online:
                last_people = people
                await manager.broadcast({"type": "VISION_STATS", "stats": frames.stats,
                                         "version": engine.version})
        except Exception as exc:  # keep the loop alive no matter what
            print(f"[tick] {exc!r}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_ticker())
    yield
    task.cancel()


app = FastAPI(title="AegisGate SOC Backend", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/snapshots", StaticFiles(directory=str(settings.snapshot_dir)), name="snapshots")


def _check_token(token: Optional[str]) -> None:
    if CONTROL_TOKEN and token != CONTROL_TOKEN:
        raise HTTPException(status_code=401, detail="Missing or wrong X-Control-Token")


# ------------------------------------------------------------------ ingest
@app.post("/api/event/hardware")
async def hardware_event(request: Request):
    """Restricted hardware contract — same path, payload and reply as Alok's script."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    evt = parse_hardware(data, time.time())
    if evt is None:
        return {"status": "ok", "note": "event ignored (unknown type)"}
    await _publish(engine.handle_hardware(evt))
    return {"status": "ok"}


@app.post("/api/event/vision")
async def vision_event(request: Request):
    """Per-person crossings (new) or the restricted / old cctv formats (legacy)."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    msgs = []
    for crossing in parse_vision(data, time.time()):
        msgs += engine.handle_crossing(crossing)
    await _publish(msgs)
    return {"status": "processed", "crossings": len(msgs)}


@app.post("/api/vision/frame")
async def vision_frame(request: Request):
    """Annotated preview frame + live stats from the vision module (~5 fps)."""
    data = await request.json()
    frames.push(decode_b64_image(data.get("jpeg_base64")), data.get("stats"))
    return {"status": "ok"}


# ------------------------------------------------------------------ read
@app.get("/health")
async def health():
    return {"status": "ok", "time": time.time()}


@app.get("/api/dashboard")
async def dashboard(feed_limit: int = 60, incident_limit: int = 30):
    incidents = store.list_incidents(limit=incident_limit)
    by_id = {i["id"]: i for i in incidents}
    feed = []
    for e in store.list_events(limit=feed_limit):
        item = {k: e[k] for k in ("id", "ts", "kind", "title", "detail", "severity", "incident_id")}
        inc = by_id.get(e["incident_id"]) or (store.get_incident(e["incident_id"]) if e["incident_id"] else None)
        if inc:
            item.update(severity=inc["risk"]["severity"], score=inc["risk"]["score"],
                        updated_at=inc["updated_at"], title=f"{inc['title']} · risk {inc['risk']['score']}",
                        detail=inc["message"])
        feed.append(item)
    return {"gate": engine.state(), "feed": feed, "incidents": incidents,
            "records": store.list_records(limit=100), "server_time": time.time()}


@app.get("/api/incidents")
async def list_incidents(limit: int = 50):
    return store.list_incidents(limit=limit)


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = store.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "Incident not found")
    return inc


@app.get("/api/incidents/{incident_id}/report.pdf")
async def incident_pdf(incident_id: str):
    inc = store.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "Incident not found")
    pdf = build_incident_pdf(inc, settings.snapshot_dir)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{incident_id}.pdf"'})


@app.get("/api/records")
async def list_records(limit: int = 100):
    return store.list_records(limit=limit)


@app.get("/api/events")
async def list_events(limit: int = 100):
    return store.list_events(limit=limit)


@app.get("/api/risk/rules")
async def risk_rules():
    return {"rules": RULES_TABLE,
            "severity_bands": {"LOW": "0-24", "MEDIUM": "25-49", "HIGH": "50-74", "CRITICAL": "75-100"}}


@app.get("/api/frame.jpg")
async def frame_jpg():
    return Response(frames.current(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/video_feed")
async def video_feed():
    async def gen():
        while True:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frames.current() + b"\r\n"
            await asyncio.sleep(0.2)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


# ------------------------------------------------------------------ websocket
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "HELLO", "version": engine.version, "gate": engine.state()})
        while True:
            await ws.receive_text()          # keep-alive pings from clients
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ------------------------------------------------------------------ demo controls
DEMO_BADGE = {"badge_id": "E2806892", "holder_name": "Dr. Sarah Connor"}
_demo_track = {"n": 1000}


def _next_track() -> str:
    _demo_track["n"] += 1
    return f"demo-{_demo_track['n']}"


async def _hw(event: str, **extra):
    """Feed the backend exactly what the ESP32 would send."""
    evt = parse_hardware({"event": event, "timestamp": time.time(), **extra}, time.time())
    await _publish(engine.handle_hardware(evt))


async def _cross(direction: str):
    c = Crossing(track_id=_next_track(), direction=direction, ts=time.time(), source="demo")
    await _publish(engine.handle_crossing(c))


async def _run_scenario(name: str):
    t = settings.held_open_threshold_s
    if name == "normal":
        await _hw("BADGE_TAP", **DEMO_BADGE); await asyncio.sleep(1.0)
        await _hw("DOOR_OPEN"); await asyncio.sleep(1.0)
        await _cross("IN"); await asyncio.sleep(2.0)
        await _hw("DOOR_CLOSE")
    elif name == "tailgating":
        await _hw("BADGE_TAP", **DEMO_BADGE); await asyncio.sleep(1.0)
        await _hw("DOOR_OPEN"); await asyncio.sleep(1.0)
        await _cross("IN"); await asyncio.sleep(1.2)
        await _cross("IN"); await asyncio.sleep(2.0)
        await _hw("DOOR_CLOSE")
    elif name == "unauthorized":
        await _cross("IN")
    elif name == "forced":
        await _hw("DOOR_OPEN"); await asyncio.sleep(3.0)
        await _hw("DOOR_CLOSE")
    elif name == "held_open":
        await _hw("DOOR_CLOSE")                       # tells the backend close events exist
        await _hw("BADGE_TAP", **DEMO_BADGE); await asyncio.sleep(1.0)
        await _hw("DOOR_OPEN"); await asyncio.sleep(1.0)
        await _cross("IN"); await asyncio.sleep(t + 1.5)
        await _hw("DOOR_CLOSE")


@app.post("/api/demo/scenario/{name}")
async def demo_scenario(name: str, x_control_token: Optional[str] = Header(default=None)):
    _check_token(x_control_token)
    if name not in ("normal", "tailgating", "unauthorized", "forced", "held_open"):
        raise HTTPException(400, "Unknown scenario")
    asyncio.create_task(_run_scenario(name))
    return {"status": "started", "scenario": name}


@app.post("/api/demo/event/{kind}")
async def demo_event(kind: str, x_control_token: Optional[str] = Header(default=None)):
    _check_token(x_control_token)
    if kind == "tap":
        await _hw("BADGE_TAP", **DEMO_BADGE)
    elif kind == "tap_unknown":
        await _hw("BADGE_TAP", badge_id="FFFF0000")
    elif kind == "in":
        await _cross("IN")
    elif kind == "out":
        await _cross("OUT")
    elif kind == "door_open":
        await _hw("DOOR_OPEN")
    elif kind == "door_close":
        await _hw("DOOR_CLOSE")
    else:
        raise HTTPException(400, "Unknown demo event")
    return {"status": "ok", "event": kind}


@app.post("/api/demo/reset")
async def demo_reset(x_control_token: Optional[str] = Header(default=None)):
    _check_token(x_control_token)
    await _publish(engine.reset())
    return {"status": "reset"}


@app.get("/")
async def root():
    return JSONResponse({"service": "AegisGate backend", "dashboard": "streamlit run dashboard/app.py",
                         "docs": "/docs", "websocket": "/ws"})
