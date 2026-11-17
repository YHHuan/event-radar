"""Official campus and museum calendars; explicit dates, bounded public reads.

Script data is decoded as data, never executed. Exhibition spans stay spans;
publication dates, ticket deadlines and opening hours are not performances.
"""
import hashlib
import json
import re
from datetime import date
from urllib.parse import urljoin, urlparse

import requests

from .independent_music import Document, dates, iso, meta, performance, schema_objects, upcoming
from ..normalize import clean_text

KINDS = {"ntu_film", "nccu_arts", "fubon", "tfam", "tcam", "opentix_planning"}
REASONS = {
    "film": "大學策展放映，適合透過選片與映後交流探索不同觀點。",
    "exhibition": "美術館策展與現場作品，值得留時間慢慢看；留意展期與休館日。",
    "theatre_dance": "校園藝文演出，從戲劇與身體表演接觸創作觀點。",
    "live_music": "現場音樂與跨領域演出，可提前安排時間。",
}
CURATORIAL_NOTES = (
    ("坂本龍一", "聲音、影像與大型裝置交會，適合喜歡音樂和沉浸式現場的人。"),
    ("真鍋大度", "聲音、演算法與空間裝置交會，可和綠美圖建築一起安排半天。"),
    ("國巨基金會", "古典與當代作品相遇的典藏展，值得安排一趟綠美圖；留意票種與預約規則。"),
    ("SANAA", "從建築模型看空間與環境的關係，適合提前留出台中行程。"),
    ("莫內到馬諦斯", "從印象派到抽象藝術的創作脈絡，適合規劃一場慢慢看的跨年特展。"),
)


def make(source, title, url, perfs, today, lens, *, note="", image="", description="", booking=None):
    perfs = sorted([p for p in perfs if upcoming(p["start_time"], p.get("end_time"), today, 730)],
                   key=lambda p: p["start_time"])
    if not perfs or not title:
        return None
    item = {
        "dedupe_key": "arts-" + hashlib.sha256((source["id"] + url + title).encode()).hexdigest()[:20],
        "title": clean_text(title), "source_name": source["name"], "source_url": url, "ticket_url": url,
        "organizer": source["name"], "category": "展覽" if lens == "exhibition" else "藝文",
        "city": perfs[0]["city"], "first_start": perfs[0]["start_time"], "performances": perfs,
        "image_url": image, "tags": ["校園藝文"] if source["kind"] in {"ntu_film", "nccu_arts"} else [],
        "description_clean": description[:700],
        "_selection": {"automatic": True, "lens": lens, "checked_on": today.isoformat(),
                       "selection_reason": next((why for term, why in CURATORIAL_NOTES if term in title), REASONS[lens]),
                       "registration_note": note},
    }
    if booking:
        item["_booking"] = booking
    return item


def read(session, url, *, payload=None):
    with session.request("POST" if payload else "GET", url, json=payload,
                         timeout=(8, 25), stream=True) as response:
        response.raise_for_status()
        parts, size = [], 0
        for part in response.iter_content(65536):
            size += len(part)
            if size > 4_000_000:
                raise ValueError("arts source exceeds size limit")
            parts.append(part)
        return b"".join(parts).decode("utf-8-sig")


def museum_listing(html, source, today):
    root = Document(html).root
    marker = "/ExhibitionDetail?" if source["kind"] == "fubon" else "/zh/exhibition/"
    cards = [n for n in root.walk("a") if marker in n.attrs.get("href", "")]
    if not cards:
        raise ValueError("museum exhibition cards missing")
    out, seen = [], set()
    for node in cards:
        url = urljoin(source["url"], node.attrs["href"])
        if url in seen:
            continue
        seen.add(url)
        ds = dates(node.text())
        # An indefinite collection is a discovery window, not a guessed end date.
        if len(ds) != 2:
            continue
        title = next((clean_text(n.text()) for n in node.walk("h2") if clean_text(n.text())), "")
        if not title:
            title = next((clean_text(n.text()) for n in node.walk("h3") if clean_text(n.text())), "")
        venue = source["name"]
        city = "台北市" if source["kind"] == "fubon" else "台中市"
        note = ("展期為日期範圍；每日開館時段、臨時異動與預約請看館方公告。" if source["kind"] == "fubon"
                else "展期不代表每日開館；週一休館，國定假日與臨時異動請看館方公告。")
        booking = {"status": "announced", "url": url, "checked_on": today.isoformat(),
                   "note": "展期已公告；票價與預約請查館方頁面"}
        image = next((urljoin(source["url"], n.attrs["src"]) for n in node.walk("img") if n.attrs.get("src")), "")
        item = make(source, title, url, [performance(ds[0], ds[1], venue, city=city)], today,
                    "exhibition", note=note, image=image, booking=booking)
        if item:
            out.append(item)
    return out


def tfam(data, source, today):
    if not isinstance(data, dict) or str(data.get("Status")) != "1" or not isinstance(data.get("Data"), list):
        raise ValueError("TFAM exhibition schema missing")
    out = []
    for row in data["Data"]:
        if not row.get("IsIssueDate") or not row.get("ExID"):
            continue
        title, area = clean_text(row.get("ExName")), clean_text(row.get("Area"))
        # The same catalog contains Venice and online-only exhibitions.
        if re.search(r"威尼斯|Venice|Prigioni|線上|Net.Open", title + area, re.I):
            continue
        ds = dates((row.get("BeginDate") or "") + " " + (row.get("EndDate") or ""))
        if len(ds) != 2 or not area:
            continue
        page = "Exhibition_Special.aspx" if row.get("IsSpecial") else "Exhibition_page.aspx"
        url = f"https://www.tfam.museum/Exhibition/{page}?ddlLang=zh-tw&id={int(row['ExID'])}"
        item = make(source, title, url, [performance(ds[0], ds[1], "臺北市立美術館 " + area, city="台北市")],
                    today, "exhibition", description=clean_text(Document(row.get("Content") or "").root.text()),
                    note="展期不代表每日開館；週一休館，票價、預約與臨時異動請查館方公告。",
                    image=urljoin("https://www.tfam.museum/File/", (row.get("NowPlayImg") or "").replace("\\", "/")),
                    booking={"status": "announced", "url": url, "checked_on": today.isoformat(),
                             "note": "展期已公告；參觀與預約方式請查館方頁面"})
        if item:
            out.append(item)
    return out


def ntu_films(html, script, source, today):
    root = Document(html).root
    title = next((clean_text(n.text()) for n in root.walk("h1")), "")
    year = re.search(r"window\.FESTIVAL_YEAR\s*=\s*(20\d{2})\s*;", script)
    month = re.search(r"window\.FESTIVAL_MONTH_NUM\s*=\s*(\d{1,2})\s*;", script)
    block = re.search(r"window\.FILMS\s*=\s*\[(.*?)\n\];", script, re.S)
    if not title or not year or not month or not block:
        raise ValueError("NTU dated film schema missing")
    out = []
    # Only primitive fields in each official film record are read. No JS eval.
    records = re.findall(r"(?:^|\n)\s*\{\s*\n(.*?)\n\s*\}(?:,|\s*$)", block[1], re.S)
    if not records:
        raise ValueError("NTU film records missing")
    for record in records:
        fields = {}
        for key in ("id", "date", "time", "zh", "still"):
            m = re.search(r"^\s*" + key + r'\s*:\s*("(?:[^"\\]|\\.)*"|\d+)\s*,?\s*$', record, re.M)
            if not m:
                raise ValueError("NTU film field missing: " + key)
            fields[key] = json.loads(m[1])
        day = date(int(year[1]), int(month[1]), int(fields["date"])).isoformat()
        start = iso(day + "T" + fields["time"])
        url = urljoin(source["url"], "film.html?id=" + fields["id"])
        # Film duration is not a reliable event end when there is a post-screening talk.
        item = make(source, "臺大電影節｜" + title + "《" + fields["zh"] + "》", url,
                    [performance(start, "", "臺大怡仁堂", city="台北市", price="免費入場")], today, "film",
                    image=urljoin(source["url"], fields["still"]), note="開放校內外觀眾；特殊場次報名與映後資訊請看官網。")
        if item:
            out.append(item)
    return out


def nccu_detail(html, source, title, url, today):
    root = Document(html).root
    date_node = next((n for n in root.walk() if n.has_class("tx_date")), None)
    if not date_node:
        raise ValueError("NCCU performance date missing")
    ds = dates(date_node.text())
    if len(ds) != 1:
        raise ValueError("NCCU ambiguous dates")
    extra = re.search(r"&\s*(\d{1,2})(?!\d)", date_node.text())
    if extra:
        ds.append(ds[0][:8] + f"{int(extra[1]):02d}")
    if all(day < today.isoformat() for day in ds):
        return None
    lines = [clean_text(t) for t in root.text().splitlines() if clean_text(t)]
    clocks = re.search(r"(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})", " ".join(lines))
    venue = next((line for line in lines if re.search(r"藝文中心\d樓", line)), "")
    if not venue or not clocks:
        raise ValueError("NCCU performance venue/time missing")
    perfs = [performance(iso(d + "T" + clocks[1]), iso(d + "T" + clocks[2]),
                         "政大" + venue, city="台北市") for d in ds]
    lens = "film" if "/fm" in url else "live_music" if re.search(r"樂團|音樂", title) else "theatre_dance"
    return make(source, title, url, perfs, today, lens,
                note="各場分別報名；名額與校外觀眾參加方式請查官方報名頁。")


def opentix_detail(html, source, url, today):
    records = []
    for obj in schema_objects(html):
        if isinstance(obj, dict):
            records.extend(obj.get("@graph", [obj]))
        elif isinstance(obj, list):
            records.extend(obj)
    records = [r for r in records if isinstance(r, dict) and r.get("@type") in {"Event", "MusicEvent", "TheaterEvent", "DanceEvent"}]
    if not records:
        raise ValueError("OPENTIX performance metadata missing")
    perfs, starts, availability = [], [], []
    for row in records:
        if "Cancelled" in row.get("eventStatus", "") or "Postponed" in row.get("eventStatus", ""):
            continue
        loc, offers = row.get("location") or {}, row.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        addr = loc.get("address") or {}
        city = (addr.get("addressLocality") or "").replace("臺", "台") if isinstance(addr, dict) else ""
        if city not in {"台北市", "新北市", "台中市", "桃園市", "新竹市", "新竹縣", "宜蘭縣", "基隆市",
                        "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "台南市", "高雄市",
                        "屏東縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"}:
            continue
        start, end = iso(row.get("startDate")), iso(row.get("endDate"))
        if not upcoming(start, end, today, 730):
            continue
        perfs.append(performance(start, end, loc.get("name", ""), addr.get("streetAddress", ""), city))
        availability.append(offers.get("availability", ""))
        if offers.get("validFrom") or offers.get("availabilityStarts"):
            starts.append(iso(offers.get("validFrom") or offers["availabilityStarts"]))
    if not perfs:
        return None
    first = records[0]
    title = first.get("name", "")
    lens = "film" if re.search(r"影展|電影節", title) else "theatre_dance" if re.search(r"劇|舞|戲", title) else "live_music"
    booking = {"status": "announced", "url": url, "checked_on": today.isoformat()}
    if availability and all(str(value).rsplit("/", 1)[-1] in {"SoldOut", "Discontinued"} for value in availability):
        booking["status"] = "sold_out"
    if starts:
        booking["sale_start"] = min(starts)
    # AggregateOffer InStock is not a live seats guarantee; do not publish it.
    result = make(source, title, url, perfs, today, lens, image=first.get("image", ""),
                description=clean_text(Document(first.get("description", "")).root.text()),
                note="依公開場次與公告開賣日整理；即時票況、折扣資格請確認售票頁。", booking=booking)
    if result:
        # A catalog is discovery, not a hand-picked endorsement of every listing.
        result["_selection"]["catalog"] = url not in source.get("watch_urls", [])
    return result


def fetch(source, today):
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0 (event-radar; public arts calendar)"
        kind = source["kind"]
        if kind == "tfam":
            out = []
            for typ in ("1", "2"):
                data = json.loads(read(session, source["endpoint"], payload={"JJMethod": "GetEx", "Type": typ}))
                out.extend(tfam(data, source, today))
            return out
        html = read(session, source.get("endpoint") or source["url"])
        if kind in {"fubon", "tcam"}:
            return museum_listing(html, source, today)
        if kind == "ntu_film":
            return ntu_films(html, read(session, urljoin(source["url"], "js/films.js")), source, today)
        if kind == "nccu_arts":
            root, out, seen = Document(html).root, [], set()
            for node in root.walk("a"):
                href = node.attrs.get("href", "")
                if not re.fullmatch(r"(?:pf|fm)\d+\.html", href) or href in seen:
                    continue
                seen.add(href)
                if len(seen) > 16:
                    raise ValueError("NCCU calendar exceeds detail limit")
                title = next((clean_text(n.text()) for n in node.walk("span") if n.has_class("text_rg")), "")
                url = urljoin(source["url"], href)
                item = nccu_detail(read(session, url), source, title, url, today)
                if item:
                    out.append(item)
            if not seen:
                raise ValueError("NCCU calendar links missing")
            return out
        if kind == "opentix_planning":
            root = Document(html).root
            links = []
            for node in root.walk("a"):
                href = node.attrs.get("href", "")
                ds = dates(node.text())
                if re.fullmatch(r"/event/\d+", href) and ds and ds[-1] >= today.isoformat():
                    links.append((ds[0] <= today.isoformat(), ds[0], urljoin(source["url"], href)))
            urls = list(dict.fromkeys(source.get("watch_urls", []) + [u for _, _, u in sorted(links)]))[:24]
            if not urls:
                raise ValueError("OPENTIX calendar links missing")
            out = []
            for url in urls:
                if urlparse(url).hostname != "www.opentix.life":
                    raise ValueError("unexpected ticket host")
                item = opentix_detail(read(session, url), source, url, today)
                if item:
                    out.append(item)
            return out
        raise ValueError("unsupported arts calendar")
