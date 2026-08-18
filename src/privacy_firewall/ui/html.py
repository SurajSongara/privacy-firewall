"""The review UI page — fully self-contained HTML/CSS/JS (no CDN)."""

PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Firewall — Review</title>
<style>
  :root {
    --accent: #6366f1; --accent-strong: #4f46e5;
    --redact: #059669; --ask: #d97706; --keep: #64748b; --manual: #7c3aed;
    --bg: #f1f5f9; --panel: #ffffff; --line: #e2e8f0;
    --text: #0f172a; --muted: #64748b;
    --shadow: 0 1px 2px rgba(15,23,42,.06), 0 4px 12px rgba(15,23,42,.06);
    --shadow-lg: 0 4px 8px rgba(15,23,42,.08), 0 12px 32px rgba(15,23,42,.14);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; color: var(--text); background: var(--bg);
    font: 14px/1.5 -apple-system, "Segoe UI", system-ui, Roboto, "Helvetica Neue", Arial, sans-serif;
  }
  code, .mono { font-family: ui-monospace, "Cascadia Code", Consolas, Menlo, monospace; }

  /* ---------- header: row 1 = navigation/actions, row 2 = PDF tools ---------- */
  header {
    background: rgba(255,255,255,.92); backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--line);
    position: sticky; top: 0; z-index: 30;
  }
  .hrow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 8px 20px; }
  .hrow.tools {
    border-top: 1px solid #eef1f6; background: rgba(248,250,252,.85);
    padding: 5px 20px;
  }
  .hrow.tools .btn, .hrow.tools select.ctl { padding: 5px 12px; font-size: 12.5px; }
  .hrow.tools .toolgroup button { padding: 5px 10px; }
  /* Controls never shrink or clip — the row wraps instead; only the
     file-path chip is allowed to compress (and hides when tight). */
  .hrow > :not(.pathchip) { flex-shrink: 0; }
  @media (max-width: 1000px) { header .pathchip { display: none !important; } }
  .legend { margin-left: auto; color: var(--muted); font-size: 12px; white-space: nowrap; }
  .logo { display: flex; align-items: center; gap: 9px; }
  .logo svg { width: 24px; height: 24px; flex-shrink: 0; }
  .logo .name { font-size: 15px; font-weight: 700; letter-spacing: -.01em; }
  .logo .sub { font-size: 11px; color: var(--muted); margin-top: -2px; }
  .pathchip {
    display: flex; align-items: center; gap: 2px; min-width: 0; max-width: 480px;
    background: #f8fafc; border: 1px solid var(--line); border-radius: 8px;
    padding: 3px 4px 3px 10px; color: var(--muted);
    font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  }
  .pathchip .p {
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
    min-width: 0; cursor: pointer;
  }
  .pathchip .p:hover { color: var(--text); }
  .pathchip button {
    border: none; background: none; cursor: pointer; color: var(--muted);
    padding: 3px 6px; border-radius: 6px; display: flex; align-items: center;
    flex-shrink: 0;
  }
  .pathchip button:hover { background: #e2e8f0; color: var(--text); }
  .pathchip button svg { width: 13px; height: 13px; }
  .runmeta { color: var(--muted); font-size: 12px; white-space: nowrap; }
  header .spacer { flex: 1; }
  .pill {
    padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
    white-space: nowrap;
  }
  .pill.redact { background: #d1fae5; color: #065f46; }
  .pill.ask    { background: #fef3c7; color: #92400e; }
  .pill.keep   { background: #e2e8f0; color: #334155; }
  .btn {
    border: 1px solid var(--line); background: var(--panel); color: var(--text);
    border-radius: 8px; padding: 7px 14px; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: background .12s, border-color .12s, box-shadow .12s;
  }
  .btn:hover { background: #f8fafc; border-color: #cbd5e1; }
  .btn.primary {
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%);
    border-color: transparent; color: #fff; box-shadow: 0 1px 3px rgba(79,70,229,.4);
  }
  .btn.primary:hover { filter: brightness(1.07); }
  .btn.active { background: #eef2ff; border-color: var(--accent); color: var(--accent-strong); }
  .btn:disabled { opacity: .5; cursor: default; filter: none; }
  select.ctl {
    border: 1px solid var(--line); background: var(--panel); color: var(--text);
    border-radius: 8px; padding: 7px 8px; font-size: 13px; font-weight: 600; cursor: pointer;
  }

  /* zoom + page nav */
  .toolgroup {
    display: flex; align-items: center; gap: 0; border: 1px solid var(--line);
    border-radius: 8px; background: var(--panel); overflow: hidden;
  }
  .toolgroup button {
    border: 0; background: none; padding: 7px 10px; font-size: 13px; font-weight: 700;
    cursor: pointer; color: var(--muted);
  }
  .toolgroup button:hover { background: #f1f5f9; color: var(--text); }
  .toolgroup .val {
    font-size: 12px; font-weight: 600; color: var(--muted); padding: 0 4px;
    min-width: 44px; text-align: center;
  }

  /* ---------- banner / hint ---------- */
  #banner {
    display: none; align-items: center; gap: 12px; padding: 10px 20px;
    background: #ecfdf5; color: #065f46;
    border-bottom: 1px solid #a7f3d0; font-weight: 600; word-break: break-all; font-size: 13px;
  }
  #banner a.view {
    flex-shrink: 0; text-decoration: none; background: #059669; color: #fff;
    border-radius: 8px; padding: 6px 14px; font-size: 12.5px; font-weight: 700;
  }
  #banner a.view:hover { filter: brightness(1.08); }
  #preview-banner {
    display: none; padding: 8px 20px; background: #fdf4ff; color: #86198f;
    border-bottom: 1px solid #f5d0fe; font-weight: 600; font-size: 13px;
  }
  #progress-banner {
    display: none; align-items: center; gap: 10px; padding: 8px 20px;
    background: #eef2ff; color: #3730a3; border-bottom: 1px solid #c7d2fe;
    font-weight: 600; font-size: 13px;
  }
  #progress-banner .spin {
    width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0;
    border: 2px solid #c7d2fe; border-top-color: var(--accent);
    animation: spin .9s linear infinite;
  }
  #progress-banner.err { background: #fef2f2; color: #b91c1c; border-bottom-color: #fecaca; }
  #progress-banner.err .spin { display: none; }
  .hint {
    display: flex; align-items: center; gap: 8px; padding: 8px 20px;
    background: #eef2ff; color: #3730a3; border-bottom: 1px solid #e0e7ff; font-size: 12.5px;
  }
  .hint b { font-weight: 700; }
  .hint kbd {
    background: #fff; border: 1px solid #c7d2fe; border-radius: 4px; padding: 0 5px;
    font-size: 11px; font-family: inherit;
  }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin: 0 3px -1px 8px; }

  /* ---------- loading screen ---------- */
  #loading {
    position: fixed; inset: 0; z-index: 90; background: var(--bg);
    display: flex; align-items: center; justify-content: center;
  }
  #loading .card {
    background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
    box-shadow: var(--shadow-lg); padding: 36px 48px; text-align: center; max-width: 460px;
  }
  #loading .spinner {
    width: 36px; height: 36px; margin: 14px auto; border-radius: 50%;
    border: 3px solid #e0e7ff; border-top-color: var(--accent);
    animation: spin .9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #loading .stage { font-weight: 600; margin-top: 4px; }
  #loading .elapsed { color: var(--muted); font-size: 12px; margin-top: 6px; }
  #loading .err { color: #b91c1c; font-weight: 600; white-space: pre-wrap; word-break: break-word; }

  /* ---------- layout ---------- */
  main { display: flex; gap: 20px; padding: 20px; align-items: flex-start; justify-content: center; }
  #sidebar { width: 370px; flex-shrink: 0; position: sticky; top: 104px; max-height: calc(100vh - 134px); overflow-y: auto; padding-bottom: 8px; }
  #pages { flex: 1; min-width: 0; overflow-x: auto; padding-bottom: 8px; }

  /* ---------- search-to-mark card ---------- */
  #marker-card {
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    box-shadow: var(--shadow); padding: 10px 12px; margin-bottom: 10px;
    display: flex; flex-direction: column; gap: 6px;
  }
  #marker-card .row { display: flex; gap: 6px; }
  #marker-card input[type="text"] {
    border: 1px solid var(--line); border-radius: 8px; padding: 6px 9px; font-size: 12.5px;
    flex: 1; min-width: 0; outline: none;
  }
  #marker-card input[type="text"]:focus { border-color: var(--accent); }
  #marker-card .chk { display: flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--muted); cursor: pointer; white-space: nowrap; }
  #marker-card button {
    border: 0; background: var(--manual); color: #fff; border-radius: 8px;
    padding: 6px 12px; font-size: 12px; font-weight: 700; cursor: pointer;
  }
  #marker-card button:hover { filter: brightness(1.1); }

  /* ---------- filter tabs ---------- */
  #filter-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
  #filter-tabs button {
    flex: 1; border: 1px solid var(--line); background: var(--panel); color: var(--muted);
    border-radius: 8px; padding: 5px 2px; font-size: 11.5px; font-weight: 600; cursor: pointer;
  }
  #filter-tabs button.on { background: #eef2ff; border-color: var(--accent); color: var(--accent-strong); }

  /* ---------- sidebar groups ---------- */
  .side-empty {
    background: var(--panel); border: 1px dashed #cbd5e1; border-radius: 12px;
    padding: 18px; color: var(--muted); font-size: 13px; text-align: center;
  }
  .group {
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    margin-bottom: 12px; box-shadow: var(--shadow); overflow: hidden;
  }
  .group h2 {
    display: flex; align-items: center; gap: 8px; font-size: 12.5px; margin: 0;
    padding: 9px 12px; border-bottom: 1px solid var(--line); background: #f8fafc;
    text-transform: uppercase; letter-spacing: .04em;
  }
  .group h2 .count { color: var(--muted); font-weight: 500; }
  .group h2 .bulk { margin-left: auto; display: flex; gap: 6px; }
  .group h2 .bulk button {
    font-size: 11px; border: 1px solid var(--line); background: #fff; color: var(--muted);
    border-radius: 6px; padding: 2px 8px; cursor: pointer; text-transform: none; letter-spacing: 0;
  }
  .group h2 .bulk button:hover { color: var(--text); border-color: #cbd5e1; }
  .entry { padding: 9px 12px; border-bottom: 1px solid #f1f5f9; cursor: pointer; border-left: 3px solid transparent; }
  .entry:last-child { border-bottom: 0; }
  .entry:hover, .entry.hl { background: #f8fafc; }
  .entry.focus { border-left-color: var(--accent); background: #eef2ff; }
  .entry .row1 { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .entry code { font-size: 12.5px; word-break: break-all; }
  .entry .meta2 { color: #94a3b8; font-size: 11px; margin-left: auto; white-space: nowrap; }
  .entry .why { color: var(--muted); font-size: 11px; margin-top: 3px; }
  .entry select {
    font-size: 12px; padding: 2px 4px; border-radius: 6px; border: 1px solid var(--line);
    background: #fff; cursor: pointer;
  }
  .entry select.is-redact { color: var(--redact); font-weight: 600; }
  .entry select.is-keep { color: var(--keep); }
  .chip {
    font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 999px;
    background: #ede9fe; color: var(--manual); text-transform: uppercase; letter-spacing: .03em;
  }
  .rm {
    border: 0; background: none; color: #94a3b8; cursor: pointer; font-size: 14px;
    padding: 0 2px; line-height: 1; border-radius: 4px;
  }
  .rm:hover { color: #dc2626; background: #fee2e2; }

  /* ---------- pages ---------- */
  .empty-note {
    background: #fffbeb; border: 1px solid #fcd34d; color: #78350f;
    border-radius: 12px; padding: 14px 18px; margin: 0 0 16px;
  }
  .empty-note button {
    border: 0; background: var(--ask); color: #fff; border-radius: 8px;
    padding: 6px 14px; font-size: 12.5px; font-weight: 700; cursor: pointer; margin-left: 10px;
  }
  .page-label { color: var(--muted); font-size: 12px; margin: 0 auto 6px; font-weight: 600; }
  .page-wrap {
    position: relative; margin: 0 auto 24px; background: #fff;
    border-radius: 10px; box-shadow: var(--shadow-lg); overflow: hidden;
  }
  .page-wrap img { display: block; width: 100%; height: auto; user-select: none; -webkit-user-drag: none; }
  .text-layer { position: absolute; inset: 0; z-index: 1; cursor: crosshair; user-select: none; }
  .preview-mode .text-layer, .preview-mode .overlay { display: none; }
  .tw {
    position: absolute; white-space: pre; color: transparent;
    transform-origin: 0 0; pointer-events: none;
  }
  .tw.sel { background: rgba(99,102,241,.35); border-radius: 2px; }
  .rubber {
    position: absolute; z-index: 3; pointer-events: none; border-radius: 2px;
    border: 1.5px solid var(--accent); background: rgba(99,102,241,.10);
  }
  .overlay { position: absolute; z-index: 2; border: 2px solid; border-radius: 3px; cursor: pointer; }
  .overlay.redact { border-color: var(--redact); background: rgba(5,150,105,.16); }
  .overlay.ask    { border-color: var(--ask); background: rgba(217,119,6,.18); }
  .overlay.keep   { border-color: var(--keep); background: rgba(100,116,139,.08); border-style: dashed; }
  .overlay:hover, .overlay.hl { filter: brightness(1.12); box-shadow: 0 0 0 2px rgba(99,102,241,.35); }
  .overlay.flash { animation: flash 1.2s ease-out; }
  @keyframes flash {
    0%, 40% { box-shadow: 0 0 0 4px rgba(99,102,241,.65); }
    100% { box-shadow: 0 0 0 2px rgba(99,102,241,0); }
  }

  /* ---------- mark-as-PII popup ---------- */
  #popup {
    display: none; position: absolute; z-index: 60; width: 272px;
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    box-shadow: var(--shadow-lg); padding: 12px; flex-direction: column; gap: 8px;
  }
  #popup input[type="text"] {
    border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px; font-size: 13px;
    width: 100%; outline: none;
  }
  #popup input[type="text"]:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(99,102,241,.15); }
  #popup input.sel-preview {
    font-family: ui-monospace, Consolas, monospace; font-size: 12px;
    background: #f1f5f9; color: #334155;
  }
  #popup .chk { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); cursor: pointer; }
  #popup .actions { display: flex; gap: 8px; }
  #popup .actions .btn { flex: 1; padding: 7px 0; }
  #popup .btn.mark { background: var(--manual); border-color: transparent; color: #fff; }
  #popup .btn.mark:hover { filter: brightness(1.1); }

  /* ---------- toasts ---------- */
  #toasts { position: fixed; bottom: 20px; right: 20px; z-index: 100; display: flex; flex-direction: column; gap: 8px; }
  .toast {
    background: #0f172a; color: #f8fafc; border-radius: 10px; padding: 10px 16px;
    font-size: 13px; box-shadow: var(--shadow-lg); max-width: 420px; word-break: break-word;
    animation: toast-in .18s ease-out; display: flex; align-items: center; gap: 12px;
  }
  .toast.warn { background: #92400e; }
  .toast button {
    border: 1px solid rgba(255,255,255,.35); background: none; color: #fff;
    border-radius: 6px; padding: 3px 10px; font-size: 12px; font-weight: 700; cursor: pointer;
    flex-shrink: 0;
  }
  .toast button:hover { background: rgba(255,255,255,.12); }
  @keyframes toast-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
</style>
</head>
<body>
<header>
  <div class="hrow">
    <div class="logo">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M12 2 4 5.5v5.6c0 4.9 3.4 9.5 8 10.9 4.6-1.4 8-6 8-10.9V5.5L12 2Z"
              fill="url(#g)" stroke="#4338ca" stroke-width="1.2" stroke-linejoin="round"/>
        <path d="M8.6 12.1l2.3 2.3 4.5-4.6" stroke="#fff" stroke-width="1.8"
              stroke-linecap="round" stroke-linejoin="round"/>
        <defs><linearGradient id="g" x1="4" y1="2" x2="20" y2="22">
          <stop stop-color="#818cf8"/><stop offset="1" stop-color="#4f46e5"/>
        </linearGradient></defs>
      </svg>
      <div><div class="name">Privacy Firewall</div><div class="sub">Redaction review</div></div>
    </div>
    <button class="btn" id="home-btn" style="display:none" title="Back to dashboard">&larr; Dashboard</button>
    <span class="pathchip" id="path-chip" style="display:none">
      <span class="p" id="src-path"></span>
      <button id="copy-path" title="Copy full file path" aria-label="Copy file path">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/>
          <path d="M10.5 5.5v-2a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3.5v5A1.5 1.5 0 0 0 4 10h1.5"/>
        </svg>
      </button>
    </span>
    <span class="spacer"></span>
    <span class="pill redact" id="count-redact">0</span>
    <span class="pill ask" id="count-ask">0</span>
    <span class="pill keep" id="count-keep">0</span>
    <button class="btn" id="save">Save plan</button>
    <button class="btn primary" id="apply">Apply &amp; export PDF</button>
  </div>
  <div class="hrow tools">
    <span class="toolgroup" id="pagenav" title="Jump between pages">
      <button id="page-prev">&#9666;</button>
      <span class="val" id="page-ind">–</span>
      <button id="page-next">&#9656;</button>
    </span>
    <span class="toolgroup" title="Zoom">
      <button id="zoom-out">&minus;</button>
      <span class="val" id="zoom-val">100%</span>
      <button id="zoom-in">+</button>
      <button id="zoom-fit" style="font-size:11px">Fit</button>
    </span>
    <select class="ctl" id="style" title="Redaction style">
      <option value="replace" selected>Redact with *****</option>
      <option value="black_bar">Black bar</option>
      <option value="highlight">Highlight only</option>
    </select>
    <button class="btn" id="preview-btn">Preview</button>
    <span class="runmeta" id="run-meta"></span>
    <span class="legend"><span class="swatch" style="background:rgba(5,150,105,.7)"></span>redacted
      <span class="swatch" style="background:rgba(217,119,6,.7)"></span>needs review
      <span class="swatch" style="background:rgba(100,116,139,.5)"></span>kept</span>
  </div>
</header>
<div id="banner"></div>
<div id="preview-banner">Previewing redacted output — this is exactly what the exported PDF will look like.</div>
<div id="progress-banner"><span class="spin"></span><span id="progress-text">Processing…</span></div>
<div class="hint">
  <b>Tip:</b> drag a box over any text on a page — even part of a word — to mark every instance of it as PII.
  Shortcuts: <kbd>n</kbd>/<kbd>p</kbd> next/prev needs-review, <kbd>r</kbd> redact, <kbd>k</kbd> keep.
</div>
<main>
  <aside id="sidebar">
    <div id="marker-card">
      <div class="row">
        <input type="text" id="search-text" placeholder="Text to mark as PII…">
      </div>
      <div class="row">
        <input type="text" id="search-label" list="label-suggestions" placeholder="Label (e.g. NAME)">
        <label class="chk"><input type="checkbox" id="search-case"> Match case</label>
        <button id="search-mark">Mark</button>
      </div>
      <div class="row" id="search-remember-row" style="display:none">
        <label class="chk"><input type="checkbox" id="search-remember">
          Remember for every document in this workspace</label>
      </div>
    </div>
    <div id="filter-tabs"></div>
    <div id="groups"></div>
  </aside>
  <section id="pages"></section>
</main>

<div id="loading">
  <div class="card">
    <svg viewBox="0 0 24 24" fill="none" style="width:40px;height:40px">
      <path d="M12 2 4 5.5v5.6c0 4.9 3.4 9.5 8 10.9 4.6-1.4 8-6 8-10.9V5.5L12 2Z"
            fill="#818cf8" stroke="#4338ca" stroke-width="1.2" stroke-linejoin="round"/>
      <path d="M8.6 12.1l2.3 2.3 4.5-4.6" stroke="#fff" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <div class="spinner" id="load-spinner"></div>
    <div class="stage" id="load-stage">Starting…</div>
    <div class="elapsed" id="load-elapsed"></div>
    <div id="unlock-box" style="display:none;margin-top:14px;text-align:center">
      <div style="font-size:13px;color:#334155;margin-bottom:8px">🔒 This PDF is password-protected.</div>
      <input type="password" id="unlock-input" placeholder="Password" autocomplete="off"
             style="padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;width:220px;font-size:14px">
      <button id="unlock-btn" style="margin-left:6px;padding:8px 14px;border:0;border-radius:8px;background:#6366f1;color:#fff;font-weight:600;cursor:pointer">Unlock</button>
      <div id="unlock-error" style="display:none;color:#b91c1c;font-size:12px;margin-top:8px"></div>
    </div>
  </div>
</div>

<div id="popup">
  <input type="text" class="sel-preview" id="sel-preview" autocomplete="off" spellcheck="false"
         title="Edit the text before marking">

  <input type="text" id="label-input" list="label-suggestions" placeholder="Label (e.g. NAME)" autocomplete="off">
  <datalist id="label-suggestions">
    <option>NAME</option><option>ADDRESS</option><option>DATE_OF_BIRTH</option>
    <option>ACCOUNT</option><option>PHONE</option><option>EMAIL</option>
    <option>ID_NUMBER</option><option>CUSTOM</option>
  </datalist>
  <label class="chk"><input type="checkbox" id="match-case"> Match case</label>
  <label class="chk" id="remember-row" style="display:none">
    <input type="checkbox" id="remember-term"> Remember for this workspace</label>
  <div class="actions">
    <button class="btn" id="cancel-mark">Cancel</button>
    <button class="btn mark" id="mark-btn">Mark all instances</button>
  </div>
</div>
<div id="toasts"></div>

<script>
"use strict";
let PLAN = null;
let PAGES = null;          // page dims: /api/pages before ready, PLAN.pages after
let earlyView = false;     // pages shown while the pipeline still runs
const WORDS = {};          // page_number -> word list from /api/text
const LAYOUT = {};         // page_number -> [{el, x, y, w, h}] in layer px
let pendingSelection = null;
let FILTER = "all";        // all | ask | redact | keep
let FOCUS = null;          // focused detection_id (keyboard navigation)
let PREVIEW = false;
let ZOOM = 1;
const BASE_WIDTH = 900;
let bootStart = Date.now();

async function api(path, body) {
  const opts = body ? {method: "POST", headers: {"Content-Type": "application/json"},
                       body: JSON.stringify(body)} : {};
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function esc(s) {
  return s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function toast(msg, kind, action) {
  const el = document.createElement("div");
  el.className = "toast" + (kind === "warn" ? " warn" : "");
  const span = document.createElement("span");
  span.textContent = msg;
  el.appendChild(span);
  if (action) {
    const btn = document.createElement("button");
    btn.textContent = action.label;
    btn.addEventListener("click", () => { el.remove(); action.fn(); });
    el.appendChild(btn);
  }
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), action ? 8000 : 4200);
}

/* ---------- boot: poll pipeline status, then load the plan ---------- */

const STAGE_LABELS = {
  starting: "Starting…",
  parsing: "Parsing document…",
  analyzing: "Analyzing text quality…",
  ocr: "Running OCR — this can take a minute…",
  merging: "Merging text layers…",
  detecting: "Running PII detectors…",
};

async function showEarlyPages() {
  // During a long pipeline run (OCR on a large scan can take minutes),
  // show the page images straight away — geometry comes from the PDF
  // itself, so browsing works while detection is still in progress.
  if (earlyView || PAGES) return;
  try {
    const data = await api("api/pages");
    if (!data.pages || !data.pages.length) return;
    PAGES = data.pages;
    earlyView = true;
    document.getElementById("loading").style.display = "none";
    document.getElementById("progress-banner").style.display = "flex";
    initPages();
  } catch (err) {
    // PDF not readable (yet) — keep the full-screen loader.
  }
}

let unlockWired = false;
function showUnlock(errMsg) {
  document.getElementById("loading").style.display = "flex";
  document.getElementById("load-spinner").style.display = "none";
  document.getElementById("load-stage").textContent = "Password required";
  document.getElementById("load-elapsed").textContent = "";
  document.getElementById("unlock-box").style.display = "block";
  const err = document.getElementById("unlock-error");
  if (errMsg) { err.textContent = errMsg; err.style.display = "block"; }
  const input = document.getElementById("unlock-input");
  input.focus();
  if (!unlockWired) {
    unlockWired = true;
    document.getElementById("unlock-btn").addEventListener("click", submitUnlock);
    input.addEventListener("keydown", e => { if (e.key === "Enter") submitUnlock(); });
  }
}

async function submitUnlock() {
  const input = document.getElementById("unlock-input");
  const pw = input.value;
  if (!pw) return;
  document.getElementById("unlock-box").style.display = "none";
  document.getElementById("load-spinner").style.display = "";
  document.getElementById("load-stage").textContent = "Unlocking…";
  try {
    await api("api/unlock", {password: pw});
  } catch (err) {
    showUnlock("Could not unlock. Try again.");
    return;
  }
  input.value = "";
  setTimeout(boot, 600);
}

async function boot() {
  let status;
  try {
    status = await api("api/status");
  } catch (err) {
    setTimeout(boot, 1200);
    return;
  }
  const stage = document.getElementById("load-stage");
  const elapsed = Math.round((Date.now() - bootStart) / 1000);
  document.getElementById("load-elapsed").textContent = elapsed + "s elapsed";
  if (status.status === "error") {
    if (status.needs_password) {
      showUnlock();
      return;
    }
    if (earlyView) {
      const banner = document.getElementById("progress-banner");
      banner.style.display = "flex";
      banner.classList.add("err");
      document.getElementById("progress-text").textContent =
        "Pipeline failed: " + status.detail;
      return;
    }
    document.getElementById("load-spinner").style.display = "none";
    stage.className = "err";
    stage.textContent = "Pipeline failed: " + status.detail;
    return;
  }
  if (status.status !== "ready") {
    const label = STAGE_LABELS[status.status] || (status.status + "…");
    stage.textContent = label;
    document.getElementById("progress-text").textContent =
      label + " (" + elapsed + "s elapsed) — you can browse the pages meanwhile.";
    await showEarlyPages();
    setTimeout(boot, 800);
    return;
  }
  PLAN = await api("api/plan");
  PAGES = PLAN.pages;
  earlyView = false;
  document.getElementById("loading").style.display = "none";
  document.getElementById("progress-banner").style.display = "none";
  if (PLAN.workspace_terms) {
    document.getElementById("search-remember-row").style.display = "";
    document.getElementById("remember-row").style.display = "";
  }
  initPages();
  render();
  const restored = PLAN.restored || {decisions: 0, manual: 0};
  if (restored.decisions || restored.manual) {
    toast(`Resumed previous session: restored ${restored.decisions} decision` +
          `${restored.decisions === 1 ? "" : "s"} and ${restored.manual} manual mark` +
          `${restored.manual === 1 ? "" : "s"}.`);
  }
}

/* ---------- rendering ---------- */

function render() {
  const counts = {redact: 0, ask: 0, keep: 0};
  PLAN.entries.forEach(e => counts[e.effective_action]++);
  for (const k of ["redact", "ask", "keep"]) {
    document.getElementById("count-" + k).textContent = counts[k] + " " + k;
  }
  renderSourcePath();
  document.getElementById("apply").disabled = PLAN.entries.length === 0;
  renderEmptyNote();
  renderFilterTabs(counts);
  renderSidebar();
  renderOverlays();
}

function middleEllipsis(s, head, tail) {
  if (s.length <= head + tail + 1) return s;
  return s.slice(0, head) + "…" + s.slice(-tail);
}

async function copySourcePath() {
  try {
    await navigator.clipboard.writeText(PLAN.source);
  } catch (err) {
    const ta = document.createElement("textarea");
    ta.value = PLAN.source;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast("File path copied to clipboard.");
}

function renderSourcePath() {
  const chip = document.getElementById("path-chip");
  chip.style.display = "flex";
  chip.title = PLAN.source + "\n(click to copy the full path)";
  document.getElementById("src-path").textContent = middleEllipsis(PLAN.source, 10, 34);
  document.getElementById("run-meta").textContent =
    "policy: " + PLAN.policy + " · " + PLAN.pipeline;
}
document.getElementById("src-path").addEventListener("click", () => {
  if (PLAN) copySourcePath();
});
document.getElementById("copy-path").addEventListener("click", () => {
  if (PLAN) copySourcePath();
});

function renderEmptyNote() {
  const existing = document.querySelector(".empty-note");
  if (existing) existing.remove();
  if (PLAN.entries.length > 0) return;
  const note = document.createElement("div");
  note.className = "empty-note";
  note.innerHTML = "<strong>No PII detected automatically.</strong> Pipeline used: " + esc(PLAN.pipeline) +
    ". You can drag over text on the pages below to mark it manually, or re-run " +
    "the detection with OCR forced. <button id=\"rerun-ocr\">Re-run with OCR</button>";
  const pages = document.getElementById("pages");
  pages.insertBefore(note, pages.firstChild);
  note.querySelector("#rerun-ocr").addEventListener("click", rerunWithOcr);
}

function renderFilterTabs(counts) {
  const tabs = [
    {key: "all", label: "All " + PLAN.entries.length},
    {key: "ask", label: "Review " + counts.ask},
    {key: "redact", label: "Redact " + counts.redact},
    {key: "keep", label: "Keep " + counts.keep},
  ];
  const el = document.getElementById("filter-tabs");
  el.innerHTML = "";
  tabs.forEach(t => {
    const b = document.createElement("button");
    b.textContent = t.label;
    b.className = FILTER === t.key ? "on" : "";
    b.addEventListener("click", () => { FILTER = t.key; render(); });
    el.appendChild(b);
  });
}

function visibleEntries() {
  if (FILTER === "all") return PLAN.entries;
  return PLAN.entries.filter(e => e.effective_action === FILTER);
}

function renderSidebar() {
  const el = document.getElementById("groups");
  el.innerHTML = "";
  const entries = visibleEntries();
  if (entries.length === 0) {
    el.innerHTML = '<div class="side-empty">' +
      (PLAN.entries.length === 0
        ? "Nothing marked yet.<br>Drag a box over text on a page to mark it as PII."
        : "No entries match this filter.") + "</div>";
    return;
  }
  const groups = {};
  entries.forEach(e => (groups[e.type] = groups[e.type] || []).push(e));
  Object.keys(groups).sort().forEach(type => {
    const g = document.createElement("div");
    g.className = "group";
    g.innerHTML = `<h2>${esc(type)} <span class="count">${groups[type].length}</span>
      <span class="bulk">
        <button data-type="${esc(type)}" data-act="redact">redact all</button>
        <button data-type="${esc(type)}" data-act="keep">keep all</button>
      </span></h2>`;
    groups[type].forEach(e => {
      const row = document.createElement("div");
      row.className = "entry" + (e.detection_id === FOCUS ? " focus" : "");
      row.dataset.id = e.detection_id;
      const manual = e.detector === "manual";
      const remembered = e.detector === "remembered";
      row.innerHTML = `
        <div class="row1">
          <select data-id="${e.detection_id}" class="is-${e.effective_action === "keep" ? "keep" : "redact"}">
            <option value="redact"${e.effective_action !== "keep" ? " selected" : ""}>redact</option>
            <option value="keep"${e.effective_action === "keep" ? " selected" : ""}>keep</option>
          </select>
          <code>${esc(e.text)}</code>
          ${manual ? '<span class="chip">manual</span>' : ""}
          ${remembered ? '<span class="chip">remembered</span>' : ""}
          <span class="meta2">p.${e.page_number} · ${e.confidence.toFixed(2)}</span>
          ${manual ? `<button class="rm" data-id="${e.detection_id}" title="Remove manual mark">✕</button>` : ""}
          ${remembered ? `<button class="rm" data-id="${e.detection_id}" title="Forget this workspace term (all documents)">✕</button>` : ""}
        </div>
        <div class="why">${esc(e.reasons.join(" · "))}</div>`;
      row.addEventListener("click", ev => {
        if (ev.target.closest("select") || ev.target.closest(".rm")) return;
        focusEntry(e.detection_id, {scrollPage: true});
      });
      row.addEventListener("mouseenter", () => setOverlayHl(e.detection_id, true));
      row.addEventListener("mouseleave", () => setOverlayHl(e.detection_id, false));
      g.appendChild(row);
    });
    el.appendChild(g);
  });

  el.querySelectorAll("select").forEach(s =>
    s.addEventListener("change", () => decide(s.dataset.id, s.value)));
  el.querySelectorAll(".rm").forEach(b =>
    b.addEventListener("click", () => removeManual(b.dataset.id)));
  el.querySelectorAll(".bulk button").forEach(b =>
    b.addEventListener("click", () => bulkDecide(b.dataset.type, b.dataset.act)));
}

function initPages() {
  const el = document.getElementById("pages");
  el.innerHTML = "";
  Object.keys(LAYOUT).forEach(k => delete LAYOUT[k]);
  ZOOM = Math.min(1, fitZoom());   // start at 100% or fit-width, whichever is smaller
  document.getElementById("zoom-val").textContent = Math.round(ZOOM * 100) + "%";
  (PAGES || []).forEach(p => {
    const label = document.createElement("div");
    label.className = "page-label";
    label.textContent = "Page " + p.page_number + " / " + PAGES.length;
    label.style.width = (BASE_WIDTH * ZOOM) + "px";
    const wrap = document.createElement("div");
    wrap.className = "page-wrap";
    wrap.dataset.page = p.page_number;
    wrap.style.width = (BASE_WIDTH * ZOOM) + "px";
    const img = document.createElement("img");
    img.src = pageSrc(p.page_number);
    img.alt = "page " + p.page_number;
    img.style.aspectRatio = p.width + " / " + p.height;
    const layer = document.createElement("div");
    layer.className = "text-layer";
    layer.dataset.page = p.page_number;
    wrap.appendChild(img);
    wrap.appendChild(layer);
    el.appendChild(label);
    el.appendChild(wrap);
    buildTextLayer(p, wrap);
  });
  observePages();
}

function pageSrc(n) {
  // Relative paths so the page works standalone ("/") and mounted
  // under the studio ("/review/{doc_id}/").
  return PREVIEW ? "api/preview/" + n + "?t=" + Date.now() : "api/page/" + n;
}

function renderOverlays() {
  document.querySelectorAll(".page-wrap").forEach(wrap => {
    wrap.querySelectorAll(".overlay").forEach(n => n.remove());
    const p = (PAGES || []).find(p => p.page_number === Number(wrap.dataset.page));
    if (!p) return;
    PLAN.entries.filter(e => e.page_number === p.page_number).forEach(e => {
      const o = document.createElement("div");
      o.className = "overlay " + (e.decision ? e.decision : e.effective_action);
      o.dataset.id = e.detection_id;
      o.title = `${e.type}: ${e.text}\n${e.reasons.join("\n")}`;
      o.style.left = (e.bbox.x0 / p.width * 100) + "%";
      o.style.top = (e.bbox.y0 / p.height * 100) + "%";
      o.style.width = ((e.bbox.x1 - e.bbox.x0) / p.width * 100) + "%";
      o.style.height = ((e.bbox.y1 - e.bbox.y0) / p.height * 100) + "%";
      o.addEventListener("click", () =>
        decide(e.detection_id, e.effective_action === "keep" ? "redact" : "keep"));
      o.addEventListener("mouseenter", () => setEntryHl(e.detection_id, true));
      o.addEventListener("mouseleave", () => setEntryHl(e.detection_id, false));
      wrap.appendChild(o);
    });
  });
}

/* ---------- sidebar ↔ page sync ---------- */

function setOverlayHl(id, on) {
  document.querySelectorAll(`.overlay[data-id="${id}"]`).forEach(o =>
    o.classList.toggle("hl", on));
}

function setEntryHl(id, on) {
  document.querySelectorAll(`.entry[data-id="${id}"]`).forEach(r =>
    r.classList.toggle("hl", on));
}

function focusEntry(id, opts) {
  FOCUS = id;
  document.querySelectorAll(".entry.focus").forEach(r => r.classList.remove("focus"));
  const row = document.querySelector(`.entry[data-id="${id}"]`);
  if (row) {
    row.classList.add("focus");
    row.scrollIntoView({block: "nearest"});
  }
  const overlay = document.querySelector(`.overlay[data-id="${id}"]`);
  if (overlay && opts && opts.scrollPage) {
    overlay.scrollIntoView({block: "center", behavior: "smooth"});
    overlay.classList.remove("flash");
    void overlay.offsetWidth;   // restart the animation
    overlay.classList.add("flash");
  }
}

/* ---------- keyboard shortcuts ---------- */

document.addEventListener("keydown", e => {
  if (e.key === "Escape") { FOCUS = null; hidePopup(); render(); return; }
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
  if (!PLAN || PREVIEW) return;
  if (e.key === "n" || e.key === "p") {
    const pending = PLAN.entries.filter(x => x.effective_action === "ask");
    const pool = pending.length ? pending : PLAN.entries;
    if (!pool.length) return;
    let i = pool.findIndex(x => x.detection_id === FOCUS);
    i = e.key === "n" ? (i + 1) % pool.length : (i - 1 + pool.length) % pool.length;
    focusEntry(pool[i].detection_id, {scrollPage: true});
  } else if ((e.key === "r" || e.key === "k") && FOCUS) {
    decide(FOCUS, e.key === "r" ? "redact" : "keep");
  }
});

/* ---------- selectable text layer ---------- */

async function buildTextLayer(p, wrap) {
  if (!PLAN) return;   // early view: page images only, no text layer yet
  if (!WORDS[p.page_number]) {
    try {
      WORDS[p.page_number] = (await api("api/text/" + p.page_number)).words;
    } catch (err) {
      WORDS[p.page_number] = [];
    }
  }
  layoutTextLayer(p, wrap);
}

function layoutTextLayer(p, wrap) {
  const layer = wrap.querySelector(".text-layer");
  const scale = wrap.clientWidth / p.width;
  if (!scale || !isFinite(scale)) return;
  layer.innerHTML = "";
  const items = [];
  for (const w of WORDS[p.page_number] || []) {
    if (!w.text) continue;
    const el = document.createElement("span");
    el.className = "tw";
    el.textContent = w.text;
    const h = (w.y1 - w.y0) * scale;
    el.style.left = (w.x0 * scale) + "px";
    el.style.top = (w.y0 * scale) + "px";
    el.style.fontSize = Math.max(h * 0.85, 4) + "px";
    el.style.lineHeight = h + "px";
    layer.appendChild(el);
    // fr: character boundary positions as fractions of the word width
    // (from the PDF's real glyph geometry) — null for OCR words.
    const width = w.x1 - w.x0;
    const fr = (w.cx && width > 0 && w.cx.length === w.text.length + 1)
      ? w.cx.map(v => (v - w.x0) / width) : null;
    items.push({el: el, x: w.x0 * scale, y: w.y0 * scale,
                w: (w.x1 - w.x0) * scale, h: h, fr: fr});
  }
  const widths = items.map(it => it.el.offsetWidth);   // batch reads
  items.forEach((it, i) => {                            // then batch writes
    if (widths[i] > 0) it.el.style.transform = "scaleX(" + (it.w / widths[i]) + ")";
  });
  LAYOUT[p.page_number] = items;
}

function relayoutAll() {
  document.querySelectorAll(".page-wrap").forEach(wrap => {
    const p = (PAGES || []).find(p => p.page_number === Number(wrap.dataset.page));
    if (p) layoutTextLayer(p, wrap);
  });
}
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(relayoutAll, 150);
});

/* ---------- zoom + page navigation ---------- */

function fitZoom() {
  // clientWidth of the (padding-free) pages column; keep within zoom bounds
  return Math.min(2.5, Math.max(0.6, document.getElementById("pages").clientWidth / BASE_WIDTH));
}

function setZoom(z) {
  ZOOM = Math.min(2.5, Math.max(0.6, z));
  document.getElementById("zoom-val").textContent = Math.round(ZOOM * 100) + "%";
  // Explicit width (not max-width) so zooming past the column width
  // actually enlarges the page; #pages scrolls horizontally.
  document.querySelectorAll(".page-wrap, .page-label").forEach(el =>
    el.style.width = (BASE_WIDTH * ZOOM) + "px");
  relayoutAll();
}
document.getElementById("zoom-in").addEventListener("click", () => setZoom(ZOOM + 0.15));
document.getElementById("zoom-out").addEventListener("click", () => setZoom(ZOOM - 0.15));
document.getElementById("zoom-fit").addEventListener("click", () => setZoom(fitZoom()));

let currentPage = 1;
let pageObserver = null;
function observePages() {
  if (pageObserver) pageObserver.disconnect();
  pageObserver = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (en.isIntersecting) {
        currentPage = Number(en.target.dataset.page);
        document.getElementById("page-ind").textContent =
          currentPage + "/" + PAGES.length;
      }
    });
  }, {rootMargin: "-45% 0px -45% 0px"});
  document.querySelectorAll(".page-wrap").forEach(w => pageObserver.observe(w));
  document.getElementById("page-ind").textContent = "1/" + PAGES.length;
}

function gotoPage(n) {
  const clamped = Math.min((PAGES || []).length || 1, Math.max(1, n));
  const wrap = document.querySelector(`.page-wrap[data-page="${clamped}"]`);
  if (wrap) wrap.scrollIntoView({block: "start", behavior: "smooth"});
}
document.getElementById("page-prev").addEventListener("click", () => gotoPage(currentPage - 1));
document.getElementById("page-next").addEventListener("click", () => gotoPage(currentPage + 1));

/* ---------- preview mode ---------- */

document.getElementById("preview-btn").addEventListener("click", () => {
  PREVIEW = !PREVIEW;
  const btn = document.getElementById("preview-btn");
  btn.classList.toggle("active", PREVIEW);
  btn.textContent = PREVIEW ? "Exit preview" : "Preview";
  document.body.classList.toggle("preview-mode", PREVIEW);
  document.getElementById("preview-banner").style.display = PREVIEW ? "block" : "none";
  if (PREVIEW) toast("Generating preview — pages update as they render.");
  document.querySelectorAll(".page-wrap img").forEach(img => {
    img.src = pageSrc(Number(img.closest(".page-wrap").dataset.page));
  });
});

/* ---------- rubber-band selection → mark-as-PII popup ---------- */

const popup = document.getElementById("popup");
let drag = null;   // {layer, page, x0, y0, rubber, moved}

function clearHighlights() {
  document.querySelectorAll(".tw.sel").forEach(el => {
    el.classList.remove("sel");
    el.style.background = "";
  });
}

function hidePopup() {
  popup.style.display = "none";
  pendingSelection = null;
  clearHighlights();
}

function showPopup(pageX, pageY, text) {
  pendingSelection = text;
  document.getElementById("sel-preview").value = text;
  popup.style.display = "flex";
  const left = Math.max(8, Math.min(pageX - 136,
    window.scrollX + document.documentElement.clientWidth - 288));
  popup.style.left = left + "px";
  popup.style.top = (pageY + 14) + "px";
  document.getElementById("label-input").focus();
}

function dragRect(e) {
  const bounds = drag.layer.getBoundingClientRect();
  const x1 = Math.min(Math.max(e.clientX - bounds.left, 0), bounds.width);
  const y1 = Math.min(Math.max(e.clientY - bounds.top, 0), bounds.height);
  return {x: Math.min(drag.x0, x1), y: Math.min(drag.y0, y1),
          w: Math.abs(x1 - drag.x0), h: Math.abs(y1 - drag.y0)};
}

function nearestBoundary(fr, f) {
  let best = 0, dist = Infinity;
  for (let i = 0; i < fr.length; i++) {
    const d = Math.abs(fr[i] - f);
    if (d < dist) { dist = d; best = i; }
  }
  return best;
}

function highlightRect(rect) {
  // Words fully inside the band are selected whole; words the band's left
  // or right edge cuts through are clipped to a character range. Words
  // with real glyph boundaries (it.fr, from the PDF text layer) snap to
  // the nearest glyph edge; OCR words fall back to proportional mapping
  // (exact for monospace — the popup lets the reviewer trim anyway).
  const items = LAYOUT[drag.page] || [];
  for (const it of items) {
    const hit = it.x < rect.x + rect.w && it.x + it.w > rect.x &&
                it.y < rect.y + rect.h && it.y + it.h > rect.y;
    const len = it.el.textContent.length;
    let from = 0, to = 0;
    if (hit && len > 0 && it.w > 0) {
      const f0 = (rect.x - it.x) / it.w;
      const f1 = (rect.x + rect.w - it.x) / it.w;
      if (it.fr) {
        from = nearestBoundary(it.fr, f0);
        to = nearestBoundary(it.fr, f1);
      } else {
        from = Math.max(0, Math.round(f0 * len));
        to = Math.min(len, Math.round(f1 * len));
      }
    }
    const sel = to > from;
    it.selFrom = sel ? from : null;
    it.selTo = sel ? to : null;
    it.el.classList.toggle("sel", sel);
    if (sel && (from > 0 || to < len)) {
      const f0 = (it.fr ? it.fr[from] : from / len) * 100;
      const f1 = (it.fr ? it.fr[to] : to / len) * 100;
      it.el.style.background = `linear-gradient(90deg, transparent ${f0}%, ` +
        `rgba(99,102,241,.35) ${f0}% ${f1}%, transparent ${f1}%)`;
    } else {
      it.el.style.background = "";
    }
  }
}

document.addEventListener("mousedown", e => {
  if (e.target.closest("#popup")) return;
  hidePopup();
  const layer = e.target.closest(".text-layer");
  if (!layer || e.button !== 0) return;
  e.preventDefault();
  const bounds = layer.getBoundingClientRect();
  const rubber = document.createElement("div");
  rubber.className = "rubber";
  layer.appendChild(rubber);
  drag = {layer: layer, page: Number(layer.dataset.page), rubber: rubber,
          x0: e.clientX - bounds.left, y0: e.clientY - bounds.top, moved: false};
});

document.addEventListener("mousemove", e => {
  if (!drag) return;
  const rect = dragRect(e);
  if (rect.w + rect.h > 4) drag.moved = true;
  drag.rubber.style.left = rect.x + "px";
  drag.rubber.style.top = rect.y + "px";
  drag.rubber.style.width = rect.w + "px";
  drag.rubber.style.height = rect.h + "px";
  highlightRect(rect);
});

document.addEventListener("mouseup", e => {
  if (!drag) return;
  drag.rubber.remove();
  const moved = drag.moved;
  const selected = (LAYOUT[drag.page] || []).filter(it => it.selFrom !== null && it.selFrom !== undefined);
  drag = null;
  if (!moved || selected.length === 0) { clearHighlights(); return; }
  const text = selected.map(it => it.el.textContent.slice(it.selFrom, it.selTo)).join(" ").trim();
  if (!text) { clearHighlights(); return; }
  showPopup(e.pageX, e.pageY, text);
});

/* ---------- actions ---------- */

async function refreshPlan() {
  const plan = await api("api/plan");
  PLAN.entries = plan.entries;
  PLAN.counts = plan.counts;
  render();
}

async function decide(id, decision, skipRender) {
  await api("api/decision", {detection_id: id, decision: decision});
  const entry = PLAN.entries.find(e => e.detection_id === id);
  entry.decision = decision;
  entry.effective_action = decision !== null ? decision : entry.suggested_action;
  if (!skipRender) render();
}

async function bulkDecide(type, act) {
  const affected = PLAN.entries.filter(e => e.type === type);
  const snapshot = affected.map(e => ({id: e.detection_id, decision: e.decision}));
  for (const e of affected) await decide(e.detection_id, act, true);
  render();
  toast(`Set ${affected.length} ${type} entr${affected.length === 1 ? "y" : "ies"} to ${act}.`,
    null, {label: "Undo", fn: async () => {
      for (const s of snapshot) await decide(s.id, s.decision, true);
      render();
    }});
}

async function markText(text, label, caseSensitive, remember) {
  try {
    const result = await api("api/mark",
      {text: text, label: label, case_sensitive: caseSensitive, remember: !!remember});
    const skipped = result.skipped || 0;
    const suffix = result.remembered ? " Remembered for this workspace." : "";
    if (result.added === 0 && skipped > 0) {
      toast("All " + skipped + (skipped > 1 ? " matches are" : " match is") +
            " already marked." + suffix);
    } else if (result.added === 0) {
      toast("Text not found in the document.", "warn");
    } else {
      toast("Marked " + result.added + " instance" + (result.added > 1 ? "s" : "") +
            " as " + label.toUpperCase() + " for redaction" +
            (skipped > 0 ? " (" + skipped + " already marked)" : "") + "." + suffix);
    }
    await refreshPlan();
  } catch (err) {
    toast("Mark failed: " + err.message, "warn");
  }
}

async function markSelection() {
  if (!pendingSelection) return;
  const text = document.getElementById("sel-preview").value.trim();
  if (!text) { toast("The text to mark is empty.", "warn"); return; }
  const label = document.getElementById("label-input").value.trim() || "CUSTOM";
  const caseSensitive = document.getElementById("match-case").checked;
  const remember = document.getElementById("remember-term").checked;
  document.getElementById("remember-term").checked = false;
  hidePopup();
  await markText(text, label, caseSensitive, remember);
}
document.getElementById("mark-btn").addEventListener("click", markSelection);
document.getElementById("cancel-mark").addEventListener("click", hidePopup);
document.getElementById("label-input").addEventListener("keydown", e => {
  if (e.key === "Enter") markSelection();
});
document.getElementById("sel-preview").addEventListener("keydown", e => {
  if (e.key === "Enter") markSelection();
});

document.getElementById("search-mark").addEventListener("click", async () => {
  const text = document.getElementById("search-text").value.trim();
  if (!text) { toast("Type the text to mark first.", "warn"); return; }
  const label = document.getElementById("search-label").value.trim() || "CUSTOM";
  const remember = document.getElementById("search-remember").checked;
  document.getElementById("search-remember").checked = false;
  await markText(text, label, document.getElementById("search-case").checked, remember);
  document.getElementById("search-text").value = "";
});
document.getElementById("search-text").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("search-mark").click();
});

async function removeManual(id) {
  const entry = PLAN.entries.find(e => e.detection_id === id);
  const remembered = entry && entry.detector === "remembered";
  try {
    await api("api/remove", {detection_id: id});
    // Forgetting a workspace term removes its sibling entries too —
    // reload the plan rather than filtering the single id.
    await refreshPlan();
    toast(remembered ? "Workspace term forgotten — removed from all suggestions."
                     : "Manual mark removed.");
  } catch (err) {
    toast("Remove failed: " + err.message, "warn");
  }
}

async function rerunWithOcr() {
  try {
    await api("api/rerun", {});
  } catch (err) {
    toast("Re-run failed: " + err.message, "warn");
    return;
  }
  PLAN = null;
  FOCUS = null;
  Object.keys(WORDS).forEach(k => delete WORDS[k]);
  document.getElementById("pages").innerHTML = "";
  document.getElementById("groups").innerHTML = "";
  const loading = document.getElementById("loading");
  loading.style.display = "flex";
  document.getElementById("load-spinner").style.display = "";
  document.getElementById("load-stage").className = "stage";
  bootStart = Date.now();
  boot();
}

/* ---------- dashboard link (studio mode only) ---------- */
// Mounted under the studio the path is /review/{doc_id}/ — detect that
// too, so the button survives navigation that drops the ?studio query.
if (location.search.includes("studio") || location.pathname.includes("/review/")) {
  const hb = document.getElementById("home-btn");
  hb.style.display = "";
  hb.addEventListener("click", () => { window.location.href = "/"; });
}

document.getElementById("save").addEventListener("click", async () => {
  try {
    const result = await api("api/save", {});
    toast("Plan saved: " + result.plan_path);
  } catch (err) {
    toast("Save failed: " + err.message, "warn");
  }
});

document.getElementById("apply").addEventListener("click", async () => {
  const btn = document.getElementById("apply");
  btn.disabled = true;
  btn.textContent = "Applying…";
  try {
    const style = document.getElementById("style").value;
    const result = await api("api/apply", {redaction_type: style});
    const banner = document.getElementById("banner");
    banner.style.display = "flex";
    banner.innerHTML =
      `<span>Redacted PDF written: ${esc(result.output_path)} ` +
      `(${result.redactions} redaction${result.redactions === 1 ? "" : "s"}).</span>` +
      `<a class="view" href="api/output" target="_blank" rel="noopener">View redacted PDF</a>`;
    toast("Done — click “View redacted PDF” to inspect the result.");
  } catch (err) {
    toast("Apply failed: " + err.message, "warn");
  } finally {
    btn.disabled = false;
    btn.textContent = "Apply & export PDF";
  }
});

boot();
</script>
</body>
</html>
"""

STUDIO_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Firewall — Studio</title>
<style>
  :root {
    --accent: #6366f1; --accent-strong: #4f46e5;
    --bg: #f1f5f9; --panel: #ffffff; --line: #e2e8f0;
    --text: #0f172a; --muted: #64748b;
    --shadow: 0 1px 2px rgba(15,23,42,.06), 0 4px 12px rgba(15,23,42,.06);
    --shadow-lg: 0 4px 8px rgba(15,23,42,.08), 0 12px 32px rgba(15,23,42,.14);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; color: var(--text); background: var(--bg);
    font: 14px/1.5 -apple-system, "Segoe UI", system-ui, Roboto, "Helvetica Neue", Arial, sans-serif;
    min-height: 100vh;
  }
  header {
    display: flex; align-items: center; gap: 12px; padding: 12px 20px;
    background: rgba(255,255,255,.9); backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 30;
  }
  .logo { display: flex; align-items: center; gap: 9px; }
  .logo svg { width: 26px; height: 26px; }
  .logo .name { font-size: 16px; font-weight: 700; letter-spacing: -.01em; }
  .logo .sub { font-size: 11px; color: var(--muted); margin-top: -2px; }
  header .spacer { flex: 1; }
  .btn {
    border: 1px solid var(--line); background: var(--panel); color: var(--text);
    border-radius: 8px; padding: 8px 14px; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: background .12s, border-color .12s, box-shadow .12s;
  }
  .btn:hover { background: #f8fafc; border-color: #cbd5e1; }
  .btn.primary {
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%);
    border-color: transparent; color: #fff; box-shadow: 0 1px 3px rgba(79,70,229,.4);
  }
  .btn.primary:hover { filter: brightness(1.07); }
  main { max-width: 940px; margin: 0 auto; padding: 28px 20px 48px; }
  h1 { font-size: 22px; margin: 4px 0 2px; letter-spacing: -.02em; }
  .lede { color: var(--muted); margin: 0 0 22px; }

  /* drop zone */
  #drop {
    border: 2px dashed #cbd5e1; border-radius: 16px; background: var(--panel);
    padding: 30px; text-align: center; transition: border-color .12s, background .12s;
    cursor: pointer; box-shadow: var(--shadow);
  }
  #drop.hover { border-color: var(--accent); background: #eef2ff; }
  #drop .big { font-size: 15px; font-weight: 600; }
  #drop .small { color: var(--muted); font-size: 12.5px; margin-top: 4px; }
  #drop input[type=file], #file { display: none; }

  /* document list */
  .section-title { font-size: 13px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); font-weight: 700; margin: 28px 0 12px; }
  #docs { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
  .doc {
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    box-shadow: var(--shadow); padding: 16px; display: flex; flex-direction: column; gap: 10px;
    transition: box-shadow .12s, transform .12s;
  }
  .doc:hover { box-shadow: var(--shadow-lg); transform: translateY(-1px); }
  .doc .ico { width: 34px; height: 34px; border-radius: 8px; background: #eef2ff;
    color: var(--accent-strong); display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 12px; flex-shrink: 0; }
  .doc .top { display: flex; gap: 12px; align-items: flex-start; min-width: 0; }
  .doc .nm { font-weight: 600; word-break: break-all; }
  .doc .meta { color: var(--muted); font-size: 12px; margin-top: 2px; }
  .doc .row { display: flex; align-items: center; gap: 8px; }
  .doc .tag { font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
    background: #ecfdf5; color: #065f46; }
  .doc .tag.busy { background: #eef2ff; color: #3730a3; }
  .doc .tag.fail { background: #fef2f2; color: #b91c1c; }
  .doc .actions { display: flex; gap: 8px; margin-top: 4px; }
  .doc .actions .btn { flex: 1; padding: 7px 0; text-align: center; }
  .empty { color: var(--muted); text-align: center; padding: 26px; border: 1px dashed #cbd5e1;
    border-radius: 14px; }
  #toasts { position: fixed; bottom: 20px; right: 20px; z-index: 100; display: flex;
    flex-direction: column; gap: 8px; }
  .toast { background: #0f172a; color: #f8fafc; border-radius: 10px; padding: 10px 16px;
    font-size: 13px; box-shadow: var(--shadow-lg); max-width: 420px; word-break: break-word; }
  .toast.warn { background: #92400e; }
</style>
</head>
<body>
<header>
  <div class="logo">
    <svg viewBox="0 0 24 24" fill="none">
      <path d="M12 2 4 5.5v5.6c0 4.9 3.4 9.5 8 10.9 4.6-1.4 8-6 8-10.9V5.5L12 2Z"
            fill="url(#g)" stroke="#4338ca" stroke-width="1.2" stroke-linejoin="round"/>
      <path d="M8.6 12.1l2.3 2.3 4.5-4.6" stroke="#fff" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round"/>
      <defs><linearGradient id="g" x1="4" y1="2" x2="20" y2="22">
        <stop stop-color="#818cf8"/><stop offset="1" stop-color="#4f46e5"/>
      </linearGradient></defs>
    </svg>
    <div><div class="name">Privacy Firewall</div><div class="sub">Studio</div></div>
  </div>
  <span class="spacer"></span>
  <button class="btn primary" id="upload-btn">Upload documents</button>
  <input type="file" id="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif,.txt,.md,.docx" multiple>
</header>

<main>
  <h1>Review documents for PII</h1>
  <p class="lede">Open a document to detect and redact sensitive information. Everything runs locally on your machine.</p>

  <div id="drop">
    <div class="big">Drop documents here, or click to choose</div>
    <div class="small">PDF, images (PNG · JPG · TIFF · BMP · WebP · GIF), TXT, MD, and DOCX.
      Files are saved into this workspace folder and stay on your computer.</div>
    <input type="file" id="drop-file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif,.txt,.md,.docx" multiple>
  </div>

  <div class="section-title">Documents in this workspace
    <span id="terms-note" style="text-transform:none;font-weight:400"></span></div>
  <div id="docs"></div>
</main>

<div id="toasts"></div>

<script>
"use strict";
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtSize(b) {
  if (b < 1024) return b + " B";
  if (b < 1024*1024) return (b/1024).toFixed(1) + " KB";
  return (b/1024/1024).toFixed(1) + " MB";
}
function fmtDate(t) {
  const d = new Date(t * 1000);
  return d.toLocaleDateString() + " " + d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
}
function toast(msg, kind) {
  const el = document.createElement("div");
  el.className = "toast" + (kind === "warn" ? " warn" : "");
  el.textContent = msg;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function statusTag(d) {
  if (d.status === "ready" || !d.status) return "";
  if (d.status === "error") {
    return '<span class="tag fail" title="' + esc(d.error || "") + '">Failed</span>';
  }
  return '<span class="tag busy">Processing…</span>';
}

async function uploadFiles(fileList) {
  for (const f of fileList) {
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await fetch("/api/upload", {method: "POST", body: fd});
      if (!res.ok) {
        const txt = await res.text();
        toast("Upload failed: " + txt, "warn");
        continue;
      }
      toast("Uploaded " + f.name);
    } catch (err) {
      toast("Upload failed: " + err.message, "warn");
    }
  }
  refresh();
}

async function refresh() {
  const docs = document.getElementById("docs");
  let data;
  try {
    data = await (await fetch("/api/documents")).json();
  } catch (err) {
    docs.innerHTML = '<div class="empty">Could not load documents.</div>';
    return;
  }
  const note = document.getElementById("terms-note");
  note.textContent = data.terms
    ? "· " + data.terms + " remembered term" + (data.terms > 1 ? "s" : "") : "";
  if (!data.documents.length) {
    docs.innerHTML = '<div class="empty">No documents yet. Drop a file above to get started.</div>';
    return;
  }
  docs.innerHTML = "";
  data.documents.forEach(d => {
    const card = document.createElement("div");
    card.className = "doc";
    card.innerHTML = `
      <div class="top">
        <div class="ico">${esc((d.type || "pdf").toUpperCase().slice(0, 4))}</div>
        <div style="min-width:0">
          <div class="nm">${esc(d.name)}</div>
          <div class="meta">${fmtSize(d.size)} · ${fmtDate(d.modified)}</div>
        </div>
      </div>
      <div class="row">${statusTag(d)}${d.has_plan ? '<span class="tag">Resume available</span>' : ''}</div>
      <div class="actions">
        <button class="btn primary" data-open="${esc(d.id)}">Open</button>
      </div>`;
    card.querySelector("[data-open]").addEventListener("click", () => {
      window.location.href = "/review/" + d.id + "/?studio=1";
    });
    docs.appendChild(card);
  });
}

/* upload controls */
document.getElementById("upload-btn").addEventListener("click", () =>
  document.getElementById("file").click());
document.getElementById("file").addEventListener("change", e => uploadFiles(e.target.files));
document.getElementById("drop-file").addEventListener("change", e => uploadFiles(e.target.files));

const drop = document.getElementById("drop");
["dragenter", "dragover"].forEach(ev =>
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("hover"); }));
["dragleave", "drop"].forEach(ev =>
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("hover"); }));
drop.addEventListener("click", () => document.getElementById("drop-file").click());
drop.addEventListener("drop", e => {
  if (e.dataTransfer && e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});

refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""
