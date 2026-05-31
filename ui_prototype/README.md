# Maritime AI Agent UI Prototype

这个目录只放独立前端原型，不接入现有 FastAPI 后端，避免界面打磨影响已能运行的核心能力。

## 打开方式

```bash
open ui_prototype/maritime_ai_agent.html
```

## 后续接后端时保留的能力入口

- 普通 ASR：`/api/audio/upload`
- 模拟流式：`/api/stream/upload`
- 准实时/回放：`/api/streaming/upload`
- 麦克风分片：`/api/mic/start`、`/api/mic/chunk`、`/api/mic/stop`
- 智能处置：复用现有 task/event 返回结构，前端只消费 `segments`、`events`、`meta`
- 点验：`/api/ais/ships`、`/api/inspection/filter`、`/api/inspection/run`
- TTS：先保留浏览器 `speechSynthesis`，正式版再接服务端 TTS

## 原则

- 先确认界面与交互，再接真实接口。
- 后端现有可跑能力不在原型阶段重构。
- 原型只做产品流程：音频接入、ASR展示、智能决策、话术编辑、TTS、点验筛船、事件归档。
