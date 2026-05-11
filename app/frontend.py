from __future__ import annotations

from app.config import Settings


def render_dashboard(settings: Settings) -> str:
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>数字值班员</title>
  <style>
    :root {{
      --bg: #07131f;
      --surface: #0e1d2c;
      --surface-2: #13283b;
      --panel: #f8fbff;
      --panel-2: #eef5fb;
      --line: #c9d8e7;
      --line-dark: rgba(143, 181, 217, 0.22);
      --text: #102033;
      --muted: #65778c;
      --white: #f8fbff;
      --cyan: #2bb3c0;
      --blue: #2368d1;
      --green: #1c8f65;
      --amber: #b97812;
      --red: #c93f3f;
      --shadow: 0 16px 38px rgba(4, 18, 32, 0.18);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 25% 0%, rgba(43, 179, 192, 0.18), transparent 32%),
        linear-gradient(180deg, #06111c 0%, #0a1724 44%, #edf3f8 44%, #edf3f8 100%);
    }}
    button, input, select, textarea {{ font: inherit; }}
    button {{
      border: 0;
      border-radius: 8px;
      min-height: 38px;
      padding: 9px 13px;
      background: var(--blue);
      color: white;
      cursor: pointer;
      font-weight: 650;
    }}
    button.secondary {{ background: #e7eef7; color: #173047; }}
    button.green {{ background: var(--green); }}
    button.red {{ background: var(--red); }}
    button.dark {{ background: #183247; }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    input, select, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 11px;
      background: #fff;
      color: var(--text);
      outline: none;
    }}
    textarea {{ min-height: 84px; resize: vertical; line-height: 1.5; }}
    .shell {{ max-width: 1480px; margin: 0 auto; padding: 18px; }}
    .topbar {{
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 18px;
      align-items: center;
      color: var(--white);
      margin-bottom: 16px;
    }}
    .brand {{ display: flex; align-items: center; gap: 14px; }}
    .mark {{
      width: 52px; height: 52px; border-radius: 12px;
      display: grid; place-items: center;
      background: linear-gradient(135deg, #1b8ea0, #2368d1);
      box-shadow: 0 12px 28px rgba(35, 104, 209, 0.28);
      font-size: 24px; font-weight: 800;
    }}
    .brand h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    .brand-row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 6px; }}
    .tag {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 5px 9px; border-radius: 999px;
      background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.16);
      color: rgba(248,251,255,0.86); font-size: 12px;
    }}
    .status-strip {{ display: grid; grid-template-columns: repeat(4, 128px); gap: 10px; }}
    .stat {{
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 10px; padding: 10px;
    }}
    .stat b {{ display: block; font-size: 19px; color: #fff; }}
    .stat span {{ color: rgba(248,251,255,0.7); font-size: 12px; }}
    .layout {{
      display: grid;
      grid-template-columns: 330px minmax(430px, 1fr) 390px;
      gap: 14px;
      align-items: start;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid rgba(16, 32, 51, 0.08);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .panel-head {{
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 13px 14px;
      background: linear-gradient(180deg, #ffffff, #eef5fb);
      border-bottom: 1px solid var(--line);
    }}
    .panel-head h2 {{ margin: 0; font-size: 17px; }}
    .panel-body {{ padding: 14px; }}
    .tabs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }}
    .tab {{ background: #e8f0f7; color: #24435e; }}
    .tab.active {{ background: var(--surface-2); color: white; }}
    .mode {{ display: none; }}
    .mode.active {{ display: block; }}
    .form-grid {{ display: grid; gap: 10px; }}
    .row-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .audio-box {{
      margin-top: 10px; padding: 10px;
      border: 1px dashed #a9bed2; border-radius: 8px; background: #f4f8fc;
    }}
    audio {{ width: 100%; height: 36px; }}
    .pipeline {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 8px;
    }}
    .step {{
      min-height: 82px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      position: relative;
    }}
    .step.active {{ border-color: var(--blue); box-shadow: inset 0 0 0 1px rgba(35,104,209,0.15); }}
    .step.done {{ border-color: rgba(28,143,101,0.55); background: #f3fbf7; }}
    .step.warn {{ border-color: rgba(185,120,18,0.55); background: #fff9ec; }}
    .step.danger {{ border-color: rgba(201,63,63,0.6); background: #fff2f2; }}
    .step b {{ display: block; font-size: 13px; margin-bottom: 8px; }}
    .step span {{ color: var(--muted); font-size: 12px; line-height: 1.4; }}
    .decision {{
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
    }}
    .decision-card {{
      border-radius: 8px;
      padding: 12px;
      border: 1px solid var(--line);
      background: #fff;
      min-height: 94px;
    }}
    .decision-card b {{ display: block; font-size: 14px; margin-bottom: 8px; }}
    .decision-card strong {{ font-size: 24px; display: block; }}
    .decision-card small {{ color: var(--muted); }}
    .danger-box {{ border-color: rgba(201,63,63,0.42); background: #fff5f5; }}
    .auto-box {{ border-color: rgba(28,143,101,0.42); background: #f2fbf7; }}
    .manual-box {{ border-color: rgba(185,120,18,0.42); background: #fff9ee; }}
    .content-grid {{
      display: grid;
      grid-template-columns: 1.08fr 0.92fr;
      gap: 12px;
      margin-top: 12px;
    }}
    .work-card {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .work-card h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .asr-text {{
      min-height: 114px;
      padding: 11px;
      border-radius: 8px;
      border: 1px solid #d5e2ed;
      background: #f8fbfe;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .suggestion {{
      min-height: 114px;
      padding: 11px;
      border-radius: 8px;
      border: 1px solid #d8e3ed;
      background: #fbfdff;
      line-height: 1.62;
    }}
    .record-search {{ margin-bottom: 8px; }}
    .record-list {{ max-height: 278px; overflow: auto; display: grid; gap: 8px; }}
    .record {{
      border: 1px solid #d6e2ed;
      border-radius: 8px;
      background: #fff;
      padding: 9px;
      cursor: pointer;
    }}
    .record b {{ display: block; font-size: 13px; margin-bottom: 5px; }}
    .record span {{ display: block; color: var(--muted); font-size: 12px; line-height: 1.45; }}
    .map {{
      height: 312px;
      border: 1px solid #9db4c8;
      border-radius: 8px;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255,255,255,0.08) 1px, transparent 1px),
        linear-gradient(135deg, #154d66, #0a2e44 54%, #164958);
      background-size: 28px 28px, 28px 28px, auto;
      position: relative;
      overflow: hidden;
    }}
    canvas {{ width: 100%; height: 100%; display: block; }}
    .map-tools {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 10px 0;
    }}
    .ship-list {{ display: grid; gap: 8px; max-height: 212px; overflow: auto; }}
    .ship {{
      border: 1px solid #d6e2ed;
      border-radius: 8px;
      padding: 9px;
      background: #fff;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
    }}
    .ship b {{ font-size: 13px; }}
    .ship span {{ color: var(--muted); font-size: 12px; }}
    .notice-list {{ display: grid; gap: 8px; max-height: 260px; overflow: auto; }}
    .notice {{
      border: 1px solid #cddce8;
      border-radius: 8px;
      background: #fff;
      padding: 10px;
      line-height: 1.55;
    }}
    .badge {{
      display: inline-flex; align-items: center; gap: 5px;
      border-radius: 999px; padding: 4px 8px;
      font-size: 12px; font-weight: 700;
      background: #e8f0f7; color: #24435e;
    }}
    .badge.red {{ background: #ffe7e7; color: #9f2d2d; }}
    .badge.green {{ background: #e4f7ef; color: #116647; }}
    .badge.amber {{ background: #fff0d2; color: #83520c; }}
    .log {{
      min-height: 150px;
      max-height: 230px;
      overflow: auto;
      padding: 10px;
      border-radius: 8px;
      color: #dce9f7;
      background: #07131f;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      white-space: pre-wrap;
      line-height: 1.45;
    }}
    .compact-label {{ font-size: 12px; color: var(--muted); margin-bottom: 5px; }}
    .hidden {{ display: none; }}
    @media (max-width: 1180px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .status-strip {{ grid-template-columns: repeat(2, 1fr); }}
      .pipeline {{ grid-template-columns: 1fr 1fr; }}
      .content-grid, .decision {{ grid-template-columns: 1fr; }}
      .topbar {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="mark">值</div>
        <div>
          <h1>数字值班员</h1>
          <div class="brand-row">
            <span class="tag">VHF</span>
            <span class="tag">ASR</span>
            <span class="tag">LLM建议</span>
            <span class="tag">TTS</span>
            <span class="tag">AIS点验</span>
          </div>
        </div>
      </div>
      <div class="status-strip">
        <div class="stat"><b id="statRisk">0</b><span>高危事件</span></div>
        <div class="stat"><b id="statAuto">0</b><span>自动回复</span></div>
        <div class="stat"><b id="statManual">0</b><span>人工处理</span></div>
        <div class="stat"><b id="statRecords">0</b><span>汇报记录</span></div>
      </div>
    </header>

    <section class="layout">
      <aside class="panel">
        <div class="panel-head"><h2>任务入口</h2><span class="badge">在线</span></div>
        <div class="panel-body">
          <div class="tabs">
            <button class="tab active" type="button" data-mode="audioMode">音频</button>
            <button class="tab" type="button" data-mode="inspectionMode">点验</button>
          </div>

          <section id="audioMode" class="mode active">
            <form id="uploadForm" class="form-grid">
              <input id="channelId" name="channel_id" value="{settings.default_channel_id}" placeholder="频道 ID" />
              <input id="audioFile" type="file" accept=".wav,.mp3,.flac,.m4a,.aac,.pcm" />
              <select id="denoiseMode">
                <option value="off">原音识别</option>
                <option value="on">降噪识别</option>
                <option value="compare">原音/降噪对比</option>
              </select>
              <input id="transcriptOverride" placeholder="演示转写覆盖文本" />
              <button id="uploadSubmit" type="submit">上传识别</button>
            </form>
            <div id="uploadStatus" class="audio-box">等待选择音频</div>
            <div class="audio-box">
              <div class="compact-label">原音回放</div>
              <audio id="audioPlayer" controls></audio>
            </div>
            <div class="toolbar" style="margin-top:10px">
              <button type="button" class="secondary" data-demo="smoke_fire">高危演示</button>
              <button type="button" class="secondary" data-demo="static_report">自动回复</button>
              <button type="button" class="secondary" data-demo="manual_business">人工建议</button>
            </div>
          </section>

          <section id="inspectionMode" class="mode">
            <div class="map" id="mapBox"><canvas id="mapCanvas" width="640" height="420"></canvas></div>
            <div class="map-tools">
              <button type="button" class="secondary active" id="drawRect">框选</button>
              <button type="button" class="secondary" id="drawLine">过线</button>
              <button type="button" class="secondary" id="clearMap">清除</button>
            </div>
            <form id="inspectionForm" class="form-grid">
              <input id="inspectionChannel" value="{settings.default_channel_id}" placeholder="频道 ID" />
              <input id="areaName" value="北仑主航道A3段" placeholder="范围名称" />
              <div class="row-2">
                <input id="minDraft" value="10" placeholder="最小吃水 m" />
                <input id="minTonnage" value="5000" placeholder="最小吨位 t" />
              </div>
              <textarea id="noticeTemplate">{"{船名}"}，VTS提醒：你船即将通过{"{区域}"}，请保持安全航速，加强瞭望并保持守听。</textarea>
              <button type="submit">生成点验通知</button>
            </form>
          </section>
        </div>
      </aside>

      <section class="panel">
        <div class="panel-head"><h2>业务流转</h2><span id="currentState" class="badge">待命</span></div>
        <div class="panel-body">
          <div class="pipeline">
            <div class="step active" id="stepInput"><b>01 音频输入</b><span>原音保留</span></div>
            <div class="step" id="stepAsr"><b>02 ASR</b><span>转写/切分</span></div>
            <div class="step" id="stepRisk"><b>03 高危分类</b><span>秒级拦截</span></div>
            <div class="step" id="stepDecision"><b>04 自动化判断</b><span>动转静/人工</span></div>
            <div class="step" id="stepOutput"><b>05 TTS处置</b><span>一键播报</span></div>
          </div>

          <div class="decision">
            <div class="decision-card danger-box"><b>高危</b><strong id="riskLabel">否</strong><small id="riskReason">等待识别</small></div>
            <div class="decision-card auto-box"><b>自动回复</b><strong id="autoLabel">否</strong><small id="autoReason">等待识别</small></div>
            <div class="decision-card manual-box"><b>人工处理</b><strong id="manualLabel">待命</strong><small id="manualReason">等待识别</small></div>
          </div>

          <div class="content-grid">
            <div class="work-card">
              <h3>ASR内容</h3>
              <div id="asrText" class="asr-text">等待音频或场景输入</div>
              <div class="toolbar" style="margin-top:10px">
                <button type="button" class="secondary" id="copyAsr">复制ASR</button>
                <button type="button" class="secondary" id="saveRecord">存入列表</button>
              </div>
            </div>
            <div class="work-card">
              <h3>LLM处置建议</h3>
              <div id="llmSuggestion" class="suggestion">等待分类结果</div>
              <div class="toolbar" style="margin-top:10px">
                <button type="button" class="green" id="playTts">一键TTS</button>
                <button type="button" class="red" id="manualTakeover">人工接管</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <aside class="panel">
        <div class="panel-head"><h2>值班台</h2><span class="badge" id="clock">--:--:--</span></div>
        <div class="panel-body">
          <div class="work-card">
            <h3>汇报索引</h3>
            <input id="recordSearch" class="record-search" placeholder="搜索船名/靠泊/抛锚/风险" />
            <div id="recordList" class="record-list"></div>
          </div>
          <div class="work-card" style="margin-top:12px">
            <h3>点验通知</h3>
            <div id="noticeList" class="notice-list"></div>
          </div>
          <div class="work-card" style="margin-top:12px">
            <h3>AIS目标</h3>
            <div id="shipList" class="ship-list"></div>
          </div>
          <div class="work-card" style="margin-top:12px">
            <h3>运行日志</h3>
            <div id="log" class="log">READY</div>
          </div>
        </div>
      </aside>
    </section>
  </main>

  <script>
    const state = {{
      records: [],
      notices: [],
      ships: [],
      activeText: "",
      activeReply: "",
      counts: {{ risk: 0, auto: 0, manual: 0 }},
      drawMode: "rect",
      drawing: false,
      startPoint: null,
      shapes: []
    }};

    const $ = (id) => document.getElementById(id);

    function log(value) {{
      const line = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      $("log").textContent = `[${{new Date().toLocaleTimeString()}}] ${{line}}\\n\\n` + $("log").textContent;
    }}

    function setUploadStatus(text, kind = "") {{
      const node = $("uploadStatus");
      node.textContent = text;
      node.style.borderColor = kind === "red" ? "rgba(201,63,63,0.55)" : kind === "green" ? "rgba(28,143,101,0.55)" : "#a9bed2";
      node.style.background = kind === "red" ? "#fff2f2" : kind === "green" ? "#f2fbf7" : "#f4f8fc";
    }}

    async function requestJson(url, options = {{}}) {{
      const resp = await fetch(url, options);
      const text = await resp.text();
      let data = {{}};
      if (text) {{
        try {{
          data = JSON.parse(text);
        }} catch (error) {{
          data = {{ raw: text }};
        }}
      }}
      if (!resp.ok) {{
        const message = data.detail ? JSON.stringify(data.detail) : (data.raw || resp.statusText);
        throw new Error(`${{resp.status}} ${{message}}`);
      }}
      return data;
    }}

    function setBadge(text, kind = "") {{
      $("currentState").className = `badge ${{kind}}`;
      $("currentState").textContent = text;
    }}

    function setSteps(stage, kind = "") {{
      ["stepInput","stepAsr","stepRisk","stepDecision","stepOutput"].forEach((id, index) => {{
        const node = $(id);
        node.className = "step";
        if (index < stage) node.classList.add("done");
        if (index === stage) node.classList.add(kind || "active");
      }});
    }}

    function updateStats() {{
      $("statRisk").textContent = state.counts.risk;
      $("statAuto").textContent = state.counts.auto;
      $("statManual").textContent = state.counts.manual;
      $("statRecords").textContent = state.records.length;
    }}

    function speak(text) {{
      if (!text) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "zh-CN";
      utterance.rate = 0.92;
      window.speechSynthesis.speak(utterance);
    }}

    function flattenSegments(segments) {{
      if (!Array.isArray(segments)) return [];
      if (segments.length && segments[0].items) {{
        return segments.flatMap((group) => group.items || []);
      }}
      return segments;
    }}

    function fallbackOpinion(text) {{
      if (/离泊|出港|开航|目的地|航行计划|天气/.test(text)) {{
        return "VTS收到。建议值班员核实船舶计划、通航态势和天气条件后，再给出明确指令。";
      }}
      return "VTS收到。建议值班员复核通话语义、船名、位置和当前态势后，给出保守回复。";
    }}

    function classifyTask(task) {{
      const segments = flattenSegments(task.segments);
      const text = segments.map((item) => item.text).filter(Boolean).join("\\n") || "未获取到ASR文本";
      const events = Array.isArray(task.events) ? task.events : [];
      const primary = events[0] || null;
      const highRisk = events.some((event) => event.risk_level === "L1" || event.risk_level === "L2");
      const auto = events.some((event) => event.is_auto_reply === true);
      const manual = highRisk || !auto;
      const reply = primary?.broadcast_text || (auto ? "VTS收到，请保持守听，按计划靠泊或锚泊作业。" : fallbackOpinion(text));
      const suggestion = primary?.suggestion || (auto ? "识别为由动转静标准报告，可记录汇报信息并生成自动回复。" : fallbackOpinion(text));

      state.activeText = text;
      state.activeReply = reply;
      $("asrText").textContent = text;
      $("llmSuggestion").textContent = suggestion + "\\n\\n播报稿：" + reply;

      $("riskLabel").textContent = highRisk ? "是" : "否";
      $("riskReason").textContent = primary?.event_type || "未命中高危";
      $("autoLabel").textContent = auto ? "是" : "否";
      $("autoReason").textContent = auto ? "由动转静报告" : "不满足自动化条件";
      $("manualLabel").textContent = manual ? "需要" : "无需";
      $("manualReason").textContent = highRisk ? "高危人工接管" : auto ? "可自动播报" : "LLM建议人工复核";

      if (highRisk) {{
        state.counts.risk += 1;
        state.counts.manual += 1;
        setBadge("高危人工处理", "red");
        setSteps(4, "danger");
      }} else if (auto) {{
        state.counts.auto += 1;
        setBadge("自动回复就绪", "green");
        setSteps(4, "done");
      }} else {{
        state.counts.manual += 1;
        setBadge("人工建议就绪", "amber");
        setSteps(4, "warn");
      }}
      addRecord({{ text, reply, event: primary, status: highRisk ? "高危" : auto ? "自动回复" : "人工建议" }});
      updateStats();
    }}

    function addRecord(record) {{
      const item = {{
        id: `R${{String(state.records.length + 1).padStart(4, "0")}}`,
        time: new Date().toLocaleTimeString(),
        ...record
      }};
      state.records.unshift(item);
      renderRecords();
    }}

    function renderRecords() {{
      const q = $("recordSearch").value.trim();
      const rows = state.records.filter((item) => !q || (item.text + item.reply + item.status).includes(q));
      $("recordList").innerHTML = rows.map((item) => `
        <div class="record" data-id="${{item.id}}">
          <b>${{item.id}} · ${{item.status}} · ${{item.time}}</b>
          <span>${{item.text.slice(0, 86)}}</span>
        </div>
      `).join("") || `<div class="record"><span>暂无记录</span></div>`;
      document.querySelectorAll(".record[data-id]").forEach((node) => {{
        node.onclick = () => {{
          const item = state.records.find((record) => record.id === node.dataset.id);
          if (!item) return;
          state.activeText = item.text;
          state.activeReply = item.reply;
          $("asrText").textContent = item.text;
          $("llmSuggestion").textContent = item.reply;
        }};
      }});
      updateStats();
    }}

    async function pollTask(taskId, shouldClassify = true) {{
      setSteps(1, "active");
      for (let i = 0; i < 80; i++) {{
        const data = await requestJson(`/api/tasks/${{taskId}}`);
        if (data.status === "running") {{
          setBadge("ASR处理中");
          setUploadStatus(`任务运行中：${{taskId}}`);
          setSteps(1, "active");
        }}
        if (data.status === "completed") {{
          setSteps(2, "active");
          if (shouldClassify) classifyTask(data);
          setUploadStatus("识别完成", "green");
          log({{ task_id: taskId, status: "completed" }});
          return data;
        }}
        if (data.status === "failed") {{
          setBadge("任务失败", "red");
          setUploadStatus(`识别失败：${{data.error || "后端任务失败"}}`, "red");
          log(data);
          return data;
        }}
        await new Promise((resolve) => setTimeout(resolve, 1200));
      }}
      setBadge("等待超时", "amber");
    }}

    $("uploadForm").onsubmit = async (event) => {{
      event.preventDefault();
      const file = $("audioFile").files[0];
      if (!file) {{
        setUploadStatus("请先选择音频文件", "red");
        log("未选择音频文件");
        return;
      }}
      $("audioPlayer").src = URL.createObjectURL(file);
      state.activeText = "";
      setBadge("音频接入");
      setUploadStatus(`准备上传：${{file.name}}`);
      setSteps(0, "active");
      const formData = new FormData();
      formData.append("file", file);
      formData.append("channel_id", $("channelId").value);
      formData.append("denoise_mode", $("denoiseMode").value);
      if ($("transcriptOverride").value.trim()) formData.append("transcript_override", $("transcriptOverride").value.trim());
      $("uploadSubmit").disabled = true;
      $("uploadSubmit").textContent = "上传中";
      try {{
        setUploadStatus("正在提交到后端");
        const data = await requestJson("/api/audio/upload", {{ method: "POST", body: formData }});
        setUploadStatus(`任务已创建：${{data.task_id || "unknown"}}`);
        log(data);
        if (data.task_id) await pollTask(data.task_id);
      }} catch (error) {{
        setBadge("上传失败", "red");
        setUploadStatus(`上传失败：${{error.message}}`, "red");
        log(`上传失败：${{error.message}}`);
      }} finally {{
        $("uploadSubmit").disabled = false;
        $("uploadSubmit").textContent = "上传识别";
      }}
    }};

    document.querySelectorAll("[data-demo]").forEach((node) => {{
      node.onclick = async () => {{
        const scenarioId = node.dataset.demo;
        const formData = new FormData();
        formData.append("channel_id", $("channelId").value);
        setBadge("场景输入");
        setSteps(0, "active");
        const resp = await fetch(`/api/demo/scenario/${{scenarioId}}`, {{ method: "POST", body: formData }});
        const data = await resp.json();
        log(data);
        if (data.task_id) await pollTask(data.task_id);
      }};
    }});

    $("playTts").onclick = () => speak(state.activeReply || $("llmSuggestion").textContent);
    $("manualTakeover").onclick = () => {{
      state.counts.manual += 1;
      setBadge("人工接管", "red");
      updateStats();
      log("人工接管已记录");
    }};
    $("copyAsr").onclick = () => navigator.clipboard?.writeText(state.activeText || "");
    $("saveRecord").onclick = () => addRecord({{ text: state.activeText || $("asrText").textContent, reply: state.activeReply, status: "手动存档" }});
    $("recordSearch").oninput = renderRecords;

    document.querySelectorAll(".tab").forEach((tab) => {{
      tab.onclick = () => {{
        document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".mode").forEach((item) => item.classList.remove("active"));
        tab.classList.add("active");
        $(tab.dataset.mode).classList.add("active");
      }};
    }});

    function drawMap() {{
      const canvas = $("mapCanvas");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "rgba(165,220,232,0.38)";
      ctx.lineWidth = 1;
      for (let x = 40; x < canvas.width; x += 80) {{ ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke(); }}
      for (let y = 36; y < canvas.height; y += 68) {{ ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke(); }}
      ctx.strokeStyle = "#78d8e3";
      ctx.lineWidth = 3;
      state.shapes.forEach((shape) => {{
        ctx.beginPath();
        if (shape.type === "rect") ctx.strokeRect(shape.x, shape.y, shape.w, shape.h);
        if (shape.type === "line") {{ ctx.moveTo(shape.x1, shape.y1); ctx.lineTo(shape.x2, shape.y2); ctx.stroke(); }}
      }});
      state.ships.forEach((ship, index) => {{
        const x = 90 + (index * 128) % 470;
        const y = 72 + (index * 84) % 260;
        ctx.fillStyle = index % 2 ? "#f5c45d" : "#9be7d0";
        ctx.beginPath();
        ctx.moveTo(x, y - 9); ctx.lineTo(x + 17, y + 8); ctx.lineTo(x - 13, y + 10); ctx.closePath(); ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.font = "13px sans-serif";
        ctx.fillText(ship.ship_name || ship.shipName, x + 18, y + 5);
      }});
    }}

    function canvasPoint(event) {{
      const rect = $("mapCanvas").getBoundingClientRect();
      return {{
        x: (event.clientX - rect.left) * $("mapCanvas").width / rect.width,
        y: (event.clientY - rect.top) * $("mapCanvas").height / rect.height
      }};
    }}

    $("mapCanvas").onmousedown = (event) => {{ state.drawing = true; state.startPoint = canvasPoint(event); }};
    $("mapCanvas").onmouseup = (event) => {{
      if (!state.drawing || !state.startPoint) return;
      const end = canvasPoint(event);
      const start = state.startPoint;
      if (state.drawMode === "rect") state.shapes.push({{ type: "rect", x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), w: Math.abs(end.x - start.x), h: Math.abs(end.y - start.y) }});
      if (state.drawMode === "line") state.shapes.push({{ type: "line", x1: start.x, y1: start.y, x2: end.x, y2: end.y }});
      state.drawing = false;
      drawMap();
    }};
    $("drawRect").onclick = () => {{ state.drawMode = "rect"; $("drawRect").classList.add("active"); $("drawLine").classList.remove("active"); }};
    $("drawLine").onclick = () => {{ state.drawMode = "line"; $("drawLine").classList.add("active"); $("drawRect").classList.remove("active"); }};
    $("clearMap").onclick = () => {{ state.shapes = []; drawMap(); }};

    async function loadShips() {{
      const resp = await fetch("/api/inspection/ships");
      const data = await resp.json();
      state.ships = data.items || [];
      $("shipList").innerHTML = state.ships.map((ship) => `
        <div class="ship"><div><b>${{ship.ship_name}}</b><span>吃水 ${{ship.draft_m}}m · ${{ship.destination}}</span></div><span class="badge">${{ship.position_label}}</span></div>
      `).join("");
      drawMap();
    }}

    $("inspectionForm").onsubmit = async (event) => {{
      event.preventDefault();
      const formData = new FormData();
      formData.append("channel_id", $("inspectionChannel").value);
      formData.append("area_name", $("areaName").value);
      formData.append("min_draft_m", $("minDraft").value);
      formData.append("notice_template", $("noticeTemplate").value);
      const resp = await fetch("/api/inspection/run", {{ method: "POST", body: formData }});
      const data = await resp.json();
      log(data);
      if (data.task_id) {{
        const task = await pollTask(data.task_id, false);
        const notices = task?.meta?.notices || [];
        state.notices = notices;
        $("noticeList").innerHTML = notices.map((item) => `
          <div class="notice">
            <b>${{item.ship.ship_name}}</b><br />
            ${{item.notice_text}}
            <div class="toolbar" style="margin-top:8px"><button type="button" class="green" data-say="${{item.notice_id}}">TTS</button></div>
          </div>
        `).join("") || `<div class="notice">暂无命中船舶</div>`;
        document.querySelectorAll("[data-say]").forEach((btn) => {{
          btn.onclick = () => {{
            const item = state.notices.find((notice) => notice.notice_id === btn.dataset.say);
            if (item) speak(item.notice_text);
          }};
        }});
      }}
    }};

    setInterval(() => $("clock").textContent = new Date().toLocaleTimeString(), 1000);
    updateStats();
    renderRecords();
    loadShips();
  </script>
</body>
</html>
"""
