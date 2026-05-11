# 船方呼叫高危分类模型实现流程

目标：从连续混合 VHF 音频中提取船方呼叫片段，并判断是否属于高危场景。

当前约束：

- 原始音频是连续混合语音，包含船方呼叫和值班员回复。
- 没有 ASR 人工标注。
- 没有高危/非高危分类标签。
- 业务上只针对“船方呼叫”做高危判断。

建议不要直接训练端到端音频分类模型，而是先建设数据闭环：

```text
连续音频
-> VAD 切分
-> ASR 转写
-> 角色识别：船方 / 值班员 / 混合 / 不确定
-> 弱标签：高危 / 非高危 / 不确定
-> 人工复核小样本
-> 训练文本分类小模型
-> 规则 + 小模型 + LLM 复核接入后端
```

## 1. 目录约定

建议新增以下目录：

```text
data_pipeline/
├── manifests/
│   ├── raw_audio_manifest.csv
│   ├── vad_segments_manifest.csv
│   ├── asr_segments_manifest.csv
│   ├── weak_labeled_manifest.csv
│   └── human_labeled_manifest.csv
├── clips/
│   ├── vad_segments/
│   └── ship_calls/
├── models/
│   └── risk_text_classifier/
└── reports/
    ├── label_stats.json
    └── eval_metrics.json
```

Git 不提交真实音频、模型权重和评测输出，只提交脚本和文档。

## 2. 第一步：建立原始音频清单

输入：

```text
/root/autodl-tmp/vhf-data/raw_audio/*.wav
```

输出：

```csv
audio_id,audio_path,channel_id,recorded_at
raw_0001,/root/autodl-tmp/vhf-data/raw_audio/raw_0001.wav,beilun_vhf_01,2026-05-11T10:00:00
```

脚本建议：

```bash
python scripts/build_raw_audio_manifest.py \
  --audio-dir /root/autodl-tmp/vhf-data/raw_audio \
  --output data_pipeline/manifests/raw_audio_manifest.csv
```

核心代码流程：

```python
from pathlib import Path
import csv

def build_manifest(audio_dir: Path, output: Path):
    files = sorted(audio_dir.rglob("*.wav"))
    with output.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["audio_id", "audio_path", "channel_id", "recorded_at"])
        writer.writeheader()
        for i, path in enumerate(files, 1):
            writer.writerow({
                "audio_id": f"raw_{i:06d}",
                "audio_path": str(path),
                "channel_id": "beilun_vhf_01",
                "recorded_at": ""
            })
```

## 3. 第二步：VAD 切分连续音频

目标：把连续混合音频切成较短的人声片段。

输入：

```text
raw_audio_manifest.csv
```

输出：

```csv
segment_id,raw_audio_id,clip_path,start_ms,end_ms,duration_ms
seg_000001,raw_0001,data_pipeline/clips/vad_segments/seg_000001.wav,1200,4600,3400
```

建议策略：

- 先用现有 `app/services/vad.py` 的 `WavEnergyVAD`。
- 后续替换为 WebRTC VAD 或 Silero VAD。
- 最长片段建议 8 到 12 秒。
- 相邻短停顿片段可以合并，避免一句话被切碎。

核心代码流程：

```python
from pathlib import Path
from app.services.vad import WavEnergyVAD
from app.services.audio_utils import slice_wav_segment

def split_with_vad(raw_audio_path: Path, output_dir: Path):
    vad = WavEnergyVAD(
        frame_ms=30,
        silence_ms=900,
        min_speech_ms=600,
        max_segment_ms=8000,
    )
    segments = vad.detect(raw_audio_path)
    rows = []
    for i, seg in enumerate(segments):
        clip_path = output_dir / f"{raw_audio_path.stem}_{i:04d}.wav"
        slice_wav_segment(raw_audio_path, clip_path, seg.start_ms, seg.end_ms)
        rows.append({
            "clip_path": str(clip_path),
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "duration_ms": seg.end_ms - seg.start_ms,
        })
    return rows
```

## 4. 第三步：ASR 批量转写

目标：给每个 VAD 片段生成机器转写文本，作为后续角色识别和弱标签的基础。

输入：

```text
vad_segments_manifest.csv
```

输出：

```csv
segment_id,clip_path,asr_text,asr_model,asr_confidence
seg_000001,data_pipeline/clips/vad_segments/seg_000001.wav,VTS宁远8报告已靠泊3号码头,funasr:iic/SenseVoiceSmall,0.85
```

可先复用：

```bash
python scripts/evaluate_asr_models.py \
  --manifest data_pipeline/manifests/vad_segments_manifest.csv \
  --models sensevoice_small \
  --output-dir data_pipeline/reports/asr_eval
```

如果 manifest 没有人工 `transcript`，这个脚本仍会输出 `prediction`，只是不能计算准确率。

核心代码流程：

```python
from app.services.asr import FunASRAdapter

asr = FunASRAdapter(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",
    punc_model="",
    device="cuda:0",
    hub="ms",
)

def transcribe_clip(clip_path):
    result = asr.transcribe(clip_path)
    return {
        "asr_text": result.text,
        "asr_model": result.engine,
        "asr_confidence": result.confidence,
    }
```

## 5. 第四步：角色识别，筛出船方呼叫

目标：从混合语音片段中区分：

```text
ship      船方呼叫
operator  值班员/管理人员回复
mixed     双方混合或压盖
unclear   无法判断
```

第一版不要训练模型，先用规则 + LLM 辅助。

船方呼叫规则：

```text
VTS，XX轮报告
我船
本船
申请
请求
报告
已靠泊
已抛锚
Mayday
请求救助
```

值班员回复规则：

```text
XX轮，VTS收到
请保持守听
请待命
请报告船名
请加强瞭望
收到
```

核心代码流程：

```python
SHIP_PATTERNS = ["报告", "我船", "本船", "申请", "请求", "已靠泊", "已抛锚", "mayday", "求救"]
OPERATOR_PATTERNS = ["vts收到", "请保持守听", "请待命", "请报告", "加强瞭望"]

def classify_role(asr_text: str) -> tuple[str, float, list[str]]:
    text = asr_text.lower().replace(" ", "")
    ship_hits = [kw for kw in SHIP_PATTERNS if kw in text]
    operator_hits = [kw for kw in OPERATOR_PATTERNS if kw in text]

    if ship_hits and not operator_hits:
        return "ship", 0.80, ship_hits
    if operator_hits and not ship_hits:
        return "operator", 0.80, operator_hits
    if ship_hits and operator_hits:
        return "mixed", 0.55, ship_hits + operator_hits
    return "unclear", 0.30, []
```

输出：

```csv
segment_id,clip_path,asr_text,role,role_confidence,role_evidence
seg_000001,...,VTS宁远8报告已靠泊3号码头,ship,0.80,报告|已靠泊
```

## 6. 第五步：生成高危弱标签

目标：在没有人工标签前，先生成弱标签，供人工复核和冷启动训练。

建议标签：

```text
high       高危
normal     非高危
uncertain  不确定/需人工复核
not_target 非船方呼叫
```

高危关键词：

```text
mayday、求救、救命、进水、起火、失火、着火、冒烟、人员落水、救生筏、左倾、严重倾斜、快沉、沉没、碰撞、搁浅、失控、失去动力
```

常规非高危关键词：

```text
靠泊、靠港、到泊、码头、已靠妥、抛锚、锚泊、抛好锚、过报告线、报告船位
```

模糊高危关键词：

```text
故障、发生问题、团雾、浓雾、看不清、让清航道、避让
```

核心代码流程：

```python
HIGH_KEYWORDS = ["mayday", "求救", "进水", "着火", "冒烟", "人员落水", "救生筏", "左倾", "碰撞", "失控"]
NORMAL_KEYWORDS = ["靠泊", "靠港", "抛锚", "报告线", "报告船位", "已靠妥"]
UNCERTAIN_KEYWORDS = ["故障", "发生问题", "团雾", "浓雾", "让清航道", "避让"]

def weak_label_risk(asr_text: str, role: str) -> dict:
    if role != "ship":
        return {"risk_label": "not_target", "risk_type": "none", "confidence": 0.9, "evidence": []}

    text = asr_text.lower().replace(" ", "")
    high_hits = [kw for kw in HIGH_KEYWORDS if kw in text]
    normal_hits = [kw for kw in NORMAL_KEYWORDS if kw in text]
    uncertain_hits = [kw for kw in UNCERTAIN_KEYWORDS if kw in text]

    if high_hits:
        return {"risk_label": "high", "risk_type": "emergency", "confidence": 0.85, "evidence": high_hits}
    if uncertain_hits:
        return {"risk_label": "uncertain", "risk_type": "ambiguous_risk", "confidence": 0.65, "evidence": uncertain_hits}
    if normal_hits:
        return {"risk_label": "normal", "risk_type": "routine_report", "confidence": 0.80, "evidence": normal_hits}
    return {"risk_label": "uncertain", "risk_type": "unknown", "confidence": 0.35, "evidence": []}
```

输出：

```csv
segment_id,clip_path,asr_text,role,risk_label,risk_type,weak_confidence,evidence
seg_000023,...,机舱冒烟请求救助,ship,high,emergency,0.85,冒烟|请求救助
```

## 7. 第六步：构造人工复核队列

目标：用最少人工标注出最有价值的数据。

优先复核：

- `risk_label=high`
- `risk_label=uncertain`
- `role=mixed`
- ASR 文本很短或为空
- 弱标签置信度低
- 多模型 ASR 结果差异大

输出人工标注表：

```csv
segment_id,clip_path,asr_text,role_pred,risk_label_pred,human_role,human_risk_label,human_risk_type,notes
seg_000023,...,机舱冒烟请求救助,ship,high,ship,high,fire_smoke,
```

人工标签建议：

```text
human_role:
  ship
  operator
  mixed
  unclear

human_risk_label:
  high
  normal
  uncertain
  not_target

human_risk_type:
  fire_smoke
  flooding
  person_overboard
  collision
  grounding
  loss_power
  routine_berth
  routine_anchor
  routine_report_line
  manual_business
  unknown
```

核心代码流程：

```python
def review_priority(row: dict) -> int:
    if row["risk_label"] == "high":
        return 100
    if row["risk_label"] == "uncertain":
        return 80
    if row["role"] in {"mixed", "unclear"}:
        return 70
    if float(row["weak_confidence"]) < 0.6:
        return 60
    if len(row["asr_text"]) < 4:
        return 50
    return 10
```

建议第一批人工复核：

```text
300 到 500 条
```

## 8. 第七步：训练第一版文本分类小模型

第一版建议训练文本模型，不建议直接训练音频模型。

原因：

- 样本少时，文本分类更稳。
- 高危场景关键词明显。
- 输出可解释。
- 与 LLM 处置建议天然衔接。

模型选择：

```text
baseline: TF-IDF + LogisticRegression
增强版: Chinese RoBERTa / MacBERT / Qwen embedding + 分类头
```

第一版 baseline 代码流程：

```python
import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

df = pd.read_csv("data_pipeline/manifests/human_labeled_manifest.csv")
df = df[df["human_role"] == "ship"]
df = df[df["human_risk_label"].isin(["high", "normal", "uncertain"])]

X_train, X_test, y_train, y_test = train_test_split(
    df["asr_text"].fillna(""),
    df["human_risk_label"],
    test_size=0.2,
    random_state=42,
    stratify=df["human_risk_label"],
)

model = Pipeline([
    ("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(1, 4), min_df=2)),
    ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
])

model.fit(X_train, y_train)
pred = model.predict(X_test)
print(classification_report(y_test, pred))
joblib.dump(model, "data_pipeline/models/risk_text_classifier/model.joblib")
```

评估重点：

```text
high 召回率
high 漏报数
uncertain 比例
整体延迟
```

业务目标：

```text
高危召回率优先，宁可多报，不可漏报。
```

## 9. 第八步：LLM 复核模糊样本

LLM 不建议直接替代分类模型，建议只处理：

- 规则命中模糊高危词。
- 小模型置信度低。
- 角色为 `mixed/unclear`。
- 高危分类结果需要生成处置建议。

LLM 输入：

```json
{
  "asr_text": "我船主机故障，前方有团雾，看不清",
  "role_prediction": "ship",
  "keyword_hits": ["故障", "团雾"],
  "model_prediction": "uncertain",
  "model_confidence": 0.58
}
```

LLM 输出必须结构化：

```json
{
  "role": "ship",
  "risk_label": "uncertain",
  "risk_type": "equipment_failure_or_visibility",
  "confidence": 0.72,
  "needs_human_review": true,
  "evidence": ["主机故障", "团雾", "看不清"],
  "suggestion": "建议值班员核实船位、航速、故障程度和周边通航态势。"
}
```

## 10. 第九步：后端推理接入

建议新增服务：

```text
app/services/role_classifier.py
app/services/risk_classifier.py
app/services/llm_reviewer.py
```

推理主流程：

```python
def classify_ship_call(segment):
    asr_text = segment.text

    role = role_classifier.predict(asr_text)
    if role.label != "ship":
        return {
            "route": "not_target",
            "risk_label": "not_target",
            "needs_human_review": False,
        }

    rule_result = risk_rules.match(asr_text)
    model_result = risk_text_classifier.predict(asr_text)

    if rule_result.label == "high":
        return {
            "route": "emergency_manual",
            "risk_label": "high",
            "needs_human_review": True,
            "suggestion": llm_reviewer.suggest(asr_text),
        }

    if model_result.label == "high" and model_result.confidence >= 0.75:
        return {
            "route": "emergency_manual",
            "risk_label": "high",
            "needs_human_review": True,
            "suggestion": llm_reviewer.suggest(asr_text),
        }

    if model_result.confidence < 0.65 or rule_result.label == "uncertain":
        llm_result = llm_reviewer.review(asr_text, rule_result, model_result)
        return {
            "route": "manual_review",
            "risk_label": llm_result["risk_label"],
            "needs_human_review": llm_result["needs_human_review"],
            "suggestion": llm_result["suggestion"],
        }

    return {
        "route": "normal_business",
        "risk_label": model_result.label,
        "needs_human_review": False,
    }
```

最终后端链路：

```text
AudioPipeline.process
-> ASR segment
-> role_classifier
-> risk_rules
-> risk_text_classifier
-> llm_reviewer for high/uncertain
-> RiskEvent
```

## 11. 第十步：上线策略

比赛演示版本：

```text
ASR + 规则 + LLM建议 + 人工确认
```

第一版可用版本：

```text
ASR + 角色规则 + 高危规则 + 文本小模型 + LLM复核
```

后续增强版本：

```text
音频 embedding + ASR文本 embedding + 小模型融合分类
```

音频模型适合在以下条件满足后再做：

- 至少 2000 到 5000 条人工确认的船方呼叫片段。
- 高危样本覆盖多个类型。
- 有足够难样本：噪声、方言、英文、急促语速、压盖。
- 已经有可靠测试集。

## 12. 核心指标

分类模型不要只看 accuracy。

必须看：

```text
高危召回率 recall_high
高危漏报数 false_negative_high
高危误报率 false_positive_high
不确定率 uncertain_rate
角色识别准确率 role_accuracy
平均延迟 latency_ms
```

推荐验收口径：

```text
高危召回率 >= 95%
高危误报可接受
不确定样本进入人工复核
自动回复只覆盖低风险、规则清晰场景
```

## 13. 最小可落地任务拆分

第一周：

```text
1. 原始音频 manifest
2. VAD 切分 manifest
3. ASR 批量转写
4. 角色规则
5. 弱标签规则
6. 人工复核 CSV
```

第二周：

```text
1. 标注 300-500 条
2. 训练 TF-IDF + LogisticRegression
3. 接入后端分类服务
4. LLM 只处理 high/uncertain
5. 前端展示分类证据和人工复核入口
```

第三周：

```text
1. 主动学习扩标
2. 评估多 ASR 模型
3. 调整关键词和阈值
4. 准备比赛演示样例
```
