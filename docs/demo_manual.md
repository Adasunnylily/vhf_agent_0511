# 海事VHF语音监测智能体演示手册

## 演示主线

目标只展示一条清晰链路：

`长音频播放 -> 实时转写 -> 事件切分 -> 风险分类 -> 自动回复/人工接管/点验 -> 归档`

演示时不要展开调试说明、片段队列、模型参数表等视觉内容。需要解释原理时，用本手册口头说明。

## 推荐演示入口

1. 打开 `http://127.0.0.1:8766/maritime_ai_agent.html`。
2. 点击语音交互页的 `长音频`。
3. 观察左侧实时语音流、中间当前事件主控台、右侧船舶态势和底部事件记录。
4. 如出现高危或人工复核事件，点击 `周边船舶点验` 或 `人工接管` 展示闭环。

## 语音处理原理

### 为什么 WAV 也要经过 ffmpeg

即使上传的是 WAV，也可能存在不同编码、采样率和声道，例如 8k A-law、16k PCM、双声道等。后端统一用 ffmpeg 转为模型需要的格式，避免 ASR 输入不一致：

- 单声道
- 指定采样率
- PCM WAV
- 可选降噪增强

相关代码：

- `app/services/preprocess.py`
- `app/services/pipeline.py`
- `app/api.py`

### 降噪与 A/B 对比

后端支持 `denoise_mode=off/on/compare`。

- `off`：原始预处理后识别
- `on`：执行 ffmpeg 滤波增强后识别
- `compare`：同一音频同时跑原始版和降噪版，便于比较 ASR 文本

默认滤波链路在 `.env` 或 `app/config.py` 中配置：

`VHF_DENOISE_FILTER_CHAIN=highpass=f=120,lowpass=f=3800,afftdn=nf=-25`

### VAD 切分逻辑

VAD 使用能量阈值切分连续语音：

- 按固定帧长计算 RMS 能量
- 连续高于阈值视为语音开始
- 静音超过阈值视为语音结束
- 过短片段丢弃，过长片段强制截断

关键参数：

- `VHF_VAD_FRAME_MS`
- `VHF_VAD_SILENCE_MS`
- `VHF_VAD_MIN_SPEECH_MS`
- `VHF_VAD_MAX_SEGMENT_MS`

相关代码：

- `app/services/vad.py`
- `app/main.py`
- `app/services/streaming_file_asr.py`

### 当前模型链路

以 `/healthz` 为准。

- 上传/长音频主 ASR：`VHF_ASR_PROVIDER` + `VHF_ASR_MODEL`
- 麦克风 ASR：`VHF_MIC_ASR_PROVIDER` + `VHF_MIC_ASR_MODEL`
- 事件分类/决策：`app/services/llm_decision.py`，若 LLM 不可用则回退规则
- 船名地名修正：`app/services/entity_resolver.py`
- 对话精修：`app/services/llm_dialogue.py`

查看当前实际模型：

```bash
curl http://127.0.0.1:8000/healthz
```

## 知识库演示

知识库页面支持：

- RAG 问答
- 资料上传
- 人工新增知识
- 检索
- 删除知识
- 根据输入关键词展示知识图谱关系

建议演示问题：

- `离泊申请如何处置？`
- `遇到机舱冒烟应该如何处理？`
- `靠妥报告能否自动回复？`

## 汇报口径

系统不是单纯 ASR 工具，而是数字值班员助手：

- 始终监听 VHF 长音频
- 将连续语音切为业务事件
- 用 ASR、实体库、AIS 船位和知识库共同辅助判断
- 对常规报告自动回复
- 对离泊、穿越、异常动态转人工
- 对高危事件触发点验和人工接管

