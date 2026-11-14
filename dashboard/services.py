"""
Backend access for the dashboard: settings, REST calls, and a background
WebSocket listener. The listener holds the backend's live /ws connection.
Every message bumps `version`, which invalidates the cached dashboard state,
so the panels refresh within about a second of any event.
"""
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import partial
from typing import Optional
from urllib.parse import urlparse

import requests
import streamlit as st

NGROK = {"ngrok-skip-browser-warning": "1"}


@dataclass
class Settings:
    backend_url: str
    rag_url: str
    control_token: str
    agent_token: str
    camera_mode: str
    timezone: str

    @property
    def ws_url(self) -> str:
        u = urlparse(self.backend_url)
        scheme = "wss" if u.scheme == "https" else "ws"
        return f"{scheme}://{u.netloc}{u.path.rstrip('/')}/ws"

    @property
    def backend_is_local(self) -> bool:
        return urlparse(self.backend_url).hostname in ("localhost", "127.0.0.1", "0.0.0.0")


def _get(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:                         # no secrets.toml at all
        pass
    return os.getenv(name, default)


@st.cache_resource
def settings() -> Settings:
    return Settings(
        backend_url=_get("BACKEND_URL", "http://localhost:8000").rstrip("/"),
        rag_url=_get("RAG_URL", "http://localhost:8100").rstrip("/"),
        control_token=_get("CONTROL_TOKEN"),
        agent_token=_get("AGENT_TOKEN"),
        camera_mode=_get("CAMERA_MODE", "auto").lower(),
        timezone=_get("TIMEZONE", "Asia/Kolkata"),
    )


# ------------------------------------------------------------------ live link
class LiveLink:
    def __init__(self, url: str):
        self.url = url
        self.version = 0
        self.connected = False
        self.last_message_at = 0.0
        self.error: Optional[str] = None
        self.recent = deque(maxlen=50)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        import websocket                      # websocket-client
        while True:
            try:
                ws = websocket.create_connection(self.url, timeout=10,
                                                 header=[f"{k}: {v}" for k, v in NGROK.items()])
                self.connected, self.error = True, None
                self.version += 1
                ws.settimeout(20)
                while True:
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        ws.send("ping")
                        continue
                    if not raw:
                        raise ConnectionError("socket closed")
                    try:
                        self.recent.appendleft(json.loads(raw))
                    except ValueError:
                        pass
                    self.version += 1
                    self.last_message_at = time.time()
            except Exception as exc:
                self.connected, self.error = False, exc.__class__.__name__
                time.sleep(2)


@st.cache_resource
def live_link(url: str) -> LiveLink:
    return LiveLink(url)


# ------------------------------------------------------------------ REST
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(NGROK)
    return s


_http = _session()


@st.cache_data(ttl=10, show_spinner=False, max_entries=8)
def dashboard_state(base: str, version: int, bucket: int) -> Optional[dict]:
    """Cached per WebSocket version and a 2 s bucket (fallback polling + timers)."""
    try:
        r = _http.get(f"{base}/api/dashboard", timeout=4)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(show_spinner=False, max_entries=200)
def snapshot_bytes(base: str, name: str) -> Optional[bytes]:
    try:
        r = _http.get(f"{base}/snapshots/{name}", timeout=4)
        return r.content if r.ok else None
    except Exception:
        return None


def frame_bytes(base: str) -> Optional[bytes]:
    try:
        r = _http.get(f"{base}/api/frame.jpg", timeout=3)
        return r.content if r.ok else None
    except Exception:
        return None


@st.cache_data(show_spinner=False, max_entries=100)
def _pdf(base: str, incident_id: str, updated_at: float) -> bytes:
    r = _http.get(f"{base}/api/incidents/{incident_id}/report.pdf", timeout=20)
    r.raise_for_status()
    return r.content


def pdf_loader(base: str, incident_id: str, updated_at: float):
    """Zero-arg callable for st.download_button: PDF is generated only when clicked."""
    return partial(_pdf, base, incident_id, updated_at)


@st.cache_data(ttl=300, show_spinner=False)
def risk_rules(base: str) -> Optional[dict]:
    try:
        return _http.get(f"{base}/api/risk/rules", timeout=4).json()
    except Exception:
        return None


def post(cfg: Settings, path: str) -> tuple:
    try:
        r = _http.post(f"{cfg.backend_url}{path}", timeout=5,
                       headers={"X-Control-Token": cfg.control_token} if cfg.control_token else None)
        return r.ok, (r.json().get("detail") if not r.ok else "")
    except Exception as exc:
        return False, exc.__class__.__name__


def ask_agent(cfg: Settings, question: str) -> dict:
    try:
        r = _http.post(f"{cfg.rag_url}/ask", json={"question": question}, timeout=40,
                       headers={"X-Agent-Token": cfg.agent_token} if cfg.agent_token else None)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"answer": f"The assistant is unreachable at {cfg.rag_url} ({exc.__class__.__name__}).",
                "sources": [], "mode": "error"}
