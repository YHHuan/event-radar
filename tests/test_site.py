from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from event_radar import site


class SiteTests(unittest.TestCase):
    def test_snapshot_deduplicates_and_rejects_unsafe_urls(self):
        candidates = [
            {
                "event_id": 1,
                "dedupe_key": "safe",
                "title": "台北蚤之市",
                "organizer": "台北蚤之市",
                "category": "市集",
                "description_clean": "松菸三天限定古物老物市集",
                "source_name": "精選",
                "source_url": "https://example.com/flea",
                "ticket_url": "https://example.com/flea",
                "image_url": "https://example.com/poster.jpg",
                "city": "台北市",
                "tags": ["古物"],
                "first_start": "2026-10-24T10:00:00",
                "personal_match_score": None,
                "scored_at": None,
                "performances": [{
                    "start_time": "2026-10-24T10:00:00",
                    "end_time": "2026-10-24T18:00:00",
                    "venue_name": "松山文創園區",
                    "venue_address": "台北市",
                    "price_text": "免費入場",
                }],
            },
            {
                "event_id": 2,
                "dedupe_key": "unsafe",
                "title": "不安全活動",
                "organizer": "",
                "category": "活動",
                "description_clean": "",
                "source_name": "未知",
                "source_url": "javascript:alert(1)",
                "ticket_url": "javascript:alert(1)",
                "image_url": "",
                "city": "台北市",
                "tags": [],
                "first_start": "2026-09-01T10:00:00",
                "personal_match_score": None,
                "scored_at": None,
                "performances": [{
                    "start_time": "2026-09-01T10:00:00",
                    "end_time": "",
                    "venue_name": "測試場地",
                    "venue_address": "台北市",
                    "price_text": "",
                }],
            },
        ]
        with patch.object(site, "_load_candidates", return_value=candidates):
            result = site.snapshot(today=site.date(2026, 8, 30), max_events=10)
        self.assertEqual([event["id"] for event in result["events"]], ["safe"])
        self.assertEqual(result["events"][0]["tier"], "pick")

    def test_health_check_rejects_tiny_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "site-status.json").write_text(
                '{"counts":{"count":1,"sources":{"one":1}},"coverage":{"lastDate":"2026-09-01"}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "implausibly small"):
                site.check(path, min_events=2, min_sources=1)


if __name__ == "__main__":
    unittest.main()
