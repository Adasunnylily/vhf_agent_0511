# 智能体运行日志与五维测评

## 日志文件

后端将运行轨迹追加写入 `data/agent_run_logs.jsonl`。每行是一个独立 JSON 对象，
`schema_version` 当前为 `1.0`。日志只保存输入引用、可核验输出、证据、耗时和版本，
不保存模型内部思维链。

核心字段：

- `run_id`：一次音频、任务或测试运行标识。
- `event_id`：跨 ASR、研判、动作、归档和反馈保持一致的业务事件标识。
- `capability`：`perception`、`cognition`、`execution`、`memory`、`learning`。
- `stage`：可读的处理阶段，例如 `asr_completed`。
- `status`：`started`、`success`、`failed`、`skipped`。
- `confidence`、`latency_ms`：模型返回时记录；未返回时保持空值。
- `model`、`prompt_version`、`rule_version`、`dictionary_version`：版本追踪。
- `output`、`evidence`、`metadata`：结构化结果、可核验证据和评测标签。

## API

```bash
# 查询最近日志
curl 'http://127.0.0.1:8000/api/agent-logs?limit=100'

# 按事件导出 JSONL；format 也支持 json、csv
curl -OJ 'http://127.0.0.1:8000/api/agent-logs/export?format=jsonl&event_id=EVENT_ID'

# 计算全部日志或指定 run_id 的五维指标
curl 'http://127.0.0.1:8000/api/agent-logs/metrics'
curl 'http://127.0.0.1:8000/api/agent-logs/metrics?run_id=RUN_ID'
```

外部工具可通过 `POST /api/agent-logs` 写入同一规范。必填字段为
`capability` 和 `stage`。

## 离线指标脚本

```bash
.venv/bin/python scripts/evaluate_agent_logs.py \
  --input data/agent_run_logs.jsonl \
  --output artifacts/agent_metrics.json
```

五个维度统一计算记录数、覆盖情况、成功率、标签准确率、置信度均值及
平均/P50/P95 延迟。只有在 `metadata.expected` 和 `metadata.actual` 同时存在时
才计算标签准确率。没有真实数据的指标输出 `null`，不使用模拟值补齐分数。

当前自动埋点包括：

- 感知：ASR 完成及文本修正结果。
- 认知：风险、业务类型和处置策略判定。
- 执行：人工确认、播报、归档等状态变化。
- 记忆：事件写入持久化事件库。
- 学习：人工纠错反馈被应用。
