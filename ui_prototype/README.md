# Maritime AI Agent UI Prototype

这个目录放独立前端原型。页面已接入现有 FastAPI API，但不会覆盖稳定首页。

## 打开方式

先启动 FastAPI 后端：

```bash
bash scripts/start_autodl.sh
```

再启动前端网关：

```bash
bash scripts/start_ui_prototype.sh
```

浏览器打开 `http://服务器地址:8766/maritime_ai_agent.html`。

前端网关会把 `/api/*` 转发到本机 `8000` FastAPI，因此只需要映射或转发 `8766` 端口。

点验真实底图需要在 `.env` 设置高德 Web 端 Key：

```bash
AMAP_KEY=你的高德Web端key
```

## 已接入能力入口

- 普通 ASR：`/api/audio/upload`
- 模拟流式：`/api/stream/upload`
- 准实时/回放：`/api/streaming/upload`
- 麦克风分片：`/api/mic/start`、`/api/mic/chunk`、`/api/mic/stop`
- 智能处置：复用现有 task/event 返回结构，前端只消费 `segments`、`events`、`meta`
- 点验：`/api/ais/ships`、`/api/inspection/filter`、`/api/inspection/run`
- 事件中心：`/api/events`、`/api/analytics/summary`
- 知识库：`/api/knowledge/search`
- TTS：先保留浏览器 `speechSynthesis`，正式版再接服务端 TTS

## 原则

- 独立原型优先用于界面与交互验收。
- 后端现有可跑能力不在原型阶段重构。
- 后端 API 地址可在原型的“设置中心”修改，默认使用当前域名的 `8000` 端口。
