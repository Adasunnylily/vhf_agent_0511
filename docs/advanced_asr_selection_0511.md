# 高级 ASR 候选模型接入（0511）

这个流程用于先抽样一小批 VHF 片段，对比不同 ASR 模型的转写效果。输出仍然是两张表：

- `asr_selection_long.csv`：一行一个“音频片段 + 模型”的结果。
- `asr_selection_wide.csv`：一行一个音频片段，不同模型的文本并排展示，最适合人工快速判断。

## 1. 支持的 provider

`scripts/run_asr_model_selection.py` 现在支持四类 provider：

| provider | 用途 | 是否直接调用 |
| --- | --- | --- |
| `funasr` | SenseVoice、Paraformer 等本地模型 | 是 |
| `openai_audio` | OpenAI `gpt-4o-mini-transcribe`、`gpt-4o-transcribe`、`whisper-1`、diarize 模型 | 是，需要 `OPENAI_API_KEY` |
| `gemini_audio` | Gemini 音频理解/转写，默认候选含 `gemini-3-flash-preview` 和 `gemini-2.5-flash` | 是，需要 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY` |
| `external_csv` | 豆包、Qwen、Seed-ASR、ElevenLabs 等外部结果导入 | 先用厂商工具跑，再导入 |

豆包/Qwen 先不在这里硬编码 API，是因为不同账号、地区、部署方式和鉴权方式差异比较大。当前最稳妥的方法是：先把它们的结果整理成统一 CSV，再和本地/OpenAI/Gemini 结果合并到同一张对比表。

## 2. 安装额外 SDK

本地 FunASR 环境已经存在时，不需要重复执行环境配置脚本。只在需要 OpenAI/Gemini 时安装对应 SDK：

```bash
pip install openai google-genai
```

设置 key：

```bash
export OPENAI_API_KEY="你的OpenAI Key"
export GEMINI_API_KEY="你的Gemini Key"
```

## 3. 抽样跑本地 + OpenAI + Gemini

建议先抽样 20 到 50 条，避免费用和等待时间过高：

```bash
python scripts/run_asr_model_selection.py \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --config configs/asr_models_advanced_0511.json \
  --models sensevoice_small,openai_gpt4o_mini_transcribe,openai_gpt4o_transcribe,openai_whisper_1,gemini_3_flash_preview_audio \
  --output-dir /root/autodl-tmp/vhf-data/data_pipeline/asr_selection_advanced \
  --limit 30 \
  --device cuda:0
```

如果某个模型缺少 key、SDK 或调用失败，默认会把错误写入 `asr_error__模型名`，其他模型继续跑。需要一出错就退出时加：

```bash
--fail-fast
```

这些高级模型配置已经加入海事通信 prompt：限定“中文为主、少量英文船名/呼号/MAYDAY/VTS/ETA/AIS，绝不输出日语或韩语”，并要求逐字转写、不要总结。OpenAI 类模型会同时传 `language=zh` 和 `prompt`；Gemini 类模型会把同样的场景约束放进音频理解 prompt。

结果表还会增加语言审计列：

```text
language_guard__模型名
```

如果模型输出日文假名或韩文字符，会标记 `japanese_kana` / `korean_hangul`。这类结果建议直接视为该模型在当前 VHF 数据上的幻觉样本，优先人工复核。

## 4. 尝试 OpenAI 说话人结果

如果想测试大模型直接处理“连续混合语音里的多说话人”，可以单独跑 diarize 候选：

```bash
python scripts/run_asr_model_selection.py \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --config configs/asr_models_advanced_0511.json \
  --models openai_gpt4o_transcribe_diarize \
  --output-dir /root/autodl-tmp/vhf-data/data_pipeline/asr_selection_diarize \
  --limit 20
```

这一步主要用于判断“音频大模型直接分说话人 + 转写”的可行性。正式构造训练数据时，仍建议把说话人角色、危机/非危机、自动/非自动化这些字段保存成结构化 manifest。

## 5. 导入豆包/Qwen/Seed/ElevenLabs 结果

外部模型结果整理成 CSV，至少包含：

```csv
segment_id,clip_path,asr_text,asr_confidence
seg_000001,/root/autodl-tmp/vhf-data/data_pipeline/clips/vad_segments/seg_000001.wav,VTS宁远8报告已靠泊三号码头,0.93
```

`segment_id` 优先匹配；如果没有 `segment_id`，脚本会尝试用 `clip_path` 匹配。

然后在 `configs/asr_models_advanced_0511.json` 里确认路径：

```json
{
  "name": "qwen3_asr_external",
  "provider": "external_csv",
  "model": "Qwen3-ASR-1.7B",
  "result_path": "/root/autodl-tmp/vhf-data/data_pipeline/asr_external/qwen3_asr_results.csv"
}
```

合并进同一张对比表：

```bash
python scripts/run_asr_model_selection.py \
  --vad-manifest /root/autodl-tmp/vhf-data/data_pipeline/manifests/vad_segments_manifest.csv \
  --config configs/asr_models_advanced_0511.json \
  --models sensevoice_small,qwen3_asr_external,doubao_asr_2_external \
  --output-dir /root/autodl-tmp/vhf-data/data_pipeline/asr_selection_external \
  --limit 30
```

## 6. 人工选择标准

先看 `asr_selection_wide.csv`：

- 船名、呼号、泊位、锚地、频道号是否准确。
- `MAYDAY`、碰撞、搁浅、进水、走锚、失火、人员落水等高危词是否漏识别。
- 靠泊、抛锚、离泊、进港、出港等动态报告是否稳定。
- 噪声、多人连续说话、管理方回复混在一起时是否乱编。
- 是否能保留对后续分类有用的信息，而不是只给摘要。

选出最稳的 ASR 后，再用它跑全量 `asr-transcribe`，并把 `asr_text`、`asr_model`、`asr_confidence` 保存进后续数据 manifest。
