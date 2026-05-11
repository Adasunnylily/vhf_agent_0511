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
│   ├── machine_analysis_manifest.csv
│   └── human_review_manifest.csv
└── reports/
    └── label_stats.json
```

`machine_analysis_manifest.csv` 会包含以下业务字段。这里的结果是“机器分析候选”，不是最终人工标签：

```text
asr_model                  当前转写使用的ASR模型
asr_text                   当前ASR模型输出文本
analysis_source            llm_analysis / audio_model_analysis / rule_fallback
role_pred                  ship / operator / mixed / unclear
crisis_label_pred          crisis / non_crisis / uncertain / not_target
automation_label_pred      manual_immediate / auto_reply / llm_advice / not_target
scenario_pred              LLM/音频大模型/兜底规则给出的场景
analysis_evidence          分析证据
analysis_rationale         分析理由
analysis_disagreement      LLM和音频大模型是否存在分歧
ship_keyword_hits          兜底规则命中的船方关键词，仅供参考
operator_keyword_hits      兜底规则命中的管理方关键词，仅供参考
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
  --silence-ms 1200 \
  --max-segment-ms 0 \
  --energy-threshold 450
```

注意：即使原文件后缀是 `.wav`，脚本也会检查是否为标准 `16k / mono / PCM s16le`。如果是 A-law、mu-law 等非 PCM WAV，会自动用 `ffmpeg` 转码后再 VAD，避免 `wave.Error: unknown format`。

`--max-segment-ms 0` 表示不按固定时长强切，而是根据静音间隔切分话轮。这样得到的是“连续说话片段/话轮”，不是声纹级说话人分离。船方/管理方划分会在 ASR 之后由 LLM/音频大模型或人工核实完成。

如果一个人连续讲很久导致片段过长，再临时设置：

```bash
--max-segment-ms 30000
```

不要再用 7000/8000 这类短固定窗口做数据集标签，否则会破坏完整船方呼叫。

### 3. 先抽样选择ASR模型

```bash
python scripts/run_asr_model_selection.py \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --config configs/asr_models_0511.json \
  --models sensevoice_small,paraformer_large_zh \
  --output-dir /root/autodl-tmp/vhf-data/data_pipeline/asr_selection \
  --limit 50 \
  --device cuda:0
```

优先查看：

```text
/root/autodl-tmp/vhf-data/data_pipeline/asr_selection/asr_selection_wide.csv
```

同一条音频会并排展示多个ASR模型结果，便于人工判断哪个模型更适合当前VHF数据。

### 4. 选定ASR模型后全量转写

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

### 5. 导入LLM/音频大模型分析，生成机器分析候选

如果暂时没有 LLM 或音频大模型结果，只用规则兜底：

```bash
python scripts/construct_high_risk_dataset.py weak-label \
  --asr-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv \
  --stats-output /root/autodl-tmp/vhf-data/data_pipeline/reports/label_stats.json
```

如果已有 LLM 分析结果：

```bash
python scripts/construct_high_risk_dataset.py weak-label \
  --asr-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --llm-analysis /root/autodl-tmp/vhf-data/data_pipeline/llm_analysis.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv
```

如果已有音频大模型结果：

```bash
python scripts/construct_high_risk_dataset.py weak-label \
  --asr-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --llm-analysis /root/autodl-tmp/vhf-data/data_pipeline/llm_analysis.csv \
  --audio-analysis /root/autodl-tmp/vhf-data/data_pipeline/audio_model_analysis.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv
```

`llm_analysis.csv` 和 `audio_model_analysis.csv` 字段：

```text
segment_id,role_label,role_confidence,crisis_label,crisis_confidence,automation_label,scenario,evidence,rationale
```

### 6. 生成人工复核表

```bash
python scripts/construct_high_risk_dataset.py review-manifest \
  --weak-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv \
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
