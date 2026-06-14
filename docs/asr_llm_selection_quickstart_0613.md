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
https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash
X-Api-Resource-Id: volc.bigasr.auc_turbo
```

如需异步批量识别，可设置环境变量：

```text
VOLCENGINE_FILE_ASR_ENDPOINT=https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit
VOLCENGINE_FILE_ASR_QUERY_ENDPOINT=https://openspeech.bytedance.com/api/v3/auc/bigmodel/query
```

## 2. 流式识别

目标：评估实时守听场景，后续要单独补 `TTFT / 最终时延 / 失败率 / 高危触发延迟`。

默认候选：

- `volc-sauc-duration`：火山流式 WebSocket 文件回放，资源 `volc.bigasr.sauc.duration`
- `qwen-asr-flash`：可作为准实时分片回放基线
- `paraformer-realtime-v2`：Paraformer 实时识别候选
- `sensevoice-realtime-v1`：高噪声 VHF 候选
- `paraformer-realtime-8k-v2`：Paraformer 8k 实时候选

可选（默认不跑，避免 OOM 或未实现协议）：

- `local-funasr`：设置 `VHF_STREAMING_INCLUDE_LOCAL=1`
- `s2s-omni`：设置 `VHF_STREAMING_INCLUDE_S2S=1`

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

当前系统已支持 LLM 优先判断，关键词规则兜底：

- `app/services/llm_decision.py`：OpenAI 兼容 LLM 分类，输出 JSON 决策
- `app/services/risk_engine.py`：先调用 LLM，失败或关闭时回退到关键词规则
- `app/services/vhf_dialogue.py`：VHF 对话轮次与纠错后处理
- `app/services/entity_resolver.py`：船名、地名、AIS/词典候选纠错

调用链路：

```text
ASR/流式ASR
  -> 船名地名实体纠错
  -> 说话人/对话轮次重建
  -> LLM智能分类与处置判断
  -> 关键词规则兜底
  -> 事件归档/前端展示/TTS播报
```

环境变量：

```bash
VHF_DECISION_MODE=llm
VHF_DECISION_MODEL=qwen-max
VHF_DECISION_API_KEY_ENV=DASHSCOPE_API_KEY
VHF_DECISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

实体纠错和对话轮次也可交给 LLM：

```bash
VHF_DIALOGUE_MODE=llm
# 默认复用 VHF_DECISION_MODEL / VHF_DECISION_API_KEY_ENV / VHF_DECISION_BASE_URL
# 如需单独模型，可设置：
# VHF_DIALOGUE_MODEL=qwen-max
# VHF_DIALOGUE_API_KEY_ENV=DASHSCOPE_API_KEY
# VHF_DIALOGUE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

调用链路会先做规则初修和实体候选生成，再把候选交给 LLM：

```text
ASR原文
  -> 规则初修文本
  -> 船名/地名/AIS候选
  -> LLM corrected_text + turns
  -> 失败时回退规则对话轮次
```

LLM 选型建议固定同一份 ASR 输出，再比较：

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

## 4. Paraformer 实时模型选择

建议先这样区分：

- `paraformer-realtime-v2`：优先作为 16k VHF 音频/通用实时识别候选。
- `paraformer-realtime-8k-v2`：优先作为 8k 窄带语音、电话/VHF窄带采样候选。

如果你的输入已经被预处理成 16k mono wav，先测 `paraformer-realtime-v2`。
如果现场链路实际是 8k 窄带 PCM 或低带宽 VHF 采样，再测 `paraformer-realtime-8k-v2`。

当前北仑山 VHF 样例 `025104.wav` 与 `000300.wav` 均为：

```text
codec_name=pcm_alaw
sample_rate=8000
channels=1
bit_rate=64000
```

因此原始数据应按 8k 窄带 VHF 处理，建议把 `paraformer-realtime-8k-v2` 列为重点流式候选。

最终选择不看模型名，按同一批流式样本比较：

- 首字时延 TTFT
- 最终时延 Final latency
- 船名/地名命中率
- 高危召回
- 离泊/开航申请召回
- 空文本率和失败率
