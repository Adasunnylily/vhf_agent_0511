#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List


def _write_csv(path: Path, header: List[str], rows: List[List[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create evaluation templates for VHF project.")
    parser.add_argument("--out-dir", default="data/eval", help="Output directory")
    parser.add_argument(
        "--ais-template-out",
        default="data/bootstrap/ais_ship_import_template.csv",
        help="AIS import CSV template path",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    ais_template_out = Path(args.ais_template_out)

    # A set: classification-focused labels, low annotation cost.
    a_header = [
        "audio_id",
        "segment_id",
        "audio_path",
        "channel_id",
        "business_type_gt",
        "risk_level_gt",
        "high_risk_flag_gt",
        "annotator",
        "notes",
    ]
    a_rows = [
        [
            "000001",
            "000001__seg000",
            "/path/to/000001.wav",
            "vhf_demo_01",
            "routine_report",
            "AUTO",
            "0",
            "",
            "",
        ]
    ]
    _write_csv(out_dir / "eval_set_A_classification.csv", a_header, a_rows)

    # B set: ASR + entities, used for CER/WER and entity hit rate.
    b_header = [
        "audio_id",
        "segment_id",
        "audio_path",
        "transcript_gt",
        "ship_name_gt",
        "location_gt",
        "callsign_gt",
        "mmsi_gt",
        "business_type_gt",
        "risk_level_gt",
        "annotator",
        "notes",
    ]
    b_rows = [
        [
            "000024",
            "000024__seg000",
            "/path/to/000024__seg000.wav",
            "锦龙008接码头通知，今天早晨不抛锚了，直接进去。",
            "锦龙008",
            "北仑山多用途码头",
            "",
            "",
            "routine_report",
            "AUTO",
            "",
            "",
        ]
    ]
    _write_csv(out_dir / "eval_set_B_asr_entity.csv", b_header, b_rows)

    # C set: streaming performance labels, used for latency and stability.
    c_header = [
        "audio_id",
        "audio_path",
        "mode",
        "t_start_speech_ms",
        "t_first_text_ms",
        "t_final_ms",
        "final_text_gt",
        "empty_chunk_count",
        "request_error_count",
        "notes",
    ]
    c_rows = [
        [
            "stream_0001",
            "/path/to/stream_0001.wav",
            "stream_sim|stream_replay|mic_stream",
            "",
            "",
            "",
            "",
            "0",
            "0",
            "",
        ]
    ]
    _write_csv(out_dir / "eval_set_C_stream_perf.csv", c_header, c_rows)

    # Combined template to simplify handoff.
    master_header = [
        "set_name",
        "audio_id",
        "segment_id",
        "audio_path",
        "transcript_gt",
        "ship_name_gt",
        "location_gt",
        "business_type_gt",
        "risk_level_gt",
        "t_start_speech_ms",
        "t_first_text_ms",
        "t_final_ms",
        "annotator",
        "notes",
    ]
    master_rows = [
        [
            "A_classification",
            "000001",
            "000001__seg000",
            "/path/to/000001.wav",
            "",
            "",
            "",
            "routine_report",
            "AUTO",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "B_asr_entity",
            "000024",
            "000024__seg000",
            "/path/to/000024__seg000.wav",
            "锦龙008接码头通知，今天早晨不抛锚了，直接进去。",
            "锦龙008",
            "北仑山多用途码头",
            "routine_report",
            "AUTO",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "C_stream_perf",
            "stream_0001",
            "",
            "/path/to/stream_0001.wav",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
    ]
    _write_csv(out_dir / "eval_master_template.csv", master_header, master_rows)

    ais_header = [
        "ship_name",
        "mmsi",
        "callsign",
        "imo",
        "ship_type",
        "tonnage_t",
        "draft_m",
        "length_m",
        "width_m",
        "sog_kn",
        "cog_deg",
        "heading_deg",
        "lng",
        "lat",
        "destination",
        "position_label",
        "nav_status",
        "cargo_type",
        "eta",
        "ais_update_time",
        "ais_source",
    ]
    ais_rows = [
        [
            "锦龙008",
            "413245008",
            "JL008",
            "",
            "集装箱船",
            "16800",
            "10.8",
            "172",
            "27",
            "7.2",
            "83",
            "84",
            "121.8842",
            "29.9138",
            "北仑山多用途码头",
            "北仑港主航道",
            "进港",
            "集装箱",
            "今日16:30",
            "2026-05-31T09:00:00+08:00",
            "mock_csv",
        ],
        [
            "锦华662",
            "413000662",
            "JH662",
            "",
            "杂货船",
            "9800",
            "8.7",
            "128",
            "20",
            "4.3",
            "62",
            "63",
            "121.8736",
            "29.9234",
            "北仑司2号泊",
            "北仑港主航道",
            "航行中",
            "杂货",
            "今日17:10",
            "2026-05-31T09:01:00+08:00",
            "mock_csv",
        ],
    ]
    _write_csv(ais_template_out, ais_header, ais_rows)

    print(f"Created eval templates in: {out_dir.resolve()}")
    print(f"Created AIS template in: {ais_template_out.resolve()}")


if __name__ == "__main__":
    main()
