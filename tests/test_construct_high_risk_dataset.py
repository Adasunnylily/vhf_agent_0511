import unittest

from scripts.construct_high_risk_dataset import classify_role, priority_score, weak_label_risk


class ConstructHighRiskDatasetTests(unittest.TestCase):
    def test_classify_ship_call(self) -> None:
        result = classify_role("VTS，宁远8报告，已靠泊3号码头")

        self.assertEqual(result.role, "ship")
        self.assertIn("报告", result.evidence)

    def test_classify_operator_reply(self) -> None:
        result = classify_role("宁远8，VTS收到，请保持守听")

        self.assertEqual(result.role, "operator")

    def test_high_risk_weak_label(self) -> None:
        result = weak_label_risk("我船机舱冒烟，请求救助", "ship")

        self.assertEqual(result.risk_label, "high")
        self.assertEqual(result.risk_type, "fire_smoke")

    def test_normal_weak_label(self) -> None:
        result = weak_label_risk("VTS，海丰32报告，已抛好锚", "ship")

        self.assertEqual(result.risk_label, "normal")

    def test_non_ship_is_not_target(self) -> None:
        result = weak_label_risk("VTS收到，请保持守听", "operator")

        self.assertEqual(result.risk_label, "not_target")

    def test_review_priority_orders_high_risk(self) -> None:
        score = priority_score(
            {
                "risk_label_pred": "high",
                "role_pred": "ship",
                "weak_confidence": "0.88",
                "asr_text": "机舱冒烟请求救助",
            }
        )

        self.assertGreaterEqual(score, 100)


if __name__ == "__main__":
    unittest.main()
