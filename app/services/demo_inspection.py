from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
import json
import math
from typing import Dict, List, Optional

from app.services.ws_manager import ChannelWebSocketManager


@dataclass(frozen=True)
class InspectionShip:
    ship_name: str
    tonnage_t: int
    draft_m: float
    ship_type: str
    destination: str
    position_label: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


MOCK_SHIPS: List[InspectionShip] = [
    InspectionShip("海丰32", 12800, 11.2, "集装箱船", "北仑港二期码头", "主航道A3段"),
    InspectionShip("宁远8", 4600, 8.6, "杂货船", "锚地待泊", "主航道A3段"),
    InspectionShip("货轮876", 22600, 13.5, "散货船", "穿越警戒线后进港", "警戒线北口"),
    InspectionShip("长阳3", 9800, 10.4, "液货船", "内港调头区", "主航道B1段"),
]


class InspectionTaskSimulator:
    def __init__(self, ws_manager: ChannelWebSocketManager, playback_speed: float = 10.0) -> None:
        self.ws_manager = ws_manager
        self.playback_speed = playback_speed

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
        return [ship.to_dict() for ship in MOCK_SHIPS]

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
        for ship in MOCK_SHIPS:
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
            x1 = float(geometry.get("x1", x))
            y1 = float(geometry.get("y1", y))
            x2 = float(geometry.get("x2", x))
            y2 = float(geometry.get("y2", y))
            left = min(x1, x2)
            right = max(x1, x2)
            top = min(y1, y2)
            bottom = max(y1, y2)
            return left <= x <= right and top <= y <= bottom
        if shape_type == "line":
            x1 = float(geometry.get("x1", x))
            y1 = float(geometry.get("y1", y))
            x2 = float(geometry.get("x2", x))
            y2 = float(geometry.get("y2", y))
            distance = self._point_to_segment_distance(x, y, x1, y1, x2, y2)
            return distance <= 35.0
        return False

    def _mock_position_xy(self, position_label: str) -> tuple[float, float]:
        mapping = {
            "主航道A3段": (200.0, 210.0),
            "警戒线北口": (440.0, 150.0),
            "主航道B1段": (320.0, 280.0),
        }
        return mapping.get(position_label, (280.0, 220.0))

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
