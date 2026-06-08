import unittest

from app.services.ais_risk_analyzer import AISRiskAnalyzer


class AISRiskAnalyzerTests(unittest.TestCase):
    def test_speed_related_voice_routes_to_manual_review(self) -> None:
        analyzer = AISRiskAnalyzer()
        event = {
            "risk_level": "INFO",
            "event_type": "一般业务通话",
            "asr_text": "锦华662，你能不能加点车，你现在才四节多。",
            "ais_context": {
                "ship_name": "锦华662",
                "mmsi": "413000662",
                "sog_kn": 4.3,
                "cog_deg": 62,
                "heading_deg": 63,
                "position_label": "北仑港主航道",
                "nav_status": "航行中",
            },
        }

        enriched = analyzer.enrich_event(event)

        self.assertEqual(enriched["risk_level"], "MANUAL")
        self.assertTrue(enriched["requires_human_review"])
        self.assertTrue(enriched["ais_anomaly"])
        self.assertIn("语音涉及航速调整", "\n".join(enriched["evidence"]))

    def test_high_heading_delta_adds_evidence(self) -> None:
        analyzer = AISRiskAnalyzer()
        result = analyzer.analyze(
            "中国银川报告船位",
            {
                "ship_name": "中国银川",
                "mmsi": "413512345",
                "sog_kn": 6.8,
                "cog_deg": 110,
                "heading_deg": 170,
                "position_label": "北仑港警戒区北口",
            },
        )

        self.assertTrue(result["requires_human_review"])
        self.assertIn("航首向与对地航迹偏差", "\n".join(result["evidence"]))


if __name__ == "__main__":
    unittest.main()
