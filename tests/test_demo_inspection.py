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


if __name__ == "__main__":
    unittest.main()
