from __future__ import annotations

import copy
import unittest
from datetime import date
from unittest.mock import patch

from event_radar import schedules, site
from event_radar.collectors import accupass


class ScheduleTests(unittest.TestCase):
    def test_accupass_keeps_ongoing_and_later_sessions_in_discovery(self):
        today, horizon = date(2026, 10, 18), date(2027, 1, 16)
        self.assertTrue(accupass._overlaps_window(self.bookstore()["performances"], today, horizon))
        sessions = [{"start_time": "2026-10-17T15:00:00", "end_time": "2026-10-17T17:00:00"},
                    {"start_time": "2026-10-31T15:00:00", "end_time": "2026-10-31T17:00:00"}]
        self.assertTrue(accupass._overlaps_window(sessions, today, horizon))
        self.assertFalse(accupass._overlaps_window(sessions[:1], today, horizon))
        self.assertFalse(accupass._overlaps_window([{"start_time": "2027-02-01"}], today, horizon))

    def bookstore(self):
        return {
            "event_id": 1, "dedupe_key": "existing-favorite-id",
            "title": "書店走讀《由郭怡美出發：走訪大稻埕的六家書店》",
            "organizer": "郭怡美書店", "category": "活動", "city": "台北市",
            "description_clean": "書店走讀，親自走進大稻埕老屋街區",
            "source_name": "Accupass",
            "source_url": "https://www.accupass.com/event/2609130903502821300120?utm_source=test",
            "first_start": "2026-10-17T15:00:00", "tags": [],
            "performances": [{"start_time": "2026-10-17T15:00:00",
                              "end_time": "2026-11-14T17:00:00", "venue_name": "郭怡美書店"}],
        }

    def snapshot(self, event, today=date(2026, 10, 5)):
        with patch.object(site, "_load_candidates", return_value=[event]), \
                patch.object(site, "selected_events", return_value=[]), \
                patch.object(site, "cached_events", return_value=[]):
            return site.snapshot(today=today)["events"]

    def test_organizer_sessions_replace_span_without_changing_favorite_id(self):
        original = self.bookstore()
        result = self.snapshot(original)[0]
        self.assertEqual(result["id"], "existing-favorite-id")
        self.assertEqual(result["performanceCount"], 3)
        self.assertEqual([p["start"] for p in result["performances"]], [
            "2026-10-17T15:00:00", "2026-10-31T15:00:00", "2026-11-14T15:00:00"])
        self.assertTrue(all(p["start"][:10] == p["end"][:10] for p in result["performances"]))
        self.assertEqual(result["checkedOn"], "2026-10-05")
        self.assertEqual(original["performances"][0]["end_time"], "2026-11-14T17:00:00")

    def test_later_sessions_survive_after_first_expires(self):
        result = self.snapshot(self.bookstore(), date(2026, 10, 18))[0]
        self.assertEqual(result["performanceCount"], 2)
        self.assertEqual(result["firstStart"], "2026-10-31T15:00:00")
        self.assertEqual(self.snapshot(self.bookstore(), date(2026, 11, 15)), [])

    def test_all_sessions_are_sorted_deduplicated_and_not_capped_at_twenty(self):
        event = self.bookstore()
        event["source_url"] = "https://example.org/other-series"
        event["performances"] = [{"start_time": f"2026-10-{day:02d}T19:00:00",
                                  "end_time": f"2026-10-{day:02d}T21:00:00"}
                                 for day in range(31, 5, -1)]
        event["performances"].append(copy.deepcopy(event["performances"][0]))
        result = self.snapshot(event)[0]
        self.assertEqual(result["performanceCount"], 26)
        self.assertEqual(len(result["performances"]), 26)
        self.assertEqual(result["firstStart"], "2026-10-06T19:00:00")
        self.assertEqual(result["lastStart"], "2026-10-31T19:00:00")

    def test_reviewed_schedule_rejects_invalid_and_duplicate_sessions(self):
        entry = copy.deepcopy(next(iter(schedules.reviewed_schedules().values())))
        bad = copy.deepcopy(entry)
        bad["performances"][0]["end_time"] = "2026-10-16T17:00:00"
        with patch.object(schedules, "load_yaml", return_value={"schedules": [bad]}):
            with self.assertRaisesRegex(ValueError, "invalid"):
                schedules.reviewed_schedules()
        bad = copy.deepcopy(entry)
        bad["performances"].append(bad["performances"][0])
        with patch.object(schedules, "load_yaml", return_value={"schedules": [bad]}):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                schedules.reviewed_schedules()


if __name__ == "__main__":
    unittest.main()
