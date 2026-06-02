"""信用卡 presale 偵測。售票頁常以「【Mastercard專區】」「玉山卡友專區」標出卡別合作。
我們把這些(原本當票種變體)反過來當卡別訊號,標在活動上,方便篩自己有的卡。"""
from __future__ import annotations

from .config import profile

# 卡別 canonical -> 偵測字(小寫比對)。國泰 CUBE 卡本身是 Mastercard。
CARD_PATTERNS: dict[str, tuple[str, ...]] = {
    "Mastercard": ("mastercard", "萬事達"),
    "Visa": ("visa",),
    "JCB": ("jcb",),
    "國泰CUBE": ("cube", "國泰世華", "koko"),
    "中信": ("中國信託", "中信", "ctbc"),
    "玉山": ("玉山",),
    "台新": ("台新",),
    "富邦": ("富邦",),
    "聯邦": ("聯邦",),
    "永豐": ("永豐",),
    "星展": ("星展", "dbs"),
    "匯豐": ("匯豐", "滙豐", "hsbc"),
    "新光": ("新光",),
}


def cards_in(text: str | None) -> list[str]:
    """回傳 text 中出現的卡別 canonical 名(去重、保序)。"""
    if not text:
        return []
    low = text.lower()
    out = []
    for card, kws in CARD_PATTERNS.items():
        if any(k.lower() in low for k in kws):
            out.append(card)
    return out


def my_cards() -> list[str]:
    """使用者持有的卡(profile.credit_cards.mine)。預設 CUBE(=Mastercard)+ 中信。"""
    cfg = profile().get("credit_cards", {}) or {}
    return cfg.get("mine", ["國泰CUBE", "中信", "Mastercard"])
