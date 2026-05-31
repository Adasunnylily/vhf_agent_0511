# AIS增强 + 评测集执行清单（0531）

本清单用于今天直接执行，不做额外架构改动。

## 1. 目标与交付

1. 产出三层评测集模板：分类集A、转写实体集B、流式性能集C。
2. 接入AIS船舶基础信息（先CSV/JSON导入），用于船名地名纠错和风险判断增强。
3. 固定可汇报指标：准确率、时延、稳定性、自动化决策质量。

## 2. 一键生成评测模板

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511
python3 scripts/create_eval_templates.py --out-dir data/eval
```

生成文件：

- `data/eval/eval_set_A_classification.csv`
- `data/eval/eval_set_B_asr_entity.csv`
- `data/eval/eval_set_C_stream_perf.csv`
- `data/eval/eval_master_template.csv`

## 3. AIS最小数据字段

导入时建议包含以下字段（缺失可空）：

- `ship_name`
- `mmsi`
- `callsign`
- `imo`
- `ship_type`
- `tonnage_t`
- `draft_m`
- `length_m`
- `width_m`
- `sog_kn`
- `cog_deg`
- `heading_deg`
- `lng`
- `lat`
- `destination`
- `position_label`
- `nav_status`
- `cargo_type`
- `eta`
- `ais_update_time`
- `ais_source`

## 4. AIS导入与验证

### 4.1 导入（CSV/JSON）

```bash
curl -X POST http://127.0.0.1:8000/api/ais/ships/import \
  -F "file=@data/bootstrap/ais_ship_import_template.csv"
```

### 4.2 查询

```bash
curl http://127.0.0.1:8000/api/ais/ships
curl http://127.0.0.1:8000/api/inspection/ships
```

## 5. 指标定义（汇报可直接用）

### 5.1 ASR准确性

- `CER/WER`：仅在B集有真值时计算
- `ship_name_hit_rate`：船名命中率
- `location_hit_rate`：地名命中率
- `high_risk_keyword_recall`：高危关键词召回率

### 5.2 实时性与稳定性

- `TTFT`：首字时延（ms）
- `Final Latency`：最终文本延迟（ms）
- `RTF`：实时因子
- `empty_text_rate`：空文本率
- `request_error_rate`：接口失败率

### 5.3 决策效果

- `business_type_macro_f1`
- `high_risk_recall`
- `auto_reply_precision`
- `manual_review_rate`
- `closure_rate`（已播报或已归档 / 总事件）

## 6. 自动化决策提升建议（当前版本可执行）

1. 高危先召回：高危词命中直接升级到人工接管或高危处理。
2. 低置信度降级：置信度低、船名冲突、文本过短直接人工复核。
3. AIS上下文补强：识别到候选船名后，以当前区域AIS船舶做候选纠错。
4. 话术可编辑：系统给建议，值班员可改后播报并归档。

## 7. 今天建议执行顺序

1. 生成评测模板并开始A集/B集/C集标注（至少10/10/5条）。
2. 导入AIS样例并验证`/api/ais/ships`可返回完整字段。
3. 跑`audio/upload`与`mic/stream`各3条，记录TTFT、Final、空文本率。
4. 查看`/api/events`与`/api/analytics/summary`确认事件归档和统计闭环。

