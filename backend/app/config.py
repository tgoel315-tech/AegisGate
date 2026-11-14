"""
Backend settings. Every value can be overridden with an environment variable
(or a line in backend/.env — see backend/.env.example).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    """Tiny .env loader so beginners don't need python-dotenv."""
    env_file = BACKEND_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    gate_id: str = field(default_factory=lambda: os.getenv("GATE_ID", "gate-01"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(BACKEND_DIR / "data"))))
    # Empty = local SQLite file. For Supabase/Postgres use:
    # postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))

    # --- Access-session correlation ---------------------------------------
    # Seconds after an authorised tap during which inbound crossings belong to that tap.
    session_window_s: float = field(default_factory=lambda: _float("SESSION_WINDOW_S", 8.0))
    # Extra tolerance for camera events that arrive late (network / inference lag).
    camera_grace_s: float = field(default_factory=lambda: _float("CAMERA_GRACE_S", 3.0))
    # How long an unmatched inbound crossing waits for a late badge event before it
    # becomes an unauthorised-entry incident.
    unauth_decision_delay_s: float = field(default_factory=lambda: _float("UNAUTH_DECISION_DELAY_S", 2.0))
    # People allowed through per authorised tap.
    allowed_per_tap: int = field(default_factory=lambda: int(os.getenv("ALLOWED_PER_TAP", "1")))
    # Same track + same direction inside this window is treated as a duplicate.
    crossing_dedupe_s: float = field(default_factory=lambda: _float("CROSSING_DEDUPE_S", 5.0))

    # --- Door sensor -------------------------------------------------------
    # Same 6.0 s rule as the restricted hardware script.
    forced_door_window_s: float = field(default_factory=lambda: _float("FORCED_DOOR_WINDOW_S", 6.0))
    held_open_threshold_s: float = field(default_factory=lambda: _float("HELD_OPEN_THRESHOLD_S", 10.0))
    # The restricted script has no DOOR_CLOSE event. Until one is seen, held-open
    # detection stays off so every opening isn't flagged. Set false to force it on.
    held_open_requires_close_event: bool = field(
        default_factory=lambda: _bool("HELD_OPEN_REQUIRES_CLOSE_EVENT", True))

    # --- Authorisation -----------------------------------------------------
    authorize_by_holder_name: bool = field(default_factory=lambda: _bool("AUTHORIZE_BY_HOLDER_NAME", True))

    # --- Risk ----------------------------------------------------------------
    risk_window_s: float = field(default_factory=lambda: _float("RISK_WINDOW_S", 900.0))

    # --- Camera frames -------------------------------------------------------
    frame_stale_s: float = field(default_factory=lambda: _float("FRAME_STALE_S", 3.0))

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'aegisgate.db').as_posix()}"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"


settings = Settings()
