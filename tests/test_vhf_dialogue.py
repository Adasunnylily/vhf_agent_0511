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

    def test_vts_control_phrases_are_not_assigned_to_ship(self) -> None:
        raw = "宁波交管，锦龙008叫。请讲。锦龙008接码头通知，今早晨不抛锚了，直接进去。好，注意安全。好的好的，谢谢老师。"

        result = postprocess_vhf_dialogue(raw)

        self.assertIn("锦龙008：宁波交管，锦龙008叫。", result.dialogue_review_text)
        self.assertIn("宁波交管：请讲。", result.dialogue_review_text)
        self.assertIn("宁波交管：好，注意安全。", result.dialogue_review_text)
        self.assertIn("锦龙008：好的好的，谢谢老师。", result.dialogue_review_text)

    def test_departure_request_is_assigned_to_ship(self) -> None:
        raw = "宁波舟山交管，宁远梅山。交管晚上好，宁远梅山，向您申请在北仑二期通达7号泊位作业完毕，申请离泊。好，下一个赵普。"

        result = postprocess_vhf_dialogue(raw)

        self.assertIn("宁远梅山：交管晚上好，宁远梅山，向您申请在北仑二期通达7号泊位作业完毕，申请离泊。", result.dialogue_review_text)
        self.assertIn("宁波交管：好，下一个赵普。", result.dialogue_review_text)

    def test_relay_call_uses_caller_not_target_ship(self) -> None:
        raw = "锦华662，你后面的中国银川叫。哎，讲。中国银川，你能不能加点车。"

        result = postprocess_vhf_dialogue(raw)

        self.assertIn("中国银川：锦华662，你后面的中国银川叫。", result.dialogue_review_text)
        self.assertIn("锦华662：哎，讲。", result.dialogue_review_text)

    def test_station_call_with_ship_name_is_ship_side(self) -> None:
        raw = "宁波交管，锦龙008。请讲。"

        result = postprocess_vhf_dialogue(raw)

        self.assertIn("锦龙008：宁波交管，锦龙008。", result.dialogue_review_text)
        self.assertIn("宁波交管：请讲。", result.dialogue_review_text)


if __name__ == "__main__":
    unittest.main()
