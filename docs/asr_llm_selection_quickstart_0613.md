# ASR/LLM 选型快速执行说明

## 1. 上传录音识别

目标：评估完整录音上传后的最终听写质量，适合先看船名、地名、业务类型是否准。

默认候选：

- `volc-bigasr-auc-turbo`：火山录音文件识别，默认资源 `volc.seedasr.auc`
- `qwen-asr-flash`：Qwen ASR

命令：

```bash
python3 scripts/run_asr_comparison_for_review.py \
  --task upload \
  --audio-dir /root/autodl-tmp/0515-vhf-agent/data/20260508_beilunshan_vhf \
  --out data/eval/asr_upload_for_review.csv \
  --limit 50
```

火山上传录音默认接口：

```text
https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit
X-Api-Resource-Id: volc.seedasr.auc
```

## 2. 流式识别

目标：评估实时守听场景，后续要单独补 `TTFT / 最终时延 / 失败率 / 高危触发延迟`。

默认候选：

- `volc-sauc-duration`：火山流式，资源 `volc.seedasr.sauc.duration`
- `s2s-omni`：实时双向语音理解候选
- `qwen-asr-flash`：可作为准实时分片回放基线
- `local-funasr`：本地 FunASR 基线
- `paraformer-realtime-8k-v2`：Paraformer 实时识别候选

命令：

```bash
python3 scripts/run_asr_comparison_for_review.py \
  --task streaming \
  --audio-dir /root/autodl-tmp/0515-vhf-agent/data/20260508_beilunshan_vhf \
  --out data/eval/asr_streaming_for_review.csv \
  --limit 50
```

火山流式接口：

```text
双向流式: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
流式输入: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream
X-Api-Resource-Id: volc.seedasr.sauc.duration
```

当前 CSV 脚本会先生成可人工核对的表；真正 WebSocket 流式压测需要下一步单独跑实时音频帧 runner。

## 3. LLM 分析选型

当前系统的“智能分析/风险研判”不是 LLM，主要是：

- `app/services/risk_engine.py`：规则与关键词风险判断
- `app/services/vhf_dialogue.py`：VHF 对话轮次与纠错后处理
- `app/services/entity_resolver.py`：船名、地名、AIS/词典候选纠错

后续 LLM 选型建议固定同一份 ASR 输出，再比较：

- `qwen3.7-max`
- `deepseek-v4-flash`
- `Doubao-Seed-2.0-pro`
- `Doubao-Seed-2.0-lite`

人工核对字段优先看：

- `业务类型`
- `风险等级`
- `处置类型`
- `船名`
- `地名`
- `备注`

