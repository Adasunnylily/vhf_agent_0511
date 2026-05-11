# AutoDL 部署说明（0511 版本）

0511 版本独立放在 `vhf-agent-0511/`，不依赖修改原 `vhf-agent/`。

## 1. 上传目录

建议上传到 AutoDL：

```bash
/root/autodl-tmp/vhf-agent-0511
```

数据建议放在：

```bash
/root/autodl-tmp/vhf-data/speech_clips
/root/autodl-tmp/vhf-data/manifest.csv
```

## 2. 初始化环境

```bash
cd /root/autodl-tmp/vhf-agent-0511
bash scripts/setup_autodl_0511.sh
```

如需改模型、端口、数据目录：

```bash
vim .env
```

## 3. 启动服务

```bash
cd /root/autodl-tmp/vhf-agent-0511
source .venv/bin/activate
bash scripts/start_autodl.sh
```

默认监听：

```text
http://服务器IP:8000
```

## 4. 0511 版本能力边界

- 只聚焦 VHF 语音处理。
- 暂不把 AIS 轨迹预测、碰撞预警纳入语音主链路。
- 离泊、出港、航行计划、天气等复杂审批类 VHF 业务只做识别和人工提示，不做自动放行。
- 自动回复只先覆盖由动转静场景：靠泊、抛锚、过报告线等规则清晰任务。
- 点验通知作为独立 AIS/海图任务演示：指定范围、筛选船舶、填充模板、一键 TTS 文本。

## 5. 常用命令

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
```

业务场景演示：

```bash
curl -X POST http://127.0.0.1:8000/api/demo/scenario/static_report \
  -F "channel_id=beilun_vhf_01"
```

点验通知演示：

```bash
curl -X POST http://127.0.0.1:8000/api/inspection/run \
  -F "channel_id=beilun_vhf_01" \
  -F "area_name=北仑主航道A3段" \
  -F "min_draft_m=10" \
  -F "notice_template={船名}，请注意，您已进入{区域}，请保持安全航速，加强瞭望并保持守听。"
```
