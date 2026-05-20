from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Dict, List

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
    ) -> Dict[str, object]:
        matched = [
            ship
            for ship in MOCK_SHIPS
            if ship.draft_m >= min_draft_m
            and ship.tonnage_t >= min_tonnage_t
            and self._matches_area(area_name, ship.position_label)
        ]
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
