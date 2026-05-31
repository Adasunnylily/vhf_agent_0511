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
    mmsi: str = ""
    callsign: str = ""
    imo: str = ""
    length_m: float = 0.0
    width_m: float = 0.0
    sog_kn: float = 0.0
    cog_deg: float = 0.0
    heading_deg: float = 0.0
    nav_status: str = "under_way"
    cargo_type: str = ""
    eta: str = ""
    ais_update_time: str = ""
    ais_source: str = "mock"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InspectionScenario:
    scenario_id: str
    scenario_name: str
    notice_template: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InspectionArea:
    area_id: str
    area_name: str
    geometry_type: str
    geometry: List[List[float]]
    line_buffer_m: float = 500.0
    enabled: bool = True

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


DEFAULT_SHIPS: List[InspectionShip] = [
    InspectionShip("ship_jl008", "锦龙008", 16800, 10.8, "集装箱船", "北仑山多用途码头", "北仑港主航道", 121.8842, 29.9138, "413245008", "JL008", "", 172, 27, 7.2, 83, 84, "进港", "集装箱", "今日 16:30", "", "mock_ais"),
    InspectionShip("ship_jh662", "锦华662", 9800, 8.7, "杂货船", "北仑司2号泊", "北仑港主航道", 121.8736, 29.9234, "413000662", "JH662", "", 128, 20, 4.3, 62, 63, "航行中", "杂货", "今日 17:10", "", "mock_ais"),
    InspectionShip("ship_zgyc", "中国银川", 22600, 13.5, "散货船", "算山6号泊", "北仑港警戒区北口", 121.9005, 29.9342, "413512345", "CN-YC", "", 198, 32, 6.8, 112, 110, "进港", "散货", "今日 18:00", "", "mock_ais"),
    InspectionShip("ship_yg20", "甬港拖20", 4600, 5.2, "拖船", "协和码头", "北仑港内港水域", 121.8585, 29.9058, "412320020", "YGT20", "", 38, 10, 9.5, 126, 128, "作业中", "拖带", "待定", "", "mock_ais"),
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

DEFAULT_AREAS: List[InspectionArea] = [
    InspectionArea(
        area_id="area_beilun_a3",
        area_name="北仑主航道A3段",
        geometry_type="polygon",
        geometry=[
            [121.855, 29.902],
            [121.915, 29.902],
            [121.915, 29.945],
            [121.855, 29.945],
        ],
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
        self.areas_path = self.data_dir / "inspection_areas.json"
        self._ships: List[InspectionShip] = self._load_or_init_ships()
        self._scenarios: List[InspectionScenario] = self._load_or_init_scenarios()
        self._areas: List[InspectionArea] = self._load_or_init_areas()

    def run(
        self,
        channel_id: str,
        area_name: str,
        min_draft_m: float,
        min_tonnage_t: int,
        notice_template: str,
        area_geometry: str = "",
        allowed_ship_types: Optional[List[str]] = None,
        min_speed_kn: float = 0.0,
        max_speed_kn: float = 999.0,
        destination_keyword: str = "",
    ) -> Dict[str, object]:
        matched = self.filter_ships(
            area_name=area_name,
            min_draft_m=min_draft_m,
            min_tonnage_t=min_tonnage_t,
            area_geometry=area_geometry,
            allowed_ship_types=allowed_ship_types,
            min_speed_kn=min_speed_kn,
            max_speed_kn=max_speed_kn,
            destination_keyword=destination_keyword,
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
            notice_text = self.build_notice_text(ship, area_name, notice_template)
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
            "min_speed_kn": min_speed_kn,
            "max_speed_kn": max_speed_kn,
            "destination_keyword": destination_keyword,
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

    def upsert_ships(self, ships: List[InspectionShip]) -> Dict[str, object]:
        existing = {self._ship_key(ship): ship for ship in self._ships}
        created = 0
        updated = 0
        for ship in ships:
            if not ship.ship_id:
                ship = replace(ship, ship_id=f"ship_{uuid.uuid4().hex[:10]}")
            key = self._ship_key(ship)
            if key in existing:
                updated += 1
            else:
                created += 1
            existing[key] = ship
        self._ships = list(existing.values())
        self._save_ships()
        return {"created": created, "updated": updated, "total": len(self._ships)}

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

    def list_areas(self) -> List[Dict[str, object]]:
        return [item.to_dict() for item in self._areas]

    def add_area(
        self,
        area_name: str,
        geometry_type: str,
        geometry: List[List[float]],
        line_buffer_m: float = 500.0,
    ) -> Dict[str, object]:
        area = InspectionArea(
            area_id=f"area_{uuid.uuid4().hex[:10]}",
            area_name=area_name.strip(),
            geometry_type=geometry_type.strip(),
            geometry=geometry,
            line_buffer_m=float(line_buffer_m),
        )
        self._areas.append(area)
        self._save_areas()
        return area.to_dict()

    def remove_area(self, area_id: str) -> bool:
        before = len(self._areas)
        self._areas = [area for area in self._areas if area.area_id != area_id.strip()]
        removed = len(self._areas) < before
        if removed:
            self._save_areas()
        return removed

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
        min_speed_kn: float = 0.0,
        max_speed_kn: float = 999.0,
        destination_keyword: str = "",
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
            if ship.sog_kn < min_speed_kn or ship.sog_kn > max_speed_kn:
                continue
            if destination_keyword.strip() and destination_keyword.strip() not in ship.destination:
                continue
            if geometry is not None and not self._matches_geometry(ship, geometry):
                continue
            if geometry is None and not self._matches_area(area_name, ship.position_label):
                continue
            result.append(ship)
        return result

    def build_notice_text(self, ship: InspectionShip, area_name: str, template: str) -> str:
        values = {
            "船名": ship.ship_name,
            "区域": area_name,
            "MMSI": ship.mmsi,
            "呼号": ship.callsign,
            "船型": ship.ship_type,
            "吃水": f"{ship.draft_m:g}",
            "吨位": str(ship.tonnage_t),
            "航速": f"{ship.sog_kn:g}",
            "航向": f"{ship.heading_deg:g}",
            "目的地": ship.destination,
            "位置": ship.position_label,
        }
        text = template
        for key, value in values.items():
            text = text.replace("{" + key + "}", str(value))
        return text

    def find_ship_context(self, text: str) -> Optional[Dict[str, object]]:
        needle = (text or "").strip()
        if not needle:
            return None
        for ship in self._ships:
            values = [ship.ship_name, ship.mmsi, ship.callsign]
            if any(value and value in needle for value in values):
                return ship.to_dict()
        return None

    def dynamic_lexicon_payload(self) -> Dict[str, List[Dict[str, object]]]:
        ships = []
        for ship in self._ships:
            aliases = [ship.ship_name]
            if ship.callsign:
                aliases.append(ship.callsign)
            if ship.mmsi:
                aliases.append(ship.mmsi)
            # VHF常把阿拉伯数字读成中文数字，这里为常见船名生成一组轻量别名。
            spoken = self._spoken_number_alias(ship.ship_name)
            if spoken != ship.ship_name:
                aliases.append(spoken)
            ships.append(
                {
                    "canonical": ship.ship_name,
                    "aliases": sorted(set(alias for alias in aliases if alias)),
                    "source": "ais_active",
                    "metadata": ship.to_dict(),
                }
            )
        locations = sorted(
            set(
                value
                for ship in self._ships
                for value in [ship.destination, ship.position_label]
                if value
            )
        )
        return {
            "ships": ships,
            "locations": [
                {"canonical": item, "aliases": [item], "source": "ais_active"}
                for item in locations
            ],
        }

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

    def _parse_geometry(self, area_geometry: str) -> Optional[Dict[str, object]]:
        raw = area_geometry.strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            if data.get("type") not in {"rect", "line", "polygon"}:
                return None
            return data
        except Exception:
            return None

    def _matches_geometry(self, ship: InspectionShip, geometry: Dict[str, object]) -> bool:
        x, y = ship.lng, ship.lat
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
            buffer_m = float(geometry.get("line_buffer_m", 500.0))
            return distance <= max(0.0001, buffer_m / 111_000.0)
        if shape_type == "polygon":
            raw_points = geometry.get("points", geometry.get("geometry", []))
            if not isinstance(raw_points, list):
                return False
            points = [
                (float(point[0]), float(point[1]))
                for point in raw_points
                if isinstance(point, list) and len(point) >= 2
            ]
            return self._point_in_polygon(x, y, points)
        return False

    @staticmethod
    def _point_in_polygon(x: float, y: float, points: List[tuple[float, float]]) -> bool:
        if len(points) < 3:
            return False
        inside = False
        previous = points[-1]
        for current in points:
            x1, y1 = previous
            x2, y2 = current
            intersects = ((y1 > y) != (y2 > y)) and (
                x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            )
            if intersects:
                inside = not inside
            previous = current
        return inside

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
                        self._ship_from_row(row, fallback_id=fallback_id)
                    )
                if ships:
                    merged = self._merge_seed_ships(ships)
                    if len(merged) != len(ships):
                        self._ships = merged
                        self._save_ships()
                    return merged
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

    def _load_or_init_areas(self) -> List[InspectionArea]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.areas_path.exists():
            try:
                rows = json.loads(self.areas_path.read_text(encoding="utf-8"))
                areas = [
                    InspectionArea(
                        area_id=str(row["area_id"]),
                        area_name=str(row["area_name"]),
                        geometry_type=str(row["geometry_type"]),
                        geometry=[
                            [float(point[0]), float(point[1])]
                            for point in row.get("geometry", [])
                        ],
                        line_buffer_m=float(row.get("line_buffer_m", 500.0)),
                        enabled=bool(row.get("enabled", True)),
                    )
                    for row in rows
                ]
                if areas:
                    return areas
            except Exception:
                pass
        self.areas_path.write_text(
            json.dumps([item.to_dict() for item in DEFAULT_AREAS], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return list(DEFAULT_AREAS)

    def _save_areas(self) -> None:
        self.areas_path.write_text(
            json.dumps([item.to_dict() for item in self._areas], ensure_ascii=False, indent=2),
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

    def _ship_from_row(self, row: Dict[str, object], fallback_id: str = "") -> InspectionShip:
        return InspectionShip(
            ship_id=str(row.get("ship_id") or fallback_id or f"ship_{uuid.uuid4().hex[:10]}"),
            ship_name=str(row.get("ship_name") or row.get("name") or "").strip(),
            tonnage_t=int(self._safe_float(row.get("tonnage_t") or row.get("tonnage") or row.get("dwt"), 0)),
            draft_m=self._safe_float(row.get("draft_m") or row.get("draft"), 0),
            ship_type=str(row.get("ship_type") or row.get("type") or "其他").strip(),
            destination=str(row.get("destination") or row.get("dest") or "待定").strip(),
            position_label=str(row.get("position_label") or row.get("area") or "AIS目标").strip(),
            lng=self._safe_float(row.get("lng") or row.get("longitude"), 0),
            lat=self._safe_float(row.get("lat") or row.get("latitude"), 0),
            mmsi=str(row.get("mmsi") or "").strip(),
            callsign=str(row.get("callsign") or row.get("call_sign") or "").strip(),
            imo=str(row.get("imo") or "").strip(),
            length_m=self._safe_float(row.get("length_m") or row.get("length"), 0),
            width_m=self._safe_float(row.get("width_m") or row.get("width"), 0),
            sog_kn=self._safe_float(row.get("sog_kn") or row.get("sog") or row.get("speed"), 0),
            cog_deg=self._safe_float(row.get("cog_deg") or row.get("cog"), 0),
            heading_deg=self._safe_float(row.get("heading_deg") or row.get("heading"), 0),
            nav_status=str(row.get("nav_status") or row.get("status") or "under_way").strip(),
            cargo_type=str(row.get("cargo_type") or row.get("cargo") or "").strip(),
            eta=str(row.get("eta") or "").strip(),
            ais_update_time=str(row.get("ais_update_time") or row.get("update_time") or "").strip(),
            ais_source=str(row.get("ais_source") or row.get("source") or "manual").strip(),
        )

    def _ship_key(self, ship: InspectionShip) -> str:
        if ship.mmsi:
            return f"mmsi:{ship.mmsi}"
        if ship.callsign:
            return f"callsign:{ship.callsign}"
        return f"name:{ship.ship_name}"

    def _merge_seed_ships(self, ships: List[InspectionShip]) -> List[InspectionShip]:
        existing_keys = {self._ship_key(ship) for ship in ships}
        merged = list(ships)
        for seed in DEFAULT_SHIPS:
            if self._ship_key(seed) not in existing_keys:
                merged.append(seed)
        return merged

    def _spoken_number_alias(self, value: str) -> str:
        table = str.maketrans("0123456789", "零一二三四五六七八九")
        return value.translate(table)

    def _safe_float(self, value: object, default: float) -> float:
        try:
            if value is None or str(value).strip() == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default
