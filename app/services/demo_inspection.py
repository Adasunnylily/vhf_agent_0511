from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from typing import Dict, List, Optional

from app.services.ws_manager import ChannelWebSocketManager


@dataclass(frozen=True)
class InspectionShip:
    ship_id: str
    ship_name: str
    tonnage_t: int
    draft_m: float
    ship_type: str
    destination: str
    position_label: str
    lng: float
    lat: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InspectionScenario:
    scenario_id: str
    scenario_name: str
    notice_template: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


DEFAULT_SHIPS: List[InspectionShip] = [
    InspectionShip("ship_hf32", "海丰32", 12800, 11.2, "集装箱船", "北仑港二期码头", "主航道A3段", 121.8572, 29.9374),
    InspectionShip("ship_ny8", "宁远8", 4600, 8.6, "杂货船", "锚地待泊", "主航道A3段", 121.8515, 29.9328),
    InspectionShip("ship_hl876", "货轮876", 22600, 13.5, "散货船", "穿越警戒线后进港", "警戒线北口", 121.8689, 29.9441),
    InspectionShip("ship_cy3", "长阳3", 9800, 10.4, "液货船", "内港调头区", "主航道B1段", 121.8436, 29.9289),
]

DEFAULT_SCENARIOS: List[InspectionScenario] = [
    InspectionScenario(
        scenario_id="cross_line",
        scenario_name="过线提醒",
        notice_template="{船名}，你船即将过线进入{区域}，请立即守听并按VTS指令通过。",
    ),
    InspectionScenario(
        scenario_id="speed_watch",
        scenario_name="限速守听",
        notice_template="{船名}，你船位于{区域}重点监控区，请控制航速并加强瞭望。",
    ),
    InspectionScenario(
        scenario_id="report_watch",
        scenario_name="点验报告",
        notice_template="{船名}，数字值班员提醒：你船已进入{区域}关注范围，请保持安全航速，加强瞭望并保持守听。",
    ),
]


class InspectionTaskSimulator:
    def __init__(
        self,
        ws_manager: ChannelWebSocketManager,
        playback_speed: float = 10.0,
        data_dir: Optional[Path] = None,
    ) -> None:
        self.ws_manager = ws_manager
        self.playback_speed = playback_speed
        self.data_dir = data_dir or Path("data")
        self.ships_path = self.data_dir / "inspection_ships.json"
        self.scenarios_path = self.data_dir / "inspection_scenarios.json"
        self._ships: List[InspectionShip] = self._load_or_init_ships()
        self._scenarios: List[InspectionScenario] = self._load_or_init_scenarios()

    def run(
        self,
        channel_id: str,
        area_name: str,
        min_draft_m: float,
        min_tonnage_t: int,
        notice_template: str,
        area_geometry: str = "",
        allowed_ship_types: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        matched = self.filter_ships(
            area_name=area_name,
            min_draft_m=min_draft_m,
            min_tonnage_t=min_tonnage_t,
            area_geometry=area_geometry,
            allowed_ship_types=allowed_ship_types,
        )
        notices = []

        self.ws_manager.publish(
            channel_id,
            {
                "type": "inspection_status",
                "stage": "started",
                "channel_id": channel_id,
                "area_name": area_name,
                "min_draft_m": min_draft_m,
                "min_tonnage_t": min_tonnage_t,
                "area_geometry": area_geometry,
            },
        )

        for ship in matched:
            notice_text = notice_template.replace("{船名}", ship.ship_name).replace("{区域}", area_name)
            payload = {
                "notice_id": f"notice_{uuid.uuid4().hex[:10]}",
                "ship": ship.to_dict(),
                "notice_text": notice_text,
            }
            notices.append(payload)
            self.ws_manager.publish(
                channel_id,
                {
                    "type": "inspection_notice",
                    "channel_id": channel_id,
                    "area_name": area_name,
                    "payload": payload,
                },
            )
            self._delay()

        meta = {
            "area_name": area_name,
            "min_draft_m": min_draft_m,
            "min_tonnage_t": min_tonnage_t,
            "area_geometry": area_geometry,
            "allowed_ship_types": allowed_ship_types or [],
            "matched_count": len(matched),
            "matched_ships": [ship.to_dict() for ship in matched],
            "notices": notices,
        }
        self.ws_manager.publish(
            channel_id,
            {
                "type": "inspection_status",
                "stage": "completed",
                "channel_id": channel_id,
                "meta": meta,
            },
        )
        return meta

    def list_mock_ships(self) -> List[Dict[str, object]]:
        return [ship.to_dict() for ship in self._ships]

    def add_ship(self, ship: InspectionShip) -> Dict[str, object]:
        if not ship.ship_id:
            ship = replace(ship, ship_id=f"ship_{uuid.uuid4().hex[:10]}")
        self._ships.append(ship)
        self._save_ships()
        return ship.to_dict()

    def remove_ship(self, ship_id: str) -> bool:
        target = ship_id.strip()
        if not target:
            return False
        before = len(self._ships)
        self._ships = [ship for ship in self._ships if ship.ship_id != target]
        removed = len(self._ships) < before
        if removed:
            self._save_ships()
        return removed

    def list_scenarios(self) -> List[Dict[str, object]]:
        return [item.to_dict() for item in self._scenarios]

    def add_scenario(self, scenario_name: str, notice_template: str) -> Dict[str, object]:
        scenario = InspectionScenario(
            scenario_id=f"custom_{uuid.uuid4().hex[:8]}",
            scenario_name=scenario_name.strip(),
            notice_template=notice_template.strip(),
        )
        self._scenarios.append(scenario)
        self._save_scenarios()
        return scenario.to_dict()

    def resolve_template(self, scenario_id: str, fallback_template: str) -> str:
        scenario_id = scenario_id.strip()
        if not scenario_id:
            return fallback_template
        for item in self._scenarios:
            if item.scenario_id == scenario_id:
                return item.notice_template
        return fallback_template

    def filter_ships(
        self,
        area_name: str,
        min_draft_m: float,
        min_tonnage_t: int,
        area_geometry: str = "",
        allowed_ship_types: Optional[List[str]] = None,
    ) -> List[InspectionShip]:
        geometry = self._parse_geometry(area_geometry)
        type_set = {item.strip() for item in (allowed_ship_types or []) if item.strip()}
        result: List[InspectionShip] = []
        for ship in self._ships:
            if ship.draft_m < min_draft_m:
                continue
            if ship.tonnage_t < min_tonnage_t:
                continue
            if type_set and ship.ship_type not in type_set:
                continue
            if geometry is not None and not self._matches_geometry(ship.position_label, geometry):
                continue
            if geometry is None and not self._matches_area(area_name, ship.position_label):
                continue
            result.append(ship)
        return result

    def build_notice_text(self, ship: InspectionShip, area_name: str, template: str) -> str:
        return template.replace("{船名}", ship.ship_name).replace("{区域}", area_name)

    def _delay(self) -> None:
        if self.playback_speed <= 0:
            return
        time.sleep(0.4 / self.playback_speed)

    def _matches_area(self, area_name: str, position_label: str) -> bool:
        if not area_name.strip():
            return True
        tokens = [
            token.upper()
            for token in area_name.replace("段", " ").replace("区", " ").replace("主航道", " ").split()
            if token
        ]
        if not tokens:
            return True
        upper_position = position_label.upper()
        return any(token in upper_position for token in tokens) or area_name[:2] in position_label

    def _parse_geometry(self, area_geometry: str) -> Optional[Dict[str, float]]:
        raw = area_geometry.strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            if data.get("type") not in {"rect", "line"}:
                return None
            return {k: float(v) if k != "type" else v for k, v in data.items()}  # type: ignore[return-value]
        except Exception:
            return None

    def _matches_geometry(self, position_label: str, geometry: Dict[str, float]) -> bool:
        x, y = self._mock_position_xy(position_label)
        shape_type = str(geometry.get("type", ""))
        if shape_type == "rect":
            x1 = float(geometry.get("lng1", geometry.get("x1", x)))
            y1 = float(geometry.get("lat1", geometry.get("y1", y)))
            x2 = float(geometry.get("lng2", geometry.get("x2", x)))
            y2 = float(geometry.get("lat2", geometry.get("y2", y)))
            left = min(x1, x2)
            right = max(x1, x2)
            top = min(y1, y2)
            bottom = max(y1, y2)
            return left <= x <= right and top <= y <= bottom
        if shape_type == "line":
            x1 = float(geometry.get("lng1", geometry.get("x1", x)))
            y1 = float(geometry.get("lat1", geometry.get("y1", y)))
            x2 = float(geometry.get("lng2", geometry.get("x2", x)))
            y2 = float(geometry.get("lat2", geometry.get("y2", y)))
            distance = self._point_to_segment_distance(x, y, x1, y1, x2, y2)
            return distance <= 0.01
        return False

    def _mock_position_xy(self, position_label: str) -> tuple[float, float]:
        for ship in self._ships:
            if ship.position_label == position_label:
                return ship.lng, ship.lat
        return 121.84, 29.92

    def _load_or_init_ships(self) -> List[InspectionShip]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.ships_path.exists():
            try:
                rows = json.loads(self.ships_path.read_text(encoding="utf-8"))
                ships: List[InspectionShip] = []
                for row in rows:
                    fingerprint = f"{row.get('ship_name', '')}_{row.get('lng', '')}_{row.get('lat', '')}"
                    fallback_id = f"ship_{uuid.uuid5(uuid.NAMESPACE_DNS, fingerprint).hex[:10]}"
                    ships.append(
                        InspectionShip(
                            ship_id=str(row.get("ship_id") or fallback_id),
                            ship_name=str(row["ship_name"]),
                            tonnage_t=int(row["tonnage_t"]),
                            draft_m=float(row["draft_m"]),
                            ship_type=str(row["ship_type"]),
                            destination=str(row["destination"]),
                            position_label=str(row["position_label"]),
                            lng=float(row["lng"]),
                            lat=float(row["lat"]),
                        )
                    )
                if ships:
                    return ships
            except Exception:
                pass
        self.ships_path.write_text(
            json.dumps([ship.to_dict() for ship in DEFAULT_SHIPS], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return list(DEFAULT_SHIPS)

    def _save_ships(self) -> None:
        self.ships_path.write_text(
            json.dumps([ship.to_dict() for ship in self._ships], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_or_init_scenarios(self) -> List[InspectionScenario]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.scenarios_path.exists():
            try:
                rows = json.loads(self.scenarios_path.read_text(encoding="utf-8"))
                scenarios = [
                    InspectionScenario(
                        scenario_id=str(row["scenario_id"]),
                        scenario_name=str(row["scenario_name"]),
                        notice_template=str(row["notice_template"]),
                    )
                    for row in rows
                ]
                if scenarios:
                    return scenarios
            except Exception:
                pass
        self.scenarios_path.write_text(
            json.dumps([item.to_dict() for item in DEFAULT_SCENARIOS], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return list(DEFAULT_SCENARIOS)

    def _save_scenarios(self) -> None:
        self.scenarios_path.write_text(
            json.dumps([item.to_dict() for item in self._scenarios], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _point_to_segment_distance(
        self,
        px: float,
        py: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> float:
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)
