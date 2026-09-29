// Gráficos em canvas, sem dependências (a interface precisa funcionar sem internet).
"use strict";

const JOINT_COLORS = ["#6AA8E8", "#F0A83A", "#A98BE0", "#43C08A", "#EF7B6B", "#4FC1C9", "#D7C45A"];

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

// series: [{values:[...], color, dash, width}], x: [...] (tempo), cursor: valor de x
class LineChart {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.opts = opts;
    this.x = [];
    this.series = [];
    this.cursor = null;
    this.onSeek = null;
    canvas.addEventListener("click", (ev) => {
      if (!this.onSeek || !this.x.length) return;
      const r = canvas.getBoundingClientRect();
      const px = ev.clientX - r.left;
      const { left, right } = this._pad();
      const frac = Math.min(1, Math.max(0, (px - left) / (r.width - left - right)));
      this.onSeek(this.x[0] + frac * (this.x[this.x.length - 1] - this.x[0]));
    });
  }
  _pad() { return { left: 44, right: 8, top: 6, bottom: 20 }; }
  setData(x, series) {
    this.x = x;
    this.series = series;
    let lo = Infinity, hi = -Infinity;
    for (const s of series) for (const v of s.values) if (v != null && isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (!isFinite(lo)) { lo = -1; hi = 1; }
    if (hi - lo < 1e-6) { lo -= 0.5; hi += 0.5; }
    const m = (hi - lo) * 0.08;
    this.lo = lo - m; this.hi = hi + m;
    this.draw();
  }
  setCursor(t) { this.cursor = t; this.draw(); }
  draw() {
    const { ctx, w, h } = setupCanvas(this.canvas);
    const p = this._pad();
    const pw = w - p.left - p.right, ph = h - p.top - p.bottom;
    if (!this.x.length || pw <= 0 || ph <= 0) return;
    const x0 = this.x[0], x1 = this.x[this.x.length - 1] || 1;
    const X = (t) => p.left + ((t - x0) / (x1 - x0 || 1)) * pw;
    const Y = (v) => p.top + (1 - (v - this.lo) / (this.hi - this.lo)) * ph;

    ctx.font = "11px 'Noto Sans Mono', 'DejaVu Sans Mono', monospace";
    ctx.fillStyle = "#6B727C";
    ctx.strokeStyle = "#2B3038";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const v = this.lo + (i / 4) * (this.hi - this.lo);
      const y = Y(v);
      ctx.beginPath(); ctx.moveTo(p.left, y); ctx.lineTo(w - p.right, y); ctx.stroke();
      ctx.fillText(v.toFixed(Math.abs(this.hi - this.lo) < 2 ? 2 : 1), 2, y + 4);
    }
    const ticks = 6;
    for (let i = 0; i <= ticks; i++) {
      const t = x0 + (i / ticks) * (x1 - x0);
      ctx.fillText(fmtTime(t, true), Math.min(X(t) - 12, w - 40), h - 4);
    }
    if (this.lo < 0 && this.hi > 0) {
      ctx.strokeStyle = "#3A414B";
      ctx.beginPath(); ctx.moveTo(p.left, Y(0)); ctx.lineTo(w - p.right, Y(0)); ctx.stroke();
    }
    for (const s of this.series) {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width || 1.6;
      ctx.setLineDash(s.dash || []);
      ctx.beginPath();
      let pen = false;
      for (let i = 0; i < this.x.length; i++) {
        const v = s.values[i];
        if (v == null || !isFinite(v)) { pen = false; continue; }
        const px = X(this.x[i]), py = Y(v);
        if (pen) ctx.lineTo(px, py); else { ctx.moveTo(px, py); pen = true; }
      }
      ctx.stroke();
    }
    ctx.setLineDash([]);
    if (this.cursor != null) {
      ctx.strokeStyle = "#ECEAE4";
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(X(this.cursor), p.top); ctx.lineTo(X(this.cursor), h - p.bottom); ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}

// Mapa visto de cima: trajetória da base, objetos (início vazado, fim cheio), posição atual
class TrajectoryChart {
  constructor(canvas) {
    this.canvas = canvas;
    this.xs = []; this.ys = []; this.yaw = []; this.objects = {};
    this.idx = 0;
  }
  setData(xs, ys, yaw, objects) {
    this.xs = xs; this.ys = ys; this.yaw = yaw; this.objects = objects || {};
    const all = [];
    xs.forEach((x, i) => { if (x != null) all.push([x, ys[i]]); });
    for (const o of Object.values(this.objects)) { if (o.start) all.push(o.start); if (o.end) all.push(o.end); }
    if (!all.length) { this.bounds = null; this.draw(); return; }
    let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
    for (const [x, y] of all) { minx = Math.min(minx, x); maxx = Math.max(maxx, x); miny = Math.min(miny, y); maxy = Math.max(maxy, y); }
    const m = 0.4;
    this.bounds = { minx: minx - m, maxx: maxx + m, miny: miny - m, maxy: maxy + m };
    this.draw();
  }
  setIndex(i) { this.idx = i; this.draw(); }
  draw() {
    const { ctx, w, h } = setupCanvas(this.canvas);
    if (!this.bounds) {
      ctx.fillStyle = "#6B727C"; ctx.font = "13px sans-serif";
      ctx.fillText("Sem estado da simulação neste episódio", 12, 24);
      return;
    }
    const b = this.bounds;
    const sx = (w - 20) / (b.maxx - b.minx), sy = (h - 20) / (b.maxy - b.miny);
    const s = Math.min(sx, sy);
    const ox = (w - (b.maxx - b.minx) * s) / 2, oy = (h - (b.maxy - b.miny) * s) / 2;
    // x do mundo para a direita, y do mundo para cima
    const P = (x, y) => [ox + (x - b.minx) * s, h - (oy + (y - b.miny) * s)];

    ctx.strokeStyle = "#2B3038"; ctx.lineWidth = 1;
    const step = niceStep((b.maxx - b.minx) / 6);
    for (let gx = Math.ceil(b.minx / step) * step; gx <= b.maxx; gx += step) {
      const [px] = P(gx, 0); ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, h); ctx.stroke();
    }
    for (let gy = Math.ceil(b.miny / step) * step; gy <= b.maxy; gy += step) {
      const [, py] = P(0, gy); ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(w, py); ctx.stroke();
    }
    ctx.fillStyle = "#6B727C"; ctx.font = "11px sans-serif";
    ctx.fillText(`grade ${step} m`, 8, h - 8);

    ctx.strokeStyle = "#6AA8E8"; ctx.lineWidth = 2; ctx.beginPath();
    let pen = false;
    this.xs.forEach((x, i) => {
      if (x == null) { pen = false; return; }
      const [px, py] = P(x, this.ys[i]);
      if (pen) ctx.lineTo(px, py); else { ctx.moveTo(px, py); pen = true; }
    });
    ctx.stroke();

    const colors = { red: "#EF5B52", green: "#43C08A", yellow: "#D7C45A" };
    for (const [name, o] of Object.entries(this.objects)) {
      const key = Object.keys(colors).find((k) => name.includes(k));
      const c = colors[key] || "#A3A9B1";
      if (o.start) { const [px, py] = P(...o.start); ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.strokeRect(px - 6, py - 6, 12, 12); }
      if (o.end) { const [px, py] = P(...o.end); ctx.fillStyle = c; ctx.fillRect(px - 6, py - 6, 12, 12); }
    }

    const i = Math.min(this.idx, this.xs.length - 1);
    if (i >= 0 && this.xs[i] != null) {
      const [px, py] = P(this.xs[i], this.ys[i]);
      const a = this.yaw[i] || 0;
      ctx.fillStyle = "#F0A83A";
      ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#F0A83A"; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + Math.cos(a) * 20, py - Math.sin(a) * 20); ctx.stroke();
    }
  }
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p;
}

function fmtTime(sec, short) {
  sec = Math.max(0, sec || 0);
  const m = Math.floor(sec / 60), s = sec - m * 60;
  return short ? `${m}:${String(Math.floor(s)).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}
