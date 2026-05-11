# VHF Agent Backend MVP（0511 版本）

这是 0511 技术路线版本，独立于原 `vhf-agent/` 目录。核心目标是部署到 AutoDL，聚焦 VHF 语音识别、业务分流、点验通知，以及在已按人声切分的音频上评测 ASR 模型是否达到 80% 以上准确率。

快速入口：

- AutoDL 部署：[docs/autodl_0511_deploy.md](/Users/adasunnylily/Documents/New%20project/vhf-agent-0511/docs/autodl_0511_deploy.md)
- ASR 模型评测：[docs/asr_model_eval_0511.md](/Users/adasunnylily/Documents/New%20project/vhf-agent-0511/docs/asr_model_eval_0511.md)
- Git 同步：[docs/git_sync_0511.md](/Users/adasunnylily/Documents/New%20project/vhf-agent-0511/docs/git_sync_0511.md)
- 候选模型与无参考文本策略：[docs/asr_model_shortlist_0511.md](/Users/adasunnylily/Documents/New%20project/vhf-agent-0511/docs/asr_model_shortlist_0511.md)
- 船方呼叫高危分类实现：[docs/high_risk_classifier_implementation.md](/Users/adasunnylily/Documents/New%20project/vhf-agent-0511/docs/high_risk_classifier_implementation.md)
- 数据构造代码使用：[docs/data_construction_usage.md](/Users/adasunnylily/Documents/New%20project/vhf-agent-0511/docs/data_construction_usage.md)
- 模型配置：[configs/asr_models_0511.json](/Users/adasunnylily/Documents/New%20project/vhf-agent-0511/configs/asr_models_0511.json)

这个子项目提供一个可扩展的后端 MVP，用于跑通以下链路：

```text
录音上传 -> 音频切片 -> 识别适配 -> 风险识别 -> 事件输出
```

当前版本特性：

- `FastAPI` 后端接口骨架
- 本地文件存储
- 内存任务管理
- 音频预处理：统一转换为 `16k / mono / PCM wav`
- 简化版 `wav` 能量 VAD
- `FunASR` 真识别链路
- 关键词风险分级与事件生成
- 模拟流式识别与 `WebSocket` 推送
- 可选降噪/增强与 A/B 对比
- 甲方业务场景仿真：由动转静自动回复、复杂业务人工复核、冒烟着火干预、点验通知

当前版本限制：

- 简化 VAD 仅针对 `wav` 文件效果较好
- 实时声卡监听暂未实现
- 第一版流式是“文件模拟流”，不是直接声卡采集
- 预处理依赖系统已安装 `ffmpeg`

## 目录

```text
vhf-agent/
├── app/
│   ├── api.py
│   ├── config.py
│   ├── main.py
│   ├── domain/
│   └── services/
├── data/
│   ├── clips/
│   ├── events/
│   └── uploads/
├── tests/
├── requirements.txt
└── requirements-server.txt
```

## 安装

本地最小安装：

```bash
cd vhf-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

AutoDL 服务器安装：

```bash
cd vhf-agent
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements-server.txt
cp .env.example .env
```

另外需要系统安装 `ffmpeg`，用于把 `mp3/m4a/flac/aac/pcm` 等输入统一转成 `16k / mono / PCM wav`。

## 启动

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

或：

```bash
bash scripts/start_autodl.sh
```

## 主要接口

- `GET /healthz`
- `GET /api/demo/scenarios`
- `POST /api/demo/scenario/{scenario_id}`
- `GET /api/inspection/ships`
- `POST /api/inspection/run`
- `POST /api/audio/upload`
- `POST /api/stream/upload`
- `POST /api/streaming/upload`
- `GET /api/tasks/{task_id}`
- `GET /api/events`
- `GET /api/events/{event_id}`
- `WS /api/ws/monitor/{channel_id}`

## 上传接口示例

上传接口仍保留 `transcript_override`，便于你在没有音频样本时验证风控链路：

```bash
curl -X POST http://127.0.0.1:8000/api/audio/upload \
  -F "file=@sample.wav" \
  -F "channel_id=vhf_demo_01" \
  -F "denoise_mode=compare" \
  -F "transcript_override=前方船舶请让清航道，注意避让"
```

模拟流式上传：

```bash
curl -X POST http://127.0.0.1:8000/api/stream/upload \
  -F "file=@sample.wav" \
  -F "channel_id=vhf_demo_01" \
  -F "denoise_mode=on"
```

Paraformer 真流式调试：

```bash
curl -X POST http://127.0.0.1:8000/api/streaming/upload \
  -F "file=@sample.wav" \
  -F "channel_id=vhf_demo_01" \
  -F "denoise_mode=on"
```

业务场景仿真：

```bash
curl http://127.0.0.1:8000/api/demo/scenarios

curl -X POST http://127.0.0.1:8000/api/demo/scenario/static_report \
  -F "channel_id=vhf_demo_01"
```

点验通知仿真：

```bash
curl -X POST http://127.0.0.1:8000/api/inspection/run \
  -F "channel_id=vhf_demo_01" \
  -F "area_name=北仑主航道A3段" \
  -F "min_draft_m=10" \
  -F "notice_template={船名}，请注意，您已进入{区域}，请按规定守听并回复。"
```

## FunASR 调用说明

当前后端默认使用：

- `iic/SenseVoiceSmall`
- `fsmn-vad`
- 默认不加载 `ct-punc`

代码位置：

- ASR 适配器：[app/services/asr.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/services/asr.py)
- 主装配入口：[app/main.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/main.py)

根据 FunASR 官方 `AutoModel` 用法，当前实现会延迟加载模型，并调用：

```python
from funasr import AutoModel

model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",
    vad_kwargs={"max_single_segment_time": 30000},
    device="cuda:0",
    hub="ms",
)
res = model.generate(input="audio.wav", batch_size_s=30, language="auto", use_itn=True)
```

参考来源：

- [FunASR 官方仓库](https://github.com/modelscope/FunASR)
- [FunASR AutoModel 教程](https://github.com/modelscope/FunASR/blob/main/docs/tutorial/README.md)

## 适合 AutoDL 的默认约定

- 默认设备使用 `cuda:0`
- 模型、设备、数据目录全部走环境变量
- 模型延迟加载，服务先起来，首次识别时再拉取模型
- 建议上传 `wav` 文件，避免首版引入额外转码依赖
- AutoDL 默认建议关闭 `ct-punc`，先把主识别链路跑通，避免显存/内存被额外模型占满

## 流式链路说明

当前新增的是“文件模拟流”版本：

```text
上传音频文件
-> ffmpeg 预处理
-> VAD 切片
-> 每个切片依次送入 ASR
-> 通过 WebSocket 推送分段结果和风险事件
```

这一步适合先验证：

- 预处理是否正常
- 增量识别结果是否能推到前端
- 风险事件是否能边识别边产生

此外还新增了一条 `paraformer-zh-streaming` 调试链路：

```text
上传音频文件
-> ffmpeg 预处理成 16k mono PCM wav
-> 按 chunk 切成采样块
-> paraformer-zh-streaming 增量解码
-> WebSocket 推送每个 chunk 的文本
```

## 降噪/增强说明

当前降噪不是深度学习增强模型，而是基于 `ffmpeg` 的轻量滤波链：

```text
highpass=f=120,lowpass=f=3800,afftdn=nf=-25
```

作用：

- 抑制低频噪声
- 抑制高频杂音
- 做一轮频域降噪

可通过环境变量覆盖：

```bash
VHF_DENOISE_FILTER_CHAIN=highpass=f=120,lowpass=f=3600,afftdn=nf=-20
```

上传接口支持三种模式：

- `denoise_mode=off`
- `denoise_mode=on`
- `denoise_mode=compare`

其中 `compare` 会对同一音频分别跑“原始版”和“降噪版”，并在任务结果的 `meta` 里返回两组文本，便于直接做 A/B 比较。

## 甲方需求导向的业务分流

当前规则引擎重点覆盖四类业务：

- 高危险情  
  命中 Mayday、求救、进水、着火、冒烟、救生筏、严重倾斜等关键词时，优先进入人工应急处置
- 高危疑似场景  
  命中碰撞、故障、团雾、失控、让清航道等表达时，生成复核事件，便于后续接入 LLM 做模糊语义判别
- 由动转静常规报告  
  对靠泊、抛锚、过报告线等规则清晰场景生成标准回复；识别置信度低于 0.80 时自动转复核
- 非自动化业务  
  离泊、出港、航行计划、天气等多因素业务暂不自动回复，交由值班员人工处理

点验通知链路基于 AIS/海图任务演示：

```text
指令输入 -> 指定海图范围 -> 设置船舶筛选条件 -> 筛选 AIS 船舶 -> 填充通知模板 -> 一键 TTS 内容
```

## 代码链路

1. [app/api.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/api.py)
   接收上传文件，创建后台任务
2. [app/services/storage.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/services/storage.py)
   保存原始音频、事件文件
3. [app/services/vad.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/services/vad.py)
   对 `wav` 做能量切片
4. [app/services/audio_utils.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/services/audio_utils.py)
   按切片区间裁出子音频
5. [app/services/asr.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/services/asr.py)
   调 FunASR 做逐片识别
6. [app/services/risk_engine.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/services/risk_engine.py)
   根据关键词生成风险事件
7. [app/services/pipeline.py](/Users/adasunnylily/Documents/New%20project/vhf-agent/app/services/pipeline.py)
   串起整条处理流程
