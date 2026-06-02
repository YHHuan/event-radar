"""第一段:硬規則。base_score + noise_flags + keep/demote/drop。
第二段(Claude 語意打分)在 scoring.py。"""
from __future__ import annotations

from datetime import datetime, timedelta

from .config import profile


def _hits(text: str, keywords: list[str]) -> list[str]:
    low = text.lower()
    return [k for k in keywords if k.lower() in low]


def score_event(ev: dict) -> dict:
    """就地補上 base_score / noise_flags / rule_decision / tags;回傳同 dict。"""
    p = profile()
    w = p.get("weights", {})
    tg = p.get("toggles", {})
    text = " ".join(
        str(ev.get(k, "")) for k in ("title", "organizer", "description_clean")
    )
    text += " " + " ".join(
        f"{pf.get('venue_name','')} {pf.get('venue_address','')}"
        for pf in ev.get("performances", [])
    )

    score = 0
    tags: list[str] = []
    flags: list[str] = []

    strong = _hits(text, p.get("strong_positive_keywords", []))
    medium = _hits(text, p.get("medium_positive_keywords", []))
    score += len(strong) * w.get("strong_keyword", 12)
    score += len(medium) * w.get("medium_keyword", 5)
    tags += strong + medium

    # ── 垃圾訊號:硬(詐騙/MLM,protect 救不了) vs 軟(親子/線上,可被 protect 擋) ──
    protect = _hits(text, p.get("protect_keywords", []))
    is_protected = bool(protect)
    hard = _hits(text, p.get("hard_negative_keywords", []))
    soft = [n for n in _hits(text, p.get("negative_keywords", []))
            if n not in p.get("hard_negative_keywords", [])]
    if tg.get("include_kids"):
        soft = [n for n in soft if n not in ("親子", "兒童")]
    if tg.get("include_online"):
        soft = [n for n in soft if n not in ("純線上", "線上課程")]

    if hard:
        score += w.get("noise_penalty", -40)
        flags += [f"hard:{h}" for h in hard]
    if soft and not is_protected:
        score += w.get("noise_penalty", -40)
        flags += [f"soft:{s}" for s in soft]

    # ── 時窗 ──
    horizon = p.get("horizon_days", 90)
    first = ev.get("first_start") or _earliest(ev)
    in_window = False
    if first:
        try:
            dt = datetime.fromisoformat(first)
            today = datetime.now()
            in_window = today - timedelta(days=1) <= dt <= today + timedelta(days=horizon)
        except ValueError:
            pass
    if not in_window:
        flags.append("out_of_window")

    # ── 地區:目標 = primary+secondary。偵測到他縣市 → out;偵測不到(None) → unknown(不drop) ──
    regions = profile().get("regions", {})
    target = set(["台北市", "新北市", "基隆市", "桃園市"])  # 標準名
    city = ev.get("city")
    in_region = city in target
    other_city = bool(city) and city not in target
    if other_city:
        flags.append("out_of_region")

    # ── 必要欄位 ──
    has_when = bool(first)
    has_where = bool(city) or any(pf.get("venue_name") for pf in ev.get("performances", []))
    has_link = bool(ev.get("ticket_url") or ev.get("source_url"))

    # ── 加分:實用性 / 週末 / 參與感 ──
    if in_window and (in_region or city is None):
        score += w.get("utility", 6)
    if tg.get("weekend_bonus") and first:
        try:
            if datetime.fromisoformat(first).weekday() >= 4:
                score += 3
        except ValueError:
            pass
    part_kw = ["真人圖書館", "實境", "沉浸", "工作坊", "料理", "走讀", "共食", "open mic", "即興"]
    if _hits(text, part_kw):
        score += w.get("participatory_live", 8)
        tags.append("participatory")

    # ── 信用卡 presale:活動帶「💳<卡>」標記(collector 設),命中我的卡 → 加權(優先) ──
    from .cards import my_cards
    mine = set(my_cards())
    ev_cards = {t[1:] for t in ev.get("tags", []) if t.startswith("💳")}
    if ev_cards & mine:
        score += w.get("my_card_bonus", 8)
        tags.append("my_card")

    # ── 決策 ──
    # 他縣市改 demote(不 drop):Salmon 會為夠好的演出跨縣市(已購票《COMPANY》臺中)。
    if not in_window or hard:
        decision = "drop"                      # 出時窗 / 硬垃圾 → 直接丟
    elif other_city or (soft and not is_protected) or not (has_when and has_where and has_link):
        decision = "demote"                    # 他縣市 / 軟垃圾(未保護) / 缺欄位 → 降權(Claude 可救回)
    else:
        decision = "keep"

    ev["base_score"] = max(0, min(100, score))
    ev["noise_flags"] = flags
    ev["rule_decision"] = decision
    ev["tags"] = sorted(set(tags + ev.get("tags", [])))
    return ev


def _earliest(ev: dict) -> str | None:
    starts = sorted(
        p["start_time"] for p in ev.get("performances", []) if p.get("start_time")
    )
    return starts[0] if starts else None
