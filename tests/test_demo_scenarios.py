import unittest

from app.services.demo_scenarios import ScenarioSimulator
from app.services.risk_engine import KeywordRiskEngine


class DummyWSManager:
    def publish(self, channel_id, payload) -> None:
        return None


class DemoScenarioTests(unittest.TestCase):
    def test_smoke_fire_scenario_produces_risk_event(self) -> None:
        simulator = ScenarioSimulator(
            risk_engine=KeywordRiskEngine(),
            ws_manager=DummyWSManager(),
            playback_speed=1000.0,
        )

        segments, events, meta = simulator.run("smoke_fire", "vhf_demo_01")

        self.assertGreaterEqual(len(segments), 1)
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(meta["scenario_id"], "smoke_fire")


if __name__ == "__main__":
    unittest.main()
