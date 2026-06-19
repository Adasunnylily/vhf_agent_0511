# Qwen3-ASR 本地测试说明

目标：本地部署 `Qwen/Qwen3-ASR-0.6B` / `Qwen/Qwen3-ASR-1.7B`，评估是否可替代 DashScope API，或作为 VHF 转写后处理模型。

## 1. 建议环境

官方 `qwen-asr` 包建议使用隔离环境，避免和现有 `funasr` / `dashscope` 依赖冲突。若只是快速验证，也可以在当前环境安装：

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511
pip install -U qwen-asr modelscope
```

如显卡显存紧张，先测 `0.6B`；`1.7B` 准确率通常更好，但更吃显存。

## 2. 预下载模型

大陆网络优先用 ModelScope：

```bash
mkdir -p /root/autodl-tmp/models/qwen3-asr
modelscope download --model Qwen/Qwen3-ASR-0.6B --local_dir /root/autodl-tmp/models/qwen3-asr/Qwen3-ASR-0.6B
modelscope download --model Qwen/Qwen3-ASR-1.7B --local_dir /root/autodl-tmp/models/qwen3-asr/Qwen3-ASR-1.7B
```

若 Hugging Face 网络更通：

```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli download Qwen/Qwen3-ASR-0.6B --local-dir /root/autodl-tmp/models/qwen3-asr/Qwen3-ASR-0.6B
huggingface-cli download Qwen/Qwen3-ASR-1.7B --local-dir /root/autodl-tmp/models/qwen3-asr/Qwen3-ASR-1.7B
```

下载到本地后，把 `configs/qwen3_asr_local_models.json` 里的 `model` 改成本地目录，可避免运行时再次联网。

## 3. 跑分类音频样本

先用少量样本验证依赖和显存：

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511
python3 scripts/run_asr_model_selection.py \
  --vad-manifest test_data_0614/classified_audio_manifest.csv \
  --config configs/qwen3_asr_local_models.json \
  --models qwen3-asr-0.6b-local \
  --output-dir test_data_0614/qwen3_asr_local_eval \
  --limit 5 \
  --device cuda:0
```

输出：

```text
test_data_0614/qwen3_asr_local_eval/asr_selection_long.csv
test_data_0614/qwen3_asr_local_eval/asr_selection_wide.csv
```

稳定后再跑 50 条：

```bash
python3 scripts/run_asr_model_selection.py \
  --vad-manifest test_data_0614/classified_audio_manifest.csv \
  --config configs/qwen3_asr_local_models.json \
  --output-dir test_data_0614/qwen3_asr_local_eval_full \
  --limit 50 \
  --device cuda:0
```

## 4. 接入后端主链路测试

临时切到本地 Qwen3-ASR：

```bash
export VHF_ASR_PROVIDER=qwen_local
export VHF_QWEN_LOCAL_MODEL=Qwen/Qwen3-ASR-0.6B
export VHF_QWEN_LOCAL_DEVICE_MAP=cuda:0
export VHF_QWEN_LOCAL_DTYPE=bfloat16
export VHF_QWEN_LOCAL_LANGUAGE=Chinese

bash scripts/start_autodl.sh
```

如果已下载到本地目录：

```bash
export VHF_QWEN_LOCAL_MODEL=/root/autodl-tmp/models/qwen3-asr/Qwen3-ASR-0.6B
```

## 5. 建议判断标准

- 先看 `asr_selection_wide.csv` 中船名、地名、动作词是否优于现有 API。
- 关注误识别风险词：如“进水产西口”误成“进水”等。
- 比较耗时：控制台会打印每段本地推理延迟。
- 如果 0.6B 准确率接近 API，可考虑作为低成本候选；如果 1.7B 明显更准但慢，可考虑只做后处理或人工复核前重听。
