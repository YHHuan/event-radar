"""Source directory and replaceable discovery snapshots in the existing database.

Unlike historical event rows, a successful feed refresh replaces its prior set.
Failures retain at most seven days of data and expose freshness to the reader.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from . import db
from .config import load_yaml

SCHEMA = """CREATE TABLE IF NOT EXISTS discovery_snapshots (
    source_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL,
    succeeded_at TEXT, status TEXT NOT NULL, events_json TEXT NOT NULL DEFAULT '[]'
)"""


def record_result(source_id: str, events: list[dict] | None, *, now: datetime | None = None) -> None:
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute(SCHEMA)
        conn.execute("""INSERT INTO discovery_snapshots
            (source_id, checked_at, succeeded_at, status, events_json) VALUES (?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET checked_at=excluded.checked_at,
                status=excluded.status,
                succeeded_at=COALESCE(excluded.succeeded_at, discovery_snapshots.succeeded_at),
                events_json=CASE WHEN excluded.status='ok' THEN excluded.events_json
                           ELSE discovery_snapshots.events_json END""",
                     (source_id, stamp, stamp if events is not None else None,
                      "ok" if events is not None else "error",
                      json.dumps(events or [], ensure_ascii=False)))


def _records() -> dict:
    with db.connect() as conn:
        # Reads/builds do not create or migrate source state.
        if not conn.execute("SELECT name FROM sqlite_master WHERE name='discovery_snapshots'").fetchone():
            return {}
        return {row["source_id"]: dict(row) for row in conn.execute("SELECT * FROM discovery_snapshots")}


def _fresh(row: dict, today: date) -> bool:
    return bool(row.get("succeeded_at") and
                today - timedelta(days=7) <= date.fromisoformat(row["succeeded_at"][:10]) <= today)


def cached_events(*, today: date | None = None) -> list[dict]:
    today = today or date.today()
    records = _records()
    out = []
    for source in load_yaml("discovery.yaml").get("sources", []):
        row = records.get(source["id"], {})
        if source.get("mode") != "automatic" or not _fresh(row, today):
            continue
        for event in json.loads(row["events_json"]):
            event["_selection"]["checked_on"] = row["succeeded_at"][:10]
            event["_selection"]["source_id"] = source["id"]
            out.append(event)
    return out


def public_sources(*, today: date | None = None) -> list[dict]:
    today = today or date.today()
    records = _records()
    out = []
    for source in load_yaml("discovery.yaml").get("sources", []):
        row = records.get(source["id"], {})
        automatic = source.get("mode") == "automatic"
        fresh = _fresh(row, today)
        status = ("人工追蹤" if not automatic else "尚未更新" if not row else
                  "更新失敗，保留近期資料" if row["status"] == "error" and fresh else
                  "更新失敗，等待恢復" if row["status"] == "error" else
                  "資料已過期" if not fresh else "每日更新")
        events = json.loads(row.get("events_json", "[]")) if fresh else []
        upcoming = sum(any((p.get("end_time") or p.get("start_time") or "")[:10] >= today.isoformat()
                           for p in e.get("performances", [])) for e in events)
        out.append({"id": source["id"], "name": source["name"], "url": source["url"],
                    "lenses": source["lenses"], "mode": source["mode"], "status": status,
                    "note": source["note"], "checkedAt": row.get("checked_at", ""),
                    "lastSuccess": row.get("succeeded_at") or "", "count": upcoming})
    return out


def managed_source_names() -> set[str]:
    return {item["name"] for item in load_yaml("discovery.yaml").get("sources", [])
            if item.get("mode") == "automatic"}
