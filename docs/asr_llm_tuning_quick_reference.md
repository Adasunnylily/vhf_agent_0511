# ASR/LLM 调参入口速查

## 1. ASR 主链路

在 `.env` 修改：

```bash
VHF_ASR_PROVIDER=dashscope_paraformer
VHF_ASR_MODEL=paraformer-realtime-8k-v2
VHF_ASR_SAMPLE_RATE=8000
VHF_ASR_DIARIZATION_ENABLED=1
VHF_ASR_SPEAKER_COUNT=2
VHF_ASR_VOCABULARY_ID=你的DashScope词表ID
VHF_ASR_HOTWORDS_PATH=data/hotwords/nbzh_hotwords.txt
```

建议：

- 上传录音优先对比 `qwen3-asr-flash` 和火山录音模型。
- 现场/准实时优先对比 `paraformer-realtime-8k-v2`、`paraformer-realtime-v2`、`sensevoice-realtime-v1`。
- 已确认 VHF 样例多为 `8000 Hz mono pcm_alaw`，所以 8k 实时模型需要重点测试。

## 2. ASR 二次精修

实时模型先低延迟出字，再用 Qwen 对音频片段做二次精修。失败会自动回退，不影响主流程。

```bash
VHF_ASR_REFINE_ENABLED=1
VHF_ASR_REFINE_MODEL=qwen3-asr-flash
VHF_ASR_REFINE_API_KEY_ENV=DASHSCOPE_API_KEY
VHF_ASR_REFINE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VHF_ASR_REFINE_MIN_DURATION_MS=1000
```

代码入口：

- `app/services/asr.py`：`ASRRefiner`
- `app/services/pipeline.py`：上传录音/离线切片精修
- `app/services/streaming.py`：模拟流式切片精修
- `app/services/streaming_realtime.py`：准实时最终结果精修
- `app/api.py`：麦克风分片精修

## 3. ASR Prompt 与热词

Prompt：

- `app/services/asr_prompts.py`：默认 ASR 听写约束
- `.env`：`VHF_ASR_EVAL_PROMPT` 或 `VHF_QWEN_ASR_PROMPT`

热词：

- `data/hotwords/nbzh_hotwords.txt`
- `scripts/sync_dashscope_vocabulary.py`：把热词同步为 DashScope 词表

注意：

- DashScope/Paraformer 的热词需要词表 ID，属于模型解码侧增强。
- Qwen ASR 当前主要通过 prompt + 热词文本约束，属于输入提示增强。

## 4. 说话人轮次/实体纠错

```bash
VHF_DIALOGUE_MODE=llm
VHF_DIALOGUE_MODEL=qwen-max
VHF_DIALOGUE_API_KEY_ENV=DASHSCOPE_API_KEY
VHF_DIALOGUE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

代码入口：

- `app/services/llm_dialogue.py`：LLM 轮次重建 prompt
- `app/services/vhf_dialogue.py`：规则/LLM 混合后处理
- `app/services/entity_resolver.py`：船名、地名、AIS 候选实体

## 5. 业务分类/智能决策

```bash
VHF_DECISION_MODE=llm
VHF_DECISION_MODEL=qwen-max
VHF_DECISION_API_KEY_ENV=DASHSCOPE_API_KEY
VHF_DECISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

代码入口：

- `app/services/llm_decision.py`：分类与处置 prompt
- `app/services/risk_engine.py`：LLM 优先，失败回退规则

## 6. 推荐实验顺序

1. 固定同一批 20-50 条音频，先跑上传录音模型对比。
2. 选 Top2 后再跑准实时/流式，重点看 TTFT、最终延迟、船名地名命中率。
3. 固定 ASR 主模型后，再调 `VHF_DIALOGUE_*` 和 `VHF_DECISION_*`。
4. 每次人工修正后，把 `gt_transcript`、`ship_name_gt`、`location_gt`、`decision_gt` 补到增强版标注表。
