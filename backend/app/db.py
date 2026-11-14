"""
Persistence. SQLite by default; any SQLAlchemy URL works (e.g. Supabase Postgres).

Tables
  events     every hardware / camera / system event (powers the live feed)
  incidents  one row per incident with full evidence JSON (powers PDFs)
  records    entry / exit log (one row per authorised entry)
"""
import time
import uuid
from typing import List, Optional

from sqlalchemy import (JSON, Column, Float, Integer, MetaData, String, Table,
                        create_engine, delete, desc, insert, select, update)

metadata = MetaData()

events = Table(
    "events", metadata,
    Column("id", String(40), primary_key=True),
    Column("ts", Float, index=True),
    Column("gate_id", String(40)),
    Column("kind", String(32)),          # BADGE | CROSSING | DOOR | ENTRY | INCIDENT | SYSTEM
    Column("title", String(200)),
    Column("detail", String(500)),
    Column("severity", String(16), nullable=True),
    Column("incident_id", String(40), nullable=True),
    Column("data", JSON),
)

incidents = Table(
    "incidents", metadata,
    Column("id", String(40), primary_key=True),
    Column("gate_id", String(40)),
    Column("type", String(40), index=True),
    Column("created_at", Float, index=True),
    Column("updated_at", Float),
    Column("score", Integer),
    Column("severity", String(16)),
    Column("data", JSON),
)

records = Table(
    "records", metadata,
    Column("id", String(40), primary_key=True),
    Column("gate_id", String(40)),
    Column("badge_id", String(40), nullable=True),
    Column("holder", String(120), nullable=True),
    Column("track_id", String(60), nullable=True),
    Column("time_in", Float, index=True),
    Column("time_out", Float, nullable=True),
    Column("status", String(16)),        # INSIDE | EXITED
)


class Store:
    def __init__(self, url: str):
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {
            "pool_pre_ping": True}
        self.engine = create_engine(url, future=True, **kwargs)
        metadata.create_all(self.engine)

    # ---------------- events ----------------
    def add_event(self, gate_id: str, kind: str, title: str, detail: str = "",
                  data: Optional[dict] = None, ts: Optional[float] = None,
                  severity: Optional[str] = None, incident_id: Optional[str] = None) -> dict:
        row = {
            "id": f"evt_{uuid.uuid4().hex[:12]}", "ts": ts or time.time(), "gate_id": gate_id,
            "kind": kind, "title": title[:200], "detail": (detail or "")[:500],
            "severity": severity, "incident_id": incident_id, "data": data or {},
        }
        with self.engine.begin() as c:
            c.execute(insert(events).values(**row))
        return row

    def list_events(self, limit: int = 100) -> List[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(events).order_by(desc(events.c.ts)).limit(limit)).mappings().all()
        return [dict(r) for r in rows]

    # ---------------- incidents ----------------
    def save_incident(self, inc: dict) -> None:
        values = {
            "gate_id": inc["gate_id"], "type": inc["type"], "created_at": inc["created_at"],
            "updated_at": inc["updated_at"], "score": inc["risk"]["score"],
            "severity": inc["risk"]["severity"], "data": inc,
        }
        with self.engine.begin() as c:
            exists = c.execute(select(incidents.c.id).where(incidents.c.id == inc["id"])).first()
            if exists:
                c.execute(update(incidents).where(incidents.c.id == inc["id"]).values(**values))
            else:
                c.execute(insert(incidents).values(id=inc["id"], **values))

    def get_incident(self, incident_id: str) -> Optional[dict]:
        with self.engine.connect() as c:
            row = c.execute(select(incidents.c.data).where(incidents.c.id == incident_id)).first()
        return dict(row[0]) if row else None

    def list_incidents(self, limit: int = 50, since: Optional[float] = None) -> List[dict]:
        q = select(incidents.c.data).order_by(desc(incidents.c.created_at)).limit(limit)
        if since is not None:
            q = q.where(incidents.c.created_at >= since)
        with self.engine.connect() as c:
            return [dict(r[0]) for r in c.execute(q).all()]

    # ---------------- entry / exit records ----------------
    def add_record(self, gate_id: str, badge_id: Optional[str], holder: Optional[str],
                   track_id: Optional[str], ts: float) -> dict:
        row = {"id": f"rec_{uuid.uuid4().hex[:10]}", "gate_id": gate_id, "badge_id": badge_id,
               "holder": holder, "track_id": track_id, "time_in": ts, "time_out": None,
               "status": "INSIDE"}
        with self.engine.begin() as c:
            c.execute(insert(records).values(**row))
        return row

    def close_oldest_open_record(self, ts: float) -> Optional[dict]:
        with self.engine.begin() as c:
            row = c.execute(select(records).where(records.c.status == "INSIDE")
                            .order_by(records.c.time_in).limit(1)).mappings().first()
            if not row:
                return None
            c.execute(update(records).where(records.c.id == row["id"])
                      .values(time_out=ts, status="EXITED"))
        out = dict(row)
        out.update(time_out=ts, status="EXITED")
        return out

    def list_records(self, limit: int = 100) -> List[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(records).order_by(desc(records.c.time_in)).limit(limit)).mappings().all()
        return [dict(r) for r in rows]

    def count_inside(self) -> int:
        with self.engine.connect() as c:
            return len(c.execute(select(records.c.id).where(records.c.status == "INSIDE")).all())

    def reset(self) -> None:
        with self.engine.begin() as c:
            for t in (events, incidents, records):
                c.execute(delete(t))
