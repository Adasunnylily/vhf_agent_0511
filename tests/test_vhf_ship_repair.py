import unittest

from app.services.vhf_ship_repair import apply_common_vhf_repairs, repair_ship_names_in_text


class VhfShipRepairTests(unittest.TestCase):
    def test_common_phrase_repairs(self) -> None:
        text = "波舟山交管警0027救这辆，金塘南抛锚线，二期注意安全"
        fixed = apply_common_vhf_repairs(text)
        self.assertIn("宁波舟山交管", fixed)
        self.assertIn("金塘南抛锚", fixed)
        self.assertIn("好的，注意安全", fixed)

    def test_lexicon_repair_jinlong227(self) -> None:
        text = "呃，宁波交管锦龙627黄牛礁进口去金塘南抛锚，向你报告"
        fixed = repair_ship_names_in_text(text)
        self.assertIn("锦龙227", fixed)


if __name__ == "__main__":
    unittest.main()
