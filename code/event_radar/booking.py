"""Booking evidence is separate from performance dates and live inventory."""
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from urllib.parse import unquote
from zoneinfo import ZoneInfo
from .config import load_yaml


def evidence(event):
    return event.get("_booking") or (event.get("_selection") or {}).get("booking") or {}


def validate(value):
    if not value:
        return
    if value.get("status", "unknown") not in {"announced", "unknown", "sold_out", "closed"}:
        raise ValueError("unknown booking status")
    if urlparse(value.get("url", "")).scheme != "https":
        raise ValueError("booking evidence needs an HTTPS source")
    date.fromisoformat(value["checked_on"])
    for key in ("sale_start", "early_bird_end", "registration_end"):
        if value.get(key):
            datetime.fromisoformat(value[key])


def public(event):
    value = dict(evidence(event))
    url = unquote(event.get("source_url", "")).rstrip("/")
    for review in load_yaml("booking_reviews.yaml").get("reviews", []):
        if unquote(review["event_url"]).rstrip("/") == url:
            # A fresh event listing does not refresh a manually checked deadline.
            value.update({k: v for k, v in review.items() if k != "event_url"})
    if not value:
        return {}
    validate(value)
    return {key: value[key] for key in ("status", "url", "checked_on", "sale_start",
                                       "early_bird_end", "registration_end", "note") if key in value}


def horizon(event, default=120):
    # Only a dated announcement with booking provenance can reach two years.
    return 730 if evidence(event) else 365 if event.get("_selection") else default


def action(value, today, *, now=None):
    """Return a truthful reminder, never treating a link as proof of spare seats."""
    if not value or value.get("status") in {"closed", "sold_out"}:
        return "", None
    try:
        checked = date.fromisoformat(value["checked_on"])
    except (ValueError, KeyError, TypeError):
        return "", None
    fresh = today - timedelta(days=7) <= checked <= today
    def local(stamp):
        result = datetime.fromisoformat(stamp)
        return result.astimezone(ZoneInfo("Asia/Taipei")).replace(tzinfo=None) if result.tzinfo else result
    if now and now.tzinfo:
        now = now.astimezone(ZoneInfo("Asia/Taipei")).replace(tzinfo=None)
    finish = value.get("registration_end")
    if finish and (local(finish).date() < today or (now and len(finish) > 10 and local(finish) < now)):
        return "", None
    deadlines = []
    for key, label in (("early_bird_end", "早鳥截止"), ("registration_end", "報名截止")):
        if value.get(key):
            dt = local(value[key])
            if dt.date() >= today and (now is None or len(value[key]) == 10 or dt >= now):
                deadlines.append((value[key], label))
    if not fresh:
        return "購票資訊需重新確認（上次核對 " + checked.isoformat() + "）", None
    if deadlines:
        stamp, label = min(deadlines)
        return label + " " + stamp.replace("T", " "), stamp
    start = value.get("sale_start")
    if start and (local(start).date() > today or (now and len(start) > 10 and local(start) > now)):
        return "開賣 " + start.replace("T", " "), start
    if start:
        return "已到公告開賣日；票況請查售票頁", None
    return value.get("note") or "展期已公告；開賣與預約資訊請查官方頁", None
