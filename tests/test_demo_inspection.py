import unittest

from app.services.demo_inspection import InspectionTaskSimulator


class DummyWSManager:
    def publish(self, channel_id, payload) -> None:
        return None


class DemoInspectionTests(unittest.TestCase):
    def test_inspection_task_matches_large_draft_ships(self) -> None:
        simulator = InspectionTaskSimulator(ws_manager=DummyWSManager(), playback_speed=1000.0)

        meta = simulator.run(
            channel_id="vhf_demo_01",
            area_name="北仑主航道A3段",
            min_draft_m=10.0,
            min_tonnage_t=5000,
            notice_template="{船名}，请注意，您已进入{区域}。",
        )

        self.assertGreaterEqual(meta["matched_count"], 1)
        self.assertGreaterEqual(len(meta["notices"]), 1)

    def test_filter_ships_by_type_and_geometry(self) -> None:
        simulator = InspectionTaskSimulator(ws_manager=DummyWSManager(), playback_speed=1000.0)

        # 框选 A3 近似区域，只允许集装箱船
        geometry = '{"type":"rect","x1":150,"y1":160,"x2":260,"y2":260}'
        matched = simulator.filter_ships(
            area_name="",
            min_draft_m=9.0,
            min_tonnage_t=10000,
            area_geometry=geometry,
            allowed_ship_types=["集装箱船"],
        )

        self.assertGreaterEqual(len(matched), 1)
        self.assertTrue(all(ship.ship_type == "集装箱船" for ship in matched))


if __name__ == "__main__":
    unittest.main()
