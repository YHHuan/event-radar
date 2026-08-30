from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from event_radar.taste import analyze_event, blended_score, model_score_is_fresh, normalized_image_url


def event(title: str, description: str = "", *, city: str = "台北市") -> dict:
    return {
        "title": title,
        "description_clean": description,
        "organizer": "",
        "category": "",
        "subcategory": "",
        "tags": [],
        "city": city,
        "first_start": "2026-09-12T19:30:00",
        "source_url": "https://example.com/event",
        "ticket_url": "https://example.com/event",
        "image_url": "https://example.com/poster.jpg",
        "performances": [
            {
                "start_time": "2026-09-12T19:30:00",
                "venue_name": "華山文創園區",
                "venue_address": "台北市",
            }
        ],
    }


class TasteTests(unittest.TestCase):
    def test_signature_event_is_explainable_and_strong(self):
        item = event(
            "驫舞20《大群舞》",
            "二十周年當代舞作，現場演奏並於劇場演出。",
        )
        result = analyze_event(item, today=date(2026, 8, 30))
        self.assertGreaterEqual(result["score"], 75)
        self.assertEqual(result["decision"], "keep")
        self.assertIn("身體與感官", [facet["label"] for facet in result["facets"]])
        self.assertNotIn("100", result["reason"])

    def test_repeated_generic_words_do_not_multiply_score(self):
        once = analyze_event(event("一般活動", "市集"), today=date(2026, 8, 30))["score"]
        repeated = analyze_event(
            event("一般活動", "市集 市集 市集 市集 市集"), today=date(2026, 8, 30)
        )["score"]
        self.assertEqual(once, repeated)

    def test_generic_recurring_course_is_demoted(self):
        result = analyze_event(
            event("手作入門班招生中", "每週工作坊，常態班招生中"),
            today=date(2026, 8, 30),
        )
        self.assertEqual(result["decision"], "demote")
        self.assertLess(result["score"], 50)

    def test_destination_city_can_survive_on_strong_fit(self):
        result = analyze_event(
            event("台中爵士音樂節二十周年戶外專場", "策展音樂節與現場演奏", city="台中市"),
            today=date(2026, 8, 30),
        )
        self.assertEqual(result["decision"], "keep")
        self.assertIn("專程", result["reason"])

    def test_expired_model_score_is_ignored(self):
        item = event("普通音樂會")
        item["personal_match_score"] = 99
        item["scored_at"] = "2026-07-01T12:00:00+08:00"
        deterministic = analyze_event(item, today=date(2026, 8, 30))
        score, mode = blended_score(item, deterministic)
        self.assertEqual(mode, "taste")
        self.assertEqual(score, deterministic["score"])

    def test_fresh_model_score_is_only_blended(self):
        now = datetime.now().astimezone()
        item = event("普通音樂會")
        item["personal_match_score"] = 100
        item["scored_at"] = (now - timedelta(days=2)).isoformat()
        self.assertTrue(model_score_is_fresh(item["scored_at"], now=now))
        deterministic = analyze_event(item)
        score, mode = blended_score(item, deterministic)
        self.assertEqual(mode, "blended")
        self.assertLess(score, 100)
        self.assertGreater(score, deterministic["score"])

    def test_malformed_culture_image_is_repaired(self):
        malformed = "https://cloud.culture.twhttps://cloud.culture.tw/image/a.jpg"
        self.assertEqual(
            normalized_image_url(malformed), "https://cloud.culture.tw/image/a.jpg"
        )


if __name__ == "__main__":
    unittest.main()
