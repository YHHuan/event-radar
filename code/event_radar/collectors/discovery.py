"""Bounded public discovery feeds. Unknown dates never become calendar entries."""
from __future__ import annotations

import hashlib
import io
import json
import re
import ssl
import zipfile
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

from ..config import load_yaml
from ..normalize import clean_text, detect_city
from ..source_network import record_result, cached_events
from .kktix import _entry_to_event

FOLK = re.compile(r"民俗|遶境|繞境|進香|蜂炮|迎王|王船|夜祭|太祖祭|義民|萬年季|跑水節|偶戲節|收冬祭|豐年祭|豐年節|平安鹽祭|迎城隍|迎媽祖|搶孤")
MUSIC = re.compile(r"音樂祭|音樂節|大港開唱|浮現祭|浪人祭|火球祭|打狗祭|搖滾台中|PASIWALI", re.I)
RACE = re.compile(r"CRUFU|夸父|接力|跨夜|環島|環台|環臺|橫越|百[Kk]|超馬|超級馬拉松|越野|IRONMAN|CHALLENGE TAIWAN|極限超級鐵人", re.I)
NOISE = re.compile(r"取消|延期|暫定|待定|未定|住宿|接駁|周邊|商品|研習|裁判|志工|終身學習|熱身賽|小鐵人|親子|兒童|訓練班")


def lens_for(title: str) -> str | None:
    if NOISE.search(title):
        return None
    for lens, pattern in (("music_festival", MUSIC), ("folk", FOLK), ("endurance", RACE)):
        if pattern.search(title):
            return lens
    return None


def safe_url(value: str) -> str:
    parsed = urlparse(value or "")
    return value if parsed.scheme in {"https", "http"} and parsed.netloc else ""


def make_event(source: dict, identifier: str, title: str, start: str, end: str,
               venue: str, city: str, url: str, *, description: str = "", note: str = "",
               image: str = "", lens: str | None = None) -> dict:
    lens = lens or lens_for(title)
    reason = {"folk": "地方祭典與傳統文化，適合走進現場看儀式、表演與街區。",
              "music_festival": "音樂祭與多組演出，適合為喜歡的音樂安排一趟。",
              "endurance": "接力、越野或長距離挑戰；先確認組別、資格與報名期限。"}[lens]
    return {
        "dedupe_key": "discovery-" + source["id"] + "-" + hashlib.sha256(identifier.encode()).hexdigest()[:16],
        "title": title, "source_name": source["name"], "source_url": url, "ticket_url": url,
        "city": city, "organizer": source.get("organizer", ""), "tags": [],
        "description_clean": description[:500], "first_start": start, "image_url": safe_url(image),
        "_selection": {"lens": lens, "selection_reason": reason, "automatic": True,
                       "registration_note": note},
        "performances": [{"start_time": start, "end_time": end or start,
                          "venue_name": venue, "venue_address": venue, "city": city,
                          "availability_text": note}],
    }


def relevant(start: str, end: str, today: date) -> bool:
    try:
        first, last = date.fromisoformat(start[:10]), date.fromisoformat((end or start)[:10])
        return first <= last and last >= today and first <= today + timedelta(days=365)
    except (TypeError, ValueError):
        return False


def parse_tourism(data: dict, source: dict, today: date) -> list[dict]:
    entries = data.get("Events") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("tourism Events schema missing or empty")
    out = []
    for row in entries:
        title = clean_text(row.get("EventName"))
        lens = lens_for(title)
        if not lens or row.get("EventStatus") != "EventScheduled":
            continue
        start, end = row.get("StartDateTime", ""), row.get("EndDateTime", "")
        # Some publishers incorrectly encode all-day midnight as 16:00+08:00.
        # Do not guess an eight-hour correction. Review those rows separately.
        if not start or ("T16:00:00+08:00" in start and "T15:59:59+08:00" in (end or "")):
            continue
        try:
            first, last = datetime.fromisoformat(start), datetime.fromisoformat(end or start)
        except ValueError:
            continue
        if first.hour == first.minute == first.second == 0:
            start, end = first.date().isoformat(), last.date().isoformat()
        else:
            start, end = first.isoformat(), last.isoformat()
        if not relevant(start, end, today):
            continue
        # Seasonal series are not daily performances; require a reviewed schedule.
        if (last.date() - first.date()).days > 31:
            continue
        address = row.get("PostalAddress") or {}
        city = (address.get("City") or "").replace("臺", "台")
        venue = "".join(address.get(k) or "" for k in ("City", "Town", "StreetAddress"))
        identifier = row.get("EventID") or ""
        if not identifier or not city or not venue:
            continue
        url = safe_url(row.get("WebsiteURL")) or "https://media.taiwan.net.tw/zh-tw/portal/travel/details/" + identifier.lower()
        out.append(make_event(source, identifier, title, start, end, venue, city, url,
                              description=clean_text(row.get("Description")),
                              note="系列活動各場次與參加方式請看主辦公告。" if start[:10] != end[:10] else "",
                              image=next((x.get("URL", "") for x in row.get("Images", []) if x.get("URL")), ""), lens=lens))
    return out


def parse_focusline(data: list, source: dict, today: date) -> list[dict]:
    if not isinstance(data, list) or not data or not all(isinstance(x, dict) and "actDate" in x for x in data):
        raise ValueError("Focusline activity schema missing or empty")
    out = []
    for row in data:
        title = clean_text(row.get("actName"))
        if row.get("status") != 1 or lens_for(title) != "endurance":
            continue
        start = (row.get("actDate") or "")[:10]  # Listing gives a race day, not a start time.
        if not relevant(start, start, today):
            continue
        try:
            geo = json.loads(row.get("geo") or "{}")
        except (ValueError, TypeError):
            continue
        if geo.get("type") != "TW":
            continue
        city = next(iter(geo.get("cities") or []), "").replace("臺", "台")
        venue = clean_text(row.get("location"))
        code = row.get("actCode", "")
        if not city or not venue or not re.fullmatch(r"[A-Za-z0-9]+", code):
            continue
        registration = row.get("register") or {}
        begin, deadline = (registration.get("start") or "")[:10], (registration.get("end") or "")[:10]
        note = "報名狀態與組別資格請看主辦公告。"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline):
            note = f"報名已截止（{deadline}）" if deadline < today.isoformat() else f"報名至 {deadline}，名額以主辦公告為準。"
            if begin and begin > today.isoformat():
                note = f"預計 {begin} 開放報名；截止 {deadline}。"
        out.append(make_event(source, code, title, start, start, venue, city,
                              f"https://www.focusline.com.tw/{code}", note=note))
    return out


class CalendarTable(HTMLParser):
    """Keep visible cell text and links; no scripts, embedded images or nested tables."""
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.parts, self.links = [], None, None, []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        elif tag in {"td", "th"} and self.cells is not None:
            self.parts, self.links = [], []
        elif self.parts is not None:
            if tag in {"br", "p", "div"}:
                self.parts.append(" ")
            if tag == "a":
                self.links.append(dict(attrs).get("href", ""))

    def handle_data(self, data):
        if self.parts is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.parts is not None:
            self.cells.append((clean_text("".join(self.parts)), self.links))
            self.parts = None
        elif tag == "tr" and self.cells is not None:
            self.rows.append(self.cells)
            self.cells = None


def parse_ctau(html: str, source: dict, today: date) -> list[dict]:
    parser = CalendarTable()
    parser.feed(html)
    if not any(len(row) == 4 and "日期" in row[1][0] for row in parser.rows):
        raise ValueError("CTAU calendar table missing")
    out, seen = [], set()
    for row in parser.rows:
        if len(row) != 4:
            continue
        title, dates, venue, distance = [cell[0] for cell in row]
        if lens_for(title) != "endurance" or re.search(r"暫定|未定|取消|延期|組隊參加", dates):
            continue
        year = re.search(r"(?<!\d)(20\d{2})(?!\d)", title)
        day = re.match(r"\s*(?:20\d{2}\s+)?(\d{1,2})/(\d{1,2})(?:\s*[-~～]\s*(?:(\d{1,2})/)?(\d{1,2}))?", dates)
        if not year or not day:
            continue
        try:
            first = date(int(year[1]), int(day[1]), int(day[2]))
            last = date(first.year, int(day[3] or day[1]), int(day[4] or day[2]))
        except ValueError:
            continue
        start, end = first.isoformat(), last.isoformat()
        if not relevant(start, end, today):
            continue
        # Only domestic races with an explicit place, not overseas team selection.
        city = detect_city(venue, title)
        if not city:
            city = "新北市" if "新莊" in venue or "新店國小" in venue else "台北市" if "東吳大學" in venue else ""
        if not city:
            continue
        if "CTAU超馬系列賽" in title:
            repeated_year = list(re.finditer(year[1], title))
            if len(repeated_year) > 1:
                title = title[repeated_year[-1].start():]
        title = title.split("主辦單位")[0].strip()
        # The association sometimes reuses old article URLs. Link to the current
        # calendar which actually contains this edition's dates and registration.
        identity = title + start
        if identity in seen:
            continue
        seen.add(identity)
        deadline = re.search(r"(\d{1,2})/(\d{1,2})\s*前", dates)
        note = "組別、起跑時間及參賽資格請查主辦規程。"
        if deadline:
            try:
                cutoff = date(first.year - (int(deadline[1]) > first.month), int(deadline[1]), int(deadline[2]))
                note = (f"報名已截止（{cutoff}）。" if cutoff < today else f"報名至 {cutoff}，額滿可能提早截止。") + note
            except ValueError:
                pass
        # Keep distance/relay detail visible without treating different groups'
        # start times as a single performance time.
        description = distance + "；" + venue
        event = make_event(source, identity, title, start, end, venue, city, source["url"],
                           description=description, note=note + " " + distance, lens="endurance")
        event["_selection"]["selection_reason"] = distance + "；組別與路線詳見主辦行事曆。"
        event["_selection"]["shared_url"] = True
        out.append(event)
    return out


def parse_festival_feed(data: dict, source: dict, today: date) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("entry"), list):
        raise ValueError("KKTIX entry schema missing")
    out = []
    for row in data["entry"]:
        title = clean_text(row.get("title"))
        if lens_for(title) != "music_festival":
            continue
        event = _entry_to_event(row, source["slug"])
        if not event:
            continue
        # The explicitly labeled event time is authoritative, not publication or
        # ticket-sales metadata. Preserve multi-day/overnight ranges.
        time_line = (row.get("content") or "").split("\n")[0]
        if not re.match(r"\s*時間[:：]", time_line):
            continue
        times = re.findall(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", time_line)
        if not times:
            continue
        start = datetime.strptime(times[0], "%Y/%m/%d %H:%M").isoformat()
        end = datetime.strptime(times[-1], "%Y/%m/%d %H:%M").isoformat() if len(times) > 1 else ""
        if not end:
            short_end = re.search(r"[~～]\s*(\d{2}:\d{2})(?:\s|$)", (row.get("content") or "").split("\n")[0])
            if short_end:
                finish = datetime.fromisoformat(start[:10] + "T" + short_end[1])
                if finish < datetime.fromisoformat(start):
                    finish += timedelta(days=1)
                end = finish.isoformat()
        if not relevant(start, end, today) or not event.get("city"):
            continue
        perf = event["performances"][0]
        out.append(make_event(source, row["url"], event["title"], start, end,
                              perf["venue_name"], event["city"], event["source_url"],
                              description=event["description_clean"], lens="music_festival"))
    return out


class TourismTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        # Python 3.13+ rejects the government's legacy CA extensions. Retain CA
        # chain and hostname verification; compatibility applies to this host only.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def fetch(source: dict, today: date) -> list[dict]:
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0 (event-radar; public event discovery)"
        session.mount("https://media.taiwan.net.tw/", TourismTLSAdapter())
        with session.get(source["endpoint"], timeout=(10, 25), stream=True) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 8_000_000:
                    raise ValueError("source exceeds download limit")
                chunks.append(chunk)
            content = b"".join(chunks)
    kind = source["kind"]
    if kind == "tourism":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            info = archive.getinfo("EventList.json")
            if info.file_size > 12_000_000:
                raise ValueError("source exceeds uncompressed limit")
            data = json.loads(archive.read(info).decode("utf-8-sig"))
        return parse_tourism(data, source, today)
    if kind == "ctau":
        return parse_ctau(content.decode("utf-8-sig"), source, today)
    data = json.loads(content.decode("utf-8-sig"))
    return {"focusline": parse_focusline, "kktix": parse_festival_feed}[kind](data, source, today)


def collect() -> list[dict]:
    today = date.today()
    for source in load_yaml("discovery.yaml").get("sources", []):
        if source.get("mode") != "automatic":
            continue
        try:
            events = fetch(source, today)
            record_result(source["id"], events)
            print(f"  [discovery] {source['id']}: {len(events)} upcoming selections")
        except Exception as exc:  # One unavailable publisher must not erase others.
            record_result(source["id"], None)
            print(f"  [discovery] {source['id']} FAILED: {type(exc).__name__}: {exc}")
    return cached_events(today=today)
