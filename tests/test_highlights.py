from __future__ import annotations

import copy
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from event_radar import highlights, site
from event_radar.collectors import curated, kktix
from event_radar.taste import analyze_event

TODAY = date(2026, 10, 5)


class HighlightTests(unittest.TestCase):
    def test_catalog_requires_sources_and_separates_undated_interests(self):
        data = highlights.catalog()
        self.assertEqual({item["lens"] for item in data["events"]}, set(highlights.LENSES))
        for item in data["watchlist"]:
            self.assertNotIn("start_time", item)
        broken = copy.deepcopy(data)
        broken["watchlist"][0]["start_time"] = "2027-02-20"
        with self.assertRaisesRegex(ValueError, "watchlist"):
            highlights.validate_catalog(broken)
        broken = copy.deepcopy(data)
        broken["events"][0]["source_url"] = "javascript:alert(1)"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            highlights.validate_catalog(broken)

    def test_long_range_race_and_ongoing_pilgrimage_survive(self):
        with patch.object(site, "_load_candidates", return_value=[]):
            public = site.snapshot(today=TODAY)
        events = {event["id"]: event for event in public["events"]}
        ongoing = events["selected-nanyao-2026"]
        self.assertTrue(ongoing["ongoing"])
        self.assertEqual(ongoing["lastEnd"], "2026-10-11")
        race = events["selected-challenge-taiwan-2027"]
        self.assertEqual(race["firstStart"], "2027-04-24")
        self.assertTrue(race["dateOnly"])
        self.assertIn("endurance", [lens["key"] for lens in race["lenses"]])
        self.assertIn("已截止", events["selected-tianzhong-2026"]["registrationNote"])
        self.assertFalse({event["id"] for event in public["watchlist"]} & set(events))

    def test_expired_selections_are_not_reused_next_year(self):
        with patch.object(site, "_load_candidates", return_value=[]):
            public = site.snapshot(today=date(2027, 10, 5))
        self.assertEqual(public["events"], [])
        self.assertTrue(public["watchlist"])

    def test_reviewed_corrections_override_stale_database_row(self):
        stale = copy.deepcopy(highlights.selected_events()[0])
        stale.pop("_selection")
        stale["dedupe_key"] = "old-database-id"
        stale["title"] = "Old event title"
        stale["performances"][0]["start_time"] = "2026-10-08"
        with patch.object(site, "_load_candidates", return_value=[stale]):
            public = site.snapshot(today=TODAY)
        matching = [event for event in public["events"] if event["url"] == stale["source_url"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["firstStart"][:10], "2026-10-09")

    def test_new_race_lens_requires_reviewed_selection(self):
        event = copy.deepcopy(highlights.selected_events()[-1])
        event.pop("_selection")
        event["title"] = "社區週末馬拉松"
        result = analyze_event(event, today=TODAY)
        self.assertNotIn("endurance", [lens["key"] for lens in result["lenses"]])
        self.assertEqual(result["decision"], "drop")  # Normal 120-day horizon.

    def test_curated_does_not_duplicate_preexisting_jazz_listing(self):
        events = curated.collect()
        urls = [event["source_url"] for event in events]
        self.assertEqual(len(urls), len(set(urls)))

    def test_candidate_query_uses_actual_performance_overlap(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE events (event_id INTEGER, status TEXT, first_start TEXT);
            CREATE TABLE performances (event_id INTEGER, start_time TEXT, end_time TEXT);
            INSERT INTO events VALUES (1,'active','2026-09-01'),(2,'active','2026-10-01'),
              (3,'active','2026-01-01'),(4,'active','2027-09-01');
            INSERT INTO performances VALUES
              (1,'2026-09-01','2026-10-11'), (2,'2026-10-01','2026-10-04'),
              (3,'2026-01-01','2026-01-01'), (3,'2026-10-10',NULL),
              (4,'2027-09-01',NULL);
        """)

        @contextmanager
        def connect():
            yield conn

        try:
            with patch.object(site.db, "init_db"), patch.object(site.db, "connect", connect):
                events = site._load_candidates(TODAY, 120)
            self.assertEqual({event["event_id"] for event in events}, {1, 3})
        finally:
            conn.close()

    def test_future_performance_rescues_historical_first_start(self):
        event = copy.deepcopy(highlights.selected_events()[0])
        event.pop("_selection")
        event["first_start"] = "2026-01-01"
        result = analyze_event(event, today=TODAY)
        self.assertNotEqual(result["decision"], "drop")

    def test_festival_feed_omits_accommodation_variants(self):
        entries = [{"title": title, "url": f"https://festival.kktix.cc/events/{index}",
                    "published": "2026-11-07T12:00:00", "content": "地點：台南市"}
                   for index, title in enumerate(["浪人祭", "浪人祭住宿套票", "浪人祭接駁車"])]
        with patch.object(kktix, "_cfg", return_value={"enabled": True, "organizers": [
            {"slug": "festival", "exclude_title_keywords": ["住宿", "接駁"]}
        ]}), patch.object(kktix.requests, "get") as get, patch.object(kktix.time, "sleep"):
            get.return_value.json.return_value = {"entry": entries}
            self.assertEqual([event["title"] for event in kktix.collect()], ["浪人祭"])


if __name__ == "__main__":
    unittest.main()
