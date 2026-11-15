/**
 * AegisGate — SOC Real-Time Security Operations Dashboard
 * Core Frontend Controller & WebSockets Client
 */

// ----------------- Global State -----------------
let ws = null;
let allRecords = [];
let allAlerts = [];
let isDirectWebcam = false;
let webcamStream = null;
let audioCtx = null;
let gateArmedTimer = null;

// ----------------- DOM Elements -----------------
const clockDisplay = document.getElementById("clockDisplay");
const hudTimestamp = document.getElementById("hudTimestamp");
const wsStatus = document.getElementById("wsStatus");
const wsLabel = document.getElementById("wsLabel");
const gateStatusPill = document.getElementById("gateStatusPill");
const gateStateText = document.getElementById("gateStateText");
const camStatusPill = document.getElementById("camStatusPill");
const camStatusText = document.getElementById("camStatusText");
const liveVideoFeed = document.getElementById("liveVideoFeed");
const webcamVideo = document.getElementById("webcamVideo");
const tripwireCanvas = document.getElementById("tripwireCanvas");
const breachBanner = document.getElementById("breachBanner");
const breachBannerText = document.getElementById("breachBannerText");
const tripwireStatus = document.getElementById("tripwireStatus");
const tripwireStateText = document.getElementById("tripwireStateText");
const alertCardsTrack = document.getElementById("alertCardsTrack");
const noAlertsPlaceholder = document.getElementById("noAlertsPlaceholder");
const alertCountBadge = document.getElementById("alertCountBadge");
const recordsTableBody = document.getElementById("recordsTableBody");
const activeInsideCount = document.getElementById("activeInsideCount");
const totalRecordsLabel = document.getElementById("totalRecordsLabel");
const recordSearch = document.getElementById("recordSearch");
const audioSirenToggle = document.getElementById("audioSirenToggle");
const alertModal = document.getElementById("alertModal");
const modalImage = document.getElementById("modalImage");
const modalTimestamp = document.getElementById("modalTimestamp");
const modalDescription = document.getElementById("modalDescription");
const modalSeverity = document.getElementById("modalSeverity");

// ----------------- 1. Clock & Timers -----------------
function updateClocks() {
  const now = new Date();
  const timeStr = now.toTimeString().split(" ")[0];
  const dateStr = now.toISOString().split("T")[0];

  if (clockDisplay) clockDisplay.textContent = `${timeStr} UTC+05:30`;
  if (hudTimestamp) hudTimestamp.textContent = `${dateStr} ${timeStr}`;
}
setInterval(updateClocks, 1000);
updateClocks();

// ----------------- 2. WebSocket Real-Time Channel -----------------
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  console.log(`[WS] Connecting to ${wsUrl}...`);
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log("[WS] Connected to AegisGate Security Core.");
    if (wsStatus) {
      wsStatus.classList.add("online");
      wsLabel.textContent = "LIVE LINK";
    }
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleSocketMessage(msg);
    } catch (e) {
      console.error("[WS] Parse error:", e);
    }
  };

  ws.onclose = () => {
    console.warn("[WS] Connection lost. Retrying in 2.5s...");
    if (wsStatus) {
      wsStatus.classList.remove("online");
      wsLabel.textContent = "RECONNECTING";
    }
    setTimeout(initWebSocket, 2500);
  };

  ws.onerror = (err) => {
    console.error("[WS] Socket error:", err);
    ws.close();
  };
}

function handleSocketMessage(msg) {
  switch (msg.type) {
    case "INITIAL_SYNC":
      if (msg.records) {
        allRecords = msg.records;
        renderRecordsTable(allRecords);
      }
      if (msg.alerts) {
        allAlerts = msg.alerts;
        renderAlertCarousel(allAlerts);
      }
      updateGateState(msg.gate || "STANDBY");
      updateCameraState(msg.camera_connected !== false);
      break;

    case "ENTRY_RECORD_ADDED":
      // Prepend to list
      allRecords.unshift(msg.record);
      renderRecordsTable(allRecords);
      highlightNewRow(msg.record.id);
      break;

    case "ENTRY_RECORD_UPDATED":
      // Update record in list
      const idx = allRecords.findIndex(r => r.id === msg.record.id || r.serial_no === msg.record.serial_no);
      if (idx !== -1) {
        allRecords[idx] = msg.record;
      } else {
        allRecords.unshift(msg.record);
      }
      renderRecordsTable(allRecords);
      break;

    case "NEW_ALERT":
      // Add new breach card
      allAlerts.unshift(msg.alert);
      renderAlertCarousel(allAlerts);
      triggerBreachAlarm(msg.alert);
      break;

    case "GATE_ARMED":
    case "BADGE_TAPPED":
      armGateTemporarily(msg.user ? msg.user.name : "Authorized Personnel");
      break;

    case "SYSTEM_RESET":
      allRecords = [];
      allAlerts = [];
      renderRecordsTable(allRecords);
      renderAlertCarousel(allAlerts);
      updateGateState("STANDBY");
      break;
  }
}

// ----------------- 3. Gate & Camera State Management -----------------
function updateGateState(state) {
  if (!gateStatusPill || !gateStateText) return;

  gateStatusPill.className = "gate-status-pill";
  if (state === "ARMED") {
    gateStatusPill.classList.add("armed");
    gateStateText.textContent = "ARMED (ACCESS OPEN)";
    if (tripwireStatus) {
      tripwireStatus.className = "tripwire-status armed";
      tripwireStateText.textContent = "TRANSIT ARMED";
    }
  } else if (state === "BREACH") {
    gateStatusPill.classList.add("breach");
    gateStateText.textContent = "BREACH ALARM";
    if (tripwireStatus) {
      tripwireStatus.className = "tripwire-status breach";
      tripwireStateText.textContent = "BREACH DETECTED";
    }
  } else {
    gateStateText.textContent = "STANDBY";
    if (tripwireStatus) {
      tripwireStatus.className = "tripwire-status";
      tripwireStateText.textContent = "TRIPWIRE ARMED";
    }
  }
}

function armGateTemporarily(userName) {
  updateGateState("ARMED");
  if (gateArmedTimer) clearTimeout(gateArmedTimer);
  gateArmedTimer = setTimeout(() => {
    updateGateState("STANDBY");
  }, 4000);
}

function updateCameraState(connected) {
  if (!camStatusPill || !camStatusText) return;
  if (connected) {
    camStatusPill.className = "cam-status-pill";
    camStatusText.textContent = "CONNECTED";
  } else {
    camStatusPill.className = "cam-status-pill disconnected";
    camStatusText.textContent = "STANDBY / DEMO";
  }
}

function handleStreamError(imgElem) {
  console.warn("[STREAM] Video stream disconnected. Retrying in 3s...");
  updateCameraState(false);
  setTimeout(() => {
    imgElem.src = `/api/video_feed?t=${Date.now()}`;
  }, 3000);
}

// ----------------- 4. Section C: Entry/Exit Records Table -----------------
function renderRecordsTable(records) {
  if (!recordsTableBody) return;

  const filterText = (recordSearch ? recordSearch.value : "").toLowerCase().trim();
  const filtered = records.filter(r => {
    if (!filterText) return true;
    return (
      (r.name && r.name.toLowerCase().includes(filterText)) ||
      (r.badge_id && r.badge_id.toLowerCase().includes(filterText)) ||
      String(r.serial_no).includes(filterText)
    );
  });

  let activeInside = 0;
  recordsTableBody.innerHTML = "";

  if (filtered.length === 0) {
    recordsTableBody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align:center; padding: 40px; color: var(--text-muted);">
          No access logs matching criteria.
        </td>
      </tr>
    `;
  } else {
    filtered.forEach((r) => {
      const isInside = r.status === "INSIDE" || r.time_out === "--:--:--" || !r.time_out;
      if (isInside) activeInside++;

      const isUnknown = !r.name || r.name === "Unknown";
      const initial = isUnknown ? "?" : r.name.charAt(0).toUpperCase();

      const tr = document.createElement("tr");
      tr.id = `row-${r.id || r.serial_no}`;

      tr.innerHTML = `
        <td class="serial-cell">#${String(r.serial_no).padStart(3, "0")}</td>
        <td class="name-cell ${isUnknown ? 'unknown' : ''}">
          <div class="name-avatar">${initial}</div>
          <span>${r.name || "Unknown"}</span>
        </td>
        <td class="time-cell">${r.time_in || "--:--:--"}</td>
        <td class="time-cell">
          ${
            isInside
              ? `<span class="status-inside-pill"><span class="legend-dot green"></span> INSIDE</span>`
              : (r.time_out || "--:--:--")
          }
        </td>
      `;
      recordsTableBody.appendChild(tr);
    });
  }

  if (activeInsideCount) activeInsideCount.textContent = `ACTIVE INSIDE: ${activeInside}`;
  if (totalRecordsLabel) totalRecordsLabel.textContent = `Showing ${filtered.length} of ${records.length} entries`;
}

function filterRecords() {
  renderRecordsTable(allRecords);
}

function highlightNewRow(rowId) {
  setTimeout(() => {
    const row = document.getElementById(`row-${rowId}`);
    if (row) {
      row.classList.add("row-new");
      setTimeout(() => row.classList.remove("row-new"), 1200);
    }
  }, 50);
}

// ----------------- 5. Section: ALERT CAPTURE (Carousel of Cards) -----------------
function renderAlertCarousel(alerts) {
  if (!alertCardsTrack) return;

  if (!alerts || alerts.length === 0) {
    if (noAlertsPlaceholder) noAlertsPlaceholder.style.display = "flex";
    if (alertCountBadge) alertCountBadge.textContent = "0 INCIDENTS";
    return;
  }

  if (noAlertsPlaceholder) noAlertsPlaceholder.style.display = "none";
  if (alertCountBadge) alertCountBadge.textContent = `${alerts.length} INCIDENT${alerts.length > 1 ? 'S' : ''}`;

  // Keep existing cards, render alert cards
  alertCardsTrack.innerHTML = "";
  alerts.forEach((alt, idx) => {
    const card = document.createElement("div");
    card.className = "alert-card";
    if (idx === 0) card.classList.add("new-pulse");

    card.onclick = () => openAlertModal(alt);

    card.innerHTML = `
      <div class="card-img-container">
        <img src="${alt.snapshot_url}" alt="CCTV Incident Snapshot" onerror="this.src='/static/fallback_alert.jpg'">
        <span class="card-badge-overlay">${alt.type || 'TAILGATING'}</span>
        <span class="card-time-overlay">${alt.time_raw || alt.timestamp}</span>
      </div>
      <div class="card-body">
        <div class="alert-type-title">TAILGATING DETECTED</div>
        <p class="alert-desc-text">${alt.description || '2 persons crossed on 1 badge tap.'}</p>
        <div class="card-footer-meta">
          <span class="severity-tag">● ${alt.severity || 'CRITICAL'}</span>
          <span>Tap to View</span>
        </div>
      </div>
    `;
    alertCardsTrack.appendChild(card);
  });

  // Scroll to leftmost position so newest is in view
  alertCardsTrack.scrollTo({ left: 0, behavior: "smooth" });
}

function scrollCarousel(direction) {
  if (!alertCardsTrack) return;
  const scrollAmount = 260 * direction;
  alertCardsTrack.scrollBy({ left: scrollAmount, behavior: "smooth" });
}

// ----------------- 6. Tailgating Breach Alarm & Audio Siren -----------------
function triggerBreachAlarm(alert) {
  updateGateState("BREACH");

  // Show breach banner overlay on CCTV
  if (breachBanner) {
    if (breachBannerText) {
      breachBannerText.textContent = `ALARM: ${alert.type || 'TAILGATING DETECTED'}!`;
    }
    breachBanner.classList.add("active");
    setTimeout(() => {
      breachBanner.classList.remove("active");
      updateGateState("STANDBY");
    }, 4500);
  }

  // Play synthesized security siren
  if (audioSirenToggle && audioSirenToggle.checked) {
    playSecuritySirenChime();
  }
}

function playSecuritySirenChime() {
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }

    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();

    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(880, audioCtx.currentTime); // High pitch
    osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.35); // Sweep down
    osc.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + 0.70); // Sweep up

    gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 1.2);

    osc.connect(gain);
    gain.connect(audioCtx.destination);

    osc.start();
    osc.stop(audioCtx.currentTime + 1.2);
  } catch (e) {
    console.warn("[AUDIO] Siren playback skipped:", e);
  }
}

// ----------------- 7. Lightbox Modal for Full-Res Alert -----------------
let activeModalAlert = null;

function openAlertModal(alert) {
  activeModalAlert = alert;
  if (!alertModal) return;

  if (modalImage) modalImage.src = alert.snapshot_url;
  if (modalTimestamp) modalTimestamp.textContent = alert.timestamp || alert.time_raw;
  if (modalDescription) modalDescription.textContent = alert.description;
  if (modalSeverity) modalSeverity.textContent = alert.severity || "CRITICAL";

  alertModal.classList.add("open");
}

function closeAlertModal() {
  if (alertModal) alertModal.classList.remove("open");
  activeModalAlert = null;
}

function exportIncidentPDF() {
  if (!activeModalAlert) return;
  alert(`Official Incident Report Queued:\n- Incident ID: ${activeModalAlert.id}\n- Time: ${activeModalAlert.timestamp}\n- Type: ${activeModalAlert.type}\n\nEvidence snapshot and audit log preserved in compliance store.`);
}

// ----------------- 8. Interactive Hackathon Controller Actions -----------------
async function demoAction(actionName) {
  try {
    const res = await fetch("/api/demo/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: actionName })
    });
    const data = await res.json();
    console.log(`[DEMO] Triggered '${actionName}':`, data);
  } catch (err) {
    console.error(`[DEMO] Failed action ${actionName}:`, err);
  }
}

function triggerManualSnapshot() {
  demoAction("tailgating");
}

function refreshRecords() {
  fetch("/api/records")
    .then(r => r.json())
    .then(data => {
      allRecords = data;
      renderRecordsTable(allRecords);
    });
}

// ----------------- 9. Camera Source Toggle (Server vs Browser Webcam) -----------------
function toggleCameraSource() {
  isDirectWebcam = !isDirectWebcam;

  if (isDirectWebcam) {
    console.log("[CAM] Switching to Direct Browser WebCam...");
    if (liveVideoFeed) liveVideoFeed.style.display = "none";
    if (webcamVideo) webcamVideo.style.display = "block";
    if (tripwireCanvas) tripwireCanvas.style.display = "block";

    navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } })
      .then(stream => {
        webcamStream = stream;
        webcamVideo.srcObject = stream;
        updateCameraState(true);
      })
      .catch(err => {
        console.warn("[CAM] Direct webcam access denied/busy:", err);
        alert("Could not access direct browser webcam (camera may be in use by CCTV engine). Reverting to server MJPEG feed.");
        toggleCameraSource();
      });
  } else {
    console.log("[CAM] Switching to Server MJPEG Feed...");
    if (webcamStream) {
      webcamStream.getTracks().forEach(t => t.stop());
      webcamStream = null;
    }
    if (webcamVideo) webcamVideo.style.display = "none";
    if (tripwireCanvas) tripwireCanvas.style.display = "none";
    if (liveVideoFeed) {
      liveVideoFeed.style.display = "block";
      liveVideoFeed.src = `/api/video_feed?t=${Date.now()}`;
    }
    updateCameraState(true);
  }
}

// ----------------- 10. Initialization -----------------
window.addEventListener("DOMContentLoaded", () => {
  console.log("[INIT] AegisGate Security Dashboard loaded.");
  initWebSocket();

  // Initial fetch of records and alerts to guarantee instant render
  fetch("/api/records")
    .then(r => r.json())
    .then(data => {
      allRecords = data;
      renderRecordsTable(allRecords);
    })
    .catch(console.warn);

  fetch("/api/alerts")
    .then(r => r.json())
    .then(data => {
      allAlerts = data;
      renderAlertCarousel(allAlerts);
    })
    .catch(console.warn);
});
