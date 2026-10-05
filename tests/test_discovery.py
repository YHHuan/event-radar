from __future__ import annotations

import copy
import json
import ssl
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from event_radar import db, site, source_network
from event_radar.collectors import discovery as d
from event_radar.taste import analyze_event

TODAY = date(2026, 10, 5)
SOURCE = {"id": "fixture", "name": "官方測試來源", "url": "https://example.org/calendar",
          "mode": "automatic", "lenses": ["folk", "endurance"], "note": "公開來源"}


class ParserTests(unittest.TestCase):
    def tourism_row(self):
        return {"EventID": "Event_1", "EventName": "2026地方迎王祭典", "EventStatus": "EventScheduled",
                "StartDateTime": "2026-10-10T00:00:00+08:00", "EndDateTime": "2026-10-12T23:59:59+08:00",
                "PostalAddress": {"City": "臺南市", "Town": "北門區", "StreetAddress": "廟前廣場"}}

    def test_tourism_preserves_date_precision_and_rejects_ambiguous_or_cancelled(self):
        row = self.tourism_row()
        event = d.parse_tourism({"Events": [row]}, SOURCE, TODAY)[0]
        self.assertEqual(event["performances"][0]["start_time"], "2026-10-10")
        self.assertEqual(event["performances"][0]["end_time"], "2026-10-12")
        self.assertEqual(event["city"], "台南市")
        for changes in [{"EventStatus": "EventCancelled"}, {"StartDateTime": "待公告"},
                        {"StartDateTime": "2026-10-09T16:00:00+08:00", "EndDateTime": "2026-10-12T15:59:59+08:00"},
                        {"StartDateTime": "2026-06-01T00:00:00+08:00"},
                        {"StartDateTime": "2025-10-10T00:00:00+08:00", "EndDateTime": "2025-10-12T00:00:00+08:00"}]:
            with self.subTest(changes=changes):
                self.assertEqual(d.parse_tourism({"Events": [{**row, **changes}]}, SOURCE, TODAY), [])
        timed = d.parse_tourism({"Events": [{**row, "StartDateTime": "2026-10-10T16:00:00+08:00",
                                              "EndDateTime": "2026-10-10T21:00:00+08:00"}]}, SOURCE, TODAY)[0]
        self.assertIn("T16:00", timed["first_start"])

    def test_focusline_uses_race_day_not_registration_and_filters_routine_races(self):
        row = {"actCode": "261121AB", "status": 1, "actName": "2026 CRUFU RUN 夸父追日",
               "actDate": "2026-11-21T00:00:00", "location": "金沙鎮林務所",
               "geo": json.dumps({"type": "TW", "cities": ["金門縣"]}),
               "register": {"start": "2026-05-25T12:00:00", "end": "2026-08-31T23:59:59"}}
        event = d.parse_focusline([row], SOURCE, TODAY)[0]
        self.assertEqual(event["first_start"], "2026-11-21")
        self.assertIn("已截止", event["_selection"]["registration_note"])
        for changes in [{"status": 2}, {"actName": "社區5K路跑"}, {"actName": "親子小鐵人挑戰"},
                        {"actName": "超馬志工終身學習"}, {"actDate": "日期待定"}]:
            self.assertEqual(d.parse_focusline([{**row, **changes}], SOURCE, TODAY), [])
        upcoming = copy.deepcopy(row)
        upcoming["register"] = {"start": "2026-10-20", "end": "2026-10-30"}
        self.assertIn("預計 2026-10-20", d.parse_focusline([upcoming], SOURCE, TODAY)[0]["_selection"]["registration_note"])

    def test_ctau_year_multiday_deadline_and_unknown_dates(self):
        html = '''<table><tr><th>活動名稱</th><th>日期</th><th>地點</th><th>里程 / 限時</th></tr>
        <tr><td>2026宜蘭冬山河超級馬拉松</td><td>11/20-11/21<br><a href="/signup">10/19前報名去</a></td>
        <td>宜蘭縣親水公園 100K夜21:00起跑</td><td>100英里 / 100K夜</td></tr>
        <tr><td>2027CTAU超馬系列賽 陽明山超級馬拉松</td><td>2027 01/23 12/22前報名去</td>
        <td>台北市至善國中</td><td>63K</td></tr>
        <tr><td>2027 超馬志工終身學習</td><td>07/04</td><td>台北市</td><td>講座</td></tr>
        <tr><td>2026 暫定超馬</td><td>10/12 暫定</td><td>台北市</td><td>50K</td></tr>
        <tr><td>未知年份超馬</td><td>11/20</td><td>台北市</td><td>50K</td></tr></table>'''
        events = d.parse_ctau(html, SOURCE, TODAY)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["performances"][0]["end_time"], "2026-11-21")
        self.assertEqual(events[0]["first_start"], "2026-11-20")
        self.assertIn("2026-10-19", events[0]["_selection"]["registration_note"])
        self.assertIn("2026-12-22", events[1]["_selection"]["registration_note"])
        self.assertEqual(events[1]["first_start"], "2027-01-23")

    def test_festival_event_times_override_published_and_keep_overnight(self):
        row = {"title": "2026光球音樂祭", "url": "https://test.kktix.cc/events/a",
               "published": "2026-01-01T00:00:00+08:00",
               "content": "時間：2026/11/07 22:00(+0800) ~ 2026/11/08 05:00(+0800)\n地點：台北市北流"}
        source = {**SOURCE, "slug": "test"}
        event = d.parse_festival_feed({"entry": [row]}, source, TODAY)[0]
        self.assertEqual(event["first_start"], "2026-11-07T22:00:00")
        self.assertEqual(event["performances"][0]["end_time"], "2026-11-08T05:00:00")
        row["content"] = "時間：2026/11/07 22:00(+0800)~05:00\n地點：台北市北流"
        self.assertEqual(d.parse_festival_feed({"entry": [row]}, source, TODAY)[0]["performances"][0]["end_time"], "2026-11-08T05:00:00")
        row["content"] = row["content"].replace("時間", "報名時間")
        self.assertEqual(d.parse_festival_feed({"entry": [row]}, source, TODAY), [])
        row["title"] += "住宿套票"
        self.assertEqual(d.parse_festival_feed({"entry": [row]}, source, TODAY), [])

    def test_changed_schemas_fail_visibly(self):
        for parser, bad in [(d.parse_tourism, {}), (d.parse_focusline, []),
                            (d.parse_ctau, "<html>Unavailable</html>"), (d.parse_festival_feed, {})]:
            with self.subTest(parser=parser.__name__), self.assertRaises(ValueError):
                parser(bad, SOURCE, TODAY)

    def test_folk_lens_does_not_promote_exhibits_merely_mentioning_rituals(self):
        event = d.make_event(SOURCE, "one", "2026地方迎王祭典", "2026-10-10", "2026-10-11",
                             "台南市廣場", "台南市", "https://example.org/event", description="祭典也有親子攤位", lens="folk")
        self.assertEqual(analyze_event(event, today=TODAY)["decision"], "keep")
        event.pop("_selection")
        event["title"] = "民俗文物常設展"
        result = analyze_event(event, today=TODAY)
        self.assertNotIn("folk", [lens["key"] for lens in result["lenses"]])

    def test_tourism_tls_still_verifies_certificate_chain_and_hostname(self):
        with patch.object(d.HTTPAdapter, "init_poolmanager") as initialize:
            d.TourismTLSAdapter()
            context = initialize.call_args.kwargs["ssl_context"]
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name)
        for name, value in [("DATA_DIR", path), ("DB_PATH", path / "events.db")]:
            patcher = patch.object(db, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(source_network, "load_yaml", return_value={"sources": [SOURCE]})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.event = d.make_event(SOURCE, "one", "2026民俗祭典", "2026-10-10", "2026-10-11",
                                  "新北市廣場", "新北市", "https://example.org/event", lens="folk")

    def test_failure_keeps_only_recent_snapshot_and_empty_success_retires_events(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        source_network.record_result("fixture", [self.event], now=now)
        source_network.record_result("fixture", None, now=datetime(2026, 10, 6, tzinfo=timezone.utc))
        self.assertEqual(len(source_network.cached_events(today=date(2026, 10, 6))), 1)
        self.assertIn("更新失敗", source_network.public_sources(today=TODAY)[0]["status"])
        self.assertEqual(source_network.cached_events(today=date(2026, 10, 13)), [])
        self.assertEqual(source_network.public_sources(today=date(2026, 10, 13))[0]["count"], 0)
        source_network.record_result("fixture", [], now=now)
        self.assertEqual(source_network.cached_events(today=TODAY), [])
        self.assertEqual(source_network.public_sources(today=TODAY)[0]["status"], "每日更新")

    def test_reviewed_correction_wins_over_feed_date_and_expired_db_cannot_resurrect(self):
        source_network.record_result("fixture", [self.event], now=datetime(2026, 10, 5, tzinfo=timezone.utc))
        reviewed = copy.deepcopy(self.event)
        reviewed["dedupe_key"] = "selected-correct"
        reviewed["first_start"] = reviewed["performances"][0]["start_time"] = "2026-10-09"
        reviewed["source_url"] = reviewed["ticket_url"] = "https://example.org/official-announcement"
        reviewed["_selection"]["automatic"] = False
        with patch.object(site, "selected_events", return_value=[reviewed]), patch.object(site, "_load_candidates", return_value=[]):
            public = site.snapshot(today=TODAY)
        self.assertEqual(len(public["events"]), 1)
        self.assertEqual(public["events"][0]["firstStart"], "2026-10-09")
        # An expired feed must not sneak back through historical DB rows.
        with patch.object(site, "selected_events", return_value=[]), patch.object(site, "_load_candidates", return_value=[self.event]):
            public = site.snapshot(today=date(2026, 10, 13))
        self.assertEqual(public["events"], [])

    def test_old_review_does_not_hide_next_year_at_same_organizer_url(self):
        old = copy.deepcopy(self.event)
        next_year = copy.deepcopy(self.event)
        next_year["title"] = "2027民俗祭典"
        next_year["first_start"] = next_year["performances"][0]["start_time"] = "2027-10-10"
        next_year["performances"][0]["end_time"] = "2027-10-11"
        source_network.record_result("fixture", [next_year], now=datetime(2027, 10, 5, tzinfo=timezone.utc))
        with patch.object(site, "selected_events", return_value=[old]), patch.object(site, "_load_candidates", return_value=[]):
            public = site.snapshot(today=date(2027, 10, 5))
        self.assertEqual([e["title"] for e in public["events"]], ["2027民俗祭典"])


if __name__ == "__main__":
    unittest.main()
