from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.frontend import render_dashboard
from app.services.asr import FunASRStreamingAdapter, create_asr_adapter, create_asr_refiner
from app.services.demo_inspection import InspectionTaskSimulator
from app.services.demo_scenarios import ScenarioSimulator
from app.services.entity_resolver import EntityResolver
from app.services.event_repository import SQLiteEventRepository
from app.services.knowledge_repository import KnowledgeRepository
from app.services.pipeline import AudioPipeline
from app.services.preprocess import AudioPreprocessor
from app.services.risk_engine import KeywordRiskEngine
from app.services.storage import LocalStorage
from app.services.streaming import StreamingAudioProcessor
from app.services.streaming_realtime import RealtimeStreamingProcessor
from app.services.task_manager import InMemoryTaskManager
from app.services.vad import WavEnergyVAD
from app.services.ws_manager import ChannelWebSocketManager

settings.ensure_dirs()

storage = LocalStorage(settings)
task_manager = InMemoryTaskManager()
event_store = SQLiteEventRepository(settings.data_dir / "events.sqlite3")
knowledge_repository = KnowledgeRepository(settings.data_dir)
preprocessor = AudioPreprocessor(storage)
ws_manager = ChannelWebSocketManager()
entity_resolver = EntityResolver(
    lexicon_path=settings.entity_lexicon_path,
    enabled=settings.entity_resolver_enabled,
)
streaming_chunk_size = [
    int(part.strip())
    for part in settings.streaming_chunk_size.split(",")
    if part.strip()
]
shared_asr = create_asr_adapter(settings)
shared_mic_asr = create_asr_adapter(
    replace(settings, asr_provider=settings.mic_asr_provider, asr_model=settings.mic_asr_model)
)
shared_asr_refiner = create_asr_refiner(settings)
shared_streaming_asr = FunASRStreamingAdapter(
    model=settings.streaming_model,
    device=settings.asr_device,
    hub=settings.asr_hub,
    model_revision=settings.asr_model_revision,
    chunk_size=streaming_chunk_size,
    encoder_chunk_look_back=settings.streaming_encoder_chunk_look_back,
    decoder_chunk_look_back=settings.streaming_decoder_chunk_look_back,
)
pipeline = AudioPipeline(
    preprocessor=preprocessor,
    vad=WavEnergyVAD(
        frame_ms=settings.vad_frame_ms,
        silence_ms=settings.vad_silence_ms,
        min_speech_ms=settings.vad_min_speech_ms,
        max_segment_ms=settings.vad_max_segment_ms,
    ),
    asr=shared_asr,
    risk_engine=KeywordRiskEngine(),
    storage=storage,
    entity_resolver=entity_resolver,
    asr_refiner=shared_asr_refiner,
)
stream_processor = StreamingAudioProcessor(
    preprocessor=preprocessor,
    vad=WavEnergyVAD(
        frame_ms=settings.vad_frame_ms,
        silence_ms=settings.vad_silence_ms,
        min_speech_ms=settings.vad_min_speech_ms,
        max_segment_ms=settings.vad_max_segment_ms,
    ),
    asr=shared_asr,
    risk_engine=KeywordRiskEngine(),
    storage=storage,
    ws_manager=ws_manager,
    simulation_speed=settings.stream_simulation_speed,
    entity_resolver=entity_resolver,
    asr_refiner=shared_asr_refiner,
)
realtime_stream_processor = RealtimeStreamingProcessor(
    preprocessor=preprocessor,
    asr=shared_streaming_asr,
    risk_engine=KeywordRiskEngine(),
    ws_manager=ws_manager,
    chunk_size=streaming_chunk_size,
    entity_resolver=entity_resolver,
    asr_refiner=shared_asr_refiner,
)
scenario_simulator = ScenarioSimulator(
    risk_engine=KeywordRiskEngine(),
    ws_manager=ws_manager,
)
inspection_simulator = InspectionTaskSimulator(ws_manager=ws_manager, data_dir=settings.data_dir)
entity_resolver.set_dynamic_lexicon(inspection_simulator.dynamic_lexicon_payload())

app = FastAPI(title=settings.project_name, version=settings.version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    ws_manager.set_loop(asyncio.get_running_loop())


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return render_dashboard(settings)
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{settings.project_name}</title>
  <style>
    :root {{
      --bg: #f3f6fb;
      --panel: #ffffff;
      --line: #d8e0ea;
      --text: #142033;
      --muted: #5b6b81;
      --primary: #0f62fe;
      --primary-dark: #0043ce;
      --danger: #cf2e2e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
      background: linear-gradient(180deg, #eef4ff 0%, var(--bg) 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 24px 20px 40px;
    }}
    .hero {{
      margin-bottom: 18px;
      padding: 20px 22px;
      background: linear-gradient(135deg, #0f2748 0%, #154c84 60%, #1a6cb1 100%);
      color: #f5fbff;
      border-radius: 22px;
      box-shadow: 0 18px 40px rgba(13, 35, 70, 0.18);
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 30px;
    }}
    .hero p {{
      margin: 0;
      color: rgba(245, 251, 255, 0.88);
      line-height: 1.6;
    }}
    .hero-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .hero-pill {{
      padding: 12px 14px;
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 14px;
      background: rgba(255,255,255,0.08);
      backdrop-filter: blur(8px);
    }}
    .hero-pill strong {{
      display: block;
      font-size: 16px;
      margin-bottom: 4px;
    }}
    .hero-pill span {{
      font-size: 13px;
      color: rgba(245, 251, 255, 0.78);
      line-height: 1.5;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.2fr 1fr 1fr;
      gap: 20px;
    }}
    .cap-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 10px 30px rgba(15, 36, 84, 0.06);
    }}
    .card h2 {{
      margin: 0 0 16px;
      font-size: 20px;
    }}
    .meta {{
      display: grid;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .meta-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 10px;
      border-bottom: 1px dashed var(--line);
    }}
    .meta-row:last-child {{
      border-bottom: 0;
      padding-bottom: 0;
    }}
    .label {{
      color: var(--muted);
    }}
    form {{
      display: grid;
      gap: 12px;
    }}
    input[type="text"], input[type="file"] {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px 14px;
      font-size: 14px;
      background: #fff;
    }}
    select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px 14px;
      font-size: 14px;
      background: #fff;
    }}
    button {{
      border: 0;
      border-radius: 10px;
      background: var(--primary);
      color: #fff;
      padding: 12px 16px;
      font-size: 14px;
      cursor: pointer;
      transition: background 0.2s ease;
    }}
    button:hover {{
      background: var(--primary-dark);
    }}
    .link-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .link-row a {{
      color: var(--primary);
      text-decoration: none;
      font-weight: 600;
    }}
    .log {{
      margin-top: 14px;
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 12px;
      padding: 14px;
      min-height: 180px;
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      font-size: 13px;
      line-height: 1.5;
    }}
    .hint {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .ok {{ color: #1f7a1f; }}
    .err {{ color: var(--danger); }}
    .cap-card {{
      background: linear-gradient(145deg, #ffffff 0%, #eef5ff 100%);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(15, 36, 84, 0.05);
    }}
    .cap-card h3 {{
      margin: 0 0 8px;
      font-size: 17px;
    }}
    .cap-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    .full-span {{
      grid-column: 1 / -1;
    }}
    .ops-layout {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    .ops-box {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: linear-gradient(180deg, #f9fbff 0%, #ffffff 100%);
    }}
    .ops-box h3 {{
      margin: 0 0 8px;
      font-size: 15px;
    }}
    .ops-box p {{
      margin: 0;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.6;
    }}
    .scenario-note {{
      margin-top: 14px;
      border: 1px solid #d9e5f6;
      background: linear-gradient(180deg, #f8fbff 0%, #eef6ff 100%);
      border-radius: 14px;
      padding: 16px;
    }}
    .scenario-note h3 {{
      margin: 0 0 10px;
      font-size: 16px;
    }}
    .scenario-note p {{
      margin: 0 0 8px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.6;
    }}
    .scenario-note p:last-child {{
      margin-bottom: 0;
    }}
    @media (max-width: 1100px) {{
      .grid {{
        grid-template-columns: 1fr;
      }}
      .ops-layout {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{settings.project_name}</h1>
      <p>面向VTS值班场景，当前版本重点展示三类业务能力：由动转静报告自动回复、复杂业务人工复核、冒烟着火等高危内容秒级干预，同时支持点验通知、语音增强与识别链路演示。</p>
      <div class="hero-strip">
        <div class="hero-pill">
          <strong>减负</strong>
          <span>靠港、码头、到泊等高频通信自动生成标准回复</span>
        </div>
        <div class="hero-pill">
          <strong>管控</strong>
          <span>离泊、出港等多因素业务进入人工复核流程</span>
        </div>
        <div class="hero-pill">
          <strong>干预</strong>
          <span>冒烟、着火、Mayday 等高危内容秒级触发提醒</span>
        </div>
        <div class="hero-pill">
          <strong>增强</strong>
          <span>支持降噪、切分优化、文本清洗和流式链路演示</span>
        </div>
      </div>
    </section>

    <section class="cap-grid">
      <div class="cap-card">
        <h3>由动转静自动回复</h3>
        <p>针对靠泊、抛锚、过报告线等高频标准化通信，自动识别并生成规则回复，降低值班员重复劳动。</p>
      </div>
      <div class="cap-card">
        <h3>非自动化业务人工处理</h3>
        <p>对离泊、出港、航行计划等多因素通话自动分流，但暂不自动回复，保留值班员判断权。</p>
      </div>
      <div class="cap-card">
        <h3>冒烟着火秒级干预</h3>
        <p>对冒烟、着火、Mayday、进水等高危内容进行高优先级抓取，联动告警、播报建议和人工干预。</p>
      </div>
      <div class="cap-card">
        <h3>语音算法增强</h3>
        <p>通过标准化、降噪增强、切分优化、文本清洗和海事术语后处理，持续提升复杂噪声下的识别可用性。</p>
      </div>
      <div class="cap-card">
        <h3>点验任务自动通知</h3>
        <p>在海图指定区域、船舶筛选条件和通知模板后，自动筛选目标船舶并生成一键TTS通知内容。</p>
      </div>
    </section>

    <section class="grid">
      <div class="card">
        <h2>系统状态</h2>
        <div class="meta">
          <div class="meta-row"><span class="label">状态</span><span class="ok">running</span></div>
          <div class="meta-row"><span class="label">版本</span><span>{settings.version}</span></div>
          <div class="meta-row"><span class="label">主识别模型</span><span>{settings.asr_model}</span></div>
          <div class="meta-row"><span class="label">设备</span><span>{settings.asr_device}</span></div>
          <div class="meta-row"><span class="label">标点模型</span><span>{settings.asr_punc_model or "disabled"}</span></div>
          <div class="meta-row"><span class="label">流式模拟倍速</span><span>{settings.stream_simulation_speed}</span></div>
        </div>
        <div class="link-row">
          <a href="/docs" target="_blank">打开 API 文档</a>
          <a href="/healthz" target="_blank">查看健康检查</a>
          <a href="/api/events" target="_blank">查看事件列表</a>
        </div>
      </div>

      <div class="card">
        <h2>真实音频识别</h2>
        <form id="upload-form">
          <input type="text" id="channel_id" name="channel_id" value="{settings.default_channel_id}" placeholder="频道 ID" />
          <input type="file" id="file" name="file" accept=".wav,.mp3,.flac,.m4a,.aac,.pcm" />
          <select id="denoise_mode" name="denoise_mode">
            <option value="off">不降噪</option>
            <option value="on">开启降噪</option>
            <option value="compare">A/B 对比</option>
          </select>
          <input type="text" id="transcript_override" name="transcript_override" placeholder="可选：手工转写覆盖文本，用于无样本调试" />
          <button type="submit">上传并开始识别</button>
        </form>
        <p class="hint">这一路会先将输入统一预处理为 16k / mono / PCM wav。开启降噪时会再执行一轮 ffmpeg 语音增强；A/B 对比会分别跑原始版和降噪版。</p>
      </div>

      <div class="card">
        <h2>流式监听调试</h2>
        <form id="stream-form">
          <input type="text" id="stream_channel_id" name="channel_id" value="{settings.default_channel_id}" placeholder="频道 ID" />
          <input type="file" id="stream_file" name="file" accept=".wav,.mp3,.flac,.m4a,.aac,.pcm" />
          <select id="stream_denoise_mode" name="denoise_mode">
            <option value="off">不降噪</option>
            <option value="on">开启降噪</option>
          </select>
          <input type="text" id="stream_transcript_override" name="transcript_override" placeholder="可选：手工转写覆盖文本，用于无样本调试" />
          <button type="submit">上传并模拟流式识别</button>
        </form>
        <div class="link-row">
          <button type="button" onclick="connectMonitor()">连接实时监控</button>
        </div>
        <p class="hint">这一路会通过 WebSocket 推送预处理、VAD 片段、识别结果和命中事件，适合先验证流式链路。</p>
      </div>

      <div class="card full-span">
        <h2>值班操作闭环</h2>
        <div class="ops-layout">
          <div class="ops-box">
            <h3>由动转静自动回复</h3>
            <p>系统识别靠泊、抛锚、过报告线等高频标准化报告，自动生成规则回复文本。</p>
          </div>
          <div class="ops-box">
            <h3>非自动化业务人工处理</h3>
            <p>系统识别离泊、出港、航行计划等复杂业务，不自动放行，由值班员人工处理。</p>
          </div>
          <div class="ops-box">
            <h3>高危内容秒级干预</h3>
            <p>系统命中冒烟、着火、求救等关键词后，立即弹出高优先级事件和播报建议。</p>
          </div>
          <div class="ops-box">
            <h3>算法增强持续迭代</h3>
            <p>通过语音增强、切分优化和海事术语后处理，持续提升噪声环境下的识别准确度。</p>
          </div>
        </div>
      </div>

      <div class="card">
        <h2>Paraformer 真流式调试</h2>
        <form id="true-stream-form">
          <input type="text" id="true_stream_channel_id" name="channel_id" value="{settings.default_channel_id}" placeholder="频道 ID" />
          <input type="file" id="true_stream_file" name="file" accept=".wav,.mp3,.flac,.m4a,.aac,.pcm" />
          <select id="true_stream_denoise_mode" name="denoise_mode">
            <option value="off">不降噪</option>
            <option value="on">开启降噪</option>
          </select>
          <button type="submit">上传并调用 paraformer-zh-streaming</button>
        </form>
        <p class="hint">这一路会将音频转成 16k 单声道 PCM，再按 chunk 送入 `paraformer-zh-streaming`。WebSocket 会推送每个 chunk 的增量文本。</p>
      </div>

      <div class="card">
        <h2>业务场景仿真演示</h2>
        <form id="scenario-form">
          <input type="text" id="scenario_channel_id" name="channel_id" value="{settings.default_channel_id}" placeholder="频道 ID" />
          <select id="scenario_id" name="scenario_id">
            <option value="static_report">由动转静报告自动回复</option>
            <option value="manual_business">非自动化业务人工处理</option>
            <option value="smoke_fire">冒烟/着火秒级干预</option>
          </select>
          <button type="submit">启动场景仿真</button>
        </form>
        <p class="hint">这一路不依赖真实音频，直接按甲方关心的业务脚本推送分段文本、业务分流结果、告警和播报建议，适合汇报演示。</p>
        <div class="scenario-note" id="scenario-note">
          <h3>场景说明</h3>
          <p>选择一个业务场景后，系统不会播放真实音频，而是模拟“已经识别出的VHF通话结果”，并按真实值班流程推送事件。</p>
          <p>你可以把它理解为：为了避开真实噪声音频的不确定性，我们先稳定展示后半段业务闭环。</p>
          <p>输出内容包括：分段文本、业务分类、风险等级、自动回复建议或人工处理提示、建议播报词。</p>
        </div>
      </div>

      <div class="card">
        <h2>点验任务自动通知演示</h2>
        <form id="inspection-form">
          <input type="text" id="inspection_channel_id" name="channel_id" value="{settings.default_channel_id}" placeholder="频道 ID" />
          <input type="text" id="inspection_area_name" name="area_name" value="北仑主航道A3段" placeholder="指定区域/电子围栏名称" />
          <input type="text" id="inspection_min_draft" name="min_draft_m" value="10" placeholder="最小吃水（米）" />
          <input type="text" id="inspection_template" name="notice_template" value="{{船名}}，请注意，您已进入{{区域}}，请按规定守听并回复。" placeholder="通知模板" />
          <button type="submit">启动点验通知仿真</button>
        </form>
        <div class="scenario-note">
          <h3>这个演示在讲什么</h3>
          <p><strong>输入：</strong>在海图上预设一个区域，并设定船舶筛选条件，例如“吃水大于10米”。</p>
          <p><strong>系统动作：</strong>根据规则筛选符合条件的船舶，自动填充通知模板。</p>
          <p><strong>输出：</strong>页面会推送被命中的船舶列表和生成后的通知文本，便于后续一键TTS播报。</p>
        </div>
      </div>

      <div class="card">
        <h2>任务与实时日志</h2>
        <div class="link-row">
          <button type="button" onclick="refreshEvents()">刷新事件列表</button>
        </div>
        <div id="log" class="log">等待操作...</div>
      </div>
    </section>
  </div>

  <script>
    const form = document.getElementById("upload-form");
    const streamForm = document.getElementById("stream-form");
    const trueStreamForm = document.getElementById("true-stream-form");
    const scenarioForm = document.getElementById("scenario-form");
    const inspectionForm = document.getElementById("inspection-form");
    const scenarioNote = document.getElementById("scenario-note");
    const log = document.getElementById("log");
    let ws = null;
    const logBuffer = [];
    const scenarioMap = {{
      static_report: {{
        title: "由动转静报告自动回复",
        input: "船方主动报告“已靠泊、抛好锚、过报告线”等高频标准化通信。",
        routing: "系统将其识别为低风险高频业务，进入“自动回复建议”流程。",
        output: "页面会展示标准回复文本，例如“VTS收到，请保持守听，按计划靠泊或锚泊作业”。",
        briefing: "适合向甲方说明：先处理由动转静这类重复性强、规则清晰的通信，减轻值班员负担。"
      }},
      manual_business: {{
        title: "非自动化业务人工处理",
        input: "船方发起“申请离泊、请求出港、目的地、航行计划”等复杂业务申请。",
        routing: "系统识别后转人工处理，不生成自动放行结论。",
        output: "页面会展示人工处理提示和保守回复，例如“请保持守听，等待值班员进一步指令”。",
        briefing: "适合向甲方说明：现阶段暂不把审批类VHF业务做成自动化，避免越过态势、天气、计划等人工判断。"
      }},
      smoke_fire: {{
        title: "冒烟/着火秒级干预",
        input: "船方通话中出现“冒烟、着火、Mayday、进水”等高危表达。",
        routing: "系统将其识别为一级紧急险情，优先触发风险事件与干预建议。",
        output: "页面会展示命中证据、风险等级和建议播报词，方便值班员第一时间干预。",
        briefing: "适合向甲方说明：系统重点抓高危内容，缩短人工发现时间，提高响应时效。"
      }}
    }};

    function appendLog(value) {{
      const content = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      logBuffer.push(content);
      if (logBuffer.length > 80) {{
        logBuffer.shift();
      }}
      log.textContent = logBuffer.join("\\n\\n");
      log.scrollTop = log.scrollHeight;
    }}

    function setLog(value) {{
      logBuffer.length = 0;
      appendLog(value);
    }}

    function renderScenarioNote() {{
      const scenarioId = document.getElementById("scenario_id").value;
      const item = scenarioMap[scenarioId];
      if (!item) return;
      scenarioNote.innerHTML = `
        <h3>${{item.title}}</h3>
        <p><strong>模拟输入：</strong>${{item.input}}</p>
        <p><strong>系统分流：</strong>${{item.routing}}</p>
        <p><strong>页面输出：</strong>${{item.output}}</p>
        <p><strong>汇报口径：</strong>${{item.briefing}}</p>
      `;
    }}

    async function refreshEvents() {{
      setLog("正在拉取事件列表...");
      const resp = await fetch("/api/events");
      const data = await resp.json();
      setLog(JSON.stringify(data, null, 2));
    }}

    async function pollTask(taskId) {{
      let round = 0;
      while (round < 60) {{
        const resp = await fetch(`/api/tasks/${{taskId}}`);
        const data = await resp.json();
        setLog(JSON.stringify(data, null, 2));
        if (data.status === "completed" || data.status === "failed") {{
          return;
        }}
        round += 1;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }}
    }}

    function connectMonitor() {{
      const channelId = document.getElementById("stream_channel_id").value || "{settings.default_channel_id}";
      if (ws) {{
        ws.close();
      }}
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${{protocol}}://${{window.location.host}}/api/ws/monitor/${{channelId}}`);
      ws.onopen = () => appendLog(`WebSocket 已连接: ${{channelId}}`);
      ws.onmessage = (event) => {{
        try {{
          const data = JSON.parse(event.data);
          appendLog(data);
        }} catch {{
          appendLog(event.data);
        }}
      }};
      ws.onerror = () => appendLog("WebSocket 连接出错");
      ws.onclose = () => appendLog("WebSocket 已关闭");
    }}

    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const fileInput = document.getElementById("file");
      if (!fileInput.files.length) {{
        setLog("请选择一个音频文件。");
        return;
      }}

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      formData.append("channel_id", document.getElementById("channel_id").value);
      formData.append("denoise_mode", document.getElementById("denoise_mode").value);
      const transcriptOverride = document.getElementById("transcript_override").value;
      if (transcriptOverride) {{
        formData.append("transcript_override", transcriptOverride);
      }}

      setLog("文件已提交，正在创建任务...");
      const resp = await fetch("/api/audio/upload", {{
        method: "POST",
        body: formData
      }});

      if (!resp.ok) {{
        const text = await resp.text();
        setLog("上传失败\\n" + text);
        return;
      }}

      const data = await resp.json();
      setLog(JSON.stringify(data, null, 2));
      if (data.task_id) {{
        await pollTask(data.task_id);
      }}
    }});

    streamForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const fileInput = document.getElementById("stream_file");
      if (!fileInput.files.length) {{
        setLog("请选择一个音频文件。");
        return;
      }}

      if (!ws || ws.readyState !== WebSocket.OPEN) {{
        connectMonitor();
        await new Promise((resolve) => setTimeout(resolve, 500));
      }}

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      formData.append("channel_id", document.getElementById("stream_channel_id").value);
      formData.append("denoise_mode", document.getElementById("stream_denoise_mode").value);
      const transcriptOverride = document.getElementById("stream_transcript_override").value;
      if (transcriptOverride) {{
        formData.append("transcript_override", transcriptOverride);
      }}

      setLog("文件已提交，正在启动模拟流式识别...");
      const resp = await fetch("/api/stream/upload", {{
        method: "POST",
        body: formData
      }});

      if (!resp.ok) {{
        const text = await resp.text();
        setLog("启动模拟流失败\\n" + text);
        return;
      }}

      const data = await resp.json();
      setLog(JSON.stringify(data, null, 2));
    }});

    trueStreamForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const fileInput = document.getElementById("true_stream_file");
      if (!fileInput.files.length) {{
        setLog("请选择一个音频文件。");
        return;
      }}

      const channelId = document.getElementById("true_stream_channel_id").value;
      document.getElementById("stream_channel_id").value = channelId;
      if (!ws || ws.readyState !== WebSocket.OPEN) {{
        connectMonitor();
        await new Promise((resolve) => setTimeout(resolve, 500));
      }}

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      formData.append("channel_id", channelId);
      formData.append("denoise_mode", document.getElementById("true_stream_denoise_mode").value);

      setLog("文件已提交，正在调用 paraformer-zh-streaming...");
      const resp = await fetch("/api/streaming/upload", {{
        method: "POST",
        body: formData
      }});

      if (!resp.ok) {{
        const text = await resp.text();
        setLog("启动真流式失败\\n" + text);
        return;
      }}

      const data = await resp.json();
      setLog(JSON.stringify(data, null, 2));
    }});

    scenarioForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const channelId = document.getElementById("scenario_channel_id").value;
      document.getElementById("stream_channel_id").value = channelId;
      if (!ws || ws.readyState !== WebSocket.OPEN) {{
        connectMonitor();
        await new Promise((resolve) => setTimeout(resolve, 500));
      }}

      const scenarioId = document.getElementById("scenario_id").value;
      const formData = new FormData();
      formData.append("channel_id", channelId);

      setLog(`正在启动场景仿真: ${{scenarioId}}`);
      const resp = await fetch(`/api/demo/scenario/${{scenarioId}}`, {{
        method: "POST",
        body: formData
      }});

      if (!resp.ok) {{
        const text = await resp.text();
        setLog("启动场景仿真失败\\n" + text);
        return;
      }}

      const data = await resp.json();
      appendLog(data);
    }});

    inspectionForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const channelId = document.getElementById("inspection_channel_id").value;
      document.getElementById("stream_channel_id").value = channelId;
      if (!ws || ws.readyState !== WebSocket.OPEN) {{
        connectMonitor();
        await new Promise((resolve) => setTimeout(resolve, 500));
      }}

      const formData = new FormData();
      formData.append("channel_id", channelId);
      formData.append("area_name", document.getElementById("inspection_area_name").value);
      formData.append("min_draft_m", document.getElementById("inspection_min_draft").value);
      formData.append("notice_template", document.getElementById("inspection_template").value);

      setLog("正在启动点验任务自动通知演示...");
      const resp = await fetch("/api/inspection/run", {{
        method: "POST",
        body: formData
      }});

      if (!resp.ok) {{
        const text = await resp.text();
        setLog("启动点验任务失败\\n" + text);
        return;
      }}

      const data = await resp.json();
      appendLog(data);
    }});

    document.getElementById("scenario_id").addEventListener("change", renderScenarioNote);
    renderScenarioNote();
  </script>
</body>
</html>
    """


@app.get("/prototype", response_class=HTMLResponse)
async def prototype() -> str:
    return _render_prototype()


def _render_prototype() -> str:
    prototype_path = Path(__file__).resolve().parent.parent / "ui_prototype" / "maritime_ai_agent.html"
    if not prototype_path.exists():
        return "<h1>Prototype not found</h1>"
    return prototype_path.read_text(encoding="utf-8")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/healthz")
async def healthz() -> dict:
    from app.services.asr_prompts import resolve_dashscope_vocabulary_id, resolve_paraformer_model

    uses_paraformer_vocabulary = settings.asr_provider in {"dashscope_paraformer", "paraformer_v2"}
    vocabulary_model = resolve_paraformer_model(settings.asr_model or "paraformer-v2") if uses_paraformer_vocabulary else ""
    vocabulary_id = (
        settings.asr_vocabulary_id or resolve_dashscope_vocabulary_id(target_model=vocabulary_model)
    ) if uses_paraformer_vocabulary else ""
    return {
        "status": "ok",
        "service": settings.project_name,
        "asr_provider": settings.asr_provider,
        "asr_model": settings.asr_model,
        "mic_asr_provider": settings.mic_asr_provider,
        "mic_asr_model": settings.mic_asr_model,
        "asr_diarization_enabled": settings.asr_diarization_enabled,
        "asr_speaker_count": settings.asr_speaker_count,
        "dashscope_api_key_env": settings.dashscope_asr_api_key_env,
        "dashscope_api_key_present": bool(os.getenv(settings.dashscope_asr_api_key_env)),
        "asr_device": settings.asr_device,
        "asr_hub": settings.asr_hub,
        "asr_punc_model": settings.asr_punc_model,
        "qwen_api_key_env": settings.qwen_asr_api_key_env,
        "qwen_api_key_present": bool(os.getenv(settings.qwen_asr_api_key_env)),
        "qwen_base_url": settings.qwen_asr_base_url,
        "stream_simulation_speed": settings.stream_simulation_speed,
        "streaming_model": settings.streaming_model,
        "streaming_chunk_size": settings.streaming_chunk_size,
        "asr_vocabulary_model": vocabulary_model,
        "asr_vocabulary_active": bool(vocabulary_id),
    }


from app.api import router as api_router  # noqa: E402

app.include_router(api_router)
