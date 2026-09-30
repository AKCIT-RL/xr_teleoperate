// Interface de teleoperação — lógica da página.
"use strict";

const PROC_ORDER = ["sim", "bridge", "teleop"];
const PROC_LABEL = { sim: "Simulação", bridge: "Ponte WebRTC", teleop: "Teleop" };
const STATE_TEXT = { parado: "parado", iniciando: "iniciando…", pronto: "pronto", parando: "encerrando…", erro: "erro" };
const JOINT_SHORT = ["omb. P", "omb. R", "omb. Y", "cotovelo", "pulso R", "pulso P", "pulso Y"];

const S = {
  schema: null, presets: {}, tasks: [], interfaces: [],
  base: {}, overrides: { sim: {}, bridge: {}, teleop: {} },
  preview: null, server: null, checks: [], robotLog: [],
  logs: { sim: [], bridge: [], teleop: [] },
  logTab: "teleop", levels: { info: true, warn: true, error: true, debug: false },
  view: "op", showConfig: false, safety: [false, false, false],
  videoKey: null, videoMode: "stereo",
  rec: { list: [], sel: null, data: null, index: 0, playing: false, charts: null },
};

// ---------- utilidades ----------
const $ = (id) => document.getElementById(id);
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (_) { /* sem corpo */ }
  if (!r.ok) throw new Error((data && data.msg) || `HTTP ${r.status}`);
  return data;
}
function store(key, val) { try { localStorage.setItem("teleopgui." + key, JSON.stringify(val)); } catch (_) {} }
function load(key, def) { try { const v = localStorage.getItem("teleopgui." + key); return v ? JSON.parse(v) : def; } catch (_) { return def; } }
function fmtDur(sec) { sec = Math.floor(sec || 0); const m = Math.floor(sec / 60), s = sec % 60; return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; }
function fmtClock(ts) { const d = new Date(ts * 1000); return d.toTimeString().slice(0, 8); }
function toast(msg) { alert(msg); }
const ICON = {
  stop: '<svg width="14" height="14" viewBox="0 0 14 14"><rect x="2" y="2" width="10" height="10" fill="currentColor"/></svg>',
  play: '<svg width="14" height="14" viewBox="0 0 14 14"><path d="M3 2l9 5-9 5z" fill="currentColor"/></svg>',
  restart: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 8a5 5 0 1 1-1.5-3.5M13 2v3h-3"/></svg>',
  pause: '<svg width="16" height="16" viewBox="0 0 14 14"><rect x="3" y="2" width="3" height="10" fill="currentColor"/><rect x="8" y="2" width="3" height="10" fill="currentColor"/></svg>',
};

// ---------- estado derivado ----------
const srv = () => S.server || { procs: {}, teleop_ipc: {}, session: {}, video: {} };
const proc = (n) => srv().procs[n] || { state: "parado", flags: {} };
const anyRunning = () => PROC_ORDER.some((n) => ["iniciando", "pronto", "parando"].includes(proc(n).state));
const sessionMode = () => (srv().session && srv().session.active && srv().session.mode) || S.base.mode;
const isReal = () => sessionMode() === "real";
const activeProcs = () => (isReal() ? ["bridge", "teleop"] : ["sim", "bridge", "teleop"]);
const questConnected = () => !!(proc("bridge").flags || {}).quest_connected;
const safetyOk = () => S.safety.every(Boolean);

// ---------- inicialização ----------
async function init() {
  const sc = await api("/api/schema");
  S.schema = sc.schema; S.presets = sc.presets; S.tasks = sc.tasks; S.interfaces = sc.interfaces;
  S.base = Object.assign({}, sc.default_base, load("base", {}));
  S.overrides = Object.assign({ sim: {}, bridge: {}, teleop: {} }, load("overrides", {}));
  if (!S.base.quest_ip || !S.interfaces.some((i) => i.ip === S.base.quest_ip)) {
    const wifi = S.interfaces.find((i) => /^wl/.test(i.name)) || S.interfaces.find((i) => !/docker|tailscale|br-|veth/.test(i.name));
    S.base.quest_ip = wifi ? wifi.ip : "";
  }
  S.levels = Object.assign(S.levels, load("levels", {}));
  document.querySelectorAll("[data-lv]").forEach((cb) => { cb.checked = !!S.levels[cb.dataset.lv]; });

  bindStatic();
  buildAdvanced();
  renderConfigFields();
  await refreshPreview();
  runChecks();
  connectWS();
  setInterval(() => { if (!anyRunning() && S.view === "op") runChecks(true); }, 10000);
  setInterval(tick, 1000);
  pollUsb();
  setInterval(pollUsb, 4000);
}

function bindStatic() {
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  document.querySelectorAll("#mode-seg button").forEach((b) => b.addEventListener("click", () => {
    if (anyRunning()) return;
    S.base.mode = b.dataset.mode; saveBase(); renderConfigFields(); buildAdvanced(); refreshPreview(); runChecks(); renderAll();
  }));
  $("btn-stop-all").addEventListener("click", async () => {
    if (!anyRunning() || confirm("Encerrar todos os processos?")) {
      try { await api("/api/session/stop", {}); } catch (e) { toast(e.message); }
    }
  });
  $("btn-start-session").addEventListener("click", startSession);
  $("btn-recheck").addEventListener("click", () => runChecks());
  $("btn-reset-adv").addEventListener("click", () => { S.overrides = { sim: {}, bridge: {}, teleop: {} }; store("overrides", S.overrides); refreshPreview(); });
  $("btn-show-config").addEventListener("click", () => { S.showConfig = true; renderAll(); });
  $("btn-back-live").addEventListener("click", () => { S.showConfig = false; renderAll(); });
  document.querySelectorAll("#video-seg button").forEach((b) => b.addEventListener("click", () => { S.videoMode = b.dataset.v; renderVideo(); }));
  $("btn-fullscreen").addEventListener("click", () => { const el = $("video-box"); (document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen()).catch(() => {}); });
  document.querySelectorAll("[data-lv]").forEach((cb) => cb.addEventListener("change", () => { S.levels[cb.dataset.lv] = cb.checked; store("levels", S.levels); renderLogs(true); }));
  document.querySelectorAll("[data-safety]").forEach((cb, i) => cb.addEventListener("change", () => { S.safety[i % 3] = cb.checked; syncSafety(); renderAll(); }));
  // gravações
  $("btn-rec-refresh").addEventListener("click", loadRecordings);
  $("rec-filter").addEventListener("input", renderRecList);
  $("pl-slider").addEventListener("input", (e) => seekIndex(+e.target.value));
  $("pl-play").addEventListener("click", togglePlay);
  $("pl-back").addEventListener("click", () => seekIndex(S.rec.index - 5 * recFps()));
  $("pl-fwd").addEventListener("click", () => seekIndex(S.rec.index + 5 * recFps()));
  $("btn-replay").addEventListener("click", startReplay);
  $("btn-replay-stop").addEventListener("click", async () => { try { await api("/api/session/stop", {}); } catch (e) { toast(e.message); } });
  window.addEventListener("resize", () => { if (S.rec.charts) drawCharts(); });
  document.addEventListener("keydown", onKey);
}

function syncSafety() {
  document.querySelectorAll("[data-safety]").forEach((cb, i) => { cb.checked = S.safety[i % 3]; });
}

function setView(v) {
  S.view = v;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("view-op").classList.toggle("hidden", v !== "op");
  $("view-rec").classList.toggle("hidden", v !== "rec");
  if (v === "rec" && !S.rec.list.length) loadRecordings();
  if (v === "rec" && S.rec.charts) setTimeout(drawCharts, 0);
}

// ---------- websocket ----------
function connectWS() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "state") { S.server = m; renderAll(); }
    else if (m.type === "proc") { if (S.server) S.server.procs[m.proc.name] = m.proc; renderAll(); }
    else if (m.type === "logs") { S.logs[m.proc] = m.entries; if (m.proc === S.logTab) renderLogs(true); }
    else if (m.type === "log") onLog(m.proc, m.entry, m.new);
  };
  // ao (re)conectar, reabre o vídeo: um stream MJPEG que caiu não volta sozinho
  ws.onopen = () => { S.videoKey = null; };
  ws.onclose = () => setTimeout(connectWS, 1500);
}

function openVideo(v) {
  const img = $("video-img");
  img.onerror = () => { S.videoKey = null; };   // tenta de novo no próximo renderVideo
  img.src = `/video.mjpg?host=${encodeURIComponent(v.host)}&port=${v.port}&t=${Date.now()}`;
}

// ---------- configuração ----------
function saveBase() { store("base", S.base); }
function setBase(k, v) { S.base[k] = v; saveBase(); refreshPreview(); renderConfigFields(); }

function field(label, control, note) {
  return h("label", { class: "field" }, label, control, note ? h("span", { class: "small" }, note) : null);
}
function checkbox(label, key, disabled) {
  return h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!S.base[key], disabled, onchange: (e) => setBase(key, e.target.checked) }), label);
}
function selectEl(options, value, onchange, attrs = {}) {
  const sel = h("select", Object.assign({ onchange: (e) => onchange(e.target.value) }, attrs));
  for (const [v, t] of options) sel.append(h("option", { value: v, selected: v === value }, t));
  return sel;
}
function ifaceOptions(emptyText) {
  const opts = S.interfaces.map((i) => [i.ip, `${i.name} · ${i.ip}${i.usb ? " (cabo USB)" : ""}`]);
  if (emptyText) opts.unshift(["", emptyText]);
  return opts;
}

function renderConfigFields() {
  const real = S.base.mode === "real";
  const g = $("cfg-fields");
  g.innerHTML = "";
  const preset = S.presets[S.base.preset] || {};
  const controller = S.base.input_mode === "controller";

  const questSel = selectEl(ifaceOptions("— escolha —"), S.base.quest_ip, (v) => setBase("quest_ip", v));
  const net = h("fieldset", {}, h("legend", {}, real ? "Rede do Quest (Wi‑Fi ou cabo)" : "Rede e vídeo"),
    field("IP do PC (o Quest conecta aqui)", questSel, `No app: ${S.base.quest_ip || "?"}:8765 · vira --ice-host`),
    h("div", { id: "usb-box", class: "usb-box" }),
    checkbox("Vídeo estéreo para o Quest", "stereo"));

  const input = h("fieldset", {}, h("legend", {}, "Entrada do operador"),
    selectEl([["controller", "Controles"], ["hand", "Mãos (sem locomoção)"]], S.base.input_mode, (v) => setBase("input_mode", v)),
    checkbox("Locomoção pelos thumbsticks", "motion", !controller || (!real && !preset.motion)),
    (!real && !preset.motion) ? h("span", { class: "small" }, "Esta tarefa tem base fixa.") : null);

  const rec = h("fieldset", {}, h("legend", {}, "Gravação"),
    checkbox("Habilitar gravação de episódios", "record"),
    field("Nome da pasta", h("input", { type: "text", value: S.base.record_name || "", onchange: (e) => setBase("record_name", e.target.value.trim()) }), "teleop/utils/data/<pasta>/episode_XXXX"));

  if (!real) {
    const presetSel = selectEl(Object.entries(S.presets).map(([k, p]) => [k, p.label]), S.base.preset, (v) => {
      S.base.preset = v;
      if (S.presets[v]) S.base.record_name = S.presets[v].record_name;
      setBase("preset", v);
    });
    g.append(
      h("fieldset", {}, h("legend", {}, "Tarefa"), presetSel, h("span", { class: "small mono" }, preset.task || ""), h("span", { class: "small" }, preset.note || "")),
      h("fieldset", {}, h("legend", {}, "Simulação"), checkbox("Headless (sem janela do Isaac)", "headless"),
        h("span", { class: "small" }, "A visão do robô vem pela câmera (ZMQ) e aparece na tela de Operação.")),
      input, net, rec);
  } else {
    const robotSel = selectEl(S.interfaces.map((i) => [i.name, `${i.name} · ${i.ip}`]).concat([["", "— escolha —"]]),
      S.base.robot_iface, (v) => setBase("robot_iface", v));
    g.append(
      net,
      h("fieldset", {}, h("legend", {}, "Rede do robô (cabo)"),
        field("Interface cabeada", robotSel, "vira --network-interface do teleop (DDS domínio 0)"),
        field("IP do robô", h("input", { type: "text", class: "mono", value: S.base.robot_ip || "", onchange: (e) => setBase("robot_ip", e.target.value.trim()) }),
          "vira --img-server-ip da ponte e do teleop")),
      input,
      h("fieldset", {}, h("legend", {}, "Efetuador do robô"),
        selectEl([["", "Nenhum (mão fixa)"], ["dex1", "Garra Dex1"]], S.base.real_ee || "", (v) => setBase("real_ee", v)),
        h("span", { class: "small" }, "Com Unity só há suporte a Dex1 ou nenhum.")),
      rec);
  }
  $("cfg-real-banner").classList.toggle("hidden", !real);
  renderSafetyInConfig();
  renderUsb(true);
}

// ---------- rede pelo cabo USB (Quest em modo NCM) ----------
const usbSelected = () => !!(S.usb && S.usb.pc_ip && S.base.quest_ip === S.usb.pc_ip);

async function pollUsb() {
  try { S.usb = await api("/api/usb-network"); } catch (_) { return; }
  if (S.usb.pc_ip && !S.interfaces.some((i) => i.ip === S.usb.pc_ip)) {
    // a placa do cabo acabou de aparecer: atualiza a lista de IPs
    try { S.interfaces = (await api("/api/schema")).interfaces; renderConfigFields(); } catch (_) {}
  }
  renderUsb();
  if (!$("live").classList.contains("hidden")) { renderQuest(); renderTop(); }
}

async function enableUsb() {
  S.usbBusy = true; S.usbMsg = null; renderUsb(true);
  try {
    const r = await api("/api/usb-network/enable", {});
    S.usb = r.status; S.usbMsg = { ok: r.ok, text: r.msg };
    if (r.ok && r.status.pc_ip) {
      S.interfaces = (await api("/api/schema")).interfaces;
      S.base.quest_ip = r.status.pc_ip; saveBase(); refreshPreview(); renderConfigFields();
    }
  } catch (e) { S.usbMsg = { ok: false, text: e.message }; }
  S.usbBusy = false; renderUsb(true); renderAll();
}

function renderUsb(force) {
  const box = $("usb-box");
  if (!box) return;
  const u = S.usb || {};
  const sig = [u.active, u.pc_ip, u.quest_ip, u.adb, u.profile, S.usbBusy, S.usbMsg, S.base.quest_ip];
  if (!force && !changed(box, sig)) return;
  box.dataset.sig = JSON.stringify(sig);
  box.innerHTML = "";
  const dot = u.active ? "ok" : S.usbBusy ? "busy" : "";
  const status = u.active ? `Cabo USB ativo · PC ${u.pc_ip} · Quest ${u.quest_ip}`
    : u.pc_ip ? `Placa do cabo presente (${u.pc_ip}), Quest ainda sem IP`
    : "Cabo USB inativo";
  box.append(h("div", { class: "usb-row" }, h("span", { class: `dot ${dot}` }), h("span", {}, status)));
  const btns = h("div", { class: "usb-row" });
  if (!u.active) {
    btns.append(h("button", { class: "btn", style: "height:38px", disabled: S.usbBusy || anyRunning(), onclick: enableUsb },
      S.usbBusy ? "Ativando… (até 30 s)" : "Ativar cabo USB"));
  } else if (!usbSelected()) {
    btns.append(h("button", { class: "btn", style: "height:38px", disabled: anyRunning(),
      onclick: () => { setBase("quest_ip", u.pc_ip); } }, "Usar o cabo nesta sessão"));
  } else {
    btns.append(h("span", { class: "small okt" }, "Sessão configurada para o cabo."));
  }
  box.append(btns);
  const notes = [];
  if (S.usbMsg) notes.push(h("div", { class: S.usbMsg.ok ? "small okt" : "small badt" }, S.usbMsg.text));
  if (!u.profile && S.usb) notes.push(h("div", { class: "small" }, "Perfil de rede do PC ausente. Rode uma vez: ", h("span", { class: "mono" }, u.profile_cmd)));
  if (!u.active && u.adb && u.adb !== "device") notes.push(h("div", { class: "small" }, `adb: ${u.adb}` + (u.adb === "unauthorized" ? " — autorize a depuração USB no óculos." : "")));
  if (u.active) notes.push(h("div", { class: "small" }, `No app: ${u.pc_ip}:8765. Reiniciar o óculos ou reconectar o cabo desliga o modo cabo.`));
  box.append(...notes);
}

function renderSafetyInConfig() {
  // no modo real, a lista de segurança também aparece na configuração
  let box = $("cfg-safety");
  if (S.base.mode !== "real") { if (box) box.remove(); return; }
  if (!box) {
    box = h("div", { class: "card", id: "cfg-safety" }, h("h2", {}, "Antes de iniciar"),
      ...["Robô em walk mode (regular)", "Área ao redor livre", "Parada de emergência com alguém"].map((t) =>
        h("label", { class: "check" }, h("input", { type: "checkbox", "data-safety": true }), t)));
    $("btn-start-session").parentElement.after(box);
    box.querySelectorAll("[data-safety]").forEach((cb, i) => cb.addEventListener("change", () => { S.safety[i] = cb.checked; syncSafety(); renderAll(); }));
  }
  syncSafety();
}

// ---------- Avançado ----------
const advInputs = {};
function buildAdvanced() {
  const cols = $("adv-cols");
  cols.innerHTML = "";
  for (const p of PROC_ORDER) {
    advInputs[p] = {};
    const col = h("div", { class: "adv-col", id: `adv-${p}` },
      h("div", { style: "display:flex;align-items:center" }, h("b", {}, PROC_LABEL[p]), h("div", { class: "spacer" }),
        h("span", { class: "small", id: `adv-${p}-note` })));
    for (const prm of S.schema[p]) {
      let input;
      const onChange = (val) => { S.overrides[p][prm.key] = val; store("overrides", S.overrides); refreshPreview(); };
      if (prm.kind === "bool") {
        input = h("input", { type: "checkbox", disabled: prm.locked, onchange: (e) => onChange(e.target.checked) });
      } else if (prm.kind === "select") {
        input = selectEl(prm.options.map((o) => [o, o === "" ? "(nenhum)" : o]), "", onChange, { disabled: prm.locked });
      } else if (prm.key === "task" && p === "sim") {
        input = h("input", { type: "text", list: "task-list", onchange: (e) => onChange(e.target.value.trim()) });
      } else {
        input = h("input", { type: "text", placeholder: prm.key === "extra" ? "ex.: --flag valor" : "—", onchange: (e) => onChange(e.target.value.trim() || null) });
      }
      advInputs[p][prm.key] = input;
      const row = h("div", { class: "adv-row", id: `adv-${p}-${prm.key}`, title: prm.help || prm.label },
        h("label", {}, prm.flag || "extras"), input);
      col.append(row);
    }
    cols.append(col);
  }
  if (!$("task-list")) {
    const dl = h("datalist", { id: "task-list" });
    S.tasks.forEach((t) => dl.append(h("option", { value: t })));
    document.body.append(dl);
  }
}

function renderAdvanced() {
  const pv = S.preview;
  if (!pv) return;
  for (const p of PROC_ORDER) {
    const active = pv.active.includes(p);
    $(`adv-${p}`).classList.toggle("off", !active);
    $(`adv-${p}-note`).textContent = active ? (p === "sim" ? "sim_main.py" : p === "bridge" ? "python_webrtc.py" : "teleop_hand_and_arm.py") : "não usada neste modo";
    for (const prm of S.schema[p]) {
      const el = advInputs[p][prm.key];
      const v = pv.values[p][prm.key];
      if (document.activeElement !== el) {
        if (prm.kind === "bool") el.checked = !!v;
        else el.value = v == null ? "" : String(v);
      }
      $(`adv-${p}-${prm.key}`).classList.toggle("changed", prm.key in (S.overrides[p] || {}));
    }
  }
  const box = $("cmd-preview");
  box.innerHTML = "";
  box.append(h("div", { class: "h2cap", style: "margin-bottom:6px" }, "Comandos que serão executados"));
  for (const p of pv.active) box.append(h("div", {}, h("span", { class: "who" }, `${p.padEnd(6, " ")} $ `), pv.commands[p]));
}

let previewTimer = null;
function refreshPreview() {
  clearTimeout(previewTimer);
  return new Promise((resolve) => {
    previewTimer = setTimeout(async () => {
      try {
        S.preview = await api("/api/preview", { base: S.base, overrides: S.overrides });
        renderAdvanced();
        renderWarnings();
        renderSteps();
        renderTop();
      } catch (e) { console.error(e); }
      resolve();
    }, 120);
  });
}

function renderWarnings() {
  const w = (S.preview && S.preview.warnings) || [];
  const box = $("cfg-warnings");
  box.classList.toggle("hidden", !w.length);
  box.innerHTML = "";
  w.forEach((t) => box.append(h("div", {}, "⚠ " + t)));
}

async function runChecks(quiet) {
  try {
    const r = await api("/api/checks", { base: S.base });
    S.checks = r.items;
    if (r.interfaces && r.interfaces.length !== S.interfaces.length) { S.interfaces = r.interfaces; renderConfigFields(); }
    if (S.base.mode === "real") {
      const now = Date.now() / 1000;
      r.items.filter((i) => ["ping", "imgserver"].includes(i.key)).forEach((i) => S.robotLog.push({ id: S.robotLog.length + 1, ts: now, level: i.ok ? "info" : "error", text: i.text, count: 1 }));
      if (S.logTab === "robot") renderLogs(true);
    }
    renderChecks();
  } catch (e) { if (!quiet) toast("Falha nas verificações: " + e.message); }
}

function renderChecks() {
  const box = $("cfg-checks");
  box.innerHTML = "";
  for (const c of S.checks) {
    const status = c.ok === true ? h("span", { class: "okt" }, "ok") : c.ok === false ? h("span", { class: "badt" }, "!") : h("span", { class: "neut" }, "?");
    const row = h("div", { class: "checkrow" }, h("span", {}, c.text), status);
    box.append(row);
    if (c.key === "stale" && c.pids && c.pids.length) {
      box.append(h("button", { class: "btn", style: "height:34px", onclick: async () => {
        if (!confirm("Encerrar os processos antigos listados?")) return;
        await api("/api/kill-stale", { pids: c.pids }); setTimeout(() => runChecks(), 1500);
      } }, "Encerrar processos antigos"));
    }
  }
}

function renderSteps() {
  const box = $("cfg-steps");
  box.innerHTML = "";
  const real = S.base.mode === "real";
  const ses = srv().session || {};
  const steps = [];
  if (!real) steps.push(["sim", "Simulação", "pronta quando o controlador inicia"]);
  else {
    const img = S.checks.find((c) => c.key === "imgserver");
    steps.push(["img", "Servidor de imagens (robô)", img ? img.text : "iniciado manualmente no robô"]);
  }
  steps.push(["bridge", "Ponte WebRTC", "sobe depois da " + (real ? "verificação do robô" : "simulação")]);
  steps.push(["teleop", "Teleop", "aguarda as poses do Quest"]);
  steps.push(["quest", "Quest", `no app, conectar em ${S.base.quest_ip || "?"}:8765`]);
  steps.forEach(([key, title, sub], i) => {
    let cls = "";
    if (key === "img") { const c = S.checks.find((x) => x.key === "imgserver"); cls = c ? (c.ok ? "done" : "fail") : ""; }
    else if (key === "quest") cls = questConnected() ? "done" : (proc("bridge").state === "pronto" ? "cur" : "");
    else { const st = proc(key).state; cls = st === "pronto" ? "done" : st === "erro" ? "fail" : st === "iniciando" ? "cur" : ""; }
    if (ses.step === key && cls === "") cls = "cur";
    box.append(h("div", { class: `step ${cls}` }, h("div", { class: "step-n" }, cls === "done" ? "✓" : cls === "fail" ? "✕" : String(i + 1)),
      h("div", {}, h("div", { class: "step-t" }, title), h("div", { class: "small" }, sub))));
  });
  if (ses.error) box.append(h("div", { class: "warnbox" }, ses.error));
  const btn = $("btn-start-session");
  const blocked = anyRunning() || (real && !safetyOk()) || !S.base.quest_ip;
  btn.disabled = blocked;
  $("cfg-start-note").textContent = anyRunning() ? "Sessão em andamento." :
    (real && !safetyOk()) ? "Marque os itens de segurança para liberar." :
    !S.base.quest_ip ? "Escolha o IP do PC na rede do Quest." : "Cada processo também pode ser iniciado sozinho na tela de operação.";
}

async function startSession() {
  try {
    await api("/api/session/start", { base: S.base, overrides: S.overrides });
    S.showConfig = false;
    S.logTab = activeProcs()[0];
    renderAll();
  } catch (e) { toast(e.message); }
}

// ---------- operação ----------
function renderAll() {
  const live = (anyRunning() || (srv().session || {}).active) && !S.showConfig && sessionMode() !== "replay";
  $("config").classList.toggle("hidden", live);
  $("live").classList.toggle("hidden", !live);
  $("btn-back-live").classList.toggle("hidden", !(S.showConfig && anyRunning()));
  document.querySelectorAll("#mode-seg button").forEach((b) => {
    b.classList.toggle("on", b.dataset.mode === S.base.mode);
    b.classList.toggle("real", b.dataset.mode === "real");
    b.disabled = anyRunning();
  });
  renderTop();
  renderSteps();
  if (live) {
    renderProcs(); renderTeleop(); renderQuest(); renderVideo(); renderLogTabs();
    if (!S.wasLive) renderLogs(true);
  }
  S.wasLive = live;
  $("live-real-banner").classList.toggle("hidden", !isReal());
  $("real-checklist").classList.toggle("hidden", !isReal());
  if (S.view === "rec") renderReplayStatus();
}

function renderTop() {
  const b = S.base, preset = S.presets[b.preset] || {};
  const info = $("top-info");
  info.innerHTML = "";
  if (sessionMode() === "replay") info.append("Replay: ", h("b", {}, `${(srv().session.replay || {}).task || ""}/${(srv().session.replay || {}).episode || ""}`));
  else if (b.mode === "real") info.append("Robô: ", h("b", { class: "mono" }, b.robot_ip || "?"), " · ", h("b", { class: "mono" }, b.robot_iface || "sem interface"));
  else info.append("Tarefa: ", h("b", {}, preset.label || b.preset));
  const dots = $("top-dots");
  dots.innerHTML = "";
  const ipc = srv().teleop_ipc || {};
  const items = [];
  if (!isReal()) items.push(["Simulação", dotClass(proc("sim").state)]);
  else items.push(["Câmera do robô", (srv().video || {}).live ? "ok" : ""]);
  items.push(["Ponte", dotClass(proc("bridge").state)]);
  items.push([usbSelected() ? "Quest · cabo" : "Quest · Wi‑Fi",
    questConnected() ? "ok" : (usbSelected() && S.usb && !S.usb.active ? "err" : "")]);
  items.push([ipc.recording ? "Teleop · gravando" : ipc.start ? "Teleop · teleoperando" : "Teleop", ipc.recording ? "rec" : dotClass(proc("teleop").state)]);
  for (const [t, c] of items) dots.append(h("div", { class: "dotitem" }, h("span", { class: `dot ${c}` }), t));
}
function dotClass(st) { return st === "pronto" ? "ok" : (st === "iniciando" || st === "parando") ? "busy" : st === "erro" ? "err" : ""; }

function procSub(n) {
  const p = proc(n);
  const st = STATE_TEXT[p.state] || p.state;
  if (p.state === "erro") return `erro (código ${p.exit_code}) · veja o log`;
  if (p.state !== "pronto") return st + (p.uptime ? ` · ${fmtDur(p.uptime)}` : "");
  if (n === "sim") return `${S.base.headless ? "headless · " : ""}pronta · ${fmtDur(p.uptime)}`;
  if (n === "bridge") return questConnected() ? `Quest conectado${p.stats ? " · " + p.stats : ""}` : "aguardando o Quest";
  if (n === "teleop") {
    const ipc = srv().teleop_ipc || {};
    const link = (proc("bridge").flags || {}).teleop_link ? "" : " · sem ligação com a ponte";
    return (ipc.recording ? "gravando" : ipc.start ? "teleoperando" : "pronto · aguardando início") + link;
  }
  return st;
}

// Recria o conteúdo só quando `sig` muda (senão um clique pode cair num botão recriado)
function changed(el, sig) {
  const s = JSON.stringify(sig);
  if (el.dataset.sig === s) return false;
  el.dataset.sig = s;
  return true;
}

function renderProcs() {
  const box = $("proc-list");
  const img = S.checks.find((c) => c.key === "imgserver");
  const sig = [isReal(), activeProcs(), activeProcs().map((n) => proc(n).state), safetyOk(), !!(img && img.ok)];
  if (changed(box, sig)) {
    box.innerHTML = "";
    if (isReal()) {
      box.append(h("div", { class: "proc-row" }, h("span", { class: `dot ${img && img.ok ? "ok" : ""}`, id: "img-dot" }),
        h("div", { class: "grow" }, h("div", { class: "proc-name" }, "Servidor de imagens"), h("div", { class: "proc-sub", id: "img-sub" })),
        h("button", { class: "btn", style: "height:36px;font-size:13px", onclick: () => runChecks() }, "Testar")));
    }
    for (const n of activeProcs()) {
      const p = proc(n);
      const running = ["iniciando", "pronto", "parando"].includes(p.state);
      const gatedReal = isReal() && n === "teleop" && !safetyOk();
      const btns = running
        ? [h("button", { class: "icon-btn", title: "Reiniciar", "aria-label": `Reiniciar ${PROC_LABEL[n]}`, html: ICON.restart, onclick: () => procAction(n, "restart") }),
           h("button", { class: "icon-btn stop", title: "Parar", "aria-label": `Parar ${PROC_LABEL[n]}`, html: ICON.stop, onclick: () => procAction(n, "stop") })]
        : [h("button", { class: "icon-btn go", title: gatedReal ? "Marque os itens de segurança" : "Iniciar", disabled: gatedReal, "aria-label": `Iniciar ${PROC_LABEL[n]}`, html: ICON.play, onclick: () => procAction(n, "start") })];
      box.append(h("div", { class: "proc-row" }, h("span", { class: `dot ${dotClass(p.state)}` }),
        h("div", { class: "grow" }, h("div", { class: "proc-name" }, PROC_LABEL[n]), h("div", { class: "proc-sub", id: `sub-${n}` })), ...btns));
    }
  }
  // textos que mudam a todo momento (tempo, estatísticas) são atualizados no lugar
  if ($("img-sub")) $("img-sub").textContent = img ? img.text : "iniciado no robô";
  for (const n of activeProcs()) {
    const el = $(`sub-${n}`);
    if (el) { el.textContent = procSub(n); el.title = proc(n).command || ""; }
  }
}

async function procAction(n, action) {
  if (action === "stop" && n === "sim" && !confirm("Encerrar a simulação?")) return;
  try { await api(`/api/process/${n}/${action}`, { base: S.base, overrides: S.overrides }); }
  catch (e) { toast(e.message); }
}

function renderTeleop() {
  const box = $("teleop-controls");
  const ipc = srv().teleop_ipc || {};
  const recordOn = S.preview && S.preview.values.teleop.record;
  const sig = [ipc.online, ipc.start, ipc.recording, recordOn, questConnected(), safetyOk(), isReal(), proc("teleop").state];
  if (!changed(box, sig)) {
    const rb = $("btn-rec-toggle");
    if (rb && ipc.recording) rb.textContent = `Parar gravação · ${fmtDur(ipc.record_elapsed)}`;
    return;
  }
  box.innerHTML = "";
  if (!ipc.online) {
    box.append(h("button", { class: "btn btn-big", disabled: true }, proc("teleop").state === "iniciando" ? "Teleop iniciando…" : "Teleop não está rodando"));
    return;
  }
  const v = S.preview && S.preview.values.teleop;
  const aNote = v && v.motion && v.input_mode === "controller" ? " O botão A do controle direito também encerra." : "";
  if (!ipc.start) {
    const blocked = (!questConnected() && !isReal()) || (isReal() && (!safetyOk() || !questConnected()));
    box.append(h("button", { class: "btn-primary", disabled: blocked, onclick: () => teleopCmd("start") }, "Iniciar teleoperação (R)"));
    box.append(h("div", { class: "small" }, !questConnected() ? "Conecte o Quest primeiro: o robô seguiria poses paradas." :
      (isReal() && !safetyOk()) ? "Marque os itens de segurança." : "Deixe os braços em posição neutra antes de iniciar."));
  } else {
    box.append(h("div", { class: "btn-live" }, h("span", { class: "dot ok" }), "Teleoperando"));
    if (recordOn) {
      box.append(ipc.recording
        ? h("button", { class: "btn-rec", id: "btn-rec-toggle", onclick: () => teleopCmd("record") }, `Parar gravação · ${fmtDur(ipc.record_elapsed)}`)
        : h("button", { class: "btn btn-big", onclick: () => teleopCmd("record") }, "Gravar episódio (S)"));
    }
    if (aNote) box.append(h("div", { class: "small" }, "Botão A do controle direito encerra a teleoperação."));
  }
  box.append(h("button", { class: "btn btn-quiet", title: "Fecha o processo do teleop." + aNote,
    onclick: () => { if (confirm("Encerrar a teleoperação? O processo do teleop vai fechar." + aNote)) teleopCmd("stop"); } }, "Encerrar teleop (Q)"));
}

// Atalhos R / S / Q (como no terminal), com as mesmas regras dos botões
function onKey(ev) {
  if (ev.repeat || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const t = ev.target;
  // só campos de digitação bloqueiam os atalhos (checkboxes e botões não)
  const typing = t && (t.isContentEditable || ["SELECT", "TEXTAREA"].includes(t.tagName) ||
    (t.tagName === "INPUT" && ["text", "search", "number", ""].includes(t.type)));
  if (typing) return;
  if (S.view !== "op" || $("live").classList.contains("hidden")) return;
  const key = ev.key.toLowerCase();
  if (!["r", "s", "q"].includes(key)) return;
  const ipc = srv().teleop_ipc || {};
  if (!ipc.online) return;
  ev.preventDefault();
  if (key === "r" && !ipc.start) {
    if (!questConnected()) { toast("Conecte o Quest antes de iniciar a teleoperação."); return; }
    if (isReal() && !safetyOk()) { toast("Marque os itens de segurança antes de iniciar."); return; }
    teleopCmd("start");
  } else if (key === "s" && ipc.start && S.preview && S.preview.values.teleop.record) {
    teleopCmd("record");
  } else if (key === "q") {
    if (confirm("Encerrar a teleoperação? O processo do teleop vai fechar.")) teleopCmd("stop");
  }
}

async function teleopCmd(cmd) {
  try { const r = await api(`/api/teleop/${cmd}`, {}); if (r.status !== "ok") toast(r.msg); }
  catch (e) { toast(e.message); }
}

function renderQuest() {
  const box = $("quest-info");
  box.innerHTML = "";
  const f = proc("bridge").flags || {};
  // estatísticas de mensagens aparecem no subtítulo da ponte; ligação ponte→teleop no do teleop
  const u = S.usb || {};
  const via = usbSelected()
    ? (u.active ? h("span", { class: "okt" }, "cabo USB") : h("span", { class: "badt" }, "cabo USB — inativo!"))
    : "Wi‑Fi";
  const rows = [
    ["Endereço no app", h("span", { class: "mono" }, `${S.base.quest_ip || "?"}:8765`)],
    ["Caminho", via],
    ["Estado", f.quest_connected ? h("span", { class: "okt" }, "conectado") : f.quest_signaling ? "negociando…" : "aguardando o app"],
  ];
  for (const [k, v] of rows) box.append(h("div", { class: "kv" }, h("span", {}, k), h("span", {}, v)));
}

function renderVideo() {
  const v = srv().video || {};
  const key = `${v.host}:${v.port}`;
  if (v.host && S.videoKey !== key) { S.videoKey = key; openVideo(v); }
  // o servidor tem quadros mas nenhum cliente de vídeo: este navegador perdeu o stream
  if (v.live && v.clients === 0 && S.videoKey === key && !S.videoRetry) {
    S.videoRetry = setTimeout(() => { S.videoRetry = null; if ((srv().video || {}).clients === 0) openVideo(srv().video); }, 2000);
  }
  $("video-overlay").classList.toggle("hidden", !!v.live);
  $("video-info").textContent = v.host ? `câmera da cabeça · ZMQ ${v.host}:${v.port}` : "";
  $("video-box").classList.toggle("mono", S.videoMode === "mono");
  document.querySelectorAll("#video-seg button").forEach((b) => b.classList.toggle("on", b.dataset.v === S.videoMode));
  const ipc = srv().teleop_ipc || {};
  $("rec-badge").classList.toggle("hidden", !ipc.recording);
  $("rec-badge-text").textContent = `REC · ${fmtDur(ipc.record_elapsed)}`;
}

// ---------- logs ----------
function logSources() {
  const list = [["teleop", "Teleop"]];
  list.push(isReal() ? ["robot", "Robô"] : ["sim", "Simulação"]);
  list.push(["bridge", "Ponte"]);
  return list;
}
function logEntries(p) { return p === "robot" ? S.robotLog : S.logs[p] || []; }

function renderLogTabs() {
  const box = $("log-tabs");
  const sources = logSources();
  if (!sources.some(([k]) => k === S.logTab)) S.logTab = sources[0][0];
  const sig = [sources, S.logTab, sources.map(([k]) => [(srv().procs[k] || {}).warn, (srv().procs[k] || {}).error])];
  if (!changed(box, sig)) return;
  box.innerHTML = "";
  for (const [k, t] of sources) {
    const p = srv().procs[k] || {};
    const b = h("button", { class: `ltab ${k === S.logTab ? "active" : ""}`, onclick: () => { S.logTab = k; renderLogTabs(); renderLogs(true); } }, t);
    if (p.error) b.append(h("span", { class: "badge e" }, p.error));
    else if (p.warn) b.append(h("span", { class: "badge w" }, p.warn));
    box.append(b);
  }
}

function logNode(e) {
  return h("div", { class: `le ${e.level}`, "data-id": e.id },
    h("span", { class: "ts" }, fmtClock(e.ts)), h("span", { class: "tx" }, e.text),
    e.count > 1 ? h("span", { class: "cnt" }, `×${e.count}`) : null);
}
let logRendered = null;
function renderLogs(full) {
  const body = $("log-body");
  const entries = logEntries(S.logTab).filter((e) => S.levels[e.level]);
  if (full || logRendered !== S.logTab) {
    body.innerHTML = "";
    entries.slice(-1500).forEach((e) => body.append(logNode(e)));
    logRendered = S.logTab;
  }
  if ($("log-follow").checked) body.scrollTop = body.scrollHeight;
}
function onLog(p, entry, isNew) {
  const arr = S.logs[p];
  if (isNew) { arr.push(entry); if (arr.length > 3000) arr.shift(); }
  else { const i = arr.findIndex((e) => e.id === entry.id); if (i >= 0) arr[i] = entry; else arr.push(entry); }
  if (p === S.logTab && !$("live").classList.contains("hidden")) {
    const body = $("log-body");
    const existing = body.querySelector(`[data-id="${entry.id}"]`);
    if (!S.levels[entry.level]) { if (existing) existing.remove(); return; }
    if (existing) existing.replaceWith(logNode(entry)); else body.append(logNode(entry));
    while (body.childElementCount > 1500) body.firstElementChild.remove();
    if ($("log-follow").checked) body.scrollTop = body.scrollHeight;
  }
  if (p === "sim" && S.view === "rec") renderReplayLog();
}

function tick() {
  if (!$("live").classList.contains("hidden")) { renderProcs(); renderTeleop(); renderVideo(); }
}

// ---------- gravações ----------
async function loadRecordings() {
  try {
    const r = await api("/api/recordings");
    S.rec.list = r.episodes;
    renderRecList();
  } catch (e) { $("rec-list").textContent = "Falha ao listar: " + e.message; }
}

function renderRecList() {
  const box = $("rec-list");
  const q = $("rec-filter").value.trim().toLowerCase();
  box.innerHTML = "";
  const groups = {};
  S.rec.list.filter((e) => !q || `${e.task}/${e.episode}`.toLowerCase().includes(q)).forEach((e) => (groups[e.task] = groups[e.task] || []).push(e));
  if (!Object.keys(groups).length) { box.append(h("div", { class: "small", style: "padding:16px" }, "Nenhum episódio em teleop/utils/data.")); return; }
  for (const [task, eps] of Object.entries(groups)) {
    box.append(h("div", { class: "rec-group" }, task));
    for (const e of eps) {
      const sel = S.rec.sel && S.rec.sel.task === e.task && S.rec.sel.episode === e.episode;
      const m = e.meta;
      const sub = m ? `${fmtDur(m.duration)} · ${m.frames} quadros · ${new Date(e.mtime * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}`
        : `${e.size_mb} MB · ${new Date(e.mtime * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}`;
      box.append(h("button", { class: `rec-item ${sel ? "sel" : ""}`, onclick: () => openEpisode(e.task, e.episode) },
        h("span", { class: "n" }, e.episode), h("span", { class: "small" }, sub)));
    }
  }
}

async function openEpisode(task, episode) {
  S.rec.sel = { task, episode };
  S.rec.playing = false;
  renderRecList();
  $("rec-empty").textContent = "Carregando episódio…";
  $("rec-empty").classList.remove("hidden");
  $("rec-head").classList.add("hidden");
  $("rec-body").classList.add("hidden");
  try {
    S.rec.data = await api(`/api/recordings/${encodeURIComponent(task)}/${encodeURIComponent(episode)}/series`);
  } catch (e) { $("rec-empty").textContent = "Falha ao abrir: " + e.message; return; }
  const m = S.rec.data.meta;
  const item = S.rec.list.find((e) => e.task === task && e.episode === episode);
  if (item) { item.meta = m; renderRecList(); }
  $("rec-empty").classList.add("hidden");
  $("rec-head").classList.remove("hidden");
  $("rec-body").classList.remove("hidden");
  $("rec-title").textContent = `${task} / ${episode}`;
  $("rec-sub").textContent = `${m.task_name || "tarefa desconhecida"} · ${fmtDur(m.duration)} · ${m.frames} quadros · ${m.fps} Hz`;
  $("pl-img1").classList.toggle("hidden", m.cameras.length < 2);
  $("pl-slider").max = Math.max(0, m.frames - 1);
  setupCharts();
  seekIndex(0);
  renderReplayStatus();
}

const recFps = () => (S.rec.data ? S.rec.data.meta.fps : 30);

function setupCharts() {
  const d = S.rec.data, s = d.series;
  if (!S.rec.charts) {
    S.rec.charts = {
      left: new LineChart($("ch-left")), right: new LineChart($("ch-right")),
      vel: new LineChart($("ch-vel")), traj: new TrajectoryChart($("ch-traj")),
    };
    for (const k of ["left", "right", "vel"]) S.rec.charts[k].onSeek = (t) => seekIndex(Math.round(t * recFps()));
  }
  const arm = (state, action) => {
    const out = [];
    for (let j = 0; j < 7; j++) {
      out.push({ values: state.map((q) => q[j]), color: JOINT_COLORS[j], width: 1.7 });
      out.push({ values: action.map((q) => q[j]), color: JOINT_COLORS[j], width: 1, dash: [3, 3] });
    }
    return out;
  };
  S.rec.charts.left.setData(s.t, arm(s.left_state, s.left_action));
  S.rec.charts.right.setData(s.t, arm(s.right_state, s.right_action));
  S.rec.charts.vel.setData(s.t, [
    { values: s.vx, color: "#43C08A", width: 1.6 }, { values: s.vy, color: "#6AA8E8", width: 1.6 }, { values: s.wz, color: "#F0A83A", width: 1.6 }]);
  S.rec.charts.traj.setData(s.base_x, s.base_y, s.base_yaw, d.objects);
  const jl = (id) => { const el = $(id); el.innerHTML = ""; JOINT_SHORT.forEach((n, j) => el.append(h("span", {}, h("i", { style: `background:${JOINT_COLORS[j]}` }), n))); el.append(h("span", {}, "— estado · - - comando")); };
  jl("lg-left"); jl("lg-right");
  const lv = $("lg-vel"); lv.innerHTML = "";
  [["#43C08A", "frente (m/s)"], ["#6AA8E8", "lado (m/s)"], ["#F0A83A", "giro (rad/s)"]].forEach(([c, t]) => lv.append(h("span", {}, h("i", { style: `background:${c}` }), t)));
  const lt = $("lg-traj"); lt.innerHTML = "";
  lt.append(h("span", {}, h("i", { style: "background:#6AA8E8" }), "base"), h("span", {}, "□ início · ■ fim dos blocos"));
}

function drawCharts() { if (!S.rec.charts) return; for (const c of Object.values(S.rec.charts)) c.draw(); }

function seekIndex(i) {
  if (!S.rec.data) return;
  const n = S.rec.data.meta.frames;
  i = Math.max(0, Math.min(n - 1, Math.round(i)));
  S.rec.index = i;
  $("pl-slider").value = i;
  const t = i / recFps();
  $("pl-time").textContent = `${fmtTime(t)} · quadro ${i}`;
  const base = `/api/recordings/${encodeURIComponent(S.rec.sel.task)}/${encodeURIComponent(S.rec.sel.episode)}/frame/${i}`;
  setFrame($("pl-img0"), `${base}/0.jpg`);
  if (S.rec.data.meta.cameras.length > 1) setFrame($("pl-img1"), `${base}/1.jpg`);
  const c = S.rec.charts;
  c.left.setCursor(t); c.right.setCursor(t); c.vel.setCursor(t);
  const si = S.rec.data.series.i;
  let k = si.findIndex((x) => x >= i); if (k < 0) k = si.length - 1;
  c.traj.setIndex(k);
}

// só troca a imagem quando a anterior terminou de carregar (evita fila no play)
function setFrame(img, url) {
  if (img.dataset.loading === "1") { img.dataset.next = url; return; }
  img.dataset.loading = "1";
  img.onload = img.onerror = () => {
    img.dataset.loading = "0";
    if (img.dataset.next) { const n = img.dataset.next; img.dataset.next = ""; setFrame(img, n); }
  };
  img.src = url;
}

function togglePlay() {
  S.rec.playing = !S.rec.playing;
  $("pl-play").innerHTML = S.rec.playing ? ICON.pause : ICON.play;
  if (S.rec.playing) {
    let last = performance.now(), acc = S.rec.index;
    const step = (now) => {
      if (!S.rec.playing) return;
      acc += ((now - last) / 1000) * recFps() * +$("pl-speed").value;
      last = now;
      if (acc >= S.rec.data.meta.frames - 1) { seekIndex(S.rec.data.meta.frames - 1); togglePlay(); return; }
      if (Math.floor(acc) !== S.rec.index) seekIndex(Math.floor(acc));
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

async function startReplay() {
  if (!S.rec.sel) return;
  const window_ = $("replay-window").checked;
  if (!window_ && !confirm("Sem a janela do Isaac o replay roda sem imagem visível. Continuar?")) return;
  try { await api("/api/replay", Object.assign({ window: window_ }, S.rec.sel)); }
  catch (e) { toast(e.message); }
}

function renderReplayStatus() {
  const ses = srv().session || {};
  const rp = ses.mode === "replay" ? ses.replay : null;
  const sim = proc("sim");
  const running = rp && ["iniciando", "pronto", "parando"].includes(sim.state);
  $("btn-replay").classList.toggle("hidden", !!running);
  $("btn-replay").disabled = anyRunning();
  $("btn-replay-stop").classList.toggle("hidden", !running);
  const st = $("replay-status");
  if (running) {
    const replaying = (sim.flags || {}).replay;
    const el = replaying ? Math.max(0, Date.now() / 1000 - replaying) : 0;
    // a simulação reproduz um quadro por ciclo e costuma rodar abaixo dos 30 Hz da gravação,
    // então o replay leva mais tempo que o episódio original
    st.textContent = sim.state === "iniciando" ? "Carregando a simulação para o replay…" :
      replaying ? `Replay de ${rp.task}/${rp.episode} em andamento · ${fmtDur(el)} decorridos · episódio de ${fmtDur(rp.duration)}${sim.stats ? "" : ""}` : "Simulação pronta, iniciando o replay…";
  } else st.textContent = anyRunning() ? "Encerre a sessão de teleoperação para fazer o replay." : "";
  $("replay-log").classList.toggle("hidden", !rp);
  renderReplayLog();
}

function renderReplayLog() {
  const box = $("replay-log");
  if (box.classList.contains("hidden")) return;
  box.innerHTML = "";
  (S.logs.sim || []).filter((e) => e.level !== "debug").slice(-40).forEach((e) => box.append(h("div", {}, `${fmtClock(e.ts)}  ${e.text}`)));
  box.scrollTop = box.scrollHeight;
}

init().catch((e) => { document.body.prepend(h("div", { class: "warnbox" }, "Falha ao iniciar a interface: " + e.message)); });
