"""SQLite schema + upsert。events / performances / sources / feedback / inbox。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key          TEXT UNIQUE NOT NULL,
    title               TEXT NOT NULL,
    organizer           TEXT,
    category            TEXT,
    subcategory         TEXT,
    description_clean   TEXT,
    source_name         TEXT,
    source_url          TEXT,
    ticket_url          TEXT,
    image_url           TEXT,
    city                TEXT,
    tags                TEXT,          -- json list
    first_start         TEXT,          -- ISO, 最早場次 (排序/時窗用)
    last_start          TEXT,
    n_performances      INTEGER DEFAULT 0,
    base_score          INTEGER,       -- rules.py
    noise_flags         TEXT,          -- json list
    rule_decision       TEXT,          -- keep / demote / drop
    personal_match_score INTEGER,      -- Claude
    noise_score         INTEGER,       -- Claude
    is_recommended      INTEGER,       -- Claude 0/1
    why_recommended     TEXT,
    score_model         TEXT,
    scored_at           TEXT,
    status              TEXT DEFAULT 'active',
    first_seen_at       TEXT,
    last_seen_at        TEXT
);

CREATE TABLE IF NOT EXISTS performances (
    performance_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    perf_key        TEXT,          -- dedupe within event
    start_time      TEXT,
    end_time        TEXT,
    venue_name      TEXT,
    venue_address   TEXT,
    latitude        REAL,
    longitude       REAL,
    city            TEXT,
    price_text      TEXT,
    is_ticketed     INTEGER,
    availability_text TEXT,
    UNIQUE(event_id, perf_key)
);

CREATE TABLE IF NOT EXISTS event_sources (
    event_id     INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    source_name  TEXT NOT NULL,
    source_url   TEXT,
    ticket_url   TEXT,
    last_seen_at TEXT,
    UNIQUE(event_id, source_name)
);

CREATE TABLE IF NOT EXISTS sources (
    source_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name   TEXT UNIQUE,
    source_type   TEXT,
    url           TEXT,
    category_hint TEXT,
    priority      INTEGER,
    enabled       INTEGER DEFAULT 1,
    last_run_at   TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER REFERENCES events(event_id),
    action      TEXT,   -- want / maybe / not_interested / block_similar
    created_at  TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS inbox (
    inbox_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT,
    added_at   TEXT,
    parsed     INTEGER DEFAULT 0,
    event_id   INTEGER REFERENCES events(event_id),
    note       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_firststart ON events(first_start);
CREATE INDEX IF NOT EXISTS idx_events_decision ON events(rule_decision);
CREATE INDEX IF NOT EXISTS idx_events_scored ON events(personal_match_score);
CREATE INDEX IF NOT EXISTS idx_event_sources_source ON event_sources(source_name);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _backfill_event_sources(conn)
        _migrate_dedupe_keys(conn)


def _backfill_event_sources(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO event_sources
           (event_id, source_name, source_url, ticket_url, last_seen_at)
           SELECT event_id,
                  COALESCE(source_name, 'unknown'),
                  source_url,
                  ticket_url,
                  COALESCE(last_seen_at, first_seen_at)
           FROM events
           WHERE source_name IS NOT NULL"""
    )


def _migrate_dedupe_keys(conn: sqlite3.Connection) -> None:
    """把每筆 events re-key 成目前 dedupe_key 規則,並合併共享同一新 key 的重複列。

    同一新 key = 同一活動身分(去重 key 的定義),故合併必正確。冪等:收斂後皆為 size-1
    group,只剩 no-op re-key。挑 winner:有 Claude 分數 > 場次多 > event_id 小。
    輸/贏列的 sources/performances/feedback 轉移到 winner,winner 缺的分數從輸列補。
    """
    from collections import defaultdict

    from .dedupe import dedupe_key

    rows = conn.execute(
        "SELECT event_id, dedupe_key, title, first_start, city, n_performances, "
        "personal_match_score FROM events"
    ).fetchall()
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        k = dedupe_key(r["title"], r["first_start"], r["city"], r["n_performances"] or 1)
        if k:
            groups[k].append(r)

    for k, members in groups.items():
        if len(members) == 1:
            r = members[0]
            if r["dedupe_key"] != k:
                conn.execute(
                    "UPDATE events SET dedupe_key=? WHERE event_id=?", (k, r["event_id"])
                )
            continue
        # 多筆共享新 key → 合併。winner: 有分數 > 場次多 > id 小
        winner = sorted(
            members,
            key=lambda r: (
                r["personal_match_score"] is None,
                -(r["n_performances"] or 0),
                r["event_id"],
            ),
        )[0]
        wid = winner["event_id"]
        for r in members:
            lid = r["event_id"]
            if lid == wid:
                continue
            # 轉移關聯(UNIQUE 衝突就 IGNORE,剩餘隨 cascade 刪除)
            conn.execute(
                "UPDATE OR IGNORE event_sources SET event_id=? WHERE event_id=?", (wid, lid)
            )
            conn.execute(
                "UPDATE OR IGNORE performances SET event_id=? WHERE event_id=?", (wid, lid)
            )
            conn.execute(
                "UPDATE OR IGNORE feedback SET event_id=? WHERE event_id=?", (wid, lid)
            )
            # winner 缺的 Claude 欄位從輸列補
            conn.execute(
                """UPDATE events SET
                     personal_match_score = COALESCE(personal_match_score,
                         (SELECT personal_match_score FROM events WHERE event_id=?)),
                     noise_score = COALESCE(noise_score,
                         (SELECT noise_score FROM events WHERE event_id=?)),
                     is_recommended = COALESCE(is_recommended,
                         (SELECT is_recommended FROM events WHERE event_id=?)),
                     why_recommended = COALESCE(why_recommended,
                         (SELECT why_recommended FROM events WHERE event_id=?)),
                     image_url = COALESCE(image_url,
                         (SELECT image_url FROM events WHERE event_id=?))
                   WHERE event_id=?""",
                (lid, lid, lid, lid, lid, wid),
            )
            conn.execute("DELETE FROM events WHERE event_id=?", (lid,))  # cascade 清關聯
        if winner["dedupe_key"] != k:
            conn.execute("UPDATE events SET dedupe_key=? WHERE event_id=?", (k, wid))


def upsert_event(conn: sqlite3.Connection, ev: dict) -> int:
    """ev: normalized event dict (含 performances list)。回傳 event_id。"""
    perfs = ev.get("performances", [])
    starts = sorted(p["start_time"] for p in perfs if p.get("start_time"))
    first_start = starts[0] if starts else ev.get("first_start")
    last_start = starts[-1] if starts else first_start
    ts = now_iso()
    fields = dict(
        dedupe_key=ev["dedupe_key"],
        title=ev.get("title"),
        organizer=ev.get("organizer"),
        category=ev.get("category"),
        subcategory=ev.get("subcategory"),
        description_clean=ev.get("description_clean"),
        source_name=ev.get("source_name"),
        source_url=ev.get("source_url"),
        ticket_url=ev.get("ticket_url"),
        image_url=ev.get("image_url"),
        city=ev.get("city"),
        tags=json.dumps(ev.get("tags", []), ensure_ascii=False),
        first_start=first_start,
        last_start=last_start,
        n_performances=len(perfs),
        base_score=ev.get("base_score"),
        noise_flags=json.dumps(ev.get("noise_flags", []), ensure_ascii=False),
        rule_decision=ev.get("rule_decision"),
        last_seen_at=ts,
        status="active",
        first_seen_at=ts,
    )

    cols = ", ".join(fields)
    ph = ", ".join("?" for _ in fields)
    conn.execute(
        f"""
        INSERT INTO events ({cols}) VALUES ({ph})
        ON CONFLICT(dedupe_key) DO UPDATE SET
            title = COALESCE(events.title, excluded.title),
            organizer = COALESCE(events.organizer, excluded.organizer),
            category = COALESCE(events.category, excluded.category),
            subcategory = COALESCE(events.subcategory, excluded.subcategory),
            description_clean = COALESCE(events.description_clean, excluded.description_clean),
            source_name = COALESCE(events.source_name, excluded.source_name),
            source_url = COALESCE(events.source_url, excluded.source_url),
            ticket_url = COALESCE(events.ticket_url, excluded.ticket_url),
            image_url = COALESCE(events.image_url, excluded.image_url),
            city = COALESCE(events.city, excluded.city),
            tags = CASE
                WHEN events.tags IS NULL OR events.tags = '[]' THEN excluded.tags
                ELSE events.tags
            END,
            first_start = CASE
                WHEN events.first_start IS NULL THEN excluded.first_start
                WHEN excluded.first_start IS NULL THEN events.first_start
                WHEN excluded.first_start < events.first_start THEN excluded.first_start
                ELSE events.first_start
            END,
            last_start = CASE
                WHEN events.last_start IS NULL THEN excluded.last_start
                WHEN excluded.last_start IS NULL THEN events.last_start
                WHEN excluded.last_start > events.last_start THEN excluded.last_start
                ELSE events.last_start
            END,
            n_performances = MAX(events.n_performances, excluded.n_performances),
            base_score = excluded.base_score,
            noise_flags = excluded.noise_flags,
            rule_decision = excluded.rule_decision,
            last_seen_at = excluded.last_seen_at,
            status = excluded.status
        """,
        tuple(fields.values()),
    )
    row = conn.execute(
        "SELECT event_id, tags FROM events WHERE dedupe_key=?", (ev["dedupe_key"],)
    ).fetchone()
    event_id = row["event_id"]

    # 💳 信用卡標記一定併入(不受 tags COALESCE 影響;已被 Claude 打 tag 的活動也要保留卡別)
    card_tags = [t for t in ev.get("tags", []) if t.startswith("💳")]
    if card_tags:
        existing = json.loads(row["tags"] or "[]")
        merged = existing + [t for t in card_tags if t not in existing]
        if merged != existing:
            conn.execute(
                "UPDATE events SET tags=? WHERE event_id=?",
                (json.dumps(merged, ensure_ascii=False), event_id),
            )

    for p in perfs:
        conn.execute(
            """INSERT INTO performances
               (event_id, perf_key, start_time, end_time, venue_name, venue_address,
                latitude, longitude, city, price_text, is_ticketed, availability_text)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(event_id, perf_key) DO UPDATE SET
                 start_time = excluded.start_time,
                 end_time = excluded.end_time,
                 venue_name = excluded.venue_name,
                 venue_address = excluded.venue_address,
                 latitude = excluded.latitude,
                 longitude = excluded.longitude,
                 city = excluded.city,
                 price_text = excluded.price_text,
                 is_ticketed = excluded.is_ticketed,
                 availability_text = excluded.availability_text""",
            (
                event_id, p.get("perf_key"), p.get("start_time"), p.get("end_time"),
                p.get("venue_name"), p.get("venue_address"), p.get("latitude"),
                p.get("longitude"), p.get("city"), p.get("price_text"),
                p.get("is_ticketed"), p.get("availability_text"),
            ),
        )
    conn.execute(
        """INSERT INTO event_sources
           (event_id, source_name, source_url, ticket_url, last_seen_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(event_id, source_name) DO UPDATE SET
             source_url = COALESCE(excluded.source_url, event_sources.source_url),
             ticket_url = COALESCE(excluded.ticket_url, event_sources.ticket_url),
             last_seen_at = excluded.last_seen_at""",
        (
            event_id,
            ev.get("source_name") or "unknown",
            ev.get("source_url"),
            ev.get("ticket_url"),
            ts,
        ),
    )
    conn.execute(
        """UPDATE events
           SET n_performances = (
                 SELECT COUNT(*) FROM performances WHERE event_id = ?
               ),
               first_start = COALESCE((
                 SELECT MIN(start_time) FROM performances WHERE event_id = ? AND start_time IS NOT NULL
               ), first_start),
               last_start = COALESCE((
                 SELECT MAX(start_time) FROM performances WHERE event_id = ? AND start_time IS NOT NULL
               ), last_start)
           WHERE event_id = ?""",
        (event_id, event_id, event_id, event_id),
    )
    return event_id
