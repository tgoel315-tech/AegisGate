# =============================================================================
#  RESTRICTED — OWNED BY ALOK (HARDWARE).  DO NOT EDIT, RENAME OR REFORMAT.
#
#  Everything below this banner is copied verbatim and is the source of truth for the hardware
#  communication contract. It is NOT imported or executed by AegisGate.
#  The backend re-implements the same HTTP contract through
#  backend/app/adapters/hardware.py so this file never has to change.
#  See hardware/README.md for the derived interface.
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)

@app.post("/api/event/hardware")
async def handle_hardware(data: dict):
    global last_badge_tap
    event = data.get("event")

    if event == "BADGE_TAP":
        last_badge_tap = {
            "time": data.get("timestamp", time.time()),
            "holder_name": data.get("holder_name"),
            "badge_id": data.get("badge_id")
        }
        await manager.broadcast({"type": "GATE_STATUS", "status": "UNLOCKED", "holder": last_badge_tap})

    elif event == "DOOR_OPEN":
        # Check if door opened without recent badge tap (> 6 seconds)
        if time.time() - last_badge_tap["time"] > 6.0:
            await manager.broadcast({
                "status": "BREACH",
                "type": "FORCED_ENTRY",
                "message": "CRITICAL: Door forced open without valid card tap!",
                "timestamp": time.time()
            })
    return {"status": "ok"}

@app.post("/api/event/vision")
async def handle_vision(data: dict):
    persons = data.get("persons_detected", 1)
    snapshot = data.get("snapshot_base64")

    # Check for Tailgating: If more than 1 person crossed on a single tap window
    if persons >= 2:
        alert_payload = {
            "status": "BREACH",
            "type": "TAILGATING",
            "message": f"VIOLATION: Tailgating detected! {persons} persons entered on 1 tap.",
            "holder_name": last_badge_tap["holder_name"],
            "badge_id": last_badge_tap["badge_id"],
            "snapshot": snapshot,
            "timestamp": time.time()
        }
        await manager.broadcast(alert_payload)
    else:
        await manager.broadcast({"status": "NORMAL", "message": "1 Person Verified. Normal Passage."})

    return {"status": "processed"}
