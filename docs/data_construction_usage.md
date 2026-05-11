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

`weak_labeled_manifest.csv` 会包含以下业务字段：

```text
role_pred                  ship / operator / mixed / unclear
risk_category_pred         high_risk / non_high_risk / not_target
risk_label_pred            high / normal / uncertain / not_target
risk_type_pred             高危细分或非高危细分场景
scenario_pred              具体场景
automation_label_pred      manual_immediate / auto_reply / llm_advice / manual_or_rule_review / not_target
ship_keyword_hits          船方关键词命中
operator_keyword_hits      管理方关键词命中
risk_evidence              分类证据关键词
```

高危细分覆盖：

```text
collision, grounding_or_reef, fire_or_explosion, listing_or_capsize,
flooding_or_sinking, loss_control_or_mechanical_failure, anchor_dragging,
person_overboard_or_medical, piracy_or_armed_attack,
oil_or_dangerous_cargo_spill, aircraft_distress, confined_space_trapped
```

自动化标签含义：

```text
manual_immediate      高危，立即人工处理 + LLM建议
auto_reply            非高危可自动化回复 + TTS
llm_advice            非高危不可自动化，LLM给回复意见
manual_or_rule_review 非高危但需规则/人工再确认
not_target            非船方呼叫
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
human_risk_category
human_scenario
human_automation_label
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
