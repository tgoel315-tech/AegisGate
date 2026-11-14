import os
import time
import json
import base64
import uuid
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ----------------- Configuration & Paths -----------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
ALERTS_DIR = DATA_DIR / "alerts"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
ALERTS_DIR.mkdir(parents=True, exist_ok=True)

RECORDS_FILE = DATA_DIR / "records.json"
ALERTS_FILE = DATA_DIR / "alerts.json"

# Known authorized personnel database
BADGE_DATABASE = {
    "E2806892": {"name": "Dr. Sarah Connor", "role": "Head of Cyber Security", "dept": "SecOps"},
    "A4109823": {"name": "Alex Vance", "role": "Lead Infrastructure Architect", "dept": "DevOps"},
    "B9302184": {"name": "Elena Rostova", "role": "Senior Cloud Engineer", "dept": "Core Systems"},
    "C1045921": {"name": "Marcus Brody", "role": "Director of R&D", "dept": "Research"},
    "D8823190": {"name": "David Chen", "role": "Network Defense Specialist", "dept": "SecOps"}
}

# ----------------- App Initialization -----------------
app = FastAPI(
    title="AegisGate SOC Backend",
    description="Edge-AI Anti-Tailgating Sentry & Access Management System",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Real-Time State & Data Stores -----------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)

manager = ConnectionManager()

# Global Gate State
gate_state = {
    "status": "STANDBY",         # STANDBY, ARMED, BREACH, LOCKED
    "active_badge": None,
    "armed_until": 0.0,
    "authorized_credits": 0,
    "camera_connected": False,
    "last_seen_frame": None,     # Latest raw/HUD frame bytes for MJPEG
    "last_seen_frame_time": 0.0,
    "fps": 30.0,
    "active_persons": 0
}

# ----------------- Persistence Helpers -----------------
def load_json(filepath: Path, default):
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath: Path, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Failed to save {filepath}: {e}")

# In-memory caches backed by JSON files
records_db: List[Dict[str, Any]] = load_json(RECORDS_FILE, [])
alerts_db: List[Dict[str, Any]] = load_json(ALERTS_FILE, [])

# Ensure initial sample records if empty, so dashboard looks alive from second 1
if not records_db:
    now_t = datetime.now()
    records_db = [
        {
            "serial_no": 1,
            "id": "rec_001",
            "name": "Dr. Sarah Connor",
            "time_in": (now_t.replace(minute=max(0, now_t.minute - 25))).strftime("%H:%M:%S"),
            "time_out": (now_t.replace(minute=max(0, now_t.minute - 5))).strftime("%H:%M:%S"),
            "status": "COMPLETED",
            "badge_id": "E2806892"
        },
        {
            "serial_no": 2,
            "id": "rec_002",
            "name": "Alex Vance",
            "time_in": (now_t.replace(minute=max(0, now_t.minute - 14))).strftime("%H:%M:%S"),
            "time_out": "--:--:--",
            "status": "INSIDE",
            "badge_id": "A4109823"
        },
        {
            "serial_no": 3,
            "id": "rec_003",
            "name": "Elena Rostova",
            "time_in": (now_t.replace(minute=max(0, now_t.minute - 6))).strftime("%H:%M:%S"),
            "time_out": "--:--:--",
            "status": "INSIDE",
            "badge_id": "B9302184"
        }
    ]
    save_json(RECORDS_FILE, records_db)

# ----------------- Synthetic Snapshot Generator (for fallback/demo) -----------------
def generate_synthetic_breach_frame(text="TAILGATING DETECTED", person_count=2) -> bytes:
    """Generates a realistic dark CCTV frame with tripwire and alert boxes."""
    w, h = 640, 480
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    # Dark room background with surveillance grid
    frame[:] = (18, 14, 25)
    for y in range(0, h, 40):
        cv2.line(frame, (0, y), (w, y), (30, 24, 40), 1)
    for x in range(0, w, 40):
        cv2.line(frame, (x, 0), (x, h), (30, 24, 40), 1)

    # Red divider tripwire
    div_x = 320
    cv2.line(frame, (div_x, 0), (div_x, h), (0, 0, 255), 3)
    cv2.putText(frame, "TRIPWIRE SECURE BOUNDARY", (div_x - 130, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

    # Person 1 (Authorized - Green box)
    cv2.rectangle(frame, (340, 140), (430, 380), (0, 230, 100), 2)
    cv2.rectangle(frame, (340, 120), (430, 140), (0, 230, 100), -1)
    cv2.putText(frame, "P1 [Auth]", (345, 134), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 0, 0), 1)

    # Person 2 (Intruder / Tailgater - Hot Red/Pink box crossing boundary)
    if person_count >= 2:
        cv2.rectangle(frame, (270, 160), (350, 390), (0, 50, 255), 2)
        cv2.rectangle(frame, (270, 140), (370, 160), (0, 50, 255), -1)
        cv2.putText(frame, "P2 [TAILGATING]", (275, 154), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1)

    # Alarm banner overlay
    cv2.rectangle(frame, (10, 10), (w - 10, 55), (0, 0, 180), -1)
    cv2.rectangle(frame, (10, 10), (w - 10, 55), (0, 60, 255), 2)
    cv2.putText(frame, f"AEGISGATE ALERT: {text}", (25, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

    # Timestamp
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(frame, f"CAM-01 [ENTRY CHOKEPOINT] | {now_str}", (20, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()

# ----------------- Pydantic Models -----------------
class VisionEvent(BaseModel):
    source: str = "CCTV_CAMERA"
    event: str
    card_taps: Optional[int] = 0
    authorized_entered: Optional[int] = 0
    tailgating_breaches: Optional[int] = 0
    unauthorized_crossings: Optional[int] = 0
    credits_remaining: Optional[int] = 0
    snapshot_base64: Optional[str] = None
    person_id: Optional[int] = None
    timestamp: Optional[float] = None

class HardwareEvent(BaseModel):
    badge_uid: str
    device_id: Optional[str] = "kiosk_gate_01"
    door_sensor: Optional[str] = "CLOSED"

class DemoAction(BaseModel):
    action: str  # "tap", "authorized_entry", "tailgating", "exit", "reset"
    badge_uid: Optional[str] = None
    name: Optional[str] = None

# ----------------- REST Endpoints -----------------

@app.get("/api/status")
async def get_system_status():
    """Returns real-time operational status."""
    return {
        "status": "ONLINE",
        "gate": gate_state["status"],
        "camera_connected": gate_state["camera_connected"],
        "active_inside": len([r for r in records_db if r.get("status") == "INSIDE"]),
        "total_entries": len(records_db),
        "total_alerts": len(alerts_db),
        "armed_until": gate_state["armed_until"],
        "fps": gate_state["fps"]
    }

@app.get("/api/records")
async def get_records():
    """Returns all entry/exit records sorted newest first."""
    # Return reversed copy so latest is first
    return list(reversed(records_db))

@app.get("/api/alerts")
async def get_alerts():
    """Returns all incident alert captures sorted newest first."""
    return list(reversed(alerts_db))

@app.post("/api/event/vision")
async def receive_vision_event(event: VisionEvent):
    """
    Ingests live detections from the cctv_engine.py CV pipeline.
    Matches event type and updates records / alerts in real time.
    """
    gate_state["camera_connected"] = True
    now_dt = datetime.now()
    now_str = now_dt.strftime("%H:%M:%S")

    # 1. Update last seen frame if snapshot provided
    if event.snapshot_base64 and "," in event.snapshot_base64:
        try:
            raw_b64 = event.snapshot_base64.split(",", 1)[1]
            img_bytes = base64.b64decode(raw_b64)
            gate_state["last_seen_frame"] = img_bytes
            gate_state["last_seen_frame_time"] = time.time()
        except Exception as e:
            print(f"[WARN] Failed to decode vision frame: {e}")

    # 2. Handle Authorized Crossing
    if event.event == "AUTHORIZED_ENTRY":
        gate_state["status"] = "STANDBY"
        # Determine person identity from active badge, or default to known sequence or Unknown
        badge_uid = gate_state.get("active_badge")
        if badge_uid and badge_uid in BADGE_DATABASE:
            user_info = BADGE_DATABASE[badge_uid]
            name = user_info["name"]
        else:
            name = "Unknown"

        new_serial = len(records_db) + 1
        new_record = {
            "serial_no": new_serial,
            "id": f"rec_{uuid.uuid4().hex[:6]}",
            "name": name,
            "time_in": now_str,
            "time_out": "--:--:--",
            "status": "INSIDE",
            "badge_id": badge_uid or "UNKNOWN_BADGE",
            "timestamp_in": time.time(),
            "timestamp_out": None
        }
        records_db.append(new_record)
        save_json(RECORDS_FILE, records_db)

        # Clear active badge
        gate_state["active_badge"] = None

        await manager.broadcast({
            "type": "ENTRY_RECORD_ADDED",
            "record": new_record
        })
        return {"status": "RECORD_ADDED", "record": new_record}

    # 3. Handle Tailgating Breach or Unauthorized Crossing
    elif event.event in ["TAILGATING_BREACH", "UNAUTHORIZED_CROSSING"]:
        gate_state["status"] = "BREACH"
        alert_id = f"alt_{uuid.uuid4().hex[:8]}"
        img_filename = f"{alert_id}.jpg"
        img_filepath = ALERTS_DIR / img_filename

        # Save snapshot to disk
        if gate_state.get("last_seen_frame"):
            with open(img_filepath, "wb") as f:
                f.write(gate_state["last_seen_frame"])
        else:
            synth_bytes = generate_synthetic_breach_frame(
                text="TAILGATING DETECTED" if event.event == "TAILGATING_BREACH" else "UNAUTHORIZED CROSSING",
                person_count=2 if event.event == "TAILGATING_BREACH" else 1
            )
            with open(img_filepath, "wb") as f:
                f.write(synth_bytes)

        is_tailgate = (event.event == "TAILGATING_BREACH")
        new_alert = {
            "id": alert_id,
            "timestamp": now_dt.strftime("%H:%M:%S %d/%m"),
            "time_raw": now_str,
            "type": "TAILGATING DETECTED" if is_tailgate else "UNAUTHORIZED CROSSING",
            "description": (
                f"Multiple occupants entered on single authorization. Person #{event.person_id or 2} followed through without valid credentials."
                if is_tailgate else
                f"Individual crossed secure corridor boundary with zero active badge authorizations."
            ),
            "severity": "CRITICAL" if is_tailgate else "HIGH",
            "snapshot_url": f"/data/alerts/{img_filename}",
            "created_at": time.time()
        }

        alerts_db.append(new_alert)
        save_json(ALERTS_FILE, alerts_db)

        await manager.broadcast({
            "type": "NEW_ALERT",
            "alert": new_alert
        })
        return {"status": "ALERT_RECORDED", "alert": new_alert}

    # 4. Handle Badge Tap Notification
    elif event.event == "CARD_TAPPED":
        gate_state["status"] = "ARMED"
        gate_state["armed_until"] = time.time() + 4.0
        await manager.broadcast({
            "type": "GATE_ARMED",
            "armed_until": gate_state["armed_until"],
            "total_taps": event.card_taps
        })
        return {"status": "GATE_ARMED"}

    return {"status": "ACK"}

@app.post("/api/event/hardware")
async def receive_hardware_event(hw: HardwareEvent):
    """Handles physical RFID badge taps from ESP32 or Mock Hardware."""
    gate_state["status"] = "ARMED"
    gate_state["active_badge"] = hw.badge_uid
    gate_state["armed_until"] = time.time() + 4.0
    gate_state["authorized_credits"] += 1

    user_info = BADGE_DATABASE.get(hw.badge_uid, {"name": "Unknown", "role": "Visitor", "dept": "Guest"})
    
    await manager.broadcast({
        "type": "BADGE_TAPPED",
        "badge_uid": hw.badge_uid,
        "user": user_info,
        "armed_until": gate_state["armed_until"]
    })
    return {"status": "ARMED", "user": user_info}

@app.post("/api/demo/action")
async def handle_demo_action(demo: DemoAction):
    """
    Interactive Demo Controller for live hackathon judging.
    Allows 1-click trigger of:
    - 'tap': Simulates RFID badge tap
    - 'authorized_entry': Simulates verified single-person entry
    - 'tailgating': Simulates 2 people crossing with 1 authorization, captures snapshot
    - 'exit': Simulates person leaving, updating Time Out
    """
    now_dt = datetime.now()
    now_str = now_dt.strftime("%H:%M:%S")

    if demo.action == "tap":
        # Cycle through badge database
        badge_uid = demo.badge_uid or list(BADGE_DATABASE.keys())[len(records_db) % len(BADGE_DATABASE)]
        user = BADGE_DATABASE[badge_uid]
        gate_state["status"] = "ARMED"
        gate_state["active_badge"] = badge_uid
        gate_state["armed_until"] = time.time() + 4.0
        gate_state["authorized_credits"] = 1

        await manager.broadcast({
            "type": "BADGE_TAPPED",
            "badge_uid": badge_uid,
            "user": user,
            "armed_until": gate_state["armed_until"]
        })
        return {"status": "SUCCESS", "message": f"Badge tapped by {user['name']}", "user": user}

    elif demo.action == "authorized_entry":
        # Add authorized entry record
        name = demo.name
        if not name:
            if gate_state.get("active_badge") and gate_state["active_badge"] in BADGE_DATABASE:
                name = BADGE_DATABASE[gate_state["active_badge"]]["name"]
            else:
                idx = len(records_db) % len(BADGE_DATABASE)
                name = list(BADGE_DATABASE.values())[idx]["name"]

        new_serial = len(records_db) + 1
        new_record = {
            "serial_no": new_serial,
            "id": f"rec_{uuid.uuid4().hex[:6]}",
            "name": name,
            "time_in": now_str,
            "time_out": "--:--:--",
            "status": "INSIDE",
            "badge_id": gate_state.get("active_badge") or "BADGE_AUTH",
            "timestamp_in": time.time(),
            "timestamp_out": None
        }
        records_db.append(new_record)
        save_json(RECORDS_FILE, records_db)
        gate_state["status"] = "STANDBY"
        gate_state["active_badge"] = None

        await manager.broadcast({
            "type": "ENTRY_RECORD_ADDED",
            "record": new_record
        })
        return {"status": "SUCCESS", "record": new_record}

    elif demo.action == "tailgating":
        # Instantaneously generate and save screenshot
        alert_id = f"alt_{uuid.uuid4().hex[:8]}"
        img_filename = f"{alert_id}.jpg"
        img_filepath = ALERTS_DIR / img_filename

        frame_bytes = generate_synthetic_breach_frame(text="TAILGATING DETECTED", person_count=2)
        with open(img_filepath, "wb") as f:
            f.write(frame_bytes)

        gate_state["status"] = "BREACH"
        new_alert = {
            "id": alert_id,
            "timestamp": now_dt.strftime("%H:%M:%S %d/%m"),
            "time_raw": now_str,
            "type": "TAILGATING DETECTED",
            "description": "Unauthorized secondary occupant detected tailgating behind authorized staff.",
            "severity": "CRITICAL",
            "snapshot_url": f"/data/alerts/{img_filename}",
            "created_at": time.time()
        }
        alerts_db.append(new_alert)
        save_json(ALERTS_FILE, alerts_db)

        await manager.broadcast({
            "type": "NEW_ALERT",
            "alert": new_alert
        })
        return {"status": "SUCCESS", "alert": new_alert}

    elif demo.action == "exit":
        # Find the earliest occupant still INSIDE and mark exit
        target = None
        for r in records_db:
            if r.get("status") == "INSIDE":
                target = r
                break
        
        if not target and records_db:
            target = records_db[-1]

        if target:
            target["time_out"] = now_str
            target["status"] = "COMPLETED"
            target["timestamp_out"] = time.time()
            save_json(RECORDS_FILE, records_db)

            await manager.broadcast({
                "type": "ENTRY_RECORD_UPDATED",
                "record": target
            })
            return {"status": "SUCCESS", "record": target}
        else:
            return {"status": "NO_ACTIVE_OCCUPANTS", "message": "No active occupants inside."}

    elif demo.action == "reset":
        records_db.clear()
        alerts_db.clear()
        save_json(RECORDS_FILE, records_db)
        save_json(ALERTS_FILE, alerts_db)
        await manager.broadcast({"type": "SYSTEM_RESET"})
        return {"status": "RESET_COMPLETE"}

    raise HTTPException(status_code=400, detail="Unknown demo action")

# ----------------- Video Streaming (MJPEG) -----------------
class VideoStreamer:
    def __init__(self):
        self.cap = None
        self.running = False
        self.lock = asyncio.Lock()

    def get_frame(self) -> bytes:
        # 1. If CV engine recently dispatched a frame (< 1.5s ago), use it
        if gate_state.get("last_seen_frame") and (time.time() - gate_state.get("last_seen_frame_time", 0) < 1.5):
            gate_state["camera_connected"] = True
            return gate_state["last_seen_frame"]

        # 2. Try physical webcam capture
        if self.cap is None:
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(0)

        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                gate_state["camera_connected"] = True
                # Draw vertical red tripwire divider
                h, w = frame.shape[:2]
                div_x = w // 2
                cv2.line(frame, (div_x, 0), (div_x, h), (0, 0, 255), 2)
                cv2.putText(frame, "PUBLIC ZONE", (div_x - 130, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
                cv2.putText(frame, "SECURE ZONE", (div_x + 20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1)
                
                # Timestamp
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(frame, f"CAM-01 [LIVE] | {now_str}", (15, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1)

                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                return buf.tobytes()

        # 3. Fallback: High-fidelity animated surveillance feed
        gate_state["camera_connected"] = False
        return self._generate_simulated_stream_frame()

    def _generate_simulated_stream_frame(self) -> bytes:
        w, h = 640, 480
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (20, 16, 32)

        # Surveillance grid
        for y in range(0, h, 40):
            cv2.line(frame, (0, y), (w, y), (35, 28, 48), 1)
        for x in range(0, w, 40):
            cv2.line(frame, (x, 0), (x, h), (35, 28, 48), 1)

        # Red Divider Line
        div_x = 320
        cv2.line(frame, (div_x, 0), (div_x, h), (0, 0, 255), 2)
        cv2.putText(frame, "PUBLIC CORRIDOR", (div_x - 140, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
        cv2.putText(frame, "SECURE INTERIOR", (div_x + 20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

        # Moving synthetic patrol dot
        t = time.time()
        sin_x = int(div_x - 100 + np.sin(t * 1.5) * 80)
        sin_y = int(240 + np.cos(t * 1.5) * 60)
        cv2.circle(frame, (sin_x, sin_y), 18, (255, 61, 139), -1)
        cv2.rectangle(frame, (sin_x - 25, sin_y - 45), (sin_x + 25, sin_y + 45), (255, 61, 139), 2)
        cv2.putText(frame, "Subject #1 [Roaming]", (sin_x - 45, sin_y - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)

        # Overlay text
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, f"CAM-01 [SENTRY DEMO FEED] | {now_str}", (15, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1)

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes()

video_streamer = VideoStreamer()

async def mjpeg_frame_generator():
    """Generates MJPEG multipart stream frames."""
    while True:
        frame_bytes = video_streamer.get_frame()
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
        await asyncio.sleep(0.04)  # ~25 FPS

@app.get("/api/video_feed")
async def get_video_feed():
    """Live MJPEG video stream for dashboard upper-left camera container."""
    return StreamingResponse(
        mjpeg_frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# ----------------- WebSocket for Real-Time Dashboard Updates -----------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial sync payload on connection
        await websocket.send_json({
            "type": "INITIAL_SYNC",
            "gate": gate_state["status"],
            "camera_connected": gate_state["camera_connected"],
            "records": list(reversed(records_db)),
            "alerts": list(reversed(alerts_db))
        })
        while True:
            data = await websocket.receive_text()
            # Client heartbeats or ping
            try:
                msg = json.loads(data)
                if msg.get("type") == "PING":
                    await websocket.send_json({"type": "PONG", "time": time.time()})
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# ----------------- Static Files & Mounts -----------------
# Serve alert image snapshots directly
app.mount("/data/alerts", StaticFiles(directory=str(ALERTS_DIR)), name="alerts")
# Serve frontend assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>AegisGate SOC Backend Active</h1><p>Building frontend...</p>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
