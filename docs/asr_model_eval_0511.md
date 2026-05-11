# ASR 模型评测流程（0511 版本）

目标：在“已按人声说话切分”的 VHF 音频上，找到平均识别准确率达到 `80%` 以上的模型。

## 1. 准备标注文件

准确率必须依赖人工参考文本。建议准备 `manifest.csv`：

```csv
audio_path,transcript
clip_0001.wav,VTS宁远8报告已靠泊3号码头
clip_0002.wav,海丰32报告已在锚地抛好锚
clip_0003.wav,Mayday这里是货轮876机舱冒烟请求救助
```

如果音频路径是相对路径，运行时传入 `--audio-dir`。

也支持 `jsonl`：

```jsonl
{"audio_path":"clip_0001.wav","transcript":"VTS宁远8报告已靠泊3号码头"}
```

没有人工参考文本时，脚本只能批量转写，不能判断是否超过 80%。

## 2. 运行评测

```bash
cd /root/autodl-tmp/vhf-agent-0511
source .venv/bin/activate

python scripts/evaluate_asr_models.py \
  --manifest /root/autodl-tmp/vhf-data/manifest.csv \
  --audio-dir /root/autodl-tmp/vhf-data/speech_clips \
  --config configs/asr_models_0511.json \
  --output-dir outputs/asr_eval_0511 \
  --device cuda:0
```

只评测某几个模型：

```bash
python scripts/evaluate_asr_models.py \
  --manifest /root/autodl-tmp/vhf-data/manifest.csv \
  --audio-dir /root/autodl-tmp/vhf-data/speech_clips \
  --models sensevoice_small,paraformer_large_zh \
  --output-dir outputs/asr_eval_0511
```

先抽样 50 条快速试跑：

```bash
python scripts/evaluate_asr_models.py \
  --manifest /root/autodl-tmp/vhf-data/manifest.csv \
  --audio-dir /root/autodl-tmp/vhf-data/speech_clips \
  --limit 50
```

## 3. 查看结果

输出目录：

```text
outputs/asr_eval_0511/
├── summary.csv
├── summary.json
├── sensevoice_small_details.csv
├── paraformer_large_zh_details.csv
└── ...
```

关键指标：

- `avg_cer`：平均字错误率，越低越好。
- `avg_accuracy`：`1 - avg_cer`，达到 `0.80` 表示平均准确率超过 80%。
- `pass_rate_at_80`：单条样本准确率超过 80% 的比例。

## 4. 样本建议

为了避免模型只在简单样本上达标，建议标注集至少覆盖：

- 高危：Mayday、进水、着火、冒烟、救生筏、左倾、人员落水。
- 模糊高危：故障、发生问题、团雾、失控、让清航道、碰撞。
- 自动回复：靠泊、靠港、抛锚、过报告线、码头到报。
- 非自动化：离泊、出港、目的地、航行计划、天气。
- 噪声维度：英文、方言、急促语速、情绪激动、嘈杂背景。

建议先用 200 到 500 条人工标注样本筛模型，再用更大的留出集复核。
