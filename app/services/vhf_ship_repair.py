from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Tuple

from app.config import settings

SHIP_TOKEN = re.compile(r"([\u4e00-\u9fa5]{1,6}\d{2,4})")


@lru_cache(maxsize=1)
def _ship_alias_map() -> List[Tuple[str, str]]:
    path = settings.entity_lexicon_path
    if not path.is_file():
        fallback = Path("data/lexicon_corrections.json")
        path = fallback if fallback.is_file() else path
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    pairs: List[Tuple[str, str]] = []
    for item in payload.get("ships", []):
        canonical = str(item.get("canonical") or "").strip()
        if not canonical:
            continue
        for alias in [canonical, *(item.get("aliases") or [])]:
            alias_text = str(alias).strip()
            if alias_text and alias_text != canonical:
                pairs.append((alias_text, canonical))
    return sorted(pairs, key=lambda item: len(item[0]), reverse=True)


def apply_lexicon_ship_repair(text: str) -> str:
    resolved = text or ""
    for alias, canonical in _ship_alias_map():
        if alias in resolved:
            resolved = resolved.replace(alias, canonical)
    return resolved


def apply_common_vhf_repairs(text: str) -> str:
    resolved = text or ""
    replacements = [
        (r"波舟山交管", "宁波舟山交管"),
        (r"宁波舟山交管警(\d+)", r"宁波舟山交管，锦龙\1"),
        (r"交管警(\d+)救", r"锦龙\1叫"),
        (r"119请讲", "请讲"),
        (r"金塘南抛锚线", "金塘南抛锚"),
        (r"黄牛礁进[xX]口", "黄牛礁进口"),
        (r"二期注意安全", "好的，注意安全"),
        (r"谢谢指挥指挥", "谢谢交管"),
        (r"向应报告报", "向你报告"),
    ]
    for pattern, value in replacements:
        resolved = re.sub(pattern, value, resolved)
    return resolved


def repair_ship_names_in_text(text: str) -> str:
    resolved = apply_common_vhf_repairs(text)
    resolved = apply_lexicon_ship_repair(resolved)
    return resolved


def top_ship_candidates(text: str, limit: int = 6) -> List[str]:
    hits = []
    for alias, canonical in _ship_alias_map():
        if alias in (text or "") and canonical not in hits:
            hits.append(canonical)
        if len(hits) >= limit:
            break
    for token in SHIP_TOKEN.findall(text or ""):
        if token not in hits:
            hits.append(token)
    return hits[:limit]
