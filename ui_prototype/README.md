# Maritime AI Agent UI Prototype

这个目录放独立前端原型。页面已接入现有 FastAPI API，但不会覆盖稳定首页。

## 打开方式

本地或服务器启动静态页面：

```bash
cd ui_prototype
python3 -m http.server 8766 --bind 0.0.0.0
```

浏览器打开 `http://服务器地址:8766/maritime_ai_agent.html`。

也可以由 FastAPI 同源打开：`http://服务器地址:8000/prototype`。

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
