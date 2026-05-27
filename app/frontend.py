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
      --panel: rgba(9, 25, 40, 0.86);
      --panel-2: rgba(14, 39, 61, 0.72);
      --line: rgba(113, 199, 227, 0.18);
      --text: #eaf6ff;
      --muted: #8faabd;
      --white: #f7fbff;
      --cyan: #35d5ef;
      --blue: #3a7cff;
      --green: #26d28a;
      --amber: #ffb84d;
      --red: #ff5e5b;
      --shadow: 0 24px 70px rgba(0, 0, 0, 0.32);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 16% 3%, rgba(53, 213, 239, 0.22), transparent 28%),
        radial-gradient(circle at 80% 0%, rgba(58, 124, 255, 0.18), transparent 30%),
        linear-gradient(135deg, #040a12 0%, #07131f 46%, #081a2a 100%);
    }
    button, input, select, textarea { font: inherit; }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 11px 12px;
      background: rgba(4, 14, 24, 0.72);
      color: var(--text);
      outline: none;
    }
    input::placeholder, textarea::placeholder { color: rgba(143, 170, 189, 0.75); }
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
    button.secondary { background: rgba(145, 178, 207, 0.16); color: #dcecff; border: 1px solid rgba(113,199,227,0.16); }
    button.green { background: var(--green); }
    button.red { background: var(--red); }
    button.dark { background: linear-gradient(135deg, #163044, #0d2235); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .panel, .work-card, .decision-card, .ops-tile, .stat {
      transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
    }
    .panel:hover, .work-card:hover, .decision-card:hover, .ops-tile:hover, .stat:hover {
      transform: translateY(-2px);
      border-color: rgba(47,128,255,0.38);
      box-shadow: 0 18px 46px rgba(0, 80, 180, 0.16);
    }
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
      background: linear-gradient(180deg, rgba(11, 34, 53, 0.78), rgba(5, 19, 31, 0.7));
      border: 1px solid rgba(53,213,239,0.14);
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
    .agent-strip {
      display: grid;
      grid-template-columns: 76px minmax(240px, 1fr) auto;
      gap: 14px;
      align-items: center;
      padding: 14px;
      margin-bottom: 12px;
      border-radius: 14px;
      background:
        linear-gradient(135deg, rgba(13, 41, 64, 0.94), rgba(7, 24, 39, 0.92)),
        radial-gradient(circle at 100% 0%, rgba(53,213,239,0.18), transparent 34%);
      border: 1px solid rgba(53,213,239,0.18);
    }
    .agent-avatar {
      width: 64px;
      height: 64px;
      display: grid;
      place-items: center;
      border-radius: 18px;
      background: linear-gradient(135deg, #35d5ef, #285dff);
      color: #f7fbff;
      font-size: 30px;
      font-weight: 800;
      box-shadow: inset 0 -10px 24px rgba(44,178,195,0.24);
    }
    .agent-strip h3 { margin: 0 0 6px; font-size: 18px; }
    .agent-strip p { margin: 0; color: var(--muted); line-height: 1.5; font-size: 13px; }
    .agent-pills { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .agent-pill {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 5px 10px;
      border-radius: 999px;
      background: rgba(53,213,239,0.1);
      color: #c9f5ff;
      font-size: 12px;
      font-weight: 700;
    }
    .layout {
      display: grid;
      grid-template-columns: 350px minmax(560px, 1fr) 410px;
      gap: 14px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      backdrop-filter: blur(18px);
      border-radius: 20px;
      box-shadow: var(--shadow);
      border: 1px solid rgba(113, 199, 227, 0.14);
      overflow: hidden;
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      background: linear-gradient(180deg, rgba(18, 50, 76, 0.94), rgba(9, 27, 44, 0.92));
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
      background: rgba(143, 170, 189, 0.15);
      color: #d8edff;
    }
    .badge.green { background: rgba(38,210,138,0.15); color: #8dffd0; }
    .badge.red { background: rgba(255,94,91,0.16); color: #ffb6b5; }
    .badge.amber { background: rgba(255,184,77,0.16); color: #ffd48d; }
    .badge.dark { background: rgba(53,213,239,0.13); color: #c9f5ff; }
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
      border: 1px solid rgba(113,199,227,0.16);
      background: rgba(5, 18, 31, 0.52);
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
      background: rgba(5, 18, 31, 0.62);
    }
    .step b { display: block; font-size: 13px; margin-bottom: 8px; }
    .step span { color: var(--muted); font-size: 12px; line-height: 1.4; }
    .step.active { border-color: var(--blue); box-shadow: inset 0 0 0 1px rgba(30,99,214,0.16); }
    .step.done { border-color: rgba(38,210,138,0.42); background: rgba(38,210,138,0.08); }
    .step.warn { border-color: rgba(255,184,77,0.45); background: rgba(255,184,77,0.08); }
    .step.danger { border-color: rgba(255,94,91,0.48); background: rgba(255,94,91,0.08); }
    .agent-action {
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }
    .agent-action .work-card {
      min-height: 96px;
      background: rgba(7, 24, 39, 0.66);
    }
    .agent-action b {
      display: block;
      font-size: 13px;
      margin-bottom: 8px;
    }
    .agent-action span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .decision-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-top: 12px;
    }
    .decision-card {
      min-height: 100px;
      padding: 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(5, 18, 31, 0.66);
    }
    .decision-card b { display: block; font-size: 14px; margin-bottom: 9px; }
    .decision-card strong { display: block; font-size: 24px; margin-bottom: 4px; }
    .decision-card small { color: var(--muted); line-height: 1.4; }
    .decision-card.risk { background: rgba(255,94,91,0.09); border-color: rgba(255,94,91,0.38); }
    .decision-card.risk { display: none; }
    .decision-card.auto { background: rgba(38,210,138,0.08); border-color: rgba(38,210,138,0.34); }
    .decision-card.manual { background: rgba(255,184,77,0.08); border-color: rgba(255,184,77,0.34); }
    .decision-card.auto strong { color: #7cffd1; }
    .decision-card.manual strong { color: #82b7ff; }
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
      background: rgba(5, 18, 31, 0.62);
    }
    .work-card h3 { margin: 0 0 10px; font-size: 15px; }
    .text-box {
      min-height: 126px;
      border-radius: 10px;
      border: 1px solid rgba(113,199,227,0.16);
      background: rgba(3, 13, 22, 0.62);
      padding: 11px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .suggest-box {
      min-height: 126px;
      border-radius: 10px;
      border: 1px solid rgba(113,199,227,0.16);
      background: rgba(3, 13, 22, 0.62);
      padding: 11px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .map {
      height: 320px;
      border-radius: 12px;
      border: 1px solid rgba(53,213,239,0.24);
      background:
        linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255,255,255,0.08) 1px, transparent 1px),
        linear-gradient(135deg, #14465f, #0a2b40 58%, #103949);
      background-size: 30px 30px, 30px 30px, auto;
      position: relative;
      overflow: hidden;
    }
    #amapContainer { width: 100%; height: 100%; }
    .sea-overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 10;
    }
    .sea-overlay svg { width: 100%; height: 100%; display: block; }
    .ship-arrow {
      filter: drop-shadow(0 0 8px rgba(53,213,239,0.8));
      transform-box: fill-box;
      transform-origin: center;
    }
    .ship-arrow.green { filter: drop-shadow(0 0 8px rgba(38,210,138,0.74)); }
    .ship-arrow.red { filter: drop-shadow(0 0 8px rgba(255,94,91,0.8)); }
    .radar-ring {
      transform-origin: 50% 50%;
      animation: radarPulse 2.2s ease-out infinite;
    }
    .ship-popup {
      position: absolute;
      left: 47%;
      top: 35%;
      width: 190px;
      padding: 12px;
      border-radius: 12px;
      background: rgba(3, 13, 24, 0.78);
      border: 1px solid rgba(113,199,227,0.24);
      box-shadow: 0 18px 48px rgba(0,0,0,0.38);
      color: #eaf6ff;
      font-size: 12px;
      backdrop-filter: blur(16px);
    }
    .ship-popup b { display: block; font-size: 15px; margin-bottom: 6px; }
    .ship-popup span { display: block; color: #a9c4d8; line-height: 1.6; }
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
      border: 1px solid rgba(113,199,227,0.14);
      border-radius: 10px;
      background: rgba(5, 18, 31, 0.56);
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
    .ship.selected {
      border-color: rgba(38,210,138,0.55);
      background: rgba(38,210,138,0.1);
      box-shadow: inset 4px 0 0 #26d28a;
    }
    .ship-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    .mini {
      display: inline-flex;
      align-items: center;
      padding: 3px 7px;
      border-radius: 999px;
      background: rgba(53,213,239,0.1);
      color: #bcefff;
      font-size: 11px;
    }
    .search { margin-bottom: 8px; }
    .checklist {
      display: grid;
      gap: 7px;
    }
    .check {
      display: grid;
      grid-template-columns: 24px 1fr;
      gap: 8px;
      align-items: start;
      padding: 8px;
      border-radius: 10px;
      background: #f7fbff;
      border: 1px solid #d9e6ef;
    }
    .check i {
      width: 20px;
      height: 20px;
      display: grid;
      place-items: center;
      border-radius: 50%;
      background: #183246;
      color: white;
      font-style: normal;
      font-size: 11px;
      font-weight: 800;
    }
    .check b { display: block; font-size: 12px; margin-bottom: 3px; }
    .check span { display: block; color: var(--muted); font-size: 11px; line-height: 1.45; }
    .ops-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
    }
    .ops-tile {
      min-height: 76px;
      border-radius: 14px;
      padding: 12px;
      border: 1px solid rgba(113,199,227,0.14);
      background:
        linear-gradient(135deg, rgba(53,213,239,0.08), rgba(58,124,255,0.05)),
        rgba(5, 18, 31, 0.62);
    }
    .ops-tile b { display: block; font-size: 20px; margin-bottom: 5px; color: #f5fbff; }
    .ops-tile span { display: block; color: var(--muted); font-size: 12px; }
    .console {
      width: min(1580px, calc(100vw - 28px));
      min-height: calc(100vh - 28px);
      margin: 14px auto;
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr);
      gap: 12px;
      padding: 10px;
      border-radius: 22px;
      background:
        linear-gradient(135deg, rgba(12, 35, 56, 0.86), rgba(3, 12, 22, 0.94)),
        radial-gradient(circle at 60% 8%, rgba(53,213,239,0.16), transparent 32%);
      border: 1px solid rgba(113,199,227,0.18);
      box-shadow: 0 30px 90px rgba(0, 0, 0, 0.48);
    }
    .side-rail {
      border-radius: 18px;
      padding: 16px 12px;
      background: linear-gradient(180deg, rgba(4,15,28,0.94), rgba(5,20,35,0.76));
      border: 1px solid rgba(113,199,227,0.12);
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 20px;
    }
    .product-mark { display: flex; align-items: center; gap: 10px; }
    .product-mark b { display: block; font-size: 13px; color: #f7fbff; line-height: 1.2; }
    .product-mark span { display: block; font-size: 11px; color: var(--muted); margin-top: 3px; }
    .nav-stack { display: grid; gap: 10px; align-content: start; }
    .nav-item {
      width: 100%;
      min-height: 56px;
      display: grid;
      place-items: center;
      border-radius: 13px;
      background: transparent;
      border: 1px solid transparent;
      color: #a7bfd2;
      font-size: 13px;
    }
    .nav-item.active {
      color: #f7fbff;
      background: linear-gradient(135deg, rgba(58,124,255,0.4), rgba(53,213,239,0.12));
      border-color: rgba(58,124,255,0.55);
      box-shadow: inset 0 0 24px rgba(58,124,255,0.16);
    }
    .rail-footer { display: grid; gap: 8px; }
    .workspace {
      min-width: 0;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 12px;
    }
    .app-top {
      min-height: 66px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 10px 14px 10px 18px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(8,25,42,0.92), rgba(7,23,38,0.78));
      border: 1px solid rgba(113,199,227,0.12);
    }
    .app-top h1 { margin: 0; font-size: 22px; color: #f7fbff; }
    .app-top p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
    .top-actions { display: flex; align-items: center; gap: 10px; }
    .screen { min-height: 0; }
    .screen.mode { display: none; }
    .screen.mode.active { display: grid; }
    .voice-screen {
      grid-template-columns: minmax(480px, 1.15fr) minmax(360px, 0.85fr) 340px;
      grid-template-rows: 300px minmax(0, 1fr);
      gap: 12px;
    }
    .voice-stage {
      grid-column: 1 / 2;
      grid-row: 1 / 2;
      display: grid;
      place-items: center;
      padding: 24px;
      position: relative;
      overflow: hidden;
    }
    .voice-stage::before {
      content: "";
      position: absolute;
      inset: 18px;
      border-radius: 18px;
      background: radial-gradient(circle, rgba(58,124,255,0.16), transparent 50%);
      pointer-events: none;
    }
    .voice-hero { position: relative; z-index: 1; display: flex; align-items: center; justify-content: center; gap: 26px; }
    .mic-orb {
      width: 128px;
      height: 128px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at 50% 42%, rgba(255,255,255,0.94), rgba(53,213,239,0.2) 22%, transparent 24%),
        radial-gradient(circle, #236dff, #061d48 70%);
      box-shadow: 0 0 0 16px rgba(53,213,239,0.08), 0 0 54px rgba(53,213,239,0.46);
      animation: micBreath 2.6s ease-in-out infinite;
    }
    .mic-orb.listening { animation: micBreath 1.35s ease-in-out infinite; }
    .mic-icon { font-size: 54px; transform: rotate(90deg); }
    .wave {
      width: 168px;
      height: 72px;
      opacity: 0.8;
      background:
        repeating-linear-gradient(90deg, transparent 0 9px, rgba(53,213,239,0.22) 9px 11px, transparent 11px 16px),
        linear-gradient(90deg, transparent, rgba(58,124,255,0.5), transparent);
      clip-path: polygon(0 48%, 8% 46%, 14% 42%, 20% 55%, 27% 18%, 34% 70%, 40% 30%, 47% 82%, 53% 22%, 60% 65%, 67% 37%, 75% 55%, 83% 44%, 100% 49%, 100% 54%, 0 54%);
      animation: waveFlow 1.4s ease-in-out infinite alternate;
    }
    .wave.right { transform: scaleX(-1); }
    .voice-caption { position: relative; z-index: 1; text-align: center; margin-top: -10px; }
    .voice-caption strong { display: block; font-size: 18px; margin-bottom: 6px; }
    .voice-caption span { color: var(--muted); font-size: 13px; }
    .mic-timer { margin-top: 9px; font-size: 20px; letter-spacing: 1px; color: #f7fbff; }
    .voice-controls { position: relative; z-index: 1; width: 100%; justify-content: center; }
    .input-dock { grid-column: 3 / 4; grid-row: 1 / 2; }
    .transcript-panel { grid-column: 1 / 2; grid-row: 2 / 3; }
    .decision-panel { grid-column: 2 / 3; grid-row: 1 / 3; }
    .voice-side { grid-column: 3 / 4; grid-row: 2 / 3; }
    .reply-card { margin-top: 12px; }
    .compact-stats { grid-template-columns: repeat(2, 1fr); margin: 12px 0; }
    .compact-stats .stat:last-child { grid-column: span 2; }
    .fence-screen {
      grid-template-columns: minmax(620px, 1fr) 330px;
      grid-template-rows: minmax(430px, 1fr) minmax(300px, auto);
      gap: 12px;
    }
    .fence-main { grid-column: 1 / 2; grid-row: 1 / 2; }
    .fence-main .map { height: 100%; min-height: 420px; }
    .fence-config { grid-column: 2 / 3; grid-row: 1 / 2; }
    .fence-bottom {
      grid-column: 1 / 3;
      grid-row: 2 / 3;
      display: grid;
      grid-template-columns: 1fr 1fr 1.2fr;
      align-content: start;
      gap: 12px;
      min-height: 0;
    }
    .fence-tabs {
      display: flex;
      gap: 28px;
      margin: 0 0 12px;
      padding: 0 2px 10px;
      border-bottom: 1px solid rgba(113,199,227,0.12);
    }
    .fence-tab {
      position: relative;
      color: #8faabd;
      font-size: 13px;
      padding: 4px 0;
    }
    .fence-tab.active { color: #73c8ff; }
    .fence-tab.active::after {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: -11px;
      height: 2px;
      border-radius: 999px;
      background: #2f80ff;
      box-shadow: 0 0 12px rgba(47,128,255,0.9);
    }
    .fence-metrics {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-top: 12px;
    }
    .broadcast-options {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }
    .broadcast-options label {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 9px;
      border-radius: 10px;
      border: 1px solid rgba(113,199,227,0.14);
      background: rgba(5,18,31,0.42);
      color: #cfe7fb;
      font-size: 12px;
    }
    .broadcast-options input { width: auto; accent-color: #1677ff; }
    @keyframes micBreath {
      0%, 100% { box-shadow: 0 0 0 12px rgba(53,213,239,0.08), 0 0 46px rgba(53,213,239,0.32); transform: scale(0.99); }
      50% { box-shadow: 0 0 0 22px rgba(53,213,239,0.13), 0 0 72px rgba(53,213,239,0.58); transform: scale(1.03); }
    }
    @keyframes waveFlow {
      0% { opacity: 0.45; transform: scaleY(0.72); }
      100% { opacity: 0.95; transform: scaleY(1.12); }
    }
    @keyframes radarPulse {
      0% { r: 10; opacity: 0.72; }
      100% { r: 58; opacity: 0; }
    }
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
      .console { grid-template-columns: 1fr; }
      .side-rail { grid-template-rows: auto auto; }
      .nav-stack { grid-template-columns: repeat(2, 1fr); }
      .layout { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(3, 1fr); }
      .agent-strip { grid-template-columns: 1fr; }
      .agent-pills { justify-content: flex-start; }
      .pipeline { grid-template-columns: 1fr 1fr; }
      .agent-action { grid-template-columns: 1fr 1fr; }
      .decision-grid, .card-grid { grid-template-columns: 1fr; }
      .topbar { grid-template-columns: 1fr; }
      .voice-screen, .fence-screen, .fence-bottom { grid-template-columns: 1fr; grid-template-rows: auto; }
      .voice-stage, .input-dock, .transcript-panel, .decision-panel, .voice-side, .fence-main, .fence-config, .fence-bottom { grid-column: auto; grid-row: auto; }
    }
  </style>
</head>
<body>
  <main class="console">
    <aside class="side-rail">
      <div class="product-mark">
        <div class="brand-mark">AI</div>
        <div>
          <b>海事交管智能体</b>
          <span>Maritime AI Agent</span>
        </div>
      </div>
      <nav class="nav-stack">
        <button type="button" class="nav-item tab active" data-mode="audioMode">语音交互</button>
        <button type="button" class="nav-item tab" data-mode="inspectionMode">围栏广播</button>
        <button type="button" class="nav-item">船舶监控</button>
        <button type="button" class="nav-item">事件中心</button>
        <button type="button" class="nav-item">知识库</button>
        <button type="button" class="nav-item">设置中心</button>
      </nav>
      <div class="rail-footer">
        <span class="badge green">在线</span>
        <span id="clock" class="badge dark">--:--:--</span>
      </div>
    </aside>

    <section class="workspace">
      <header class="app-top">
        <div>
          <h1 id="agentTitle">我在听，请说话...</h1>
          <p id="agentNarrative">接入VHF语音后，系统将识别船舶请求、判断处置类型，并生成可编辑回复。</p>
        </div>
        <div class="top-actions">
          <span id="currentState" class="badge green">待命</span>
          <button type="button" class="secondary" id="saveRecord">存入留档</button>
        </div>
      </header>

      <section id="audioMode" class="mode active screen voice-screen">
        <div class="voice-stage panel">
          <div class="voice-hero">
            <div class="wave"></div>
            <button type="button" class="mic-orb" id="micStartBtn">
              <span class="mic-icon">⌁</span>
            </button>
            <div class="wave right"></div>
          </div>
          <div class="voice-caption">
            <strong>现场语音输入</strong>
            <span id="micStatus">点击麦克风开始连续守听</span>
            <div class="mic-timer" id="micTimer">00:00</div>
          </div>
          <div class="toolbar voice-controls">
            <button type="button" id="micStopBtn" class="secondary" disabled>停止麦克风</button>
            <audio id="audioPlayer" controls></audio>
          </div>
        </div>

        <aside class="panel input-dock">
          <div class="panel-head"><h2>音频接入</h2><span class="badge dark">VHF</span></div>
          <div class="panel-body">
            <form id="uploadForm" class="form-grid">
              <input id="channelId" value="__DEFAULT_CHANNEL__" placeholder="频道 ID" />
              <input id="audioFile" type="file" accept=".wav,.mp3,.flac,.m4a,.aac,.pcm,.webm,.ogg" />
              <select id="processingMode">
                <option value="batch">离线识别（稳定）</option>
                <option value="stream_sim">模拟流式（VAD分段）</option>
                <option value="stream_rt">准实时回放（API稳定）</option>
              </select>
              <select id="denoiseMode">
                <option value="off">原音识别</option>
                <option value="on">降噪识别</option>
                <option value="compare">原音 / 降噪对比</option>
              </select>
              <button id="uploadSubmit" type="submit">上传并处置</button>
            </form>
            <div id="uploadStatus" class="audio-box">等待音频</div>
          </div>
        </aside>

        <section class="panel transcript-panel">
          <div class="panel-head"><h2>语音识别结果</h2><span class="badge dark">ASR</span></div>
          <div class="panel-body">
            <div id="asrText" class="text-box">你好，我是海运888，请求进入盐田港，请问可以进港吗？</div>
            <div class="agent-action">
              <div class="work-card"><b>输入证据</b><span id="agentEvidence">VHF CH16 · 清晰语音</span></div>
              <div class="work-card"><b>语义理解</b><span id="agentIntent">意图：进港申请；实体：海运888；目标港口：盐田港</span></div>
              <div class="work-card"><b>处置策略</b><span id="agentPolicy">常规进港咨询，符合港口开放规则</span></div>
              <div class="work-card"><b>下一步</b><span id="agentNextAction">可发送自动回复</span></div>
            </div>
          </div>
        </section>

        <section class="panel decision-panel">
          <div class="panel-head"><h2>智能决策</h2><span class="badge dark">Decision</span></div>
          <div class="panel-body">
            <div class="decision-grid">
              <div class="decision-card risk"><b>高危情况</b><strong id="riskLabel">待定</strong><small id="riskReason">等待识别结果</small></div>
              <div class="decision-card auto"><b>自动回复</b><strong id="autoLabel">92%</strong><small id="autoReason">常规进港咨询，符合港口开放规则</small></div>
              <div class="decision-card manual"><b>人工判断</b><strong id="manualLabel">42%</strong><small id="manualReason">涉及特殊情况时转人工确认</small></div>
            </div>
            <div class="reply-card">
              <h3>回复内容</h3>
              <div id="llmSuggestion" class="suggest-box" contenteditable="true" spellcheck="false">海运888，盐田港当前允许进港，请按 VHF CH16 保持联系，注意航道通航安全。</div>
              <div class="toolbar">
                <button type="button" class="green" id="playTts">发送语音回复</button>
                <button type="button" class="red" id="manualTakeover">转人工处理</button>
                <button type="button" class="secondary" id="copyAsr">复制文本</button>
              </div>
            </div>
            <div class="pipeline">
              <div class="step active" id="stepInput"><b>01 接入</b><span>任务建立</span></div>
              <div class="step" id="stepAsr"><b>02 听写</b><span>转写留痕</span></div>
              <div class="step" id="stepRisk"><b>03 判断</b><span>业务分流</span></div>
              <div class="step" id="stepDecision"><b>04 建议</b><span>生成话术</span></div>
              <div class="step" id="stepOutput"><b>05 执行</b><span>播报留档</span></div>
            </div>
          </div>
        </section>

        <aside class="panel voice-side">
          <div class="panel-head"><h2>运行态势</h2><span class="badge dark">Live</span></div>
          <div class="panel-body">
            <div class="ops-grid">
              <div class="ops-tile"><b id="opsAudio">待命</b><span>音频链路</span></div>
              <div class="ops-tile"><b id="opsDecision">待定</b><span>决策状态</span></div>
              <div class="ops-tile"><b id="opsNotice">0</b><span>通知队列</span></div>
              <div class="ops-tile"><b id="opsArchive">0</b><span>留档记录</span></div>
            </div>
            <div class="stats compact-stats">
              <div class="stat"><strong id="statRisk">0</strong><span>高危</span></div>
              <div class="stat"><strong id="statAuto">0</strong><span>自动</span></div>
              <div class="stat"><strong id="statManual">0</strong><span>人工</span></div>
              <div class="stat"><strong id="statRecords">0</strong><span>留档</span></div>
              <div class="stat"><strong id="statInspection">0</strong><span>广播</span></div>
            </div>
            <div class="work-card"><h3>汇报索引</h3><input id="recordSearch" class="search" placeholder="搜索船名 / 码头 / 高危" /><div id="recordList" class="list"></div></div>
            <div class="work-card"><h3>运行日志</h3><div id="log" class="log">READY</div></div>
          </div>
        </aside>
      </section>

      <section id="inspectionMode" class="mode screen fence-screen">
        <section class="panel fence-main">
          <div class="panel-head"><h2>电子围栏广播</h2><span class="badge green">实时监控</span></div>
          <div class="panel-body">
            <div class="fence-tabs">
              <span class="fence-tab">围栏管理</span>
              <span class="fence-tab active">实时监控</span>
              <span class="fence-tab">广播记录</span>
              <span class="fence-tab">规则设置</span>
            </div>
            <div class="map">
              <div id="amapContainer"></div>
              <div class="sea-overlay">
                <svg viewBox="0 0 920 520" preserveAspectRatio="none" aria-hidden="true">
                  <defs>
                    <linearGradient id="fenceBlue" x1="0" x2="1">
                      <stop offset="0%" stop-color="#1677FF" stop-opacity="0.22"/>
                      <stop offset="100%" stop-color="#00C2FF" stop-opacity="0.08"/>
                    </linearGradient>
                    <linearGradient id="fenceRed" x1="0" x2="1">
                      <stop offset="0%" stop-color="#FF4D4F" stop-opacity="0.24"/>
                      <stop offset="100%" stop-color="#FF4D4F" stop-opacity="0.08"/>
                    </linearGradient>
                  </defs>
                  <path d="M35 360 C180 280,260 220,370 190 S620 110,890 90" stroke="#35d5ef" stroke-opacity="0.28" stroke-width="2" stroke-dasharray="8 10" fill="none"/>
                  <path d="M120 430 C280 360,420 328,570 260 S760 190,900 170" stroke="#2F80FF" stroke-opacity="0.22" stroke-width="1.5" stroke-dasharray="4 8" fill="none"/>
                  <polygon points="130,120 270,50 410,105 390,250 230,285 90,210" fill="url(#fenceBlue)" stroke="#55b8ff" stroke-width="3" stroke-dasharray="9 8"/>
                  <text x="222" y="175" fill="#c9f5ff" font-size="24" font-weight="700">盐田港区围栏</text>
                  <text x="252" y="205" fill="#86aeca" font-size="17">已启用</text>
                  <polygon points="620,330 745,250 870,330 820,450 675,430" fill="url(#fenceRed)" stroke="#ff6b6d" stroke-width="3" stroke-dasharray="9 8"/>
                  <text x="693" y="350" fill="#ffd0d0" font-size="22" font-weight="700">危险作业区</text>
                  <text x="728" y="380" fill="#ffb0b0" font-size="16">已启用</text>
                  <circle class="radar-ring" cx="485" cy="250" r="18" fill="none" stroke="#00C2FF" stroke-width="3"/>
                  <circle cx="485" cy="250" r="30" fill="rgba(22,119,255,0.18)" stroke="#2F80FF"/>
                  <path class="ship-arrow" d="M485 222 L504 276 L485 266 L466 276 Z" fill="#55b8ff" transform="rotate(38 485 250)"/>
                  <path class="ship-arrow green" d="M530 390 L546 430 L530 422 L514 430 Z" fill="#00C48C" transform="rotate(62 530 410)"/>
                  <path class="ship-arrow green" d="M610 350 L626 390 L610 382 L594 390 Z" fill="#00C48C" transform="rotate(62 610 370)"/>
                  <path class="ship-arrow red" d="M450 420 L466 460 L450 452 L434 460 Z" fill="#FF4D4F" transform="rotate(70 450 440)"/>
                </svg>
                <div class="ship-popup">
                  <b>海运888</b>
                  <span>MMSI: 413512345</span>
                  <span>航速: 12.5 kn　航向: 128°</span>
                  <span>状态: 进入围栏</span>
                  <span>时间: 10:23:15</span>
                </div>
              </div>
            </div>
            <div class="map-tools">
              <button type="button" class="secondary" id="drawRect">框选围栏</button>
              <button type="button" class="secondary" id="drawLine">设置过线</button>
              <button type="button" class="secondary" id="clearMap">清除</button>
            </div>
          </div>
        </section>

        <aside class="panel fence-config">
          <div class="panel-head"><h2>广播通知配置</h2><span class="badge dark">Rule</span></div>
          <div class="panel-body">
            <form id="inspectionForm" class="form-grid">
              <input id="inspectionChannel" value="__DEFAULT_CHANNEL__" placeholder="频道 ID" />
              <input id="areaName" value="北仑主航道A3段" placeholder="围栏名称" />
              <div class="row-2">
                <input id="minDraft" value="10" placeholder="最小吃水 m" />
                <input id="minTonnage" value="5000" placeholder="最小吨位 t" />
              </div>
              <select id="shipTypes" multiple>
                <option value="__all__" selected>全部船型</option>
                <option value="集装箱船">集装箱船</option>
                <option value="散货船">散货船</option>
                <option value="液货船">液货船</option>
                <option value="杂货船">杂货船</option>
              </select>
              <select id="inspectionScenario"><option value="">选择点验场景</option></select>
              <textarea id="noticeTemplate">{船名}，数字值班员提醒：你船已进入{区域}关注范围，请保持安全航速，加强瞭望并保持守听。</textarea>
              <div class="broadcast-options">
                <label><input type="checkbox" checked />VHF 广播</label>
                <label><input type="checkbox" checked />AIS 广播</label>
                <label><input type="checkbox" />短信推送</label>
              </div>
              <select>
                <option>重复广播间隔：5分钟</option>
                <option>重复广播间隔：10分钟</option>
                <option>重复广播间隔：15分钟</option>
              </select>
              <button type="submit">生成广播通知</button>
            </form>
          </div>
        </aside>

        <section class="fence-bottom">
          <div class="fence-metrics">
            <div class="ops-tile"><b>8</b><span>围栏总数 · 已启用 6</span></div>
            <div class="ops-tile"><b>23</b><span>今日触发 · +15%</span></div>
            <div class="ops-tile"><b>21</b><span>广播成功 · 91%</span></div>
            <div class="ops-tile"><b>19</b><span>影响船舶 · +12%</span></div>
          </div>
          <div class="work-card"><h3>AIS 点验目标</h3><div id="shipList" class="list"></div></div>
          <div class="work-card"><h3>实时事件</h3><div id="noticeList" class="list"></div></div>
          <div class="work-card">
            <h3>新增规则与船舶</h3>
            <div class="form-grid">
              <input id="newScenarioName" placeholder="场景名称" />
              <textarea id="newScenarioTemplate" placeholder="模板示例：{船名}，你船进入{区域}..." ></textarea>
              <button type="button" id="saveScenarioBtn" class="secondary">保存场景模板</button>
              <input id="newShipName" placeholder="船名" />
              <div class="row-2"><input id="newShipLng" placeholder="经度" /><input id="newShipLat" placeholder="纬度" /></div>
              <div class="row-2"><input id="newShipType" placeholder="船型" /><input id="newShipPositionLabel" placeholder="位置标签" /></div>
              <div class="row-2"><input id="newShipTonnage" placeholder="吨位 t" /><input id="newShipDraft" placeholder="吃水 m" /></div>
              <input id="newShipDestination" placeholder="目的地（可选）" />
              <button type="button" id="saveShipBtn" class="secondary">保存船舶</button>
            </div>
          </div>
        </section>
      </section>
    </section>
  </main>

  <script src="https://webapi.amap.com/maps?v=2.0&key=__AMAP_KEY__&plugin=AMap.MouseTool"></script>
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
      map: null,
      mouseTool: null,
      overlays: [],
      shipMarkers: [],
      selectedShipNames: [],
      scenarios: [],
      streamText: "",
      ws: null,
      micSessionId: "",
      micRecorder: null,
      micStream: null,
      micSeq: 0,
      micActive: false,
      micUploading: false,
      micPendingBlob: null,
      micQueue: [],
      micLocalChunks: [],
      micMimeType: "",
      micSegmentChunks: [],
      micCycleTimer: null,
      micStopPromise: null,
      micStartedAt: 0,
      micTimerInterval: null
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
      node.style.background = kind === "red" ? "rgba(255,94,91,0.12)" : kind === "green" ? "rgba(38,210,138,0.1)" : "rgba(5,18,31,0.52)";
      node.style.borderColor = kind === "red" ? "rgba(255,94,91,0.48)" : kind === "green" ? "rgba(38,210,138,0.42)" : "rgba(113,199,227,0.16)";
    }

    function setMicStatus(text) {
      const node = $("micStatus");
      if (node) node.textContent = text;
    }

    function updateMicTimer() {
      const node = $("micTimer");
      if (!node) return;
      if (!state.micStartedAt) {
        node.textContent = "00:00";
        return;
      }
      const elapsed = Math.max(0, Math.floor((Date.now() - state.micStartedAt) / 1000));
      const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
      const seconds = String(elapsed % 60).padStart(2, "0");
      node.textContent = `${minutes}:${seconds}`;
    }

    function startMicTimer() {
      state.micStartedAt = Date.now();
      updateMicTimer();
      if (state.micTimerInterval) clearInterval(state.micTimerInterval);
      state.micTimerInterval = window.setInterval(updateMicTimer, 500);
    }

    function stopMicTimer() {
      if (state.micTimerInterval) clearInterval(state.micTimerInterval);
      state.micTimerInterval = null;
      state.micStartedAt = 0;
    }

    function setAgent(stage, narrative, details = {}) {
      if ($("agentTitle")) $("agentTitle").textContent = stage;
      if ($("agentNarrative")) $("agentNarrative").textContent = narrative;
      if (Object.prototype.hasOwnProperty.call(details, "evidence") && $("agentEvidence")) $("agentEvidence").textContent = details.evidence;
      if (Object.prototype.hasOwnProperty.call(details, "intent") && $("agentIntent")) $("agentIntent").textContent = details.intent;
      if (Object.prototype.hasOwnProperty.call(details, "policy") && $("agentPolicy")) $("agentPolicy").textContent = details.policy;
      if (Object.prototype.hasOwnProperty.call(details, "nextAction") && $("agentNextAction")) $("agentNextAction").textContent = details.nextAction;
    }

    function pickMicMimeType() {
      const candidates = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
      ];
      for (const mime of candidates) {
        if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(mime)) {
          return mime;
        }
      }
      return "";
    }

    function inferExtFromMime(mime) {
      const lowered = String(mime || "").toLowerCase();
      if (lowered.includes("webm")) return "webm";
      if (lowered.includes("mp4")) return "m4a";
      if (lowered.includes("ogg")) return "ogg";
      if (lowered.includes("wav")) return "wav";
      return "webm";
    }

    async function uploadMicChunk(blob) {
      if (!state.micSessionId || !blob || blob.size <= 0) return;
      if (blob.size < 2048) {
        logLine(`MIC CHUNK SKIP: too small (${blob.size} bytes)`);
        return;
      }
      if (state.micUploading) {
        state.micQueue.push(blob);
        return;
      }
      state.micUploading = true;
      const channelId = $("channelId").value.trim() || "__DEFAULT_CHANNEL__";
      const formData = new FormData();
      const ext = inferExtFromMime(blob.type);
      formData.append("file", blob, `mic_${Date.now()}.${ext}`);
      formData.append("session_id", state.micSessionId);
      formData.append("channel_id", channelId);
      formData.append("seq", String(state.micSeq));
      state.micSeq += 1;
      try {
        await requestJson("/api/mic/chunk", { method: "POST", body: formData });
      } catch (error) {
        const message = error && error.message ? error.message : String(error);
        logLine(`MIC CHUNK ERROR: ${message}`);
      } finally {
        state.micUploading = false;
        const pending = state.micQueue.shift();
        if (pending && (state.micActive || state.micSessionId)) {
          await uploadMicChunk(pending);
        }
      }
    }

    function refreshMicPlayback() {
      if (!state.micLocalChunks.length) return;
      const micBlob = new Blob(state.micLocalChunks, { type: state.micMimeType || "audio/webm" });
      $("audioPlayer").src = URL.createObjectURL(micBlob);
    }

    function startMicRecorderCycle() {
      if (!state.micActive || !state.micStream) return;
      const recorder = state.micMimeType
        ? new MediaRecorder(state.micStream, { mimeType: state.micMimeType })
        : new MediaRecorder(state.micStream);
      state.micRecorder = recorder;
      state.micSegmentChunks = [];
      state.micStopPromise = new Promise((resolve) => {
        recorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) {
            state.micSegmentChunks.push(event.data);
            state.micLocalChunks.push(event.data);
          }
        };
        recorder.onstop = async () => {
          if (state.micCycleTimer) {
            clearTimeout(state.micCycleTimer);
            state.micCycleTimer = null;
          }
          const chunks = state.micSegmentChunks.slice();
          state.micSegmentChunks = [];
          if (chunks.length) {
            const segmentBlob = new Blob(chunks, { type: state.micMimeType || "audio/webm" });
            refreshMicPlayback();
            await uploadMicChunk(segmentBlob);
          }
          resolve();
          if (state.micActive) {
            window.setTimeout(startMicRecorderCycle, 180);
          }
        };
      });
      recorder.start();
      state.micCycleTimer = window.setTimeout(() => {
        try {
          if (state.micRecorder && state.micRecorder.state !== "inactive") {
            state.micRecorder.stop();
          }
        } catch (error) {
          logLine(`MIC CYCLE STOP ERROR: ${error && error.message ? error.message : error}`);
        }
      }, 6000);
    }

    async function startMicCapture() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("当前浏览器不支持麦克风采集。");
      }
      const channelId = $("channelId").value.trim() || "__DEFAULT_CHANNEL__";
      connectSocket(channelId);
      resetFlow();
      setAgent(
        "数字值班员接入现场麦克风",
        "正在建立现场语音守听通道，后续分片转写并持续刷新处置台。",
        {
          evidence: "现场麦克风输入，实时分片上传",
          intent: "等待首段语音进入ASR",
          policy: "先展示可听写文本，高危词触发人工接管",
          nextAction: "开始说话后观察处置台实时更新"
        }
      );
      state.streamText = "";
      state.micSeq = 0;
      const startForm = new FormData();
      startForm.append("channel_id", channelId);
      startForm.append("denoise_mode", $("denoiseMode").value);
      const startResp = await requestJson("/api/mic/start", { method: "POST", body: startForm });
      state.micSessionId = startResp.session_id || "";

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.micStream = stream;
      const mimeType = pickMicMimeType();
      state.micMimeType = mimeType;
      state.micLocalChunks = [];
      state.micActive = true;
      startMicTimer();
      startMicRecorderCycle();
      $("micStartBtn").disabled = true;
      $("micStartBtn").classList.add("listening");
      $("micStopBtn").disabled = false;
      setBadge("现场流式守听中", "dark");
      if ($("opsAudio")) $("opsAudio").textContent = "监听中";
      setSteps(1, "active");
      setMicStatus(`已启动，Session=${state.micSessionId}`);
      setAgent(
        "数字值班员正在现场守听",
        "麦克风输入已启动，系统会持续接收语音分片并刷新识别内容。",
        {
          evidence: `现场会话 ${state.micSessionId}`,
          intent: "实时识别中",
          policy: "实时监听中，异常内容将进入值班席确认",
          nextAction: "等待语音片段返回"
        }
      );
    }

    async function stopMicCapture() {
      if (!state.micActive) return;
      state.micActive = false;
      if (state.micCycleTimer) {
        clearTimeout(state.micCycleTimer);
        state.micCycleTimer = null;
      }
      try {
        if (state.micRecorder && state.micRecorder.state !== "inactive") {
          state.micRecorder.stop();
        }
      } catch (error) {
        // ignore recorder stop race
      }
      if (state.micStopPromise) {
        await state.micStopPromise;
      }
      if (state.micStream) {
        state.micStream.getTracks().forEach((track) => track.stop());
      }
      const sessionId = state.micSessionId;
      state.micRecorder = null;
      state.micStream = null;
      state.micSessionId = "";
      state.micUploading = false;
      state.micPendingBlob = null;
      state.micQueue = [];
      state.micStopPromise = null;
      refreshMicPlayback();
      $("micStartBtn").disabled = false;
      $("micStartBtn").classList.remove("listening");
      $("micStopBtn").disabled = true;
      stopMicTimer();
      if ($("opsAudio")) $("opsAudio").textContent = "汇总中";
      setMicStatus("正在汇总识别结果...");
      setAgent(
        "数字值班员汇总现场语音",
        "现场守听已停止，正在整理分片转写结果并准备人工复核。",
        { nextAction: "查看转写结果，必要时人工接管或播报。" }
      );
      if (sessionId) {
        try {
          const stopForm = new FormData();
          stopForm.append("session_id", sessionId);
          const stopResp = await requestJson("/api/mic/stop", { method: "POST", body: stopForm });
          if (stopResp.text) {
            state.activeText = stopResp.text;
            $("asrText").textContent = stopResp.text;
          }
          setBadge("现场流式完成", "green");
          if ($("opsAudio")) $("opsAudio").textContent = "完成";
          setSteps(4, "done");
          setMicStatus(`已完成，有效分片 ${stopResp.chunk_count || 0} 段，跳过空片 ${stopResp.skipped_count || 0} 段`);
          setAgent(
            "现场守听完成",
            "数字值班员已完成现场语音汇总，结果已进入处置台。",
            {
              evidence: `麦克风有效分片 ${stopResp.chunk_count || 0} 段，跳过空片 ${stopResp.skipped_count || 0} 段`,
              intent: "待值班员复核现场语义",
              policy: "现场输入已进入复核队列",
              nextAction: "可一键播报建议或人工接管"
            }
          );
        } catch (error) {
          const message = error && error.message ? error.message : String(error);
          setMicStatus(`停止失败: ${message}`);
          logLine(`MIC STOP ERROR: ${message}`);
        }
      } else {
        setMicStatus("未找到会话");
      }
    }

    function setBadge(text, kind = "") {
      $("currentState").className = `badge ${kind}`.trim();
      $("currentState").textContent = text;
      if ($("opsDecision")) $("opsDecision").textContent = text;
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
      if ($("opsNotice")) $("opsNotice").textContent = String(state.notices.length);
      if ($("opsArchive")) $("opsArchive").textContent = String(state.records.length);
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
        setAgent(
          "数字值班员发现疑似风险",
          "系统已将该通话提升为人工优先处理，保留转写证据并生成处置建议。",
          {
            evidence: outcome.text ? outcome.text.slice(0, 80) : "未识别到有效文本",
            intent: "疑似高危或通航风险",
            policy: "立即人工接管，核实AIS与周边态势",
            nextAction: "值班员确认后播报提醒"
          }
        );
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
        setAgent(
          "数字值班员生成标准回复",
          "该通话被识别为常规由动转静报告，可留档并播报标准回复。",
          {
            evidence: outcome.text ? outcome.text.slice(0, 80) : "未识别到有效文本",
            intent: "常规报告",
            policy: "自动记录并生成标准回复",
            nextAction: "一键TTS播报或存入汇报索引"
          }
        );
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
        setAgent(
          "数字值班员建议人工复核",
          "该通话未满足自动回复条件，系统给出话术建议，由值班员最终确认。",
          {
            evidence: outcome.text ? outcome.text.slice(0, 80) : "未识别到有效文本",
            intent: "一般业务或待确认通话",
            policy: "系统辅助研判，值班员确认后执行",
            nextAction: "人工确认后回复或接管"
          }
        );
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

    function applyRiskEvent(event) {
      if (!event) return;
      const riskLevel = String(event.risk_level || "");
      if (riskLevel === "L1" || riskLevel === "L2") {
        state.activeRecordType = "risk";
        setBadge("高危拦截", "red");
        setSteps(2, "danger");
        setAgent(
          "数字值班员触发高危接管",
          event.summary || event.event_type || "检测到疑似高危通话，已转入人工优先处置。",
          {
            intent: event.event_type || "疑似高危事件",
            policy: "高危不自动回复，优先人工确认",
            nextAction: event.broadcast_text || event.suggestion || "准备播报提醒"
          }
        );
        $("riskLabel").textContent = "是";
        $("riskReason").textContent = event.summary || event.event_type || "高危事件";
        $("autoLabel").textContent = "否";
        $("autoReason").textContent = "高危不自动回复";
        $("manualLabel").textContent = "立即处理";
        $("manualReason").textContent = event.suggestion || "建议人工接管";
        $("llmSuggestion").textContent = event.suggestion || $("llmSuggestion").textContent;
        if (event.broadcast_text) {
          state.activeReply = event.broadcast_text;
        } else if (event.suggestion) {
          state.activeReply = event.suggestion;
        }
        state.counts.risk += 1;
        state.counts.manual += 1;
      } else if (event.is_auto_reply || event.action_type === "auto_reply") {
        state.activeRecordType = "auto";
        setBadge("自动回复", "green");
        setSteps(3, "done");
        setAgent(
          "数字值班员确认可自动回复",
          event.summary || "识别为标准化常规业务，已生成回复建议。",
          {
            intent: event.event_type || "常规业务",
            policy: "自动记录，值班员可一键播报",
            nextAction: event.broadcast_text || "播放标准回复"
          }
        );
        $("riskLabel").textContent = "否";
        $("riskReason").textContent = "未命中高危";
        $("autoLabel").textContent = "是";
        $("autoReason").textContent = event.summary || "常规自动回复";
        $("manualLabel").textContent = "无需";
        $("manualReason").textContent = "系统可自动处置";
        state.counts.auto += 1;
      } else {
        state.activeRecordType = "manual";
        setBadge("人工复核", "amber");
        setSteps(3, "warn");
        setAgent(
          "数字值班员请求人工确认",
          event.summary || "该事件需要值班员结合态势确认。",
          {
            intent: event.event_type || "待复核业务",
            policy: "不自动处置，先给出建议",
            nextAction: event.suggestion || "人工确认后回复"
          }
        );
        $("manualLabel").textContent = "建议处理";
        $("manualReason").textContent = event.suggestion || "建议人工复核";
        state.counts.manual += 1;
      }
      updateStats();
    }

    function saveRecord() {
      if (!state.activeText) return;
      state.activeReply = $("llmSuggestion").textContent.trim() || state.activeReply;
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
        container.innerHTML = `
          <div class="item">
            <b>海运888 · 进港申请</b>
            <span>示例记录 · 自动回复</span>
            <span>盐田港当前允许进港，请保持 VHF CH16 守听。</span>
          </div>
        `;
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
        <div class="item ship ${state.selectedShipNames.includes(ship.ship_name) ? "selected" : ""}">
          <div>
            <b>${ship.ship_name}</b>
            <span>${ship.position_label} · ${ship.destination}</span>
            <div class="ship-meta">
              <span class="mini">${ship.ship_type}</span>
              <span class="mini">吨位 ${ship.tonnage_t}t</span>
              <span class="mini">吃水 ${ship.draft_m}m</span>
            </div>
          </div>
          <div class="toolbar">
            <span class="badge">${state.selectedShipNames.includes(ship.ship_name) ? "已选" : ship.position_label.includes("A3") ? "A3" : "AIS"}</span>
            <button type="button" class="secondary" data-delete-ship="${ship.ship_id || ''}">删除</button>
          </div>
        </div>
      `).join("");
      container.querySelectorAll("[data-delete-ship]").forEach((button) => {
        button.addEventListener("click", async () => {
          const shipId = button.getAttribute("data-delete-ship") || "";
          if (!shipId) {
            logLine("DELETE SHIP ERROR: 缺少 ship_id");
            return;
          }
          try {
            const formData = new FormData();
            formData.append("ship_id", shipId);
            await requestJson("/api/inspection/ships/delete", { method: "POST", body: formData });
            const ships = await requestJson("/api/inspection/ships");
            state.ships = ships.items || [];
            state.selectedShipNames = state.selectedShipNames.filter(
              (name) => state.ships.some((item) => item.ship_name === name)
            );
            renderShips();
            renderShipMarkers();
            logLine(`已删除船舶: ${shipId}`);
          } catch (error) {
            const message = error && error.message ? error.message : String(error);
            logLine(`DELETE SHIP ERROR: ${message}`);
          }
        });
      });
    }

    function renderNotices() {
      const container = $("noticeList");
      if (!state.notices.length) {
        container.innerHTML = `
          <div class="item"><b>海运888 进入 盐田港区围栏</b><span>10:23:15 · 已广播</span></div>
          <div class="item"><b>中远海运123 进入 危险作业区</b><span>10:23:42 · 已广播</span></div>
          <div class="item"><b>长航货运678 离开 盐田港区围栏</b><span>10:15:33 · 已广播</span></div>
        `;
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
            setAgent(
              "数字值班员生成点验通知",
              "已根据圈选范围、船舶特征和通知模板生成播报内容。",
              {
                evidence: payload.payload.ship_name ? `命中船舶：${payload.payload.ship_name}` : "AIS点验命中目标",
                intent: "点验通知",
                policy: "按模板生成通知，值班员确认后一键播报",
                nextAction: payload.payload.notice_text || "检查点验通知列表"
              }
            );
          }
          if (payload.type === "stream_chunk_result") {
            state.streamText = payload.cumulative_text || payload.text || "";
            state.activeText = state.streamText;
            $("asrText").textContent = state.streamText || "等待流式转写...";
            setSteps(1, "active");
            setBadge("流式转写中", "dark");
            setAgent(
              "数字值班员正在听写",
              "已收到流式语音分片，正在把连续语音转为可复核文本。",
              {
                evidence: state.streamText ? state.streamText.slice(-90) : "等待首段文本",
                intent: "流式ASR转写中",
                policy: "先转写、后分流；高危关键词即时触发",
                nextAction: "继续守听并等待最终分流"
              }
            );
          }
          if (payload.type === "segment_result" && payload.segment) {
            const segText = payload.segment.text || "";
            state.streamText = `${state.streamText}\n${segText}`.trim();
            state.activeText = state.streamText;
            $("asrText").textContent = state.streamText || "等待流式转写...";
            setSteps(1, "active");
            setBadge("流式转写中", "dark");
            setAgent(
              "数字值班员正在整理语音片段",
              "VAD/分片识别结果已返回，处置台正在累积上下文。",
              {
                evidence: segText || "片段无有效文本",
                intent: "片段转写",
                policy: "多段对话先保留证据，再交给规则/LLM分流",
                nextAction: "等待任务完成或风险事件"
              }
            );
          }
          if (payload.type === "risk_event" && payload.event) {
            applyRiskEvent(payload.event);
          }
          if (payload.type === "stream_status" && payload.stage === "completed") {
            if (!state.activeReply && state.streamText) {
              state.activeReply = buildManualAdvice(state.streamText);
              $("llmSuggestion").textContent = state.activeReply;
            }
            setSteps(4, "done");
            setBadge("流式完成", "green");
            setAgent(
              "数字值班员完成流式处置",
              "流式输入已结束，当前结果可进入人工复核、播报或留档。",
              {
                evidence: state.activeText ? state.activeText.slice(0, 120) : "本次无有效转写",
                intent: "流式守听完成",
                policy: state.activeReply ? "已生成建议话术" : "未命中事件，建议人工复核",
                nextAction: state.activeReply || "请值班员确认是否需要播报"
              }
            );
          }
          if (payload.type === "stream_status" && payload.stage === "mic_chunk_skipped") {
            setMicStatus(`已跳过空白/无效分片：${payload.reason || "empty"}`);
          }
        } catch (error) {
          logLine(event.data);
        }
      };
      ws.onopen = () => logLine(`WS connected: ${channelId}`);
      ws.onclose = () => logLine(`WS closed: ${channelId}`);
    }

    function getCurrentGeometry() {
      if (!state.shapes.length) return "";
      return JSON.stringify(state.shapes[state.shapes.length - 1]);
    }

    function selectedShipTypes() {
      const values = Array.from($("shipTypes").selectedOptions).map((o) => o.value);
      return values.includes("__all__") ? [] : values;
    }

    async function previewInspectionTargets(reason = "manual") {
      if (!$("inspectionForm")) return;
      try {
        const previewForm = new FormData();
        previewForm.append("area_name", $("areaName").value.trim());
        previewForm.append("min_draft_m", $("minDraft").value.trim());
        previewForm.append("min_tonnage_t", $("minTonnage").value.trim());
        previewForm.append("area_geometry", getCurrentGeometry());
        previewForm.append("ship_types", selectedShipTypes().join(","));
        const preview = await requestJson("/api/inspection/filter", { method: "POST", body: previewForm });
        state.selectedShipNames = (preview.items || []).map((s) => s.ship_name);
        renderShips();
        renderShipMarkers();
        setAgent(
          "数字值班员预筛点验目标",
          `已根据当前地图范围和船舶条件预筛 ${state.selectedShipNames.length} 艘船。`,
          {
            evidence: state.selectedShipNames.slice(0, 6).join("、") || "暂无命中船舶",
            intent: reason === "draw" ? "地图选区筛船" : "条件筛船",
            policy: "命中船舶高亮显示，确认后生成点验通知",
            nextAction: "选择点验场景并生成通知"
          }
        );
        logLine(`点验预筛: ${state.selectedShipNames.length} 艘`);
      } catch (error) {
        const message = error && error.message ? error.message : String(error);
        logLine(`INSPECTION PREVIEW ERROR: ${message}`);
      }
    }

    function renderScenarioOptions() {
      const select = $("inspectionScenario");
      const current = select.value;
      const options = ['<option value="">选择点验场景</option>'].concat(
        state.scenarios.map((item) => `<option value="${item.scenario_id}">${item.scenario_name}</option>`)
      );
      select.innerHTML = options.join("");
      if (current) {
        select.value = current;
      }
    }

    function renderShipMarkers() {
      if (!state.map || !window.AMap) return;
      state.shipMarkers.forEach((m) => state.map.remove(m));
      state.shipMarkers = [];
      state.ships.forEach((ship) => {
        if (typeof ship.lng !== "number" || typeof ship.lat !== "number") return;
        const isSelected = state.selectedShipNames.includes(ship.ship_name);
        const marker = new AMap.Marker({
          position: [ship.lng, ship.lat],
          title: ship.ship_name,
          label: { content: ship.ship_name, direction: "top" },
          icon: isSelected ? "https://webapi.amap.com/theme/v1.3/markers/n/mark_r.png" : undefined,
        });
        state.map.add(marker);
        state.shipMarkers.push(marker);
      });
    }

    function addShapeOverlay(shape) {
      if (!state.map || !window.AMap) return;
      if (shape.type === "rect") {
        const rect = new AMap.Rectangle({
          bounds: new AMap.Bounds([shape.lng1, shape.lat1], [shape.lng2, shape.lat2]),
          strokeColor: "#2cb2c3",
          strokeWeight: 2,
          fillColor: "#2cb2c3",
          fillOpacity: 0.2
        });
        state.map.add(rect);
        state.overlays.push(rect);
      } else if (shape.type === "line") {
        const line = new AMap.Polyline({
          path: [[shape.lng1, shape.lat1], [shape.lng2, shape.lat2]],
          strokeColor: "#2cb2c3",
          strokeWeight: 3
        });
        state.map.add(line);
        state.overlays.push(line);
      }
    }

    function setupMap() {
      const mapKey = "__AMAP_KEY__";
      if (!mapKey) {
        logLine("未配置 AMAP_KEY，点验地图仅显示列表。");
        return;
      }
      state.map = new AMap.Map("amapContainer", {
        zoom: 11,
        center: [121.84, 29.93],
        mapStyle: "amap://styles/normal"
      });
      state.mouseTool = new AMap.MouseTool(state.map);

      ["drawRect", "drawLine"].forEach((id) => {
        $(id).addEventListener("click", () => {
          state.drawMode = id === "drawRect" ? "rect" : "line";
          $("drawRect").classList.toggle("active", state.drawMode === "rect");
          $("drawLine").classList.toggle("active", state.drawMode === "line");
          if (state.drawMode === "rect") {
            state.mouseTool.rectangle({ strokeColor: "#2cb2c3", fillColor: "#2cb2c3", fillOpacity: 0.2 });
          } else {
            state.mouseTool.polyline({ strokeColor: "#2cb2c3", strokeWeight: 3 });
          }
        });
      });
      $("clearMap").addEventListener("click", () => {
        state.shapes = [];
        state.overlays.forEach((o) => state.map && state.map.remove(o));
        state.overlays = [];
        state.selectedShipNames = [];
        renderShips();
        renderShipMarkers();
      });
      state.map.on("click", (e) => {
        if (!state.startPoint) {
          state.startPoint = e.lnglat;
          return;
        }
        const shape = {
          type: state.drawMode,
          lng1: state.startPoint.lng,
          lat1: state.startPoint.lat,
          lng2: e.lnglat.lng,
          lat2: e.lnglat.lat
        };
        state.shapes.push(shape);
        addShapeOverlay(shape);
        state.startPoint = null;
        previewInspectionTargets("draw");
      });
      state.mouseTool.on("draw", (evt) => {
        state.overlays.forEach((o) => state.map && state.map.remove(o));
        state.overlays = [evt.obj];
        if (evt.type === "rectangle") {
          const b = evt.obj.getBounds();
          const sw = b.getSouthWest();
          const ne = b.getNorthEast();
          state.shapes = [{ type: "rect", lng1: sw.lng, lat1: sw.lat, lng2: ne.lng, lat2: ne.lat }];
        } else if (evt.type === "polyline") {
          const path = evt.obj.getPath();
          if (path.length >= 2) {
            state.shapes = [{
              type: "line",
              lng1: path[0].lng,
              lat1: path[0].lat,
              lng2: path[path.length - 1].lng,
              lat2: path[path.length - 1].lat
            }];
          }
        }
        previewInspectionTargets("draw");
      });
    }

    function updateClock() {
      $("clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    }

    async function loadInitialData() {
      const ships = await requestJson("/api/inspection/ships");
      state.ships = ships.items || [];
      renderShips();
      renderShipMarkers();
      const scenarios = await requestJson("/api/inspection/scenarios");
      state.scenarios = scenarios.items || [];
      renderScenarioOptions();
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
      setAgent(
        "数字值班员开始处置",
        "新任务已接入，正在按接入、听写、判断、建议、执行五步流转。",
        {
          evidence: "已创建任务，等待音频进入处理链路",
          intent: "待识别",
          policy: "异常拦截、常规留档、复杂业务转值班席",
          nextAction: "等待ASR和分流结果"
        }
      );
    }

    function setupTabs() {
      document.querySelectorAll(".tab").forEach((button) => {
        button.addEventListener("click", () => {
          document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
          document.querySelectorAll(".mode").forEach((item) => item.classList.remove("active"));
          button.classList.add("active");
          $(button.dataset.mode).classList.add("active");
          if (button.dataset.mode === "inspectionMode" && state.map) {
            window.setTimeout(() => state.map && state.map.resize(), 80);
          }
        });
      });
    }

    function wireActions() {
      $("micStartBtn").addEventListener("click", async () => {
        try {
          await startMicCapture();
        } catch (error) {
          const message = error && error.message ? error.message : String(error);
          setMicStatus(`启动失败: ${message}`);
          logLine(`MIC START ERROR: ${message}`);
        }
      });
      $("micStopBtn").addEventListener("click", async () => {
        await stopMicCapture();
      });
      $("copyAsr").addEventListener("click", async () => {
        if (!state.activeText) return;
        await navigator.clipboard.writeText(state.activeText);
        logLine("已复制 ASR 文本");
      });
      $("saveRecord").addEventListener("click", saveRecord);
      $("playTts").addEventListener("click", () => {
        const editedReply = $("llmSuggestion").textContent.trim();
        state.activeReply = editedReply || state.activeReply;
        speak(state.activeReply || state.activeText);
      });
      $("llmSuggestion").addEventListener("input", () => {
        state.activeReply = $("llmSuggestion").textContent.trim();
      });
      $("manualTakeover").addEventListener("click", () => {
        setBadge("人工接管", "red");
        logLine("值班员已人工接管当前任务");
        setAgent(
          "值班员人工接管",
          "当前任务已从自动建议切换为人工处置，系统保留转写、证据和建议话术。",
          {
            policy: "人工优先，系统辅助",
            nextAction: "值班员确认后播报或记录处置结果"
          }
        );
      });
      $("recordSearch").addEventListener("input", (event) => renderRecords(event.target.value));
      $("audioFile").addEventListener("change", (event) => {
        const file = event.target.files[0];
        if (!file) return;
        $("audioPlayer").src = URL.createObjectURL(file);
        setStatus(`已选择：${file.name}`);
        setAgent(
          "数字值班员已接入录音",
          "原音已绑定到当前任务，后续识别结果会进入处置流转。",
          {
            evidence: `原音文件：${file.name}`,
            intent: "待转写",
            policy: "先听写，再判断是否高危或可自动回复",
            nextAction: "点击上传并开始识别"
          }
        );
      });
      $("inspectionScenario").addEventListener("change", () => {
        const selected = state.scenarios.find((item) => item.scenario_id === $("inspectionScenario").value);
        if (selected) {
          $("noticeTemplate").value = selected.notice_template;
        }
      });
      ["shipTypes", "minDraft", "minTonnage", "areaName"].forEach((id) => {
        $(id).addEventListener("change", () => previewInspectionTargets("filter"));
      });
      $("saveScenarioBtn").addEventListener("click", async () => {
        try {
          const formData = new FormData();
          formData.append("scenario_name", $("newScenarioName").value.trim());
          formData.append("notice_template", $("newScenarioTemplate").value.trim());
          const response = await requestJson("/api/inspection/scenarios", { method: "POST", body: formData });
          state.scenarios.push(response.item);
          renderScenarioOptions();
          $("inspectionScenario").value = response.item.scenario_id;
          $("noticeTemplate").value = response.item.notice_template;
          logLine(`场景已保存: ${response.item.scenario_name}`);
        } catch (error) {
          const message = error && error.message ? error.message : String(error);
          logLine(`SAVE SCENARIO ERROR: ${message}`);
        }
      });
      $("saveShipBtn").addEventListener("click", async () => {
        try {
          const formData = new FormData();
          formData.append("ship_name", $("newShipName").value.trim());
          formData.append("ship_type", $("newShipType").value.trim() || "其他");
          formData.append("tonnage_t", $("newShipTonnage").value.trim() || "0");
          formData.append("draft_m", $("newShipDraft").value.trim() || "0");
          formData.append("destination", $("newShipDestination").value.trim());
          formData.append("position_label", $("newShipPositionLabel").value.trim() || "自定义点位");
          formData.append("lng", $("newShipLng").value.trim());
          formData.append("lat", $("newShipLat").value.trim());
          await requestJson("/api/inspection/ships", { method: "POST", body: formData });
          const ships = await requestJson("/api/inspection/ships");
          state.ships = ships.items || [];
          renderShips();
          renderShipMarkers();
          logLine("已保存新船舶坐标。");
        } catch (error) {
          const message = error && error.message ? error.message : String(error);
          logLine(`SAVE SHIP ERROR: ${message}`);
        }
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
          state.streamText = "";
          setStatus("上传中...", "");
          if ($("opsAudio")) $("opsAudio").textContent = "处理中";
          setAgent(
            "数字值班员接入VHF录音",
            "音频正在上传，系统会保留原音并进入ASR识别链路。",
            {
              evidence: `待处理文件：${file.name}`,
              intent: "接入中",
              policy: "离线识别用于稳定演示，流式模式用于模拟实时守听",
              nextAction: "等待任务创建"
            }
          );
          const formData = new FormData();
          formData.append("file", file);
          formData.append("channel_id", channelId);
          formData.append("denoise_mode", $("denoiseMode").value);
          const mode = $("processingMode").value;
          let endpoint = "/api/audio/upload";
          if (mode === "stream_sim") endpoint = "/api/stream/upload";
          if (mode === "stream_rt") endpoint = "/api/streaming/upload";
          const createTask = await requestJson(endpoint, { method: "POST", body: formData });
          logLine(createTask);
          setAgent(
            "数字值班员开始听写",
            mode === "batch" ? "任务已创建，正在进行完整录音识别。" : "任务已创建，正在按流式/准流式模式返回片段结果。",
            {
              evidence: `任务ID：${createTask.task_id || "已创建"}`,
              intent: "ASR识别中",
              policy: "识别完成后自动分流为高危、自动回复或人工建议",
              nextAction: "等待ASR文本与业务判断"
            }
          );
          if (mode === "batch") {
            setSteps(1, "active");
          } else {
            setBadge("流式处理中", "dark");
            setSteps(1, "active");
          }
          const task = await pollTask(createTask.task_id);
          setStatus("识别完成", "green");
          if ($("opsAudio")) $("opsAudio").textContent = "完成";
          if (mode === "batch") {
            renderOutcome(task);
          } else {
            const text = flattenSegments(task.segments || [])
              .map((item) => item.text || "")
              .filter(Boolean)
              .join("\n");
            if (text) {
              state.activeText = text;
              $("asrText").textContent = text;
            }
            const events = Array.isArray(task.events) ? task.events : [];
            if (events.length) {
              events.forEach((evt) => applyRiskEvent(evt));
            } else {
              setBadge("人工复核", "amber");
              $("manualLabel").textContent = "建议处理";
              $("manualReason").textContent = "流式未命中事件，建议人工确认";
              $("llmSuggestion").textContent = buildManualAdvice(state.activeText || text);
              setAgent(
                "数字值班员建议人工复核",
                "本次流式输入未命中明确高危或自动回复条件，建议值班员复核上下文。",
                {
                  evidence: (state.activeText || text || "无有效转写").slice(0, 120),
                  intent: "未明确分类",
                  policy: "不自动处置，转人工建议",
                  nextAction: $("llmSuggestion").textContent
                }
              );
            }
            setSteps(4, "done");
          }
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
          setAgent(
            "数字值班员执行AIS点验",
            "正在根据地图范围、船舶类型、吃水和吨位条件筛选需要通知的目标。",
            {
              evidence: $("areaName").value.trim() ? `点验范围：${$("areaName").value.trim()}` : "已接入地图选区",
              intent: "AIS目标筛选",
              policy: "先筛船，再按模板生成通知",
              nextAction: "等待命中船舶列表"
            }
          );
          const scenario = $("inspectionScenario").value;
          const selected = state.scenarios.find((item) => item.scenario_id === scenario);
          if (selected) {
            $("noticeTemplate").value = selected.notice_template;
          }

          const previewForm = new FormData();
          previewForm.append("area_name", $("areaName").value.trim());
          previewForm.append("min_draft_m", $("minDraft").value.trim());
          previewForm.append("min_tonnage_t", $("minTonnage").value.trim());
          previewForm.append("area_geometry", getCurrentGeometry());
          previewForm.append("ship_types", selectedShipTypes().join(","));
          const preview = await requestJson("/api/inspection/filter", { method: "POST", body: previewForm });
          state.selectedShipNames = (preview.items || []).map((s) => s.ship_name);
          renderShips();
          renderShipMarkers();
          setAgent(
            "数字值班员锁定点验目标",
            `已筛选出 ${state.selectedShipNames.length} 艘候选船舶，地图上会高亮显示。`,
            {
              evidence: state.selectedShipNames.slice(0, 5).join("、") || "暂无命中船舶",
              intent: "目标船舶筛选完成",
              policy: "对命中船舶生成同一场景通知模板",
              nextAction: "生成点验通知并准备TTS播报"
            }
          );

          const formData = new FormData();
          formData.append("channel_id", channelId);
          formData.append("area_name", $("areaName").value.trim());
          formData.append("min_draft_m", $("minDraft").value.trim());
          formData.append("min_tonnage_t", $("minTonnage").value.trim());
          formData.append("scenario_id", scenario);
          formData.append("notice_template", $("noticeTemplate").value);
          formData.append("area_geometry", getCurrentGeometry());
          formData.append("ship_types", selectedShipTypes().join(","));
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
          setAgent(
            "数字值班员完成点验通知",
            "点验任务已完成，命中船舶和通知话术已进入右侧留档列表。",
            {
              evidence: `命中目标：${task.meta.matched_count} 艘`,
              intent: "点验通知",
              policy: "值班员确认后一键TTS播报",
              nextAction: state.activeReply || "无匹配船舶，无需播报"
            }
          );
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
    return template.replace("__DEFAULT_CHANNEL__", settings.default_channel_id).replace(
        "__AMAP_KEY__",
        settings.amap_key,
    )
