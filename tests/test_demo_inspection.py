import unittest

from app.services.demo_inspection import InspectionShip, InspectionTaskSimulator


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

        # 框选锦龙228附近水域，只允许集装箱船
        geometry = '{"type":"rect","x1":121.86,"y1":29.96,"x2":121.88,"y2":29.98}'
        matched = simulator.filter_ships(
            area_name="",
            min_draft_m=9.0,
            min_tonnage_t=10000,
            area_geometry=geometry,
            allowed_ship_types=["集装箱船"],
        )

        self.assertGreaterEqual(len(matched), 1)
        self.assertTrue(all(ship.ship_type == "集装箱船" for ship in matched))

    def test_filter_ships_near_inspection_line(self) -> None:
        simulator = InspectionTaskSimulator(ws_manager=DummyWSManager(), playback_speed=1000.0)

        geometry = (
            '{"type":"line","points":[[121.91,29.9547],[121.925,29.9547]],'
            '"line_buffer_m":300}'
        )
        matched = simulator.filter_ships(
            area_name="",
            min_draft_m=0,
            min_tonnage_t=0,
            area_geometry=geometry,
        )

        self.assertIn("锦华662", [ship.ship_name for ship in matched])

    def test_polygon_includes_ship_on_boundary(self) -> None:
        simulator = InspectionTaskSimulator(ws_manager=DummyWSManager(), playback_speed=1000.0)
        simulator._ships = [
            InspectionShip(
                "boundary",
                "边界测试船",
                5000,
                6.0,
                "杂货船",
                "",
                "",
                121.88,
                29.92,
            )
        ]

        matched = simulator.filter_ships(
            area_name="",
            min_draft_m=0,
            min_tonnage_t=0,
            area_geometry=(
                '{"type":"polygon","points":['
                '[121.87,29.91],[121.88,29.92],[121.89,29.91],[121.87,29.91]]}'
            ),
        )

        self.assertEqual(["边界测试船"], [ship.ship_name for ship in matched])

    def test_specific_ship_ids_bypass_area_name_filter(self) -> None:
        simulator = InspectionTaskSimulator(ws_manager=DummyWSManager(), playback_speed=1000.0)

        matched = simulator.filter_ships(
            area_name="不存在的区域",
            min_draft_m=0,
            min_tonnage_t=0,
            specific_ship_ids=["mock_002"],
        )

        self.assertEqual(["锦华662"], [ship.ship_name for ship in matched])

    def test_list_mock_ships_limits_to_named_ships(self) -> None:
        simulator = InspectionTaskSimulator(ws_manager=DummyWSManager(), playback_speed=1000.0)
        simulator._ships = [
            InspectionShip(
                ship_id=f"ship_{index}",
                ship_name=f"示例船{index}",
                tonnage_t=1000 + index,
                draft_m=3.0,
                ship_type="杂货船",
                destination="北仑",
                position_label="北仑港",
                lng=121.8 + index * 0.001,
                lat=29.9 + index * 0.001,
            )
            for index in range(20)
        ] + [
            InspectionShip(
                ship_id="ship_mmsi_1",
                ship_name="MMSI_123456789",
                tonnage_t=999,
                draft_m=2.0,
                ship_type="其他",
                destination="北仑",
                position_label="北仑港",
                lng=121.7,
                lat=29.8,
            )
        ]

        items = simulator.list_mock_ships()

        self.assertEqual(15, len(items))
        self.assertTrue(all(not str(item["ship_name"]).startswith("MMSI_") for item in items))

    def test_nearby_ships_returns_named_targets_by_distance(self) -> None:
        simulator = InspectionTaskSimulator(ws_manager=DummyWSManager(), playback_speed=1000.0)
        simulator._ships = [
            InspectionShip("risk", "高危船", 5000, 6.0, "杂货船", "", "", 121.88, 29.92),
            InspectionShip("near", "附近船", 5000, 6.0, "杂货船", "", "", 121.881, 29.92),
            InspectionShip("far", "远处船", 5000, 6.0, "杂货船", "", "", 122.1, 30.1),
            InspectionShip("hidden", "MMSI_123456789", 5000, 6.0, "杂货船", "", "", 121.8805, 29.92),
        ]

        items = simulator.nearby_ships(
            lng=121.88,
            lat=29.92,
            radius_m=1000,
            exclude_ship_id="risk",
        )

        self.assertEqual(["附近船"], [item["ship_name"] for item in items])
        self.assertLess(items[0]["distance_m"], 200)


if __name__ == "__main__":
    unittest.main()
