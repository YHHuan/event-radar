from __future__ import annotations

import copy
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch

from event_radar.collectors import independent_music as m
from event_radar.taste import analyze_event
from event_radar.source_network import merge_music_catalogs

TODAY = date(2026, 10, 21)
SOURCE = {"id": "music", "name": "音樂來源", "kind": "indievox", "endpoint": "https://www.indievox.com/activity"}
URL = "https://www.indievox.com/activity/detail/test"


def listing(day="2026/10/24", more=""):
    return f'''<a href="{URL}"><img alt="樂團專場"><div class="date">{day}</div></a>{more}'''


def ld(data):
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + '</script>'


def push(chunk):
    return '<script>self.__next_f.push(' + json.dumps([1, chunk], ensure_ascii=False) + ')</script>'


class IndievoxTests(unittest.TestCase):
    def detail(self, line, dates=None):
        html = f'''<meta name="og:title" content="樂團專場 | iNDIEVOX"><div id="intro">
            <p>{line}</p><p>演出地點：台中市某場館</p><p>售票時間：2026/10/01 12:00</p></div>'''
        item = {"url": URL, "title": "樂團專場", "dates": dates or ["2026-10-24"]}
        return m.indievox_detail(html, item, SOURCE, TODAY)

    def test_load_more_uses_publisher_cursor_and_full_card_span(self):
        html = listing("2026/10/24 (六) ~ 2026/10/25 (日)", '''<div class="page-show-more"
          data-action-url="https://www.indievox.com/activity/get-more-game-list"
          data-parameter="type=card&amp;offset=1&amp;startDate=2026%2F10%2F21"></div>''')
        items, cursor = m.indievox_listing(html)
        self.assertEqual(items[0]["dates"], ["2026-10-24", "2026-10-25"])
        self.assertIn("get-more-game-list?type=card&offset=1", cursor)

    def test_admission_and_sale_time_are_not_show_start(self):
        event = self.detail("演出時間：2026/10/24 (六) 入場18:00 / 開演19:30")
        self.assertEqual(event["performances"][0]["start_time"], "2026-10-24T19:30:00")
        self.assertEqual(event["city"], "台中市")

    def test_explicit_daily_shows_preserve_both_times(self):
        event = self.detail("時間：2026/10/24（六）-2026/10/25（日） 每日18:30開演，17:30開放入場",
                            ["2026-10-24", "2026-10-25"])
        self.assertEqual([p["start_time"] for p in event["performances"]],
                         ["2026-10-24T18:30:00", "2026-10-25T18:30:00"])

    def test_separate_dates_keep_different_clocks_and_gaps(self):
        event = self.detail("演出時間：2026/10/24 19:30、2026/10/31 18:00", ["2026-10-24", "2026-10-31"])
        self.assertEqual([p["start_time"] for p in event["performances"]],
                         ["2026-10-24T19:30:00", "2026-10-31T18:00:00"])

    def test_unknown_schedule_keeps_date_only_and_warns_no_invented_recurrence(self):
        event = self.detail("日期：2026/10/24 ~ 2026/10/31", ["2026-10-24", "2026-10-31"])
        self.assertEqual([p["start_time"] for p in event["performances"]], ["2026-10-24", "2026-10-31"])
        self.assertIn("中間場次", event["_selection"]["registration_note"])
        self.assertTrue(all(p["end_time"] is None for p in event["performances"]))

    def test_tour_description_uses_venue_paired_with_selected_date(self):
        html = '''<div id="intro"><p>時間：2026/10/23 20:00</p><p>地點：台北玉成戲院</p>
                  <p>時間：2026/11/01 20:00</p><p>地點：THE PILLARS 柱</p></div>'''
        item = {"url": URL, "title": "音樂巡迴【台中場】", "dates": ["2026-11-01"]}
        event = m.indievox_detail(html, item, SOURCE, TODAY)
        self.assertEqual(event["performances"][0]["venue_name"], "THE PILLARS 柱")
        self.assertEqual(event["performances"][0]["city"], "台中市")


class FansiTests(unittest.TestCase):
    def schema(self):
        def show(day, city="台北市"):
            return {"@type": "MusicEvent", "name": "公開演出", "startDate": day + "T11:30:00.000Z",
                    "endDate": day + "T13:30:00.000Z", "location": {"name": city + "音樂場館", "address": {"name": city}}}
        return {"@context": "https://schema.org", "@type": "EventSeries", "name": "音樂巡迴",
                "subEvent": [show("2026-10-23"), show("2026-10-23"), show("2026-10-31", "高雄市")]}

    def test_publication_gate_and_event_not_sale_date(self):
        row = {"id": 1, "eventOnline": "2026-10-01T00:00:00Z", "eventStart": "2026-10-23T11:30:00Z",
               "eventEnd": "2026-10-31T13:30:00Z", "saleStart": "2026-09-01T00:00:00Z"}
        unpublished = {**row, "id": 2, "eventOnline": "2026-10-21T10:00:00Z"}
        output = m.fansi_listing({"data": {"events": [json.dumps(row), json.dumps(unpublished)]}},
                                datetime(2026, 10, 21, 14, tzinfo=m.TAIPEI))
        self.assertEqual([x["id"] for x in output], [1])

    def test_streamed_inline_and_split_jsonld_and_duplicate_sections(self):
        schema = self.schema()
        data = json.dumps(schema, ensure_ascii=False)
        variants = [ld(schema), push('c:' + json.dumps(["$", "script", {"dangerouslySetInnerHTML": {"__html": data}}])),
                    push('1a:Tfff,' + data[:100]) + push(data[100:]) + push('c:{"__html":"$1a"}')]
        for html in variants:
            with self.subTest(html=html[:30]):
                event = m.fansi_detail(html, {"id": 12}, SOURCE, TODAY)
                self.assertEqual([p["start_time"] for p in event["performances"]],
                                 ["2026-10-23T19:30:00", "2026-10-31T19:30:00"])
                self.assertEqual(event["performances"][1]["city"], "高雄市")
                self.assertEqual(event["performances"][0]["end_time"], "2026-10-23T21:30:00")

    def test_cancelled_and_past_sessions_are_excluded(self):
        schema = self.schema()
        schema["subEvent"][0]["eventStatus"] = "https://schema.org/EventCancelled"
        schema["subEvent"].pop(1)
        event = m.fansi_detail(ld(schema), {"id": 12}, SOURCE, date(2026, 10, 24))
        self.assertEqual(len(event["performances"]), 1)
        self.assertEqual(event["city"], "高雄市")


class StreetVoiceTests(unittest.TestCase):
    def html(self, calendar="20261023T190000/20261023T190000"):
        schema = {"@type": "Event", "name": "新團專場", "startDate": "2026-10-23T11:00", "endDate": "2026-10-23T12:00",
                  "location": {"name": "THE WALL", "address": {"streetAddress": "台北市文山區"}}}
        return ld(schema) + f'''<h3>2026 年 10 月 23 日 | 星期五 | 19:00</h3>
            <h3><a href="https://example.org/ticket">購票</a></h3>
            <button data-href="http://www.google.com/calendar/event?dates={calendar}&amp;trp=false"></button>'''

    def test_visible_calendar_time_wins_over_naive_utc_jsonld(self):
        event = m.streetvoice_detail(self.html(), "https://streetvoice.com/gigs/1/", SOURCE, TODAY)
        self.assertEqual(event["first_start"], "2026-10-23T19:00:00")
        self.assertIsNone(event["performances"][0]["end_time"])
        self.assertEqual(event["ticket_url"], "https://example.org/ticket")

    def test_conflicting_calendar_time_is_not_silently_shifted(self):
        with self.assertRaisesRegex(ValueError, "disagreement"):
            m.streetvoice_detail(self.html("20261023T110000/20261023T120000"), "https://streetvoice.com/gigs/1/", SOURCE, TODAY)

    def test_listing_ignores_featured_and_duplicate_links_follows_next(self):
        html = '''<a href="/gigs/99/">featured</a><div id="activity-items"><a href="/gigs/1/">one</a>
           <a href="/gigs/1/">again</a><a href="/artist/">artist</a></div><a class="next" href="/gigs/all/0/?page=2">next</a>'''
        self.assertEqual(m.streetvoice_listing(html), (["https://streetvoice.com/gigs/1/"], "https://streetvoice.com/gigs/all/0/?page=2"))


class FetchTests(unittest.TestCase):
    def test_only_known_load_more_can_end_with_empty_body(self):
        client = unittest.mock.Mock()
        more = '<div class="page-show-more" data-action-url="https://www.indievox.com/activity/get-more-game-list" data-parameter="offset=1"></div>'
        client.get.side_effect = [listing(more=more), 'detail', '']
        with patch.object(m, "indievox_detail", return_value=None):
            self.assertEqual(m._fetch(SOURCE, TODAY, client), [])
        client.get.side_effect = ['']
        with self.assertRaisesRegex(ValueError, "schema"):
            m._fetch(SOURCE, TODAY, client)

    def test_http_failure_is_not_a_successful_empty_snapshot(self):
        with patch.object(m.Client, "get", side_effect=RuntimeError("unavailable")):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                m.fetch(SOURCE, TODAY)

    def test_pagination_budget_and_loop_fail_visibly(self):
        client = unittest.mock.Mock()
        with patch.object(m, "indievox_listing", return_value=([], SOURCE["endpoint"])):
            with self.assertRaisesRegex(ValueError, "repeated"):
                m._fetch(SOURCE, TODAY, client)
        with patch.object(m, "indievox_listing", return_value=([], "https://www.indievox.com/next")):
            with self.assertRaisesRegex(ValueError, "budget"):
                m._fetch({**SOURCE, "max_pages": 1}, TODAY, client)

    def test_schema_failure_not_empty_success(self):
        for parser, args in [(m.indievox_listing, ("<html>blocked</html>",)),
                             (m.streetvoice_listing, ("<html>blocked</html>",)),
                             (m.fansi_listing, ({"errors": ["bad"]}, datetime.now(m.TAIPEI)))]:
            with self.subTest(parser=parser.__name__), self.assertRaises(ValueError):
                parser(*args)

    def test_catalog_does_not_get_reviewed_selection_score_floor(self):
        event = m.event(SOURCE, "one", "新聲音", [m.performance("2026-10-23", "", "場館", "高雄市")], TODAY, url=URL)
        catalog_score = analyze_event(event, today=TODAY)["score"]
        reviewed = copy.deepcopy(event)
        reviewed["_selection"].pop("catalog")
        self.assertLess(catalog_score, analyze_event(reviewed, today=TODAY)["score"])

    def test_ticket_platform_non_music_events_are_not_indie_gigs(self):
        for title in ("選股必勝術｜財經教授的投資心法", "2026摔角兄弟會", "測試活動"):
            self.assertIsNone(m.event(SOURCE, "one", title, [m.performance("2026-10-23", "", "場館", "台北市")], TODAY, url=URL))


class MergeTests(unittest.TestCase):
    def event(self, day, title="樂團專場", url=URL, venue="場館"):
        return m.event(SOURCE, day, title, [m.performance(day, "", venue, "台北市")], TODAY, url=url)

    def test_shared_ticket_merges_day_cards_without_losing_sessions(self):
        events = [self.event("2026-10-23T19:00:00", "樂團專場 - 10/23"),
                  self.event("2026-10-24T19:00:00", "樂團專場 - 10/24")]
        merged = merge_music_catalogs(events)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "樂團專場")
        self.assertEqual(len(merged[0]["performances"]), 2)
        self.assertEqual(len(events[0]["performances"]), 1)  # input snapshot not mutated

    def test_precise_time_fills_date_only_but_separate_venues_survive(self):
        events = [self.event("2026-10-23"), self.event("2026-10-23T19:00:00"),
                  self.event("2026-10-23T19:00:00", venue="另一舞台")]
        merged = merge_music_catalogs(events)[0]
        self.assertEqual(len(merged["performances"]), 2)
        self.assertTrue(all(p["start_time"] == "2026-10-23T19:00:00" for p in merged["performances"]))

    def test_shared_generic_profile_cannot_merge_unrelated_shows(self):
        events = [self.event("2026-10-23", "甲團專場", "https://example.org/"),
                  self.event("2026-10-24", "乙團專場", "https://example.org/")]
        self.assertEqual(len(merge_music_catalogs(events)), 2)

    def test_conflicting_community_time_does_not_invent_second_show(self):
        official = self.event("2026-10-23T20:00:00")
        official["source_name"] = "iNDIEVOX"
        community = self.event("2026-10-23T19:00:00")
        community["source_name"] = "StreetVoice 街聲"
        community["ticket_url"] = URL.replace("www.", "") + "?utm_source=streetvoice"
        merged = merge_music_catalogs([official, community])[0]
        self.assertEqual(len(merged["performances"]), 1)
        self.assertEqual(merged["performances"][0]["start_time"], "2026-10-23T20:00:00")
        self.assertIn("來源時間有差異", merged["_selection"]["registration_note"])
        community["ticket_url"] = "https://sv.link/short"
        merged = merge_music_catalogs([official, community])[0]
        self.assertEqual(len(merged["performances"]), 1)
        self.assertEqual(merged["performances"][0]["start_time"], "2026-10-23T20:00:00")


if __name__ == "__main__":
    unittest.main()
