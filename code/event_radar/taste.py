"""Deterministic, explainable taste analysis for public and Telegram ranking."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from .config import taste


def _text(ev: dict[str, Any]) -> tuple[str, str, str]:
    title = str(ev.get("title") or "")
    core_chunks = [
        title,
        str(ev.get("organizer") or ""),
        str(ev.get("category") or ""),
        str(ev.get("subcategory") or ""),
        str(ev.get("description_clean") or ""),
        " ".join(str(x) for x in (ev.get("tags") or []) if x),
    ]
    chunks = list(core_chunks)
    for perf in ev.get("performances") or []:
        chunks.extend(
            [str(perf.get("venue_name") or ""), str(perf.get("venue_address") or "")]
        )
    return (
        title.casefold(),
        " ".join(core_chunks).casefold(),
        " ".join(chunks).casefold(),
    )


def _matches(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.casefold() in text]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def analyze_event(ev: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Return bounded fit, lenses and a concise human-readable reason.

    A facet scores once regardless of keyword repetition. This deliberately avoids
    treating verbose promotional copy as stronger evidence of fit.
    """
    cfg = taste()
    today = today or date.today()
    title, core_text, text = _text(ev)
    score = 12

    lenses: list[dict[str, Any]] = []
    for key, definition in cfg.get("lenses", {}).items():
        hits = _matches(text, definition.get("keywords", []))
        if hits:
            lenses.append({"key": key, "label": definition["label"], "hits": hits[:4]})
    score += min(10, 6 + max(0, len(lenses) - 1) * 2) if lenses else 0

    facets: list[dict[str, Any]] = []
    for key, definition in cfg.get("facets", {}).items():
        keywords = definition.get("keywords", [])
        core_hits = _matches(core_text, keywords)
        hits = core_hits or _matches(text, keywords)
        if not hits:
            continue
        weight = int(definition.get("weight", 0))
        # A known venue is weak place evidence; the listing itself must make
        # the setting part of the experience to earn the full facet.
        if key == "place" and not core_hits:
            weight = min(weight, 5)
        title_hits = _matches(title, keywords)
        facets.append(
            {
                "key": key,
                "label": definition["label"],
                "weight": weight,
                "hits": hits[:4],
            }
        )
        score += weight + (2 if title_hits else 0)

    signatures = _matches(title, cfg.get("signature_phrases", []))
    if signatures:
        score += 26

    city = ev.get("city")
    if city in cfg.get("primary_cities", []):
        score += 8
    elif city in cfg.get("nearby_cities", []):
        score += 4
    elif city in cfg.get("destination_cities", []):
        score -= 1
    elif city:
        score -= 9

    start = _parse_date(ev.get("first_start"))
    if start:
        days = (start - today).days
        if 0 <= days <= 30:
            score += 4
        if start.weekday() >= 4:
            score += 4
    else:
        days = None

    performances = ev.get("performances") or []
    venue = next((p.get("venue_name") for p in performances if p.get("venue_name")), None)
    public_url = ev.get("ticket_url") or ev.get("source_url")
    if start and venue and public_url:
        score += 4
    if ev.get("image_url"):
        score += 2

    generic_hits = _matches(text, cfg.get("generic_only_keywords", []))
    if generic_hits and not facets and not signatures:
        score -= 12
    recurring_hits = _matches(text, cfg.get("recurring_course_keywords", []))
    if recurring_hits:
        score -= 14

    hard_negative = _matches(text, [
        "投資說明會", "被動收入", "財富自由", "直銷", "加盟說明", "ai賺錢",
        "流量變現", "免費說明會",
    ])
    soft_negative = _matches(text, ["親子", "兒童", "純線上", "線上課程", "招生中"])
    if soft_negative:
        score -= 24
    if hard_negative:
        score = 0

    score = max(0, min(100, round(score)))
    confidence = 30
    confidence += 20 if start else 0
    confidence += 15 if venue else 0
    confidence += 15 if public_url else 0
    confidence += 10 if ev.get("description_clean") else 0
    confidence += 10 if ev.get("image_url") else 0

    ranked_facets = sorted(facets, key=lambda item: item["weight"], reverse=True)
    reason = _reason(ranked_facets, lenses, city, cfg, signatures)
    if hard_negative or (days is not None and (days < -1 or days > 120)):
        decision = "drop"
    elif not (start and venue and public_url) or soft_negative or score < 34:
        decision = "demote"
    elif city and city not in (
        cfg.get("primary_cities", []) + cfg.get("nearby_cities", []) + cfg.get("destination_cities", [])
    ) and score < 70:
        decision = "demote"
    else:
        decision = "keep"

    return {
        "score": score,
        "confidence": min(100, confidence),
        "decision": decision,
        "lenses": lenses,
        "facets": ranked_facets,
        "reason": reason,
        "signature_matches": signatures,
        "negative_matches": hard_negative + soft_negative + recurring_hits,
        "revision": cfg.get("revision"),
    }


def _reason(
    facets: list[dict[str, Any]],
    lenses: list[dict[str, Any]],
    city: str | None,
    cfg: dict[str, Any],
    signatures: list[str],
) -> str:
    labels = [item["label"] for item in facets[:2]]
    if labels:
        lead = " × ".join(labels)
    elif lenses:
        lead = lenses[0]["label"]
    else:
        return "資訊完整，可先放進探索清單。"

    if city in cfg.get("destination_cities", []):
        tail = "，若內容夠強，值得安排一趟專程。"
    elif any(item["key"] in {"place", "wander"} for item in facets):
        tail = "，適合排成一段城市行程。"
    elif signatures:
        tail = "，和你近期主動收藏的方向直接重疊。"
    else:
        tail = "，不是只靠類別名稱命中。"
    return lead + tail


def model_score_is_fresh(scored_at: str | None, *, now: datetime | None = None) -> bool:
    if not scored_at:
        return False
    now = now or datetime.now().astimezone()
    try:
        scored = datetime.fromisoformat(scored_at)
    except ValueError:
        return False
    if scored.tzinfo is None:
        scored = scored.astimezone()
    return now - scored <= timedelta(days=int(taste().get("model_score_max_age_days", 21)))


def blended_score(ev: dict[str, Any], analysis: dict[str, Any] | None = None) -> tuple[float, str]:
    """Blend a fresh semantic score; expired scores are ignored, never global mode switches."""
    analysis = analysis or analyze_event(ev)
    model_score = ev.get("personal_match_score")
    if model_score is not None and model_score_is_fresh(ev.get("scored_at")):
        return round(analysis["score"] * 0.65 + float(model_score) * 0.35, 1), "blended"
    return float(analysis["score"]), "taste"


def normalized_image_url(value: str | None) -> str:
    url = (value or "").strip()
    # Historical iCulture rows sometimes concatenated the host twice.
    url = re.sub(r"^(https://cloud\.culture\.tw)+", "https://cloud.culture.tw", url)
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(("https://", "http://")) else ""
