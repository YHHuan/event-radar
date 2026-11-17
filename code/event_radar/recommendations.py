"""Private report selection over the same verified sessions as the public site."""
import re
from datetime import date, datetime, timedelta

from . import booking, db, site


def hidden_keys():
    """Feedback stays local; do not put personal feedback in public events.json."""
    with db.connect() as conn:
        rows = conn.execute("""SELECT e.event_id,e.dedupe_key,e.source_url,e.ticket_url
            FROM events e JOIN feedback f ON f.event_id=e.event_id
            WHERE f.action IN ('not_interested','block_similar')""").fetchall()
    return {str(value).rstrip("/") for row in rows for value in
            (f"event-{row['event_id']}", row['dedupe_key'], row['source_url'], row['ticket_url']) if value}


def diverse(rows, limit):
    out, seen, organizers, lenses = [], set(), set(), set()
    for new_lens in (True, False):
        for row in rows:
            lens = next((x["key"] for x in row.get("lenses", [])), "")
            org = row.get("organizer") or row["title"]
            if len(out) >= limit:
                return out
            if row["id"] in seen or org in organizers or (new_lens and lens in lenses):
                continue
            out.append(row)
            seen.add(row["id"])
            organizers.add(org)
            lenses.add(lens)
    return out


def select(events, *, today, near_days=21, near_n=4, advance_n=3, hidden=(), now=None, interests=()):
    end = (today + timedelta(days=near_days)).isoformat()
    hidden = set(hidden)
    upcoming, advance = [], []
    for event in events:
        if event["id"] in hidden or event["url"].rstrip("/") in hidden:
            continue
        perfs = [p for p in event.get("performances", [])
                 if (p.get("end") or p["start"])[:10] >= today.isoformat()]
        if not perfs:
            continue
        text = " ".join(str(event.get(k) or "") for k in ("title", "source", "organizer", "reason"))
        bonus = 8 if any(word.casefold() in text.casefold() for word in interests if isinstance(word, str) and word) else 0
        row = {**event, "score": min(100, event["score"] + bonus), "preferenceMatch": bool(bonus),
               "performances": sorted(perfs, key=lambda p: p["start"])}
        if any(p["start"][:10] <= end for p in perfs):
            upcoming.append(row)
        info = event.get("booking") or {}
        if info.get("status") in {"closed", "sold_out"} or re.search(r"已截止|已額滿|售罄|售完|報名結束", event.get("registrationNote", "")):
            continue
        reminder, deadline = booking.action(info, today, now=now)
        # Explicit registration closure rules out a purchase recommendation.
        if info and not reminder:
            continue
        urgent = bool(deadline and today.isoformat() <= deadline[:10] <= end)
        far = min(p["start"][:10] for p in perfs) > end
        if event["score"] >= 60 and (far or urgent):
            advance.append({**row, "bookingReminder": reminder or "日期已公告；購票／報名資訊請查原頁",
                            "bookingDeadline": deadline or "", "bookingUrgent": urgent})
    advance.sort(key=lambda r: (not r["bookingUrgent"], r["bookingDeadline"] or "9999",
                               not bool(r.get("booking")), not r["preferenceMatch"], -r["score"], r["firstStart"]))
    # A new lens must not push an imminent deadline behind a generic far event.
    urgent = diverse([r for r in advance if r["bookingUrgent"]], max(0, advance_n))
    orgs = {r.get("organizer") or r["title"] for r in urgent}
    later = [r for r in advance if not r["bookingUrgent"] and (r.get("organizer") or r["title"]) not in orgs]
    advance = urgent + diverse(later, max(0, advance_n - len(urgent)))
    ids = {e["id"] for e in advance}
    def order(row):
        next_day = min(max(p["start"][:10], today.isoformat()) for p in row["performances"])
        # Equal-fit ongoing exhibitions favor a newer opening, not last year's collection.
        opened = date.fromisoformat(row["firstStart"][:10]).toordinal()
        return not row["preferenceMatch"], -row["score"], next_day, -opened
    upcoming = sorted((e for e in upcoming if e["id"] not in ids), key=order)
    return {"near": diverse(upcoming, max(0, near_n)), "advance": advance}


def plan(*, today=None, near_days=21, near_n=4, advance_n=3, interests=()):
    today = today or date.today()
    events = site.snapshot(today=today, horizon_days=730, max_events=5000)["events"]
    return select(events, today=today, near_days=near_days, near_n=near_n, advance_n=advance_n,
                  hidden=hidden_keys(), now=datetime.now() if today == date.today() else None, interests=interests)
