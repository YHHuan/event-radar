import copy
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch

from event_radar import booking, recommendations, site
from event_radar.collectors import arts

TODAY = date(2026, 11, 17)


def source(kind):
    return {"id": kind, "kind": kind, "name": kind, "url": "https://example.org/"}


def event(identifier="film", start="2027-01-01", end="", score=76, info=None):
    return {"id": identifier, "title": identifier, "organizer": identifier, "url": "https://example.org/" + identifier,
            "firstStart": start, "score": score, "lenses": [{"key": identifier}], "booking": info or {},
            "performances": [{"start": start, "end": end, "venue": "場館"}]}


class ArtsTests(unittest.TestCase):
    def test_museum_ranges_include_ongoing_and_exclude_expired_and_undated(self):
        html = '''<a href="/ExhibitionDetail?PKNO=1"><h2>現正展覽</h2>2026.10.01 - 2027.2.3</a>
          <a href="/ExhibitionDetail?PKNO=2"><h2>舊展</h2>2026.1.1 - 2026.9.1</a>
          <a href="/ExhibitionDetail?PKNO=3"><h2>常設展</h2>2026.1.1</a>'''
        rows = arts.museum_listing(html, source("fubon"), TODAY)
        self.assertEqual([r["title"] for r in rows], ["現正展覽"])
        self.assertEqual(rows[0]["performances"][0]["end_time"], "2027-02-03")
        self.assertIn("開館時段", rows[0]["_selection"]["registration_note"])
        with self.assertRaises(ValueError):
            arts.museum_listing("<html>temporary error</html>", source("fubon"), TODAY)

    def test_tfam_omits_online_and_overseas_without_losing_local_exhibition(self):
        row = {"ExID": 1, "ExName": "聲音藝術", "Area": "一樓", "BeginDate": "2026/10/31",
               "EndDate": "2027/03/14", "IsIssueDate": True, "IsSpecial": 1}
        data = {"Status": "1", "Data": [row, {**row, "ExName": "Net.Open"},
                                           {**row, "Area": "Palazzo delle Prigioni, Venice"}]}
        rows = arts.tfam(data, source("tfam"), TODAY)
        self.assertEqual(len(rows), 1)
        self.assertIn("Exhibition_Special.aspx", rows[0]["source_url"])
        with self.assertRaises(ValueError):
            arts.tfam({"Status": "0", "Data": []}, source("tfam"), TODAY)

    def test_ntu_uses_festival_year_not_film_release_year_or_javascript_execution(self):
        script = '''window.FILMS = [
          {
            id: "film-a",
            date: 19,
            time: "18:10",
            zh: "再見列寧！",
            year: 2003,
            still: "poster.jpg",
            description: ["不是日期"],
            unused: (() => { throw Error("do not execute"); })()
          }
];
window.FESTIVAL_YEAR = 2026;
window.FESTIVAL_MONTH_NUM = 11;'''
        rows = arts.ntu_films("<h1>主題選片</h1>", script, source("ntu_film"), TODAY)
        self.assertEqual(rows[0]["performances"][0]["start_time"], "2026-11-19T18:10:00")
        self.assertIsNone(rows[0]["performances"][0]["end_time"])
        self.assertEqual(arts.ntu_films("<h1>選片</h1>", script, source("ntu_film"), date(2027, 1, 1)), [])

    def test_nccu_keeps_both_sessions_not_publication_date(self):
        html = '''<p>公告2026.09.01</p><div class="tx_date">2026.11.25 &amp; 26</div>
            <p>(三)、(四) 19:30-21:10</p><p>藝文中心3樓 視聽館</p>'''
        row = arts.nccu_detail(html, source("nccu_arts"), "故事工廠", "https://example.org/pf1.html", TODAY)
        self.assertEqual([p["start_time"] for p in row["performances"]], ["2026-11-25T19:30:00", "2026-11-26T19:30:00"])
        self.assertNotIn("免費", row["_selection"]["registration_note"])

    def test_opentix_keeps_tour_sessions_separate_from_sales_and_stock(self):
        rows = []
        for day, city in [("2027-02-26", "臺中市"), ("2027-02-27", "臺北市"), ("2027-03-01", "高雄市")]:
            rows.append({"@type": "Event", "name": "配樂交響音樂會", "startDate": day + "T19:30:00",
                         "endDate": day + "T21:30:00", "location": {"name": "音樂廳", "address": {"addressLocality": city}},
                         "offers": {"validFrom": "2026-11-13T12:00:00", "availability": "InStock"}})
        html = "".join('<script type="application/ld+json">' + json.dumps(r) + "</script>" for r in rows)
        row = arts.opentix_detail(html, source("opentix_planning"), "https://www.opentix.life/event/1", TODAY)
        self.assertEqual(len(row["performances"]), 3)
        self.assertEqual(row["first_start"], "2027-02-26T19:30:00")
        self.assertEqual(row["_booking"]["sale_start"], "2026-11-13T12:00:00")
        self.assertNotIn("InStock", json.dumps(row))
        sold = arts.opentix_detail(html.replace("InStock", "SoldOut"), source("opentix_planning"),
                                  "https://www.opentix.life/event/1", TODAY)
        self.assertEqual(sold["_booking"]["status"], "sold_out")


class PlanningTests(unittest.TestCase):
    def test_ongoing_and_later_performances_survive_old_first_start(self):
        series = event("series", "2026-01-01")
        series["performances"].append({"start": "2026-11-21T19:00:00", "end": "", "venue": "劇場"})
        exhibition = event("exhibition", "2026-09-01", "2026-12-31")
        selected = recommendations.select([series, exhibition], today=TODAY)
        self.assertEqual({e["id"] for e in selected["near"]}, {"series", "exhibition"})
        self.assertEqual(len(next(e for e in selected["near"] if e["id"] == "series")["performances"]), 1)

    def test_deadline_goes_in_advance_even_for_near_event_without_duplicate(self):
        info = {"status": "announced", "checked_on": "2026-11-17", "early_bird_end": "2026-11-19"}
        selected = recommendations.select([event(start="2026-11-20", info=info)], today=TODAY)
        self.assertEqual(selected["near"], [])
        self.assertTrue(selected["advance"][0]["bookingUrgent"])
        self.assertIn("早鳥截止", selected["advance"][0]["bookingReminder"])

    def test_hidden_closed_and_sold_out_do_not_become_advance_recommendations(self):
        rows = [event("hidden"), event("sold", info={"status": "sold_out"}),
                event("closed", info={"status": "announced", "checked_on": "2026-11-17", "registration_end": "2026-11-16"})]
        self.assertEqual(recommendations.select(rows, today=TODAY, hidden={"hidden"})["advance"], [])

    def test_stale_deadline_is_recheck_not_urgency_and_past_noon_deadline_expires(self):
        value = {"checked_on": "2026-10-01", "early_bird_end": "2026-11-18"}
        text, when = booking.action(value, TODAY)
        self.assertIn("重新確認", text)
        self.assertIsNone(when)

    def test_registration_closes_at_its_announced_clock_even_today(self):
        value = {"checked_on": "2026-11-17", "registration_end": "2026-11-17T12:00:00+08:00"}
        self.assertEqual(booking.action(value, TODAY, now=datetime(2026, 11, 17, 14)), ("", None))
        value["checked_on"] = "2026-10-01"
        self.assertEqual(booking.action(value, TODAY, now=datetime(2026, 11, 17, 14)), ("", None))
        value = {"checked_on": "2026-11-17", "early_bird_end": "2026-11-17T12:00:00", "sale_start": "2026-11-10"}
        text, when = booking.action(value, TODAY, now=datetime(2026, 11, 17, 14))
        self.assertNotIn("早鳥截止", text)
        self.assertIsNone(when)

    def test_a_far_event_does_not_require_near_events_and_retains_year(self):
        rows = [event("2027展覽", "2027-03-01", "2027-06-01")]
        selected = recommendations.select(rows, today=TODAY)
        self.assertEqual(selected["near"], [])
        self.assertEqual(selected["advance"][0]["firstStart"], "2027-03-01")

    def test_review_date_is_not_falsely_refreshed_by_source_fetch(self):
        row = {"source_url": "https://example.org/e", "_booking": {"checked_on": "2026-11-17"}}
        review = {"event_url": row["source_url"], "url": row["source_url"], "checked_on": "2026-10-01", "early_bird_end": "2026-11-18"}
        with patch.object(booking, "load_yaml", return_value={"reviews": [review]}):
            self.assertEqual(booking.public(row)["checked_on"], "2026-10-01")

    def test_two_year_event_requires_booking_provenance(self):
        row = arts.make(source("tfam"), "展覽", "https://example.org/e",
                        [arts.performance("2028-03-01", "2028-04-01", "美術館", city="台北市")], TODAY, "exhibition",
                        booking={"status": "announced", "url": "https://example.org/e", "checked_on": "2026-11-17"})
        with patch.object(site, "selected_events", return_value=[row]), patch.object(site, "cached_events", return_value=[]), patch.object(site, "_load_candidates", return_value=[]):
            self.assertEqual(len(site.snapshot(today=TODAY)["events"]), 1)
            row.pop("_booking")
            self.assertEqual(site.snapshot(today=TODAY)["events"], [])


if __name__ == "__main__":
    unittest.main()
