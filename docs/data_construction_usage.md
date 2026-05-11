# 船方呼叫高危分类数据构造代码使用说明

主脚本：

```text
scripts/construct_high_risk_dataset.py
```

## 一键跑完整流程

输入是连续混合 VHF 音频目录：

```bash
python scripts/construct_high_risk_dataset.py run-all \
  --audio-dir /root/autodl-tmp/vhf-data/raw_audio \
  --output-dir /root/autodl-tmp/vhf-data/data_pipeline \
  --channel-id beilun_vhf_01 \
  --device cuda:0 \
  --review-limit 500
```

输出：

```text
/root/autodl-tmp/vhf-data/data_pipeline/
├── clips/
│   ├── normalized/
│   └── vad_segments/
├── manifests/
│   ├── raw_audio_manifest.csv
│   ├── vad_segments_manifest.csv
│   ├── asr_segments_manifest.csv
│   ├── weak_labeled_manifest.csv
│   └── human_review_manifest.csv
└── reports/
    └── label_stats.json
```

## 分步运行

### 1. 原始音频清单

```bash
python scripts/construct_high_risk_dataset.py raw-manifest \
  --audio-dir /root/autodl-tmp/vhf-data/raw_audio \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/raw_audio_manifest.csv \
  --channel-id beilun_vhf_01
```

### 2. VAD 切分

```bash
python scripts/construct_high_risk_dataset.py vad-split \
  --raw-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/raw_audio_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --clip-dir /root/autodl-tmp/vhf-data/data_pipeline/clips/vad_segments \
  --normalized-dir /root/autodl-tmp/vhf-data/data_pipeline/clips/normalized \
  --max-segment-ms 8000 \
  --energy-threshold 450
```

### 3. ASR 转写

```bash
python scripts/construct_high_risk_dataset.py asr-transcribe \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --model iic/SenseVoiceSmall \
  --asr-vad-model fsmn-vad \
  --device cuda:0
```

先抽样 50 条：

```bash
python scripts/construct_high_risk_dataset.py asr-transcribe \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest_sample.csv \
  --limit 50
```

### 4. 角色识别 + 高危弱标签

```bash
python scripts/construct_high_risk_dataset.py weak-label \
  --asr-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/weak_labeled_manifest.csv \
  --stats-output /root/autodl-tmp/vhf-data/data_pipeline/reports/label_stats.json
```

### 5. 生成人工复核表

```bash
python scripts/construct_high_risk_dataset.py review-manifest \
  --weak-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/weak_labeled_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/human_review_manifest.csv \
  --limit 500
```

## 人工标注字段

在 `human_review_manifest.csv` 中补：

```text
human_role
human_risk_label
human_risk_type
human_reference_text
notes
```

推荐取值：

```text
human_role: ship / operator / mixed / unclear
human_risk_label: high / normal / uncertain / not_target
human_risk_type: fire_smoke / flooding / person_overboard / collision / grounding / loss_control_or_power / routine_report / manual_business / unknown
```

## 注意

- 第一次跑 ASR 会下载模型，可能比较慢。
- 不要并发跑多个 `asr-transcribe`，避免显存/内存压力。
- 如果服务器显存不够，可先用 `--device cpu` 跑小样本验证流程。
