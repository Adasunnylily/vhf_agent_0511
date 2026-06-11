import unittest

from app.services.vhf_dialogue import postprocess_vhf_dialogue


class VHFDialogueTests(unittest.TestCase):
    def test_repairs_xiangyuan_15_dialogue(self) -> None:
        raw = "宁波交管现在159，请讲。交管，中午好，现在幺五靠左，大榭集装箱码头一号泊位向您报告。收到，散会。"

        result = postprocess_vhf_dialogue(raw)

        self.assertIn("湘远15叫", result.resolved_text)
        self.assertIn("湘远15靠妥大榭集装箱码头1号泊位", result.resolved_text)
        self.assertIn("收到，再会", result.resolved_text)
        self.assertIn("湘远15：宁波交管，湘远15叫。", result.dialogue_review_text)
        self.assertIn("宁波交管：请讲。", result.dialogue_review_text)
        self.assertIn("湘远15：交管，中午好，湘远15靠妥大榭集装箱码头1号泊位向您报告。", result.dialogue_review_text)
        self.assertIn("宁波交管：收到，再会。", result.dialogue_review_text)


if __name__ == "__main__":
    unittest.main()
