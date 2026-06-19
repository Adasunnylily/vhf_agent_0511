# ASR 下一步实验与落地计划 0617

目标：先用统一评测表确认主链路，不再凭单条样例判断模型好坏。

## 1. 本周优先结论

近期演示主链建议：

- 上传录音/事件结束精修：`qwen-asr-flash`
- 流式候选：`paraformer-realtime-8k-v2`
- 对照候选：`qwen-asr-flash` 准流式、`paraformer-realtime-v2`
- 后续本地实验：`Qwen3-ASR-0.6B` 测 TTFT，`Qwen3-ASR-1.7B` 测精修准确率

不要立刻把所有链路都换成本地大模型。先把评测集和脚本跑稳定。

## 2. 第一步：同步 Paraformer 热词

Paraformer/Fun-ASR 支持解码阶段热词；Qwen ASR Flash 主要靠 prompt 和后处理，不是真正解码热词。

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511

python3 scripts/sync_dashscope_vocabulary.py \
  --hotwords-path data/hotwords/nbzh_hotwords.txt \
  --target-model paraformer-realtime-8k-v2 \
  --weight 4
```

成功后会写入：

```text
data/hotwords/dashscope_vocabulary_id.txt
```

如果换成 `paraformer-realtime-v2`，必须重新用同一 target model 创建或确认词表 ID 匹配。

## 3. 第二步：跑上传录音识别对比

适合比较最终识别文本质量。

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511

python3 scripts/run_asr_comparison_for_review.py \
  --audio-dir /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511/test_data_0614 \
  --task upload \
  --models qwen-asr-flash,paraformer-v2,volc-bigasr-auc-turbo \
  --limit 50 \
  --out data/eval/asr_upload_for_review_0617.csv \
  --continue-on-error
```

重点看：

- `语音`
- `修正后文本`
- `对话轮次`
- `业务类型`
- `船名`
- `地名`
- `相应时间`
- `错误类型`

## 4. 第三步：跑流式识别对比

适合比较 TTFT、最终延迟和流式文本可用性。

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511

python3 scripts/run_asr_comparison_for_review.py \
  --audio-dir /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511/test_data_0614 \
  --task streaming \
  --models qwen-asr-flash,paraformer-realtime-8k-v2,paraformer-realtime-v2 \
  --limit 50 \
  --out data/eval/asr_streaming_for_review_0617.csv \
  --continue-on-error
```

重点看：

- `TTFT_ms`
- `最终延迟_ms`
- `流式模式`
- `语音`
- `修正后文本`
- `业务类型`
- `备注`

## 5. 第四步：人工标注最小字段

先不要全量逐字标。每条只补这些字段：

```text
是否可用
人工_业务类型
人工_船名
人工_地名
人工_是否高危
人工_是否需要自动回复
人工_是否需要人工介入
人工_备注
```

只有 B 集合再补：

```text
人工_逐字听写
```

## 6. 第五步：判断主链路

主链路不是只看 TTFT，也不是只看 CER。

建议权重：

- 业务类型准确率：30%
- 船名命中率：25%
- 地名/泊位命中率：15%
- 高危召回率：20%
- TTFT：10%

如果 `qwen-asr-flash` 和 `paraformer-realtime-8k-v2` 业务准确率相同，优先选 TTFT 更低且演示更稳的模型做主链；另一个做辅助/对照。

## 7. 高危声学信息下一步

高危不要只依赖 ASR 文本。下一步加声学分：

- 音量突增
- 语速变快
- 语音占比升高
- 重叠/压盖
- 高危关键词

最终策略：

```text
文本高危词命中
或 声学急迫分高
或 AIS 态势异常
=> 人工优先接管
```

## 8. 当前不建议马上做的事

- 不建议立刻把主链改成本地 Qwen3-ASR-1.7B。
- 不建议继续大改前端，除非后端评测结论已经稳定。
- 不建议只靠单条音频调 prompt，应按 50 条表格统一比较。
