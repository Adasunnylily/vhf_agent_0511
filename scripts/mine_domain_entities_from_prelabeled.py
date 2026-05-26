from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple


LOCATION_SUFFIXES = (
    "码头",
    "泊位",
    "号泊",
    "锚地",
    "警戒区",
    "航道",
    "水道",
    "报告线",
    "港区",
    "岛",
    "礁",
    "大桥",
)

SHIP_CONTEXT_WORDS = (
    "交管",
    "宁波交管",
    "舟山交管",
    "请讲",
    "叫",
    "呼叫",
)

BAD_CANDIDATES = {
    "宁波交管",
    "舟山交管",
    "宁波舟山交管",
    "交管",
    "老师",
    "船舶动态",
    "动态",
    "请讲",
    "收到",
    "好的",
    "谢谢",
    "报告",
    "注意",
    "安全",
    "申请",
    "可以",
    "现在",
    "这里",
    "前方",
    "左前方",
    "右前方",
    "进口",
    "出口",
    "进出口",
    "下一港",
    "穿越航道",
    "你走航道",
    "后方进口",
    "相关船舶",
    "过往船舶",
    "进口船",
    "出口船",
    "箱子船",
    "集装箱船",
    "外轮",
}

BAD_PREFIXES = ("你", "我", "他", "她", "它", "这", "那", "请", "注意", "保持", "收到", "好的")
BAD_SUBSTRINGS = ("注意", "谢谢", "收到", "交管", "老师", "船长", "安全", "联系", "保持", "动态")


def normalize_candidate(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^[，,。.\s、:：]+|[，,。.\s、:：]+$", "", text)
    text = re.sub(r"\s+", "", text)
    text = text.replace("幺", "1")
    return text


def load_existing_seed(seed_path: Path) -> Dict[str, Set[str]]:
    if not seed_path.exists():
        return {"ships": set(), "locations": set()}
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    return {
        "ships": {normalize_candidate(str(item)) for item in payload.get("ships", [])},
        "locations": {normalize_candidate(str(item)) for item in payload.get("locations", [])},
    }


def read_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_sentences(text: str) -> List[str]:
    return [item.strip() for item in re.split(r"[。！？!?；;\n]", text or "") if item.strip()]


def valid_candidate(text: str, min_len: int = 2, max_len: int = 14) -> bool:
    text = normalize_candidate(text)
    if len(text) < min_len or len(text) > max_len:
        return False
    if text in BAD_CANDIDATES:
        return False
    if text.startswith(BAD_PREFIXES):
        return False
    if any(item in text for item in BAD_SUBSTRINGS):
        return False
    if re.fullmatch(r"\d+", text):
        return False
    if re.search(r"[a-zA-Z]", text):
        return len(text) >= 3
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def add_candidate(
    counter: Counter,
    examples: Dict[str, List[str]],
    candidate: str,
    sample_id: str,
    sentence: str,
) -> None:
    candidate = normalize_candidate(candidate)
    if not valid_candidate(candidate):
        return
    counter[candidate] += 1
    if len(examples[candidate]) < 3:
        examples[candidate].append(f"{sample_id}: {sentence[:120]}")


def mine_locations(rows: Iterable[Dict[str, str]]) -> Tuple[Counter, Dict[str, List[str]]]:
    counter: Counter = Counter()
    examples: Dict[str, List[str]] = defaultdict(list)
    suffix_pattern = "|".join(re.escape(item) for item in LOCATION_SUFFIXES)
    pattern = re.compile(rf"([\u4e00-\u9fffA-Za-z0-9（）()#\-]{{1,14}}(?:{suffix_pattern}))")
    mouth_pattern = re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()#\-]{1,8}(?:东口|西口|南口|北口|溪口|门口|水门))")

    for row in rows:
        sample_id = row.get("sample_id", "")
        text = row.get("resolved_text_auto") or row.get("asr_text_auto") or ""
        for sentence in split_sentences(text):
            for match in pattern.finditer(sentence):
                candidate = match.group(1)
                add_candidate(counter, examples, candidate, sample_id, sentence)
            for match in mouth_pattern.finditer(sentence):
                candidate = match.group(1)
                add_candidate(counter, examples, candidate, sample_id, sentence)
    return counter, examples


def mine_ships(rows: Iterable[Dict[str, str]]) -> Tuple[Counter, Dict[str, List[str]]]:
    counter: Counter = Counter()
    examples: Dict[str, List[str]] = defaultdict(list)

    name_with_digit = re.compile(r"([\u4e00-\u9fff]{1,6}[0-9零一二三四五六七八九幺两]{1,5}(?:号|轮)?)")
    english_ship = re.compile(r"\b([A-Z][A-Z0-9]{1,}(?:\s+[A-Z0-9]{2,}){0,3})\b")
    before_context = re.compile(
        r"([\u4e00-\u9fffA-Za-z0-9零一二三四五六七八九幺两]{2,12})(?:，|,|、)?(?:"
        + "|".join(re.escape(item) for item in SHIP_CONTEXT_WORDS)
        + r")"
    )
    after_context = re.compile(
        r"(?:"
        + "|".join(re.escape(item) for item in SHIP_CONTEXT_WORDS)
        + r")(?:，|,|、)?([\u4e00-\u9fffA-Za-z0-9零一二三四五六七八九幺两]{2,12})"
    )

    for row in rows:
        sample_id = row.get("sample_id", "")
        text = row.get("resolved_text_auto") or row.get("asr_text_auto") or ""
        for sentence in split_sentences(text):
            for pattern in (name_with_digit, before_context, after_context, english_ship):
                for match in pattern.finditer(sentence):
                    candidate = match.group(1)
                    add_candidate(counter, examples, candidate, sample_id, sentence)
    return counter, examples


def score_candidate(candidate: str, count: int, entity_type: str, existing: Set[str]) -> int:
    score = min(60, count * 10)
    if candidate in existing:
        score += 40
    if entity_type == "location" and any(candidate.endswith(suffix) for suffix in LOCATION_SUFFIXES):
        score += 25
    if entity_type == "ship" and re.search(r"\d|[零一二三四五六七八九幺两]", candidate):
        score += 20
    if entity_type == "ship" and re.search(r"拖|引|海巡|港|轮", candidate):
        score += 12
    if len(candidate) in {4, 5, 6}:
        score += 8
    if candidate in BAD_CANDIDATES:
        score -= 80
    return max(0, min(100, score))


def build_review_rows(
    entity_type: str,
    counter: Counter,
    examples: Dict[str, List[str]],
    existing: Set[str],
    min_count: int,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for candidate, count in counter.items():
        if count < min_count and candidate not in existing:
            continue
        score = score_candidate(candidate, count, entity_type, existing)
        rows.append(
            {
                "entity_type": entity_type,
                "candidate": candidate,
                "count": count,
                "score": score,
                "already_in_seed": "yes" if candidate in existing else "no",
                "suggested_action": "accept" if score >= 70 and candidate not in existing else "review",
                "canonical_gt": "",
                "accept_gt": "",
                "examples": " || ".join(examples.get(candidate, [])),
            }
        )
    rows.sort(key=lambda row: (-int(row["score"]), -int(row["count"]), str(row["candidate"])))
    return rows


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "entity_type",
        "candidate",
        "count",
        "score",
        "already_in_seed",
        "suggested_action",
        "canonical_gt",
        "accept_gt",
        "examples",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: List[Dict[str, object]]) -> None:
    summary = {
        "total_candidates": len(rows),
        "ship_candidates": sum(1 for row in rows if row["entity_type"] == "ship"),
        "location_candidates": sum(1 for row in rows if row["entity_type"] == "location"),
        "suggested_accept": sum(1 for row in rows if row["suggested_action"] == "accept"),
        "top_ships": [row for row in rows if row["entity_type"] == "ship"][:20],
        "top_locations": [row for row in rows if row["entity_type"] == "location"][:20],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine ship/location candidates from ASR prelabel CSV.")
    parser.add_argument("--prelabel-csv", required=True, type=Path)
    parser.add_argument("--seed", type=Path, default=Path("data/bootstrap/nbzh_seed_entities.json"))
    parser.add_argument("--out", type=Path, default=Path("data/eval/entity_candidates_for_review.csv"))
    parser.add_argument("--summary-out", type=Path, default=Path("data/eval/entity_candidates_summary.json"))
    parser.add_argument("--min-count", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_rows(args.prelabel_csv)
    existing = load_existing_seed(args.seed)

    ship_counter, ship_examples = mine_ships(rows)
    location_counter, location_examples = mine_locations(rows)
    review_rows = [
        *build_review_rows("ship", ship_counter, ship_examples, existing["ships"], args.min_count),
        *build_review_rows("location", location_counter, location_examples, existing["locations"], args.min_count),
    ]
    review_rows.sort(key=lambda row: (-int(row["score"]), str(row["entity_type"]), -int(row["count"]), str(row["candidate"])))

    write_csv(args.out, review_rows)
    write_summary(args.summary_out, review_rows)
    print(f"[ok] rows={len(review_rows)} -> {args.out}")
    print(f"[ok] summary -> {args.summary_out}")


if __name__ == "__main__":
    main()
