# 数据清晰逻辑：先选ASR，再做船方/管理方与危机分类

这版流程不把关键词当成最终规则。关键词只作为冷启动兜底和人工复核排序参考。

## 核心目标

每个语音片段最终形成一行结构化数据：

```text
clip_path
asr_model
asr_text
analysis_source
role_pred                  ship / operator / mixed / unclear
crisis_label_pred          crisis / non_crisis / uncertain / not_target
automation_label_pred      manual_immediate / auto_reply / llm_advice / not_target
scenario_pred
analysis_evidence
analysis_rationale
```

逻辑分层：

```text
连续混合音频
-> VAD切片
-> 多个ASR模型转写，先让人选择ASR效果
-> 选定ASR模型后批量转写
-> ASR文本交给LLM分析，或音频片段交给音频大模型分析
-> 生成机器分析候选标签
-> 人工抽检/修正
-> 后续再训练小模型
```

## 第一步：VAD切片

```bash
python scripts/construct_high_risk_dataset.py raw-manifest \
  --audio-dir /root/autodl-tmp/vhf-data/raw_audio \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/raw_audio_manifest.csv

python scripts/construct_high_risk_dataset.py vad-split \
  --raw-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/raw_audio_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --clip-dir /root/autodl-tmp/vhf-data/data_pipeline/clips/vad_segments \
  --normalized-dir /root/autodl-tmp/vhf-data/data_pipeline/clips/normalized \
  --threshold-mode adaptive \
  --silence-ms 1200 \
  --max-segment-ms 0
```

这里切出来的是“有声话轮”，不是“说话人声纹分离”。不要按 7 秒固定窗口切，因为会把一句完整船方呼叫切碎。默认 `--max-segment-ms 0` 表示不做固定时长强切，只用静音间隔作为边界。

如果发现“切分结果还是整段原音频”，通常是 VHF 底噪超过固定阈值导致整段都被判成有声。当前默认使用 `--threshold-mode adaptive`，会按每个文件估计噪声底并在 manifest 里写入 `threshold_used`。仍然不切时先试：

```bash
--silence-ms 600 --threshold-ratio 0.45
```

后续的船方/管理方判断来自：

```text
ASR文本 -> LLM角色判断
或 音频片段 -> 音频大模型角色判断
或 人工核实
```

## 第二步：先跑部分样本，选择ASR模型

```bash
python scripts/run_asr_model_selection.py \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --config configs/asr_models_0511.json \
  --models sensevoice_small,paraformer_large_zh \
  --output-dir /root/autodl-tmp/vhf-data/data_pipeline/asr_selection \
  --limit 50 \
  --device cuda:0
```

如果要加入 OpenAI Whisper/GPT 转写、Gemini，以及导入豆包/Qwen 等外部模型结果，用高级配置：

```bash
python scripts/run_asr_model_selection.py \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --config configs/asr_models_advanced_0511.json \
  --models sensevoice_small,qwen3_asr_flash,doubao_seed_asr_flash,openai_gpt4o_mini_transcribe,openai_whisper_1,gemini_3_flash_preview_audio \
  --output-dir /root/autodl-tmp/vhf-data/data_pipeline/asr_selection_advanced \
  --limit 30 \
  --device cuda:0
```

详细说明见 `docs/advanced_asr_selection_0511.md`。

输出：

```text
asr_selection_long.csv
asr_selection_wide.csv
```

你主要看 `asr_selection_wide.csv`，同一条音频会并排展示不同模型文本：

```text
segment_id,clip_path,asr_text__sensevoice_small,asr_text__paraformer_large_zh
```

人工快速判断：

- 哪个模型中文海事表达更准。
- 哪个模型英文/呼号/船名更稳。
- 哪个模型噪声下幻觉更少。
- 哪个模型漏字、错字、乱加标点少。

选定模型后，再做全量 ASR。

当前配置会把 ASR 语言默认限定为 `zh`：中文为主，保留少量英文船名、呼号和 `MAYDAY/VTS/ETA/AIS` 等术语。高级 OpenAI/Gemini 配置还会通过 prompt 明确说明“不是日语/韩语场景”。如果输出中出现日文假名或韩文字符，结果表会在 `language_guard__模型名` 或 `language_guard_notes` 中标记，便于人工筛掉幻觉样本。

## 第三步：选定ASR后全量转写

例如选择 `SenseVoiceSmall`：

```bash
python scripts/construct_high_risk_dataset.py asr-transcribe \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --model iic/SenseVoiceSmall \
  --asr-vad-model fsmn-vad \
  --device cuda:0
```

`asr_segments_manifest.csv` 会保存：

```text
segment_id
clip_path
asr_text
asr_model
asr_confidence
```

## 第四步：用LLM或音频大模型做机器分析

机器分析结果可以来自两条路：

1. `ASR文本 -> LLM分析`
2. `音频片段 -> 音频大模型直接分析`

两种结果都整理成同一格式 CSV 或 JSONL：

```csv
segment_id,role_label,role_confidence,crisis_label,crisis_confidence,automation_label,scenario,evidence,rationale
raw_000001_seg_0001,ship,0.92,crisis,0.88,manual_immediate,fire_smoke,机舱冒烟|请求救助,船方报告机舱冒烟且请求救助
raw_000001_seg_0002,operator,0.90,not_target,0.95,not_target,operator_reply,VTS收到|保持守听,管理方回复
raw_000001_seg_0003,ship,0.86,non_crisis,0.82,auto_reply,anchor_completed,抛好锚,船方由动转静报备
raw_000001_seg_0004,ship,0.78,non_crisis,0.70,llm_advice,weather_query,请问|气象,非高危但不可自动化
```

字段含义：

```text
role_label:
  ship / operator / mixed / unclear

crisis_label:
  crisis / non_crisis / uncertain / not_target

automation_label:
  manual_immediate  高危，立即人工处理
  auto_reply        非危机且可自动化回复
  llm_advice        非危机但不可自动化，给LLM回复建议
  not_target        非船方呼叫
```

## 第五步：融合分析结果并生成复核表

如果只有ASR，没有LLM/音频大模型结果：

```bash
python scripts/construct_high_risk_dataset.py weak-label \
  --asr-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv \
  --stats-output /root/autodl-tmp/vhf-data/data_pipeline/reports/analysis_stats.json
```

如果已有 LLM 分析结果：

```bash
python scripts/construct_high_risk_dataset.py weak-label \
  --asr-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --llm-analysis /root/autodl-tmp/vhf-data/data_pipeline/llm_analysis.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv \
  --stats-output /root/autodl-tmp/vhf-data/data_pipeline/reports/analysis_stats.json
```

如果也有音频大模型结果：

```bash
python scripts/construct_high_risk_dataset.py weak-label \
  --asr-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/asr_segments_manifest.csv \
  --llm-analysis /root/autodl-tmp/vhf-data/data_pipeline/llm_analysis.csv \
  --audio-analysis /root/autodl-tmp/vhf-data/data_pipeline/audio_model_analysis.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv
```

融合优先级：

```text
ASR+LLM结构化分析
-> 音频大模型结构化分析
-> 规则兜底
```

规则兜底只用于冷启动，不作为最终可靠标签。

## 第六步：人工复核

```bash
python scripts/construct_high_risk_dataset.py review-manifest \
  --weak-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/machine_analysis_manifest.csv \
  --output /root/autodl-tmp/vhf-data/data_pipeline/manifests/human_review_manifest.csv \
  --limit 500
```

人工只需要重点修：

- `role_pred=unclear/mixed`
- `crisis_label_pred=crisis`
- `crisis_label_pred=uncertain`
- `analysis_disagreement` 不为空
- `automation_label_pred=llm_advice`

## 重要原则

1. 关键词不是最终标签，只是兜底和复核提示。
2. 先选择 ASR 模型，再做后续分类实验。
3. 船方/管理方划分是第一任务，非船方呼叫不进入危机分类。
4. 船方呼叫才分：

```text
crisis -> manual_immediate
non_crisis + 可自动化 -> auto_reply
non_crisis + 不可自动化 -> llm_advice
uncertain -> 人工复核
```
