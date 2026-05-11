# ASR 候选模型与无参考文本评测策略

## 结论先行

当前没有人工参考文本，因此不能证明某个模型“准确率超过 80%”。可先做两步：

1. 批量转写：让多个候选模型跑同一批已切分人声音频。
2. 抽样复核：用模型间一致性挑样本，人工快速标注 100 到 300 条，计算真实 CER/accuracy。

建议第一轮优先跑：

- `Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B`
- `FunASR / SenseVoiceSmall`
- `Doubao-ASR-2.0`
- `Whisper large-v3`

第二轮再补：

- `OpenAI gpt-4o-mini-transcribe`
- `ElevenLabs Scribe v2`
- `FunAudio-ASR-1.5`
- `GLM-ASR-Nano`
- `FunASR-Nano`

## 候选模型定位

| 模型 | 类型 | 建议优先级 | 用途 |
|---|---:|---:|---|
| Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B | 本地/API | 高 | 中文、英文、混合语音强候选 |
| FunASR / SenseVoiceSmall | 本地 | 高 | 项目已有适配，AutoDL 上最容易跑通 |
| Doubao-ASR-2.0 | API | 高 | 中文云端强基线 |
| Whisper large-v3 | 本地 | 中 | 稳定开源基线，适合离线对照 |
| OpenAI gpt-4o-mini-transcribe | API | 中 | 多语种、英文和噪声片段对照 |
| ElevenLabs Scribe v2 | API | 中 | 海外商业ASR对照 |
| FunAudio-ASR-1.5 | 本地/API | 中 | 需确认权重、推理方式和授权 |
| GLM-ASR-Nano | 本地/API | 观察 | 轻量低成本候选 |
| FunASR-Nano | 本地 | 观察 | 轻量实时候选 |

## 没有参考文本时怎么做

先生成空标注 manifest：

```bash
python scripts/build_unlabeled_manifest.py \
  --audio-dir /root/autodl-tmp/vhf-data/speech_clips \
  --output /root/autodl-tmp/vhf-data/manifest_unlabeled.csv
```

然后跑本地候选模型，先不计分，只输出转写：

```bash
python scripts/evaluate_asr_models.py \
  --manifest /root/autodl-tmp/vhf-data/manifest_unlabeled.csv \
  --models sensevoice_small,paraformer_large_zh \
  --output-dir outputs/asr_eval_0511
```

如果你把其他 API 模型的输出也整理成同样的 `*_details.csv` 格式，就可以生成复核队列：

```bash
python scripts/build_review_queue.py \
  --details outputs/asr_eval_0511/*_details.csv \
  --output outputs/asr_eval_0511/review_queue.csv
```

`review_queue.csv` 会把模型分歧最大的样本排在前面。优先标这些样本，最省人工。

## 如何真正判断 80%

人工在 `review_queue.csv` 的 `human_reference` 列填标准文本后，整理成：

```csv
audio_path,transcript
/root/autodl-tmp/vhf-data/speech_clips/clip_0001.wav,VTS宁远8报告已靠泊3号码头
```

再运行：

```bash
python scripts/evaluate_asr_models.py \
  --manifest /root/autodl-tmp/vhf-data/manifest_labeled.csv \
  --audio-dir /root/autodl-tmp/vhf-data/speech_clips \
  --output-dir outputs/asr_eval_labeled_0511
```

看 `summary.csv`：

- `avg_accuracy >= 0.80`：平均准确率达标。
- `pass_rate_at_80`：单条样本准确率达标比例。

## VHF 样本抽样建议

第一批人工标注建议至少覆盖：

- 高危：Mayday、进水、着火、冒烟、救生筏、左倾、人员落水。
- 模糊高危：故障、发生问题、团雾、失控、让清航道、碰撞。
- 自动回复：靠泊、靠港、抛锚、过报告线、码头到报。
- 非自动化：离泊、出港、目的地、航行计划、天气。
- 难样本：英文、方言、急促语速、情绪激动、强噪声。
