"""Public music calendars, bounded by requests and explicit performance dates.

FANSI uses the same anonymous event-list query as its public homepage, then
public EventSeries metadata (never ticket inventory or resale/customer data).
StreetVoice's naive JSON-LD times are UTC-like; its visible date and calendar
link are authoritative local times. iNDIEVOX pagination uses its load-more link.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

from ..normalize import clean_text, detect_city

TAIPEI = ZoneInfo("Asia/Taipei")
KINDS = {"indievox", "fansi", "streetvoice"}
DATE = re.compile(r"(20\d{2})[/.-](\d{1,2})[/.-](\d{1,2})")
CLOCK = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)")
CANCELLED = re.compile(r"取消|延期|暫停|待定|cancelled|canceled|postponed", re.I)
NON_MUSIC = re.compile(r"投資心法|選股|財經教授|理財講座|測試活動|教學活動|摔角")
FESTIVAL = re.compile(r"音樂祭|音樂節|大港開唱|浮現祭|火球祭|浪人祭|打狗祭", re.I)


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.walk(tag)

    def text(self):
        if self.tag in {"script", "style"}:
            return ""
        text = "".join(c.text() if isinstance(c, Node) else c for c in self.children)
        return text + ("\n" if self.tag in {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"} else "")

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def meta(root, name):
    return next((n.attrs.get("content", "") for n in root.walk("meta")
                 if n.attrs.get("property", n.attrs.get("name")) == name), "")


def text_lines(node):
    return [clean_text(x) for x in node.text().splitlines() if clean_text(x)]


def iso(value):
    """Preserve date-only precision; convert explicit zones to Taiwan time."""
    if not isinstance(value, str) or not value:
        return ""
    if len(value) == 10:
        return date.fromisoformat(value).isoformat()
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo:
        dt = dt.astimezone(TAIPEI)
    return dt.replace(tzinfo=None).isoformat(timespec="seconds")


def dates(text):
    return [date(*map(int, m.groups())).isoformat() for m in DATE.finditer(text)]


def show_clock(text):
    # Admission and ticket-sales clocks must never become a show start.
    explicit = (re.search(r"(?:開演|演出|[Ss]tart)\s*(?:時間)?\s*[:：/|｜]?\s*([01]?\d|2[0-3])[:：]([0-5]\d)", text)
                or re.search(r"([01]?\d|2[0-3])[:：]([0-5]\d)\s*(?:開演|演出)", text))
    match = explicit or (None if re.search(r"入場|開場|售票|開賣|[Dd]oor", text) else CLOCK.search(text))
    return f"{int(match[1]):02d}:{match[2]}:00" if match else ""


def public_url(value, base=""):
    url = urljoin(base, value or "")
    parsed = urlparse(url)
    return url if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username else ""


def upcoming(start, end, today, horizon=120):
    return bool(start and (end or start) >= start and (end or start)[:10] >= today.isoformat()
                and start[:10] <= (today + timedelta(days=horizon)).isoformat())


def performance(start, end, venue, address="", city="", price=""):
    return {"start_time": start, "end_time": end or None, "venue_name": clean_text(venue),
            "venue_address": clean_text(address), "city": city or detect_city(address, venue),
            "price_text": price or None}


def event(source, identifier, title, perfs, today, *, url="", ticket="", image="", organizer="", description="", note=""):
    if not title or CANCELLED.search(title) or NON_MUSIC.search(title):
        return None
    perfs = [p for p in perfs if p.get("city") and p.get("venue_name")
             and upcoming(p["start_time"], p.get("end_time"), today, source.get("horizon_days", 120))]
    perfs = sorted({(p["start_time"], p.get("end_time"), p["venue_name"]): p for p in perfs}.values(),
                   key=lambda p: (p["start_time"], p["venue_name"]))
    if not perfs:
        return None
    return {"dedupe_key": "discovery-" + source["id"] + "-" + hashlib.sha256(str(identifier).encode()).hexdigest()[:16],
            "source_name": source["name"], "source_url": url, "ticket_url": ticket or url,
            "title": title, "category": "獨立音樂", "organizer": organizer, "image_url": public_url(image),
            "description_clean": clean_text(description)[:500], "tags": ["獨立音樂", "現場演出"],
            "city": perfs[0]["city"], "first_start": perfs[0]["start_time"], "performances": perfs,
            "_selection": {"lens": "music_festival" if FESTIVAL.search(title) else "live_music",
                           "automatic": True, "catalog": True, "registration_note": note}}


class Client:
    """One request per second, bounded responses; no login or browser state."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0 (event-radar; personal public music calendar)"
        self.last = 0.0

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def request(self, method, url, **kwargs):
        time.sleep(max(0, 1.05 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        with self.session.request(method, url, timeout=(10, 25), stream=True, **kwargs) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 4_000_000:
                    raise ValueError("music source exceeds download limit")
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8-sig")


def indievox_listing(html):
    root = Document(html).root
    items = []
    for anchor in root.walk("a"):
        url = public_url(anchor.attrs.get("href"), "https://www.indievox.com")
        if not re.fullmatch(r"https://www\.indievox\.com/activity/detail/[a-zA-Z0-9_]+", url):
            continue
        image = next(anchor.walk("img"), None)
        date_node = next((n for n in anchor.walk() if n.has_class("date")), None)
        if image is None or date_node is None:
            continue
        days = dates(date_node.text())
        if not days:
            raise ValueError("iNDIEVOX listing lost event dates")
        items.append({"url": url, "title": image.attrs.get("alt", ""), "dates": days})
    more = next((n for n in root.walk() if n.has_class("page-show-more")), None)
    next_url = ""
    if more:
        action = more.attrs.get("data-action-url", "")
        if action != "https://www.indievox.com/activity/get-more-game-list":
            raise ValueError("iNDIEVOX pagination schema changed")
        next_url = action + "?" + more.attrs.get("data-parameter", "")
    if not items and (more or not any(x in root.text() for x in ("查無", "沒有節目", "無節目", "無符合"))):
        raise ValueError("iNDIEVOX listing schema missing")
    return list({item["url"]: item for item in items}.values()), next_url


def indievox_detail(html, item, source, today):
    root = Document(html).root
    intro = next((n for n in root.walk() if n.attrs.get("id") == "intro"), None)
    if intro is None:
        raise ValueError("iNDIEVOX intro missing")
    lines = text_lines(intro)
    title = meta(root, "og:title").removesuffix(" | iNDIEVOX") or item["title"]
    venue_line = next((x for x in lines if re.match(r"^(?:演出|活動)?地[點址]\s*[:：]", x)), "")
    venue = re.sub(r"^(?:演出|活動)?地[點址]\s*[:：]\s*", "", venue_line)
    # An address often follows the venue in a separate paragraph.
    following = lines[lines.index(venue_line) + 1] if venue_line and lines.index(venue_line) + 1 < len(lines) else ""
    address = venue + (" " + following if detect_city(following) else "")
    city = detect_city(address) or detect_city(title)
    price = next((re.sub(r"^票價\s*[:：]\s*", "", x)[:90] for x in lines if x.startswith("票價")), "")
    perfs = []
    time_lines = [x for x in lines if re.match(r"^(?:演出日期及時間|演出日期|演出時間|活動時間|活動日期|日期|時間)\s*[:：]", x)]
    for line in time_lines:
        ds = dates(line)
        if not ds:
            continue
        # Only an explicitly daily schedule authorizes expanding a short span.
        daily = len(ds) == 2 and re.search(r"每日|每天", line)
        if daily:
            first, last = map(date.fromisoformat, ds)
            if 0 <= (last - first).days <= 14:
                ds = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
        elif len(ds) > 1 and re.search(r"[-~～至]", DATE.sub("", line)):
            # A range alone does not establish discrete shows. Retain listed
            # endpoints below, with a schedule warning, never invent daily dates.
            continue
        positions = list(DATE.finditer(line))
        # Tour descriptions can contain several cities. Pair a date with the
        # venue in its own block instead of borrowing the first city's venue.
        line_index = lines.index(line)
        following_block = []
        for candidate in lines[line_index + 1:]:
            if candidate in time_lines:
                break
            following_block.append(candidate)
        local_venue = next((x for x in following_block if re.match(r"^(?:演出|活動)?地[點址]\s*[:：]", x)), "")
        perf_venue, perf_address, perf_city = venue, address, city
        if local_venue:
            perf_venue = re.sub(r"^(?:演出|活動)?地[點址]\s*[:：]\s*", "", local_venue)
            following_index = following_block.index(local_venue) + 1
            local_address = following_block[following_index] if following_index < len(following_block) else ""
            perf_address = perf_venue + (" " + local_address if detect_city(local_address) else "")
            perf_city = detect_city(perf_address) or detect_city(title)
        for i, day in enumerate(ds):
            segment = (line[positions[-1].end():] if daily else
                       line[positions[i].end():positions[i + 1].start() if i + 1 < len(positions) else len(line)])
            clock_text = show_clock(segment)
            if day in item["dates"] or (len(item["dates"]) > 1 and item["dates"][0] <= day <= item["dates"][-1]):
                perfs.append(performance(day + ("T" + clock_text if clock_text else ""), "", perf_venue, perf_address, perf_city, price))
    note = ""
    if not perfs:
        perfs = [performance(day, "", venue, address, city, price) for day in item["dates"]]
        note = "來源僅列日期；演出時間請確認原頁。"
        if len(item["dates"]) > 1:
            note = "來源僅列起訖日期；中間場次與演出時間請確認原頁。"
    elif any(len(p["start_time"]) == 10 for p in perfs):
        note = "部分場次僅提供日期；演出時間請確認原頁。"
    return event(source, item["url"], title, perfs, today, url=item["url"], image=meta(root, "og:image"),
                 description="\n".join(lines[:6]), note=note)


def schema_objects(html):
    root = Document(html).root
    chunks = []
    for node in root.walk("script"):
        raw = "".join(x for x in node.children if isinstance(x, str))
        if node.attrs.get("type") == "application/ld+json":
            yield json.loads(raw)
        # Next.js streams JSON-LD as a string in public RSC chunks. Decode JSON
        # strings only; never evaluate publisher JavaScript.
        for match in re.finditer(r"self\.__next_f\.push\((\[.*?\])\)\s*;?", raw, re.S):
            chunk = json.loads(match[1])
            if len(chunk) < 2 or not isinstance(chunk[1], str):
                continue
            chunks.append(chunk[1])
    stream = "".join(chunks)
    for entry in re.finditer(r'"__html"\s*:\s*', stream):
        value, _ = json.JSONDecoder().raw_decode(stream[entry.end():])
        if isinstance(value, str) and value.startswith('{'):
            yield json.loads(value)
    # Large JSON-LD strings are separate text frames referenced as "$1a".
    # Their JSON may straddle multiple push calls; join before decoding.
    for entry in re.finditer(r'\{"@context"\s*:', stream):
        value, _ = json.JSONDecoder().raw_decode(stream[entry.start():])
        yield value


def localized(value):
    if isinstance(value, str) and value.startswith("{"):
        value = json.loads(value)
    if isinstance(value, dict):
        return value.get("zh") or value.get("en") or ""
    return value or ""


def fansi_listing(data, now):
    if data.get("errors") or not isinstance(data.get("data", {}).get("events"), list):
        raise ValueError("FANSI public event-list schema missing")
    rows = []
    for value in data["data"]["events"]:
        row = json.loads(value) if isinstance(value, str) else value
        # The public UI uses this publication gate. Do not surface future or
        # test releases merely because the anonymous query contains them.
        if not row.get("eventOnline") or datetime.fromisoformat(row["eventOnline"].replace("Z", "+00:00")) > now:
            continue
        start, end = iso(row.get("eventStart")), iso(row.get("eventEnd"))
        if upcoming(start, end, now.astimezone(TAIPEI).date()):
            rows.append(row)
    return sorted(rows, key=lambda row: row["eventStart"])


def fansi_detail(html, row, source, today):
    schema = next((x for x in schema_objects(html) if isinstance(x, dict) and x.get("@type") == "EventSeries"), None)
    if schema is None or not isinstance(schema.get("subEvent"), list):
        raise ValueError("FANSI EventSeries/subEvent schema missing")
    if CANCELLED.search(schema.get("eventStatus", "")):
        return None
    perfs = []
    for show in schema["subEvent"]:
        if CANCELLED.search(show.get("eventStatus", "") + show.get("name", "")):
            continue
        place = show.get("location") or {}
        address = place.get("address") or {}
        if isinstance(address, dict):
            address = " ".join(address.get(k) or "" for k in ("addressRegion", "addressLocality", "streetAddress", "name"))
        start, end = iso(show.get("startDate")), iso(show.get("endDate"))
        if start:
            perfs.append(performance(start, end, place.get("name", ""), address))
    return event(source, row["id"], schema.get("name") or localized(row.get("eventName")), perfs, today,
                 url=f"https://go.fansi.me/events/{int(row['id'])}", image=schema.get("image", ""),
                 organizer=localized(row.get("artistName")), description="獨立音樂現場演出")


def streetvoice_listing(html):
    root = Document(html).root
    container = next((n for n in root.walk() if n.attrs.get("id") == "activity-items"), None)
    if container is None:
        if "沒有演出活動" in root.text():
            return [], ""
        raise ValueError("StreetVoice activity list missing")
    urls = list(dict.fromkeys(public_url(a.attrs.get("href"), "https://streetvoice.com")
                             for a in container.walk("a") if re.fullmatch(r"/gigs/\d+/", a.attrs.get("href", ""))))
    next_url = next((public_url(a.attrs.get("href"), "https://streetvoice.com")
                     for a in root.walk("a") if a.has_class("next")), "")
    if next_url and not re.fullmatch(r"https://streetvoice\.com/gigs/all/0/\?page=\d+", next_url):
        raise ValueError("StreetVoice pagination changed")
    return urls, next_url


def streetvoice_detail(html, url, source, today):
    root = Document(html).root
    schema = next((x for x in schema_objects(html) if isinstance(x, dict) and x.get("@type") == "Event"), None)
    if schema is None:
        raise ValueError("StreetVoice Event schema missing")
    if CANCELLED.search(schema.get("eventStatus", "")):
        return None
    # Its JSON-LD omits a timezone and can be eight hours behind the UI. The
    # calendar link is deliberately local and is checked against the heading.
    calendar = next((n.attrs["data-href"] for n in root.walk()
                     if "google.com/calendar/event?" in n.attrs.get("data-href", "")), "")
    span = parse_qs(urlparse(calendar).query).get("dates", [""])[0].split("/")
    heading = next((clean_text(n.text()) for n in root.walk("h3") if re.search(r"20\d{2} 年 \d+ 月 \d+ 日", n.text())), "")
    match = re.search(r"(20\d{2}) 年 (\d+) 月 (\d+) 日.*?(\d{1,2}):(\d{2})", heading)
    if not match:
        raise ValueError("StreetVoice visible event date missing")
    start = datetime(*map(int, match.groups())).isoformat()
    end = ""
    if len(span) == 2 and all(re.fullmatch(r"\d{8}T\d{6}", x) for x in span):
        cal_start, cal_end = [datetime.strptime(x, "%Y%m%dT%H%M%S").isoformat() for x in span]
        if cal_start != start:
            raise ValueError("StreetVoice visible/calendar time disagreement")
        if cal_end > start:
            end = cal_end
    place = schema.get("location") or {}
    address = place.get("address") or {}
    if isinstance(address, dict):
        address = " ".join(address.get(k) or "" for k in ("addressRegion", "addressLocality", "streetAddress"))
    city = detect_city(address)
    if not city:
        city = next((detect_city(n.text()) for n in root.walk("h3") if "查看地圖" in n.text()), None)
    description = schema.get("description", "")
    ticket = next((public_url(a.attrs.get("href")) for h in root.walk("h3") for a in h.walk("a")
                   if public_url(a.attrs.get("href")) and "google.com/maps" not in a.attrs["href"]), "")
    perf = performance(start, end, place.get("name", ""), address, city)
    return event(source, url, schema.get("name", ""), [perf], today, url=url, ticket=ticket,
                 image=schema.get("image", ""), description=description)


def fetch(source, today):
    client = Client()
    try:
        return _fetch(source, today, client)
    finally:
        client.session.close()


def _fetch(source, today, client):
    kind, out = source["kind"], []
    maximum = source.get("max_details", 100)
    if kind == "fansi":
        payload = json.loads(client.request("POST", "https://api.fansi.me/graphql",
                                           json={"query": "query GetEventList { events: getFGEventList(typeId: 1) }"}))
        rows = fansi_listing(payload, datetime.now(TAIPEI))
        if len(rows) > maximum:
            raise ValueError("FANSI detail budget exceeded; retain previous snapshot")
        for row in rows:
            result = fansi_detail(client.get(f"https://go.fansi.me/events/{int(row['id'])}"), row, source, today)
            if result:
                out.append(result)
        return out
    url, seen_pages, seen_items, fetched = source["endpoint"], set(), set(), 0
    for _ in range(source.get("max_pages", 16)):
        if url in seen_pages:
            raise ValueError("music pagination repeated a page")
        seen_pages.add(url)
        headers = {"X-Requested-With": "XMLHttpRequest"} if kind == "indievox" else {}
        html = client.get(url, headers=headers)
        # The public load-more endpoint terminates with an empty HTTP 200 body.
        # An empty initial listing still fails schema validation.
        if kind == "indievox" and len(seen_pages) > 1 and not html.strip():
            break
        items, next_url = (indievox_listing(html) if kind == "indievox" else streetvoice_listing(html))
        if kind == "indievox" and items and min(x["dates"][0] for x in items) > (today + timedelta(days=source.get("horizon_days", 120))).isoformat():
            break
        for item in items:
            detail_url = item["url"] if kind == "indievox" else item
            if detail_url in seen_items:
                continue
            seen_items.add(detail_url)
            if kind == "indievox" and not upcoming(item["dates"][0], item["dates"][-1], today, source.get("horizon_days", 120)):
                continue
            if fetched >= maximum:
                raise ValueError("music detail budget exceeded; retain previous snapshot")
            fetched += 1
            detail = client.get(detail_url)
            result = (indievox_detail(detail, item, source, today) if kind == "indievox"
                      else streetvoice_detail(detail, detail_url, source, today))
            if result:
                out.append(result)
        if not next_url:
            break
        url = next_url
    else:
        raise ValueError("music page budget exceeded; retain previous snapshot")
    return out
