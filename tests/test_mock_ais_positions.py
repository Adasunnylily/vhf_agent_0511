import unittest

from scripts.generate_mock_ais_positions import generate_positions


class MockAISPositionTests(unittest.TestCase):
    def test_positions_are_deterministic_and_within_port_water_extent(self) -> None:
        names = [f"测试船{index}" for index in range(15)]
        first = generate_positions(names, 20260622)
        second = generate_positions(names, 20260622)

        self.assertEqual(first, second)
        self.assertEqual(15, len(first))
        self.assertTrue(all(121.85 <= float(ship["lng"]) <= 122.03 for ship in first))
        self.assertTrue(all(29.94 <= float(ship["lat"]) <= 30.02 for ship in first))
        self.assertEqual(15, len({(ship["lng"], ship["lat"]) for ship in first}))


if __name__ == "__main__":
    unittest.main()
