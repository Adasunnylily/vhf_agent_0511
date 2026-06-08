# 原始 AIS 日志处理说明

你的 `ais_data.2026-05-08_00.log.gz` 是原始 AIS 多消息类型 CSV 流，不能直接导入当前系统。

当前可先处理成两类数据：

- 动态态势：`MMSI、经纬度、航速、航向、航迹、更新时间`
- 静态信息：`船名、呼号、船型、吃水、目的港`

并不是每条 AIS 都有船名。常见情况是：

- `1/2/3/18/19/27`：主要是位置、速度、航向，没有船名
- `5/24`：可能有船名、呼号、目的港等静态信息
- `4/20`：基站或链路管理信息，通常不用于船舶识别

## 1. 转换为系统可导入 CSV

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511

python3 scripts/convert_raw_ais_log.py \
  /root/autodl-tmp/original/autodl-tmp/try0505/vhf-agent/ais_data.2026-05-08_00.log.gz \
  --out data/ais_today_import.csv \
  --bbox 121.6,29.6,122.4,30.2
```

输出中的关键字段：

- `static_name_mmsi`：原始日志里提取到船名的 MMSI 数量。
- `position_ships`：bbox 范围内有动态位置的船舶数量。
- `named_ships`：既有动态位置、又成功合并船名的船舶数量。
- `missing_name_ships`：有动态位置但缺船名的船舶数量。

如果 `static_name_mmsi > 0` 但 `named_ships = 0`，说明这一小时内“有船名的 MMSI”和“bbox 内有位置的 MMSI”没有重叠，需要扩大时间窗口或补充 `mmsi,ship_name` 映射表。

缺船名清单默认生成在：

```text
data/ais_missing_ship_names.csv
```

如果你有 `mmsi,ship_name` 映射表：

```bash
python3 scripts/convert_raw_ais_log.py \
  /root/autodl-tmp/original/autodl-tmp/try0505/vhf-agent/ais_data.2026-05-08_00.log.gz \
  --out data/ais_today_import.csv \
  --bbox 121.6,29.6,122.4,30.2 \
  --ship-name-map data/bootstrap/ship_name_map.csv
```

## 2. 导入到系统

```bash
curl -X POST http://127.0.0.1:8000/api/ais/ships/import \
  -F "file=@data/ais_today_import.csv"
```

导入后检查：

```bash
curl http://127.0.0.1:8000/api/ais/ships
```

## 3. 测试语音文本关联 AIS

```bash
curl -X POST http://127.0.0.1:8000/api/ais/analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"锦华662，你能不能加点车，你现在才四节多。"}'
```

如果能关联到 AIS，返回中会出现：

- `resolved_text`
- `entities`
- `ais_context`
- `analysis.evidence`
- `analysis.requires_human_review`

## 4. 现阶段限制

- 只有动态 AIS 而没有船名时，只能得到 `MMSI_xxx`，不能修正语音里的中文船名。
- 要提升船名修正，需要补 `MMSI -> 船名` 映射，或者从同一天的 `5/24` 静态 AIS 消息提取船名。
- 全域 AIS 建议先用 bbox 过滤到 VHF 基站覆盖水域，否则同名/近似船名会增加误匹配。
