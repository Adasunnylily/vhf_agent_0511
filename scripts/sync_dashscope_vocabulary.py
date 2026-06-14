#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_env(REPO_ROOT / ".env")

from app.services.asr_prompts import (  # noqa: E402
    build_dashscope_vocabulary_entries,
    default_hotwords_path,
    default_vocabulary_cache_path,
    resolve_paraformer_model,
    save_dashscope_vocabulary_id,
    sync_dashscope_vocabulary,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create DashScope vocabulary from nbzh_hotwords.txt")
    parser.add_argument(
        "--hotwords-path",
        type=Path,
        default=default_hotwords_path(),
        help="Hotword source file",
    )
    parser.add_argument(
        "--target-model",
        default=os.getenv("VHF_ASR_VOCABULARY_TARGET_MODEL", os.getenv("VHF_ASR_MODEL", "paraformer-v2")),
        help="Must match Recognition model, e.g. paraformer-realtime-v2",
    )
    parser.add_argument(
        "--prefix",
        default=os.getenv("VHF_ASR_VOCABULARY_PREFIX", "vhfnbzh"),
        help="DashScope vocabulary prefix",
    )
    parser.add_argument(
        "--weight",
        type=int,
        default=int(os.getenv("VHF_ASR_VOCABULARY_WEIGHT", "4")),
        help="Hotword weight in [1, 5]",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Create a new vocabulary even if cache exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print converted vocabulary entries",
    )
    args = parser.parse_args()

    target_model = resolve_paraformer_model(args.target_model)
    entries = build_dashscope_vocabulary_entries(args.hotwords_path, weight=max(1, min(5, args.weight)))
    print(f"target_model={target_model}")
    print(f"hotwords_path={args.hotwords_path}")
    print(f"valid_entries={len(entries)}")
    if args.dry_run:
        for item in entries[:10]:
            print(item)
        if len(entries) > 10:
            print(f"... and {len(entries) - 10} more")
        return

    vocabulary_id = sync_dashscope_vocabulary(
        target_model=target_model,
        prefix=args.prefix,
        hotwords_path=args.hotwords_path,
        weight=max(1, min(5, args.weight)),
        replace_existing=args.replace,
    )
    cache_path = default_vocabulary_cache_path()
    print(f"vocabulary_id={vocabulary_id}")
    print(f"cache={cache_path}")
    print("请在 .env 中设置：")
    print(f"VHF_ASR_VOCABULARY_ID={vocabulary_id}")
    print(f"VHF_ASR_VOCABULARY_TARGET_MODEL={target_model}")


if __name__ == "__main__":
    main()
