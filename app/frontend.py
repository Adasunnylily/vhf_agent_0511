from __future__ import annotations

from app.config import Settings


def render_dashboard(settings: Settings) -> str:
    template = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>数字值班员</title>
  <style>
    :root {
      --bg: #07121d;
      --ocean: #0b2235;
      --ocean-2: #113755;
      --panel: #f7fbff;
      --panel-2: #eff5fb;
      --line: #d3e0ec;
      --text: #102235;
      --muted: #617689;
      --white: #f7fbff;
      --cyan: #2cb2c3;
      --blue: #1e63d6;
      --green: #148457;
      --amber: #bf7d17;
      --red: #d04b46;
      --shadow: 0 18px 42px rgba(6, 20, 34, 0.18);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 18% 0%, rgba(44, 178, 195, 0.22), transparent 28%),
        linear-gradient(180deg, #08131d 0%, #0a1825 32%, #eef3f7 32%, #eef3f7 100%);
    }
    button, input, select, textarea { font: inherit; }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 11px 12px;
      background: white;
      color: var(--text);
      outline: none;
    }
    textarea { resize: vertical; min-height: 84px; line-height: 1.5; }
    button {
      border: 0;
      border-radius: 10px;
      min-height: 40px;
      padding: 10px 14px;
      cursor: pointer;
      color: white;
      background: var(--blue);
      font-weight: 650;
    }
    button.secondary { background: #e6eef8; color: #1c3952; }
    button.green { background: var(--green); }
    button.red { background: var(--red); }
    button.dark { background: #163044; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .shell { max-width: 1500px; margin: 0 auto; padding: 18px; }
    .topbar {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto;
      gap: 16px;
      align-items: center;
      margin-bottom: 14px;
      color: var(--white);
    }
    .brand { display: flex; align-items: center; gap: 14px; }
    .brand-mark {
      width: 54px;
      height: 54px;
      display: grid;
      place-items: center;
      border-radius: 14px;
      background: linear-gradient(135deg, #2cb2c3, #1e63d6);
      box-shadow: 0 16px 34px rgba(30, 99, 214, 0.28);
      font-size: 24px;
      font-weight: 800;
    }
    .brand h1 { margin: 0; font-size: 29px; letter-spacing: 0; }
    .brand-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
    .tag {
      display: inline-flex;
      align-items: center;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.16);
      background: rgba(255,255,255,0.08);
      font-size: 12px;
      color: rgba(247,251,255,0.9);
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(5, 130px);
      gap: 10px;
    }
    .stat {
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: 12px;
      padding: 10px 12px;
    }
    .stat strong {
      display: block;
      color: white;
      font-size: 21px;
      line-height: 1.1;
      margin-bottom: 4px;
    }
    .stat span {
      display: block;
      color: rgba(247,251,255,0.74);
      font-size: 12px;
      line-height: 1.3;
    }
    .layout {
      display: grid;
      grid-template-columns: 330px minmax(520px, 1fr) 390px;
      gap: 14px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border-radius: 18px;
      box-shadow: var(--shadow);
      border: 1px solid rgba(16, 34, 53, 0.08);
      overflow: hidden;
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      background: linear-gradient(180deg, #ffffff, #edf4fb);
      border-bottom: 1px solid var(--line);
    }
    .panel-head h2 { margin: 0; font-size: 17px; }
    .panel-body { padding: 14px; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 9px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      background: #e8f0f7;
      color: #24435e;
    }
    .badge.green { background: #e5f6ee; color: #115d40; }
    .badge.red { background: #ffe8e8; color: #952f2f; }
    .badge.amber { background: #fff1d8; color: #87530a; }
    .badge.dark { background: #183246; color: #eef7ff; }
    .tabs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-bottom: 12px;
    }
    .tab.active { background: #183246; color: white; }
    .mode { display: none; }
    .mode.active { display: block; }
    .form-grid { display: grid; gap: 10px; }
    .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .audio-box {
      margin-top: 10px;
      padding: 11px;
      border-radius: 10px;
      border: 1px dashed #b3c5d8;
      background: #f5f9fc;
    }
    audio { width: 100%; height: 38px; }
    .pipeline {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 8px;
    }
    .step {
      min-height: 88px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
    }
    .step b { display: block; font-size: 13px; margin-bottom: 8px; }
    .step span { color: var(--muted); font-size: 12px; line-height: 1.4; }
    .step.active { border-color: var(--blue); box-shadow: inset 0 0 0 1px rgba(30,99,214,0.16); }
    .step.done { border-color: rgba(20,132,87,0.45); background: #f3fbf7; }
    .step.warn { border-color: rgba(191,125,23,0.5); background: #fff9ef; }
    .step.danger { border-color: rgba(208,75,70,0.5); background: #fff4f4; }
    .decision-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-top: 12px;
    }
    .decision-card {
      min-height: 100px;
      padding: 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: white;
    }
    .decision-card b { display: block; font-size: 14px; margin-bottom: 9px; }
    .decision-card strong { display: block; font-size: 24px; margin-bottom: 4px; }
    .decision-card small { color: var(--muted); line-height: 1.4; }
    .decision-card.risk { background: #fff3f3; border-color: rgba(208,75,70,0.42); }
    .decision-card.auto { background: #f1faf6; border-color: rgba(20,132,87,0.42); }
    .decision-card.manual { background: #fff8ef; border-color: rgba(191,125,23,0.42); }
    .card-grid {
      display: grid;
      grid-template-columns: 1.08fr 0.92fr;
      gap: 12px;
      margin-top: 12px;
    }
    .work-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #fff;
    }
    .work-card h3 { margin: 0 0 10px; font-size: 15px; }
    .text-box {
      min-height: 126px;
      border-radius: 10px;
      border: 1px solid #d7e2ec;
      background: #f8fbfe;
      padding: 11px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .suggest-box {
      min-height: 126px;
      border-radius: 10px;
      border: 1px solid #d7e2ec;
      background: #fbfdff;
      padding: 11px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .map {
      height: 320px;
      border-radius: 12px;
      border: 1px solid #99b3c8;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255,255,255,0.08) 1px, transparent 1px),
        linear-gradient(135deg, #14465f, #0a2b40 58%, #103949);
      background-size: 30px 30px, 30px 30px, auto;
      position: relative;
      overflow: hidden;
    }
    canvas { width: 100%; height: 100%; display: block; }
    .map-tools {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 10px 0;
    }
    .list {
      display: grid;
      gap: 8px;
      max-height: 250px;
      overflow: auto;
    }
    .item {
      border: 1px solid #d5e1ec;
      border-radius: 10px;
      background: #fff;
      padding: 10px;
    }
    .item b { display: block; font-size: 13px; margin-bottom: 5px; }
    .item span { display: block; color: var(--muted); font-size: 12px; line-height: 1.45; }
    .ship {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
    }
    .ship-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    .mini {
      display: inline-flex;
      align-items: center;
      padding: 3px 7px;
      border-radius: 999px;
      background: #edf4fb;
      color: #264963;
      font-size: 11px;
    }
    .search { margin-bottom: 8px; }
    .log {
      min-height: 156px;
      max-height: 240px;
      overflow: auto;
      border-radius: 12px;
      background: #07131f;
      color: #d9e8f6;
      padding: 10px;
      white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      line-height: 1.45;
    }
    .hidden { display: none; }
    @media (max-width: 1220px) {
      .layout { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(3, 1fr); }
      .pipeline { grid-template-columns: 1fr 1fr; }
      .decision-grid, .card-grid { grid-template-columns: 1fr; }
      .topbar { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">值</div>
        <div>
          <h1>数字值班员</h1>
          <div class="brand-tags">
            <span class="tag">VHF</span>
            <span class="tag">高危拦截</span>
            <span class="tag">自动回复</span>
            <span class="tag">人工建议</span>
            <span class="tag">AIS点验</span>
            <span class="tag">TTS</span>
          </div>
        </div>
      </div>
      <div class="stats">
        <div class="stat"><strong id="statRisk">0</strong><span>高危事件</span></div>
        <div class="stat"><strong id="statAuto">0</strong><span>自动回复</span></div>
        <div class="stat"><strong id="statManual">0</strong><span>人工处理</span></div>
        <div class="stat"><strong id="statRecords">0</strong><span>汇报索引</span></div>
        <div class="stat"><strong id="statInspection">0</strong><span>点验通知</span></div>
      </div>
    </header>

    <section class="layout">
      <aside class="panel">
        <div class="panel-head">
          <h2>任务入口</h2>
          <span class="badge green">ONLINE</span>
        </div>
        <div class="panel-body">
          <div class="tabs">
            <button type="button" class="tab active" data-mode="audioMode">音频处置</button>
            <button type="button" class="tab" data-mode="inspectionMode">点验通知</button>
          </div>

          <section id="audioMode" class="mode active">
            <form id="uploadForm" class="form-grid">
              <input id="channelId" value="__DEFAULT_CHANNEL__" placeholder="频道 ID" />
              <input id="audioFile" type="file" accept=".wav,.mp3,.flac,.m4a,.aac,.pcm" />
              <select id="denoiseMode">
                <option value="off">原音识别</option>
                <option value="on">降噪识别</option>
                <option value="compare">原音 / 降噪对比</option>
              </select>
              <button id="uploadSubmit" type="submit">开始处置</button>
            </form>
            <div id="uploadStatus" class="audio-box">等待音频</div>
            <div class="audio-box">
              <div class="badge dark" style="margin-bottom:8px;">原音回放</div>
              <audio id="audioPlayer" controls></audio>
            </div>
          </section>

          <section id="inspectionMode" class="mode">
            <div class="map"><canvas id="mapCanvas" width="620" height="360"></canvas></div>
            <div class="map-tools">
              <button type="button" class="secondary" id="drawRect">框选</button>
              <button type="button" class="secondary" id="drawLine">过线</button>
              <button type="button" class="secondary" id="clearMap">清除</button>
            </div>
            <form id="inspectionForm" class="form-grid">
              <input id="inspectionChannel" value="__DEFAULT_CHANNEL__" placeholder="频道 ID" />
              <input id="areaName" value="北仑主航道A3段" placeholder="范围名称" />
              <div class="row-2">
                <input id="minDraft" value="10" placeholder="最小吃水 m" />
                <input id="minTonnage" value="5000" placeholder="最小吨位 t" />
              </div>
              <textarea id="noticeTemplate">{船名}，数字值班员提醒：你船已进入{区域}关注范围，请保持安全航速，加强瞭望并保持守听。</textarea>
              <button type="submit">生成点验通知</button>
            </form>
          </section>
        </div>
      </aside>

      <section class="panel">
        <div class="panel-head">
          <h2>处置流转</h2>
          <span id="currentState" class="badge">待命</span>
        </div>
        <div class="panel-body">
          <div class="pipeline">
            <div class="step active" id="stepInput"><b>01 输入</b><span>原音保留、建立任务</span></div>
            <div class="step" id="stepAsr"><b>02 转写</b><span>ASR / 切段 / 留痕</span></div>
            <div class="step" id="stepRisk"><b>03 风险判断</b><span>高危拦截 / 常规分流</span></div>
            <div class="step" id="stepDecision"><b>04 回复决策</b><span>自动回复 / 人工建议</span></div>
            <div class="step" id="stepOutput"><b>05 播报</b><span>TTS 播放 / 留档索引</span></div>
          </div>

          <div class="decision-grid">
            <div class="decision-card risk">
              <b>高危情况</b>
              <strong id="riskLabel">待定</strong>
              <small id="riskReason">等待识别结果</small>
            </div>
            <div class="decision-card auto">
              <b>自动回复</b>
              <strong id="autoLabel">待定</strong>
              <small id="autoReason">等待识别结果</small>
            </div>
            <div class="decision-card manual">
              <b>人工处理</b>
              <strong id="manualLabel">待命</strong>
              <small id="manualReason">等待识别结果</small>
            </div>
          </div>

          <div class="card-grid">
            <div class="work-card">
              <h3>ASR 结果</h3>
              <div id="asrText" class="text-box">等待音频或点验任务</div>
              <div class="toolbar" style="margin-top:10px;">
                <button type="button" class="secondary" id="copyAsr">复制</button>
                <button type="button" class="secondary" id="saveRecord">存入索引</button>
              </div>
            </div>
            <div class="work-card">
              <h3>处置建议 / 回复</h3>
              <div id="llmSuggestion" class="suggest-box">等待处置决策</div>
              <div class="toolbar" style="margin-top:10px;">
                <button type="button" class="green" id="playTts">一键 TTS</button>
                <button type="button" class="red" id="manualTakeover">人工接管</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <aside class="panel">
        <div class="panel-head">
          <h2>值班侧栏</h2>
          <span id="clock" class="badge dark">--:--:--</span>
        </div>
        <div class="panel-body">
          <div class="work-card">
            <h3>汇报索引</h3>
            <input id="recordSearch" class="search" placeholder="搜索船名 / 靠泊 / 抛锚 / 高危" />
            <div id="recordList" class="list"></div>
          </div>

          <div class="work-card" style="margin-top:12px;">
            <h3>AIS 点验目标</h3>
            <div id="shipList" class="list"></div>
          </div>

          <div class="work-card" style="margin-top:12px;">
            <h3>点验通知</h3>
            <div id="noticeList" class="list"></div>
          </div>

          <div class="work-card" style="margin-top:12px;">
            <h3>运行日志</h3>
            <div id="log" class="log">READY</div>
          </div>
        </div>
      </aside>
    </section>
  </main>

  <script>
    const state = {
      activeText: "",
      activeReply: "",
      activeRecordType: "",
      records: [],
      notices: [],
      ships: [],
      counts: { risk: 0, auto: 0, manual: 0 },
      drawMode: "rect",
      drawing: false,
      startPoint: null,
      shapes: [],
      ws: null
    };

    const $ = (id) => document.getElementById(id);

    function logLine(value) {
      const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      $("log").textContent = `[${new Date().toLocaleTimeString()}] ${text}\n\n` + $("log").textContent;
    }

    async function requestJson(url, options = {}) {
      const response = await fetch(url, options);
      const text = await response.text();
      let data = {};
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (error) {
          data = { raw: text };
        }
      }
      if (!response.ok) {
        throw new Error(data.detail ? JSON.stringify(data.detail) : (data.raw || response.statusText));
      }
      return data;
    }

    function setStatus(text, kind = "") {
      const node = $("uploadStatus");
      node.textContent = text;
      node.style.background = kind === "red" ? "#fff3f3" : kind === "green" ? "#f2fbf7" : "#f5f9fc";
      node.style.borderColor = kind === "red" ? "rgba(208,75,70,0.48)" : kind === "green" ? "rgba(20,132,87,0.48)" : "#b3c5d8";
    }

    function setBadge(text, kind = "") {
      $("currentState").className = `badge ${kind}`.trim();
      $("currentState").textContent = text;
    }

    function setSteps(activeIndex, mode = "active") {
      ["stepInput","stepAsr","stepRisk","stepDecision","stepOutput"].forEach((id, index) => {
        const node = $(id);
        node.className = "step";
        if (index < activeIndex) node.classList.add("done");
        if (index === activeIndex) node.classList.add(mode);
      });
    }

    function updateStats() {
      $("statRisk").textContent = state.counts.risk;
      $("statAuto").textContent = state.counts.auto;
      $("statManual").textContent = state.counts.manual;
      $("statRecords").textContent = state.records.length;
      $("statInspection").textContent = state.notices.length;
    }

    function speak(text) {
      if (!text) return;
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = "zh-CN";
      utter.rate = 0.94;
      utter.pitch = 1.0;
      window.speechSynthesis.speak(utter);
    }

    function flattenSegments(segments) {
      if (!Array.isArray(segments)) return [];
      if (segments.length && segments[0].items) {
        return segments.flatMap((group) => group.items || []);
      }
      return segments;
    }

    function buildManualAdvice(text) {
      if (/离泊|出港|开航|申请/.test(text)) {
        return "建议人工核实离泊条件、周边态势和当前通航窗口后，再决定是否同意。";
      }
      if (/碰撞|失控|故障|搁浅/.test(text)) {
        return "建议人工立即核实 AIS 与通航态势，必要时点名相关船舶并发出避让提醒。";
      }
      return "建议值班员复核船名、位置、业务动作和当前通航态势后，再给出正式回复。";
    }

    function buildAutoReply(text) {
      if (/抛锚|锚泊/.test(text)) {
        return "VTS收到，锚泊信息已记录，请保持守听并按规定报告后续动态。";
      }
      if (/靠泊|靠港|码头|直接进去/.test(text)) {
        return "VTS收到，靠泊信息已记录，请保持守听，如计划变化请及时补充报告。";
      }
      return "VTS收到，常规动态转静态报告已记录，请保持守听。";
    }

    function deriveOutcome(task) {
      const segments = flattenSegments(task.segments || []);
      const text = segments.map((segment) => segment.text || "").filter(Boolean).join("\n");
      const events = Array.isArray(task.events) ? task.events : [];
      const highRisk = events.find((event) => ["L1", "L2"].includes(event.risk_level));
      const autoEvent = events.find((event) => event.is_auto_reply || event.action_type === "auto_reply");
      if (highRisk) {
        return {
          type: "risk",
          text,
          reply: highRisk.suggestion || "检测到高危情况，建议立即人工接管。",
          tts: highRisk.broadcast_text || highRisk.suggestion || "",
          reason: highRisk.summary || highRisk.event_type || "高危事件",
        };
      }
      if (autoEvent) {
        return {
          type: "auto",
          text,
          reply: buildAutoReply(text),
          tts: buildAutoReply(text),
          reason: autoEvent.summary || autoEvent.event_type || "常规自动回复",
        };
      }
      return {
        type: "manual",
        text,
        reply: buildManualAdvice(text),
        tts: buildManualAdvice(text),
        reason: "未命中高危或自动回复条件",
      };
    }

    function renderOutcome(task) {
      const outcome = deriveOutcome(task);
      state.activeText = outcome.text || "未识别到有效文本";
      state.activeReply = outcome.reply || "";
      state.activeRecordType = outcome.type;

      $("asrText").textContent = state.activeText;
      $("llmSuggestion").textContent = state.activeReply || "等待后续结果";

      if (outcome.type === "risk") {
        setSteps(2, "danger");
        setBadge("高危拦截", "red");
        $("riskLabel").textContent = "是";
        $("riskReason").textContent = outcome.reason;
        $("autoLabel").textContent = "否";
        $("autoReason").textContent = "高危情况不进入自动回复";
        $("manualLabel").textContent = "立即处理";
        $("manualReason").textContent = "需要人工接管并按建议处置";
        state.counts.risk += 1;
        state.counts.manual += 1;
      } else if (outcome.type === "auto") {
        setSteps(3, "done");
        setBadge("自动回复", "green");
        $("riskLabel").textContent = "否";
        $("riskReason").textContent = "未命中高危规则";
        $("autoLabel").textContent = "是";
        $("autoReason").textContent = outcome.reason;
        $("manualLabel").textContent = "无需";
        $("manualReason").textContent = "系统可生成标准回复并播报";
        state.counts.auto += 1;
      } else {
        setSteps(3, "warn");
        setBadge("人工复核", "amber");
        $("riskLabel").textContent = "否";
        $("riskReason").textContent = "未命中高危规则";
        $("autoLabel").textContent = "否";
        $("autoReason").textContent = "不满足自动回复条件";
        $("manualLabel").textContent = "建议处理";
        $("manualReason").textContent = outcome.reason;
        state.counts.manual += 1;
      }
      updateStats();
    }

    function saveRecord() {
      if (!state.activeText) return;
      state.records.unshift({
        id: `rec_${Date.now()}`,
        type: state.activeRecordType || "manual",
        text: state.activeText,
        reply: state.activeReply,
        createdAt: new Date().toLocaleString()
      });
      renderRecords($("recordSearch").value);
      updateStats();
      logLine("已存入汇报索引");
    }

    function renderRecords(keyword = "") {
      const container = $("recordList");
      const needle = keyword.trim();
      const items = state.records.filter((record) => !needle || `${record.text} ${record.reply}`.includes(needle));
      if (!items.length) {
        container.innerHTML = '<div class="item"><span>暂无索引记录</span></div>';
        return;
      }
      container.innerHTML = items.map((record) => `
        <div class="item">
          <b>${record.type === "risk" ? "高危人工处理" : record.type === "auto" ? "自动回复" : "人工建议"}</b>
          <span>${record.createdAt}</span>
          <span>${record.text.slice(0, 120)}</span>
          <div class="toolbar" style="margin-top:8px;">
            <button type="button" class="secondary" data-record-text="${encodeURIComponent(record.text)}">查看ASR</button>
            <button type="button" class="green" data-record-reply="${encodeURIComponent(record.reply || '')}">播放TTS</button>
          </div>
        </div>
      `).join("");
      container.querySelectorAll("[data-record-text]").forEach((button) => {
        button.addEventListener("click", () => {
          $("asrText").textContent = decodeURIComponent(button.dataset.recordText || "");
        });
      });
      container.querySelectorAll("[data-record-reply]").forEach((button) => {
        button.addEventListener("click", () => {
          speak(decodeURIComponent(button.dataset.recordReply || ""));
        });
      });
    }

    function renderShips() {
      const container = $("shipList");
      if (!state.ships.length) {
        container.innerHTML = '<div class="item"><span>等待加载 AIS 目标</span></div>';
        return;
      }
      container.innerHTML = state.ships.map((ship) => `
        <div class="item ship">
          <div>
            <b>${ship.ship_name}</b>
            <span>${ship.position_label} · ${ship.destination}</span>
            <div class="ship-meta">
              <span class="mini">${ship.ship_type}</span>
              <span class="mini">吨位 ${ship.tonnage_t}t</span>
              <span class="mini">吃水 ${ship.draft_m}m</span>
            </div>
          </div>
          <span class="badge">${ship.position_label.includes("A3") ? "A3" : "AIS"}</span>
        </div>
      `).join("");
    }

    function renderNotices() {
      const container = $("noticeList");
      if (!state.notices.length) {
        container.innerHTML = '<div class="item"><span>等待点验通知</span></div>';
        return;
      }
      container.innerHTML = state.notices.map((notice) => `
        <div class="item">
          <b>${notice.ship.ship_name}</b>
          <span>${notice.ship.position_label} · 吃水 ${notice.ship.draft_m}m · 吨位 ${notice.ship.tonnage_t}t</span>
          <span>${notice.notice_text}</span>
          <div class="toolbar" style="margin-top:8px;">
            <button type="button" class="green" data-notice="${encodeURIComponent(notice.notice_text)}">播放TTS</button>
          </div>
        </div>
      `).join("");
      container.querySelectorAll("[data-notice]").forEach((button) => {
        button.addEventListener("click", () => speak(decodeURIComponent(button.dataset.notice || "")));
      });
    }

    async function pollTask(taskId) {
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const task = await requestJson(`/api/tasks/${taskId}`);
        setStatus(`处理中: ${task.status}（轮询 ${attempt + 1}）`);
        if (task.status === "completed") return task;
        if (task.status === "failed") throw new Error(task.error || "任务失败");
        await new Promise((resolve) => setTimeout(resolve, 1200));
      }
      throw new Error("任务轮询超时");
    }

    function connectSocket(channelId) {
      if (state.ws) {
        state.ws.close();
      }
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${protocol}://${window.location.host}/api/ws/monitor/${channelId}`);
      state.ws = ws;
      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          logLine(payload);
          if (payload.type === "inspection_notice" && payload.payload) {
            state.notices.unshift(payload.payload);
            renderNotices();
            updateStats();
          }
        } catch (error) {
          logLine(event.data);
        }
      };
      ws.onopen = () => logLine(`WS connected: ${channelId}`);
      ws.onclose = () => logLine(`WS closed: ${channelId}`);
    }

    function drawMap() {
      const canvas = $("mapCanvas");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "rgba(122, 211, 232, 0.9)";
      ctx.fillStyle = "rgba(54, 186, 221, 0.18)";
      ctx.lineWidth = 2;

      ctx.beginPath();
      ctx.moveTo(64, 300);
      ctx.bezierCurveTo(180, 245, 298, 230, 540, 120);
      ctx.stroke();

      state.shapes.forEach((shape) => {
        if (shape.type === "rect") {
          const x = Math.min(shape.x1, shape.x2);
          const y = Math.min(shape.y1, shape.y2);
          const w = Math.abs(shape.x2 - shape.x1);
          const h = Math.abs(shape.y2 - shape.y1);
          ctx.fillRect(x, y, w, h);
          ctx.strokeRect(x, y, w, h);
        } else {
          ctx.beginPath();
          ctx.moveTo(shape.x1, shape.y1);
          ctx.lineTo(shape.x2, shape.y2);
          ctx.stroke();
        }
      });
    }

    function getCurrentGeometry() {
      if (!state.shapes.length) return "";
      return JSON.stringify(state.shapes[state.shapes.length - 1]);
    }

    function setupMap() {
      const canvas = $("mapCanvas");
      ["drawRect", "drawLine"].forEach((id) => {
        $(id).addEventListener("click", () => {
          state.drawMode = id === "drawRect" ? "rect" : "line";
          $("drawRect").classList.toggle("active", state.drawMode === "rect");
          $("drawLine").classList.toggle("active", state.drawMode === "line");
        });
      });
      $("clearMap").addEventListener("click", () => {
        state.shapes = [];
        drawMap();
      });
      canvas.addEventListener("mousedown", (event) => {
        const rect = canvas.getBoundingClientRect();
        state.drawing = true;
        state.startPoint = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      });
      canvas.addEventListener("mouseup", (event) => {
        if (!state.drawing || !state.startPoint) return;
        const rect = canvas.getBoundingClientRect();
        const endPoint = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        state.shapes.push({
          type: state.drawMode,
          x1: Math.round(state.startPoint.x),
          y1: Math.round(state.startPoint.y),
          x2: Math.round(endPoint.x),
          y2: Math.round(endPoint.y)
        });
        state.drawing = false;
        state.startPoint = null;
        drawMap();
      });
      drawMap();
    }

    function updateClock() {
      $("clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    }

    async function loadInitialData() {
      const ships = await requestJson("/api/inspection/ships");
      state.ships = ships.items || [];
      renderShips();
    }

    function resetFlow() {
      setSteps(0, "active");
      setBadge("处理中", "");
      $("riskLabel").textContent = "待定";
      $("riskReason").textContent = "处理中";
      $("autoLabel").textContent = "待定";
      $("autoReason").textContent = "处理中";
      $("manualLabel").textContent = "待命";
      $("manualReason").textContent = "处理中";
      $("asrText").textContent = "处理中";
      $("llmSuggestion").textContent = "处理中";
    }

    function setupTabs() {
      document.querySelectorAll(".tab").forEach((button) => {
        button.addEventListener("click", () => {
          document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
          document.querySelectorAll(".mode").forEach((item) => item.classList.remove("active"));
          button.classList.add("active");
          $(button.dataset.mode).classList.add("active");
        });
      });
    }

    function wireActions() {
      $("copyAsr").addEventListener("click", async () => {
        if (!state.activeText) return;
        await navigator.clipboard.writeText(state.activeText);
        logLine("已复制 ASR 文本");
      });
      $("saveRecord").addEventListener("click", saveRecord);
      $("playTts").addEventListener("click", () => speak(state.activeReply || state.activeText));
      $("manualTakeover").addEventListener("click", () => {
        setBadge("人工接管", "red");
        logLine("值班员已人工接管当前任务");
      });
      $("recordSearch").addEventListener("input", (event) => renderRecords(event.target.value));
      $("audioFile").addEventListener("change", (event) => {
        const file = event.target.files[0];
        if (!file) return;
        $("audioPlayer").src = URL.createObjectURL(file);
        setUploadStatus(`已选择：${file.name}`);
      });

      $("uploadForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          const file = $("audioFile").files[0];
          if (!file) {
            setStatus("请选择音频文件", "red");
            return;
          }
          const channelId = $("channelId").value.trim() || "__DEFAULT_CHANNEL__";
          connectSocket(channelId);
          resetFlow();
          setStatus("上传中...", "");
          const formData = new FormData();
          formData.append("file", file);
          formData.append("channel_id", channelId);
          formData.append("denoise_mode", $("denoiseMode").value);
          const createTask = await requestJson("/api/audio/upload", { method: "POST", body: formData });
          logLine(createTask);
          setSteps(1, "active");
          const task = await pollTask(createTask.task_id);
          setStatus("识别完成", "green");
          renderOutcome(task);
        } catch (error) {
          const message = error && error.message ? error.message : String(error);
          setStatus(`识别失败: ${message}`, "red");
          setBadge("失败", "red");
          logLine(`UPLOAD ERROR: ${message}`);
        }
      });

      $("inspectionForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          const channelId = $("inspectionChannel").value.trim() || "__DEFAULT_CHANNEL__";
          connectSocket(channelId);
          setBadge("点验处理中", "amber");
          const formData = new FormData();
          formData.append("channel_id", channelId);
          formData.append("area_name", $("areaName").value.trim());
          formData.append("min_draft_m", $("minDraft").value.trim());
          formData.append("min_tonnage_t", $("minTonnage").value.trim());
          formData.append("notice_template", $("noticeTemplate").value);
          formData.append("area_geometry", getCurrentGeometry());
          const createTask = await requestJson("/api/inspection/run", { method: "POST", body: formData });
          logLine(createTask);
          const task = await pollTask(createTask.task_id);
          const notices = (task.meta && task.meta.notices) || [];
          state.notices = notices.concat(state.notices);
          renderNotices();
          setBadge("点验完成", "green");
          $("asrText").textContent = `点验范围：${task.meta.area_name}\n命中目标：${task.meta.matched_count} 艘`;
          $("llmSuggestion").textContent = notices.map((item) => item.notice_text).join("\n") || "无匹配船舶";
          state.activeReply = notices[0] ? notices[0].notice_text : "";
          updateStats();
        } catch (error) {
          const message = error && error.message ? error.message : String(error);
          setBadge("点验失败", "red");
          logLine(`INSPECTION ERROR: ${message}`);
        }
      });
    }

    async function init() {
      setupTabs();
      setupMap();
      wireActions();
      updateClock();
      setInterval(updateClock, 1000);
      renderRecords();
      renderNotices();
      updateStats();
      await loadInitialData();
      connectSocket("__DEFAULT_CHANNEL__");
    }

    init().catch((error) => {
      const message = error && error.message ? error.message : String(error);
      logLine(`INIT ERROR: ${message}`);
      setBadge("初始化失败", "red");
    });
  </script>
</body>
</html>
"""
    return template.replace("__DEFAULT_CHANNEL__", settings.default_channel_id)
