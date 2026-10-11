/* Q-TERMINAL frontend — vanilla JS, zero deps. Flat Bloomberg style. */
"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  assets: [], cov: [], tickers: ["AAPL","MSFT","GOOGL","AMZN","NVDA","TSLA","JPM","JNJ"],
  algo: "qaoa", last: null, backend: "...", base: {}, classicalEnergy: null,
  source: "mock", datasetId: null, tour: null,
};
const CYAN = "#00e5ff", RED = "#ff2d40", PURPLE = "#c26bff",
      GREY = "#9a9a9a", GREEN = "#35d07f", AMBER = "#ff9e00";

/* ---------------- clock + tabs ---------------- */
setInterval(() => { $("clock").textContent = new Date().toLocaleTimeString(); }, 1000);
$("tabs").addEventListener("click", (e) => {
  const t = e.target.closest(".tab"); if (!t) return;
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tabview").forEach(v => v.classList.toggle("active", v.id === "v-" + t.dataset.tab));
});
function goTab(name) { document.querySelector('.tab[data-tab="' + name + '"]').click(); }

/* ---------------- collapse + drag reorder ---------------- */
document.addEventListener("click", (e) => {
  const x = e.target.closest("[data-collapse]"); if (!x) return;
  const p = x.closest(".panel"); p.classList.toggle("collapsed");
  x.textContent = p.classList.contains("collapsed") ? "+" : "–";
});
let dragPid = null;
document.addEventListener("dragstart", (e) => {
  const h = e.target.closest("h2"); const p = e.target.closest(".panel");
  if (!h || !p) { e.preventDefault(); return; }
  dragPid = p.dataset.pid; p.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
});
document.addEventListener("dragend", () => {
  dragPid = null;
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("dragging", "dragover"));
});
document.addEventListener("dragover", (e) => {
  const p = e.target.closest(".panel");
  if (p && dragPid && p.dataset.pid !== dragPid && p.parentElement.querySelector(`[data-pid="${dragPid}"]`)) {
    e.preventDefault(); p.classList.add("dragover");
  }
});
document.addEventListener("dragleave", (e) => {
  const p = e.target.closest(".panel"); if (p) p.classList.remove("dragover");
});
document.addEventListener("drop", (e) => {
  const p = e.target.closest(".panel"); if (!p || !dragPid) return;
  e.preventDefault();
  const src = p.parentElement.querySelector(`[data-pid="${dragPid}"]`);
  if (src && src !== p) p.parentElement.insertBefore(src, p);
  document.querySelectorAll(".panel").forEach(x => x.classList.remove("dragover"));
});
document.addEventListener("mouseover", (e) => {
  const h = e.target.closest(".panel > h2"); if (h) h.parentElement.setAttribute("draggable", "true");
});

/* ---------------- controls ---------------- */
function bindSlider(id, out, fmt) {
  const s = $(id);
  const upd = () => { $(out).textContent = fmt(parseFloat(s.value)); };
  s.addEventListener("input", upd); upd();
}
bindSlider("kSlider", "kVal", v => "" + v);
bindSlider("qSlider", "qVal", v => v.toFixed(2));
bindSlider("pSlider", "pVal", v => "" + v);
$("shotsSel").addEventListener("change", e => $("sVal").textContent = e.target.value);
$("algoGrid").addEventListener("click", (e) => {
  const c = e.target.closest(".algo"); if (!c) return;
  state.algo = c.dataset.algo;
  document.querySelectorAll(".algo").forEach(x => x.classList.remove("sel"));
  c.classList.add("sel");
});

/* ---------------- canvas helper (flat, no glow) ---------------- */
function ctx2d(cv) {
  const dpr = window.devicePixelRatio || 1;
  const r = cv.getBoundingClientRect();
  const W = Math.max(300, r.width), H = parseFloat(getComputedStyle(cv).height) || 260;
  cv.width = W * dpr; cv.height = H * dpr;
  const c = cv.getContext("2d"); c.scale(dpr, dpr);
  c.clearRect(0, 0, W, H);
  return { c, W, H };
}
function axes(c, W, H, pad) {
  c.strokeStyle = "#2b2b2b"; c.fillStyle = "#636363";
  c.font = "10px 'JetBrains Mono', monospace"; c.lineWidth = 1;
  c.strokeRect(pad.l, pad.t, W - pad.l - pad.r, H - pad.t - pad.b);
}
window.addEventListener("resize", () => {
  if (state.assets.length) renderSetup();
  if (state.last) renderAll(state.last);
});

/* ---------------- universe + live mock feed ---------------- */
function fmtChg(v) { return (v >= 0 ? "+" : "") + v.toFixed(2) + "%"; }
async function loadUniverse() {
  const j = await (await fetch("/api/universe")).json();
  state.assets = j.assets; state.cov = j.cov;
  state.assets.forEach(a => { state.base[a.ticker] = a.last; });
  const tb = $("assetBody"); tb.innerHTML = "";
  const pre = new Set(state.tickers);
  for (const a of state.assets) {
    const tr = document.createElement("tr");
    if (pre.has(a.ticker)) tr.classList.add("sel");
    tr.innerHTML = `<td><input type="checkbox" ${pre.has(a.ticker) ? "checked" : ""} data-t="${a.ticker}"></td>
      <td><b>${a.ticker}</b> <span style="color:var(--dim);font-size:10px">${a.name}</span></td>
      <td class="n" data-c="last" data-t="${a.ticker}">${a.last.toFixed(2)}</td>
      <td class="n ${a.chg_pct >= 0 ? "pos" : "neg"}" data-c="chg" data-t="${a.ticker}">${fmtChg(a.chg_pct)}</td>
      <td class="n">${a.beta.toFixed(2)}</td>
      <td class="n">${(a.sigma * 100).toFixed(0)}%</td>`;
    tb.appendChild(tr);
  }
  tb.addEventListener("change", (e) => {
    const cb = e.target.closest("input[type=checkbox]"); if (!cb) return;
    const t = cb.dataset.t;
    if (cb.checked && !state.tickers.includes(t)) state.tickers.push(t);
    if (!cb.checked) state.tickers = state.tickers.filter(x => x !== t);
    cb.closest("tr").classList.toggle("sel", cb.checked);
    state.tickers.sort((a, b) => state.assets.findIndex(x => x.ticker === a) - state.assets.findIndex(x => x.ticker === b));
    syncKSlider(); renderSetup();
  });
  try {
    const hj = await (await fetch("/api/health")).json();
    state.backend = hj.qiskit ? "QISKIT AER" : "NUMPY FALLBACK";
  } catch { state.backend = "OFFLINE?"; }
  $("backendPill").textContent = "BACKEND · " + state.backend;
  buildTape(); syncKSlider(); renderSetup();
  setInterval(tickFeed, 2000);
}
function syncKSlider() {
  const k = $("kSlider");
  k.max = Math.max(2, Math.min(state.tickers.length, 9));
  if (parseInt(k.value) > parseInt(k.max)) k.value = k.max;
  $("kVal").textContent = k.value;
}
function buildTape() {
  $("tape").innerHTML = state.assets.map(a =>
    `<span><span class="tk">${a.ticker}</span> <span data-tc="last" data-t="${a.ticker}">${a.last.toFixed(2)}</span> ` +
    `<span class="${a.chg_pct >= 0 ? "up" : "dn"}" data-tc="chg" data-t="${a.ticker}">${fmtChg(a.chg_pct)}</span></span>&nbsp;&nbsp;//&nbsp;&nbsp;`).join("");
}
function tickFeed() {
  if (!state.assets.length) return;
  state.assets.forEach(a => {
    a.last *= (1 + (Math.random() - 0.5) * 0.003);
    a.chg_pct = (a.last - state.base[a.ticker]) / state.base[a.ticker] * 100;
    document.querySelectorAll(`[data-c="last"][data-t="${a.ticker}"]`).forEach(el => el.textContent = a.last.toFixed(2));
    document.querySelectorAll(`[data-c="chg"][data-t="${a.ticker}"]`).forEach(el => {
      el.textContent = fmtChg(a.chg_pct);
      el.classList.toggle("pos", a.chg_pct >= 0); el.classList.toggle("neg", a.chg_pct < 0);
    });
    document.querySelectorAll(`[data-tc="last"][data-t="${a.ticker}"]`).forEach(el => el.textContent = a.last.toFixed(2));
    document.querySelectorAll(`[data-tc="chg"][data-t="${a.ticker}"]`).forEach(el => {
      el.textContent = fmtChg(a.chg_pct); el.className = a.chg_pct >= 0 ? "up" : "dn";
    });
  });
}
function subCov() {
  const idx = state.tickers.map(t => state.assets.findIndex(a => a.ticker === t));
  return idx.map(i => idx.map(j => state.cov[i][j]));
}
function comb(n, k) { k = Math.min(k, n - k); let r = 1; for (let i = 0; i < k; i++) r = r * (n - i) / (i + 1); return Math.round(r); }
function renderSetup() {
  $("selChips").innerHTML = state.assets.map(a =>
    `<span class="chip ${state.tickers.includes(a.ticker) ? "on" : ""}">${a.ticker}</span>`).join("");
  const C = subCov(), n = C.length, tk = state.tickers;
  const g = ctx2d($("heatChart"));
  const corr = C.map((row, i) => row.map((v, j) => v / Math.sqrt(C[i][i] * C[j][j])));
  const pad = 56, cw = (g.W - pad - 8) / n, ch = (g.H - 32) / n;
  g.c.font = "10px 'JetBrains Mono', monospace";
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const v = corr[i][j];
    g.c.fillStyle = v >= 0 ? `rgba(255,45,64,${(0.12 + 0.88 * v).toFixed(2)})` : `rgba(0,229,255,${(0.12 + 0.88 * -v).toFixed(2)})`;
    g.c.fillRect(pad + j * cw, 4 + i * ch, cw - 1, ch - 1);
    if (cw >= 30 && ch >= 15) {
      g.c.fillStyle = Math.abs(v) > 0.55 ? "#000" : "#c9c9c9";
      g.c.fillText(v.toFixed(2), pad + j * cw + Math.max(cw / 2 - 13, 2), 4 + i * ch + ch / 2 + 3);
    }
  }
  g.c.fillStyle = "#9a9a9a";
  tk.forEach((t, i) => { g.c.fillText(t, 4, 12 + i * ch); g.c.fillText(t.slice(0, 4), pad + i * cw, g.H - 8); });
  const u = ctx2d($("uniChart"));
  const sel = state.assets.filter(a => state.tickers.includes(a.ticker));
  const xs = sel.map(a => a.sigma * 100), ys = sel.map(a => a.mu * 100);
  const x0 = Math.min(...xs) - 3, x1 = Math.max(...xs) + 3, y0 = Math.min(...ys) - 3, y1 = Math.max(...ys) + 3;
  axes(u.c, u.W, u.H, { l: 38, t: 10, r: 10, b: 24 });
  const X = v => 38 + (v - x0) / (x1 - x0) * (u.W - 48), Y = v => 10 + (1 - (v - y0) / (y1 - y0)) * (u.H - 34);
  u.c.fillStyle = "#636363";
  for (let k = 0; k <= 4; k++) {
    const xv = x0 + (x1 - x0) * k / 4; u.c.fillText(xv.toFixed(0) + "%", X(xv) - 8, u.H - 8);
    const yv = y0 + (y1 - y0) * k / 4; u.c.fillText(yv.toFixed(0) + "%", 2, Y(yv) + 3);
  }
  for (const a of sel) {
    u.c.strokeStyle = CYAN; u.c.lineWidth = 1.5;
    u.c.strokeRect(X(a.sigma * 100) - 3, Y(a.mu * 100) - 3, 6 + a.beta * 3, 6 + a.beta * 3);
    u.c.fillStyle = "#fff"; u.c.fillText(a.ticker, X(a.sigma * 100) + 10 + a.beta * 3, Y(a.mu * 100) + 3);
  }
  u.c.fillStyle = "#636363"; u.c.fillText("VOL ->", u.W - 52, u.H - 8);
  const k = parseInt($("kSlider").value);
  $("basketExplain").innerHTML = `Universe <b>${state.tickers.length}</b> -> hold <b>${k}</b> = <b>${comb(state.tickers.length, k).toLocaleString()}</b> portfolios. Quantum explores all at once.`;
  $("basketHold").innerHTML = sel.map(a =>
    `<div class="hold"><b>${a.ticker}</b><small>${a.name} · BE ${a.beta.toFixed(2)}</small><small>MU ${(a.mu*100).toFixed(1)}% · SD ${(a.sigma*100).toFixed(0)}%</small></div>`).join("");
}

/* ================= CIRCUIT ENGINE (scrollable, overlap-free) =================
   Fixed column geometry: every layer owns an exclusive x-band. Titles are two
   short lines centered in the band, so nothing can collide. */
const GEO = { labelW: 132, top: 46, rowH: 40, bot: 22, endW: 52 };
const COLW = { H: 82, SEED: 82, DICKE: 92, COST: 184, MIXER: 82, ROT: 108 };
function cxWidth(ly) {
  if (ly.kind === "CX" || ly.kind === "XYM") { const p = (ly.pairs || []).length; return 24 + 26 * Math.max(p, 1); }
  if (ly.kind === "COST" && state.expand && (ly.rzz || []).length) return 84 + 52 * ly.rzz.length;
  return COLW[ly.kind] || 90;
}
$("expandBtn").addEventListener("click", () => {
  state.expand = !state.expand;
  $("expandBtn").textContent = state.expand ? "COLLAPSE COMPILATION (RZZ MESH)" : "EXPAND COMPILATION: RZZ → CNOT–RZ–CNOT";
  if (state.last && state.last.circuit) drawCircuit(state.last.circuit, state.last.tickers);
  else logLab("run the optimizer first — then expand.", "q");
});
function renderRouteHUD(j) {
  const el = $("routeHUD"), r = (j.circuit || {}).routing;
  if (!r) { el.textContent = ""; return; }
  const L = r.linear, H = r.heavy_hex;
  const dicke = ((j.circuit || {}).layers || []).find(l => l.kind === "DICKE");
  const ps = dicke && dicke.prep_stats;
  el.innerHTML = `TRANSPILE: <b style="color:#fff">${r.rzz_pairs} RZZ</b> → virtual <b style="color:#fff">${r.virtual_cnot} CNOT</b>${r.cx_pairs ? " (+" + r.cx_pairs + " adj CX)" : ""}` +
    ` → routed <b style="color:var(--amber)">${L.physical_cnot_lb}${H ? "–" + H.physical_cnot_ub : ""} CNOT</b>` +
    ` <span style="color:var(--dim)">[linear LB ${L.swaps_lb} SWAP${H ? " · heavy-hex UB " + H.swaps_ub + " SWAP" : ""}]</span>` +
    (ps && !ps.skipped ? `<br>DICKE PREP (unoptimized unroll, upper bound): <b style="color:#fff">${ps.cx} CX</b>, depth ${ps.depth}, ${ps.single_q} 1q gates` : "");
}
function logLab(msg, cls) {
  const el = $("labLog");
  el.insertAdjacentHTML("beforeend", `<div><span class="t">[${new Date().toLocaleTimeString()}]</span> <span class="${cls || ""}">${msg}</span></div>`);
  el.scrollTop = el.scrollHeight;
}
function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
function gateBox(x, y, label, color, w) {
  w = w || 46;
  return `<rect x="${x}" y="${y}" width="${w}" height="26" fill="#000" stroke="${color}" stroke-width="1.5"/>` +
    `<text x="${x + w / 2}" y="${y + 17}" text-anchor="middle" font-size="11" font-family="'JetBrains Mono',monospace" fill="${color}">${esc(label)}</text>`;
}
function drawCircuit(circuit, tickers, upto) {
  const svg = $("circuitSvg");
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const NS = "http://www.w3.org/2000/svg";
  const mk = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(e); return e;
  };
  const layers = (circuit.layers || []).slice(0, upto === undefined ? 99 : upto);
  if (!layers.length && circuit.flow) { drawFlow(svg, mk, circuit.flow); return; }
  const n = circuit.n_qubits || tickers.length;
  const widths = layers.map(cxWidth);
  const totalW = GEO.labelW + widths.reduce((a, b) => a + b, 0) + GEO.endW + 16;
  const totalH = GEO.top + n * GEO.rowH + GEO.bot;
  svg.setAttribute("width", totalW); svg.setAttribute("height", totalH);
  const wireY = i => GEO.top + i * GEO.rowH + GEO.rowH / 2;
  for (let i = 0; i < n; i++) {
    mk("line", { x1: GEO.labelW - 14, y1: wireY(i), x2: totalW - GEO.endW - 6, y2: wireY(i), stroke: "#3d3d3d", "stroke-width": 1.5 });
    const t = mk("text", { x: 6, y: wireY(i) + 4, fill: "#e8e8e8", "font-size": 11, "font-family": "'JetBrains Mono',monospace" });
    t.textContent = "q" + i + " " + (tickers[i] || "");
  }
  let x = GEO.labelW;
  layers.forEach((ly) => {
    const w = cxWidth(ly), cx = x + w / 2;
    const col = ly.kind === "MIXER" ? PURPLE : (ly.kind === "ROT" || ly.kind === "CX" || ly.kind === "XYM") ? PURPLE : (ly.kind === "H" || ly.kind === "DICKE") ? "#e8e8e8" : CYAN;
    const t1 = mk("text", { x: cx, y: 15, "text-anchor": "middle", fill: col, "font-size": 11, "font-weight": "bold", "font-family": "'JetBrains Mono',monospace" });
    t1.textContent = (ly.title || ly.kind).slice(0, 24);
    const t2 = mk("text", { x: cx, y: 29, "text-anchor": "middle", fill: "#636363", "font-size": 9.5, "font-family": "'JetBrains Mono',monospace" });
    t2.textContent = (ly.sub || "").slice(0, 30);
    if (ly.kind === "H" || ly.kind === "MIXER" || ly.kind === "DICKE" || ly.kind === "SEED") {
      const lbl = ly.kind === "H" ? "H" : ly.kind === "DICKE" ? "D" : "RX";
      for (let i = 0; i < n; i++) {
        const g = mk("g", {});
        g.innerHTML = gateBox(cx - 23, wireY(i) - 13, lbl, col);
      }
    } else if (ly.kind === "COST") {
      for (let i = 0; i < n; i++) {
        const g = mk("g", {});
        g.innerHTML = gateBox(x + 8, wireY(i) - 13, "RZ", CYAN);
      }
      const mesh = ly.mesh || 0;
      if (state.expand && (ly.rzz || []).length) {
        // transpiled view: CNOT(a,b) - RZ(2gJ) on b - CNOT(a,b), one column per pair
        ly.rzz.forEach((e, k) => {
          const xx = x + 66 + k * 52;
          const a = e.pair[0], b = e.pair[1];
          const y1 = wireY(a), y2 = wireY(b);
          mk("line", { x1: xx, y1: y1, x2: xx, y2: y2, stroke: CYAN, "stroke-width": 1.2 });
          mk("circle", { cx: xx, cy: y1, r: 3.5, fill: CYAN });
          mk("circle", { cx: xx, cy: y2, r: 3.5, fill: CYAN });
          const g2 = mk("g", {});
          g2.innerHTML = gateBox(xx + 6, y2 - 13, "RZ", CYAN, 30);
          const at = mk("text", { x: xx + 6, y: y2 + 26, fill: "#636363", "font-size": 8.5, "font-family": "'JetBrains Mono',monospace" });
          at.textContent = e.angle;
          mk("line", { x1: xx + 44, y1: y1, x2: xx + 44, y2: y2, stroke: CYAN, "stroke-width": 1.2 });
          mk("circle", { cx: xx + 44, cy: y1, r: 3, fill: "none", stroke: CYAN, "stroke-width": 1.2 });
          mk("circle", { cx: xx + 44, cy: y2, r: 3, fill: "none", stroke: CYAN, "stroke-width": 1.2 });
        });
        const nt = mk("text", { x: x + 66, y: GEO.top - 16, fill: AMBER, "font-size": 10, "font-family": "'JetBrains Mono',monospace" });
        nt.textContent = `transpiled: ${ly.rzz.length} RZZ = ${ly.rzz.length * 2} CNOT + ${ly.rzz.length} RZ`;
      } else {
        const bx = x + 66;
        mk("rect", { x: bx, y: GEO.top, width: w - 76, height: n * GEO.rowH, fill: "none", stroke: CYAN, "stroke-width": 1.5, "stroke-dasharray": "6 3" });
        const bt = mk("text", { x: bx + (w - 76) / 2, y: GEO.top + (n * GEO.rowH) / 2 - 2, "text-anchor": "middle", fill: CYAN, "font-size": 11, "font-weight": "bold", "font-family": "'JetBrains Mono',monospace" });
        bt.textContent = "RZZ";
        const bc = mk("text", { x: bx + (w - 76) / 2, y: GEO.top + (n * GEO.rowH) / 2 + 13, "text-anchor": "middle", fill: CYAN, "font-size": 10, "font-family": "'JetBrains Mono',monospace" });
        bc.textContent = "x" + mesh;
      }
    } else if (ly.kind === "ROT") {
      for (let i = 0; i < n; i++) {
        const g1 = mk("g", {}); g1.innerHTML = gateBox(x + 6, wireY(i) - 13, "RY", PURPLE, 44);
        const g2 = mk("g", {}); g2.innerHTML = gateBox(x + 54, wireY(i) - 13, "RZ", PURPLE, 44);
      }
    } else if (ly.kind === "CX" || ly.kind === "XYM") {
      (ly.pairs || []).forEach((pr, k) => {
        const xx = x + 14 + k * 26;
        const y1 = wireY(pr[0]), y2 = wireY(pr[1]);
        if (ly.kind === "XYM" && pr[1] === (pr[0] + 1) % n && pr[0] === n - 1) {
          // ring wrap edge: draw as curved bypass on the right side
          mk("line", { x1: xx, y1: y1, x2: xx + 10, y2: (y1 + wireY(0)) / 2, stroke: PURPLE, "stroke-width": 1.2 });
          mk("line", { x1: xx + 10, y1: (y1 + wireY(0)) / 2, x2: xx + 10, y2: wireY(0), stroke: PURPLE, "stroke-width": 1.2 });
          mk("line", { x1: xx + 10, y1: wireY(0), x2: xx, y2: wireY(0), stroke: PURPLE, "stroke-width": 1.2 });
        } else {
          mk("line", { x1: xx, y1: y1, x2: xx, y2: y2, stroke: PURPLE, "stroke-width": 1.5 });
        }
        mk("circle", { cx: xx, cy: y1, r: 4, fill: PURPLE });
        if (ly.kind === "CX") {
          mk("circle", { cx: xx, cy: y2, r: 7, fill: "#000", stroke: PURPLE, "stroke-width": 1.5 });
          mk("line", { x1: xx - 4, y1: y2, x2: xx + 4, y2: y2, stroke: PURPLE, "stroke-width": 1.5 });
          mk("line", { x1: xx, y1: y2 - 4, x2: xx, y2: y2 + 4, stroke: PURPLE, "stroke-width": 1.5 });
        } else {
          const g = mk("g", {});
          g.innerHTML = gateBox(xx - 15, y2 - 13, "XY", PURPLE, 30);
        }
      });
    }
    mk("line", { x1: x + w - 3, y1: GEO.top - 14, x2: x + w - 3, y2: GEO.top + n * GEO.rowH + 8, stroke: "#2b2b2b", "stroke-dasharray": "3 4" });
    x += w;
  });
  // measure boxes (ASCII "M", never font-dependent glyphs)
  for (let i = 0; i < n; i++) {
    const g = mk("g", {});
    g.innerHTML = gateBox(totalW - GEO.endW, wireY(i) - 12, "M", "#636363", 30);
  }
}
function drawFlow(svg, mk, flow) {
  const stages = flow.stages || [];
  const bw = 168, gap = 52, totalW = 30 + stages.length * (bw + gap);
  const totalH = 150;
  svg.setAttribute("width", totalW); svg.setAttribute("height", totalH);
  const t = mk("text", { x: 16, y: 20, fill: AMBER, "font-size": 11, "font-weight": "bold", "font-family": "'JetBrains Mono',monospace" });
  t.textContent = (flow.title || "SOLVER FLOW").slice(0, 60);
  stages.forEach((s, i) => {
    const x = 16 + i * (bw + gap), y = 44;
    const last = i === stages.length - 1;
    mk("rect", { x: x, y: y, width: bw, height: 60, fill: "#000", stroke: last ? CYAN : AMBER, "stroke-width": last ? 2 : 1.5 });
    const l = mk("text", { x: x + bw / 2, y: y + 24, "text-anchor": "middle", fill: "#fff", "font-size": 11, "font-weight": "bold", "font-family": "'JetBrains Mono',monospace" });
    l.textContent = (s.label || "").slice(0, 22);
    const d = mk("text", { x: x + bw / 2, y: y + 43, "text-anchor": "middle", fill: "#9a9a9a", "font-size": 10, "font-family": "'JetBrains Mono',monospace" });
    d.textContent = (s.detail || "").slice(0, 26);
    if (i < stages.length - 1) {
      const a = mk("text", { x: x + bw + gap / 2, y: y + 36, "text-anchor": "middle", fill: AMBER, "font-size": 16, "font-weight": "bold", "font-family": "'JetBrains Mono',monospace" });
      a.textContent = ">";
    }
  });
}
function skeletonLayers(algo, n, p, mixer) {
  const L = [];
  if (algo === "qaoa" && mixer === "xy") {
    L.push({ kind: "DICKE", title: "DICKE", sub: "feasible subspace" });
    for (let l = 0; l < p; l++) {
      L.push({ kind: "COST", title: "COST L" + (l + 1), sub: "no penalty", mesh: n * (n - 1) / 2 });
      L.push({ kind: "XYM", title: "XY L" + (l + 1), sub: "ring mixer",
               pairs: Array.from({ length: n }, (_, i) => [i, (i + 1) % n]) });
    }
    return L;
  }
  if (algo === "qaoa") {
    L.push({ kind: "H", title: "INIT H", sub: "superposition" });
    L.push({ kind: "SEED", title: "SEED", sub: "symmetry-break" });
    for (let l = 0; l < p; l++) {
      L.push({ kind: "COST", title: "COST L" + (l + 1), sub: "RZ+RZZ mesh", mesh: n * (n - 1) / 2 });
      L.push({ kind: "MIXER", title: "MIX L" + (l + 1), sub: "RX explore" });
    }
  } else if (algo === "vqe") {
    L.push({ kind: "ROT", title: "ROT in", sub: "RY+RZ" });
    for (let r = 0; r < p; r++) {
      L.push({ kind: "CX", title: "ENT r" + (r + 1), sub: "CNOT chain",
               pairs: Array.from({ length: n - 1 }, (_, i) => [i, i + 1]) });
      L.push({ kind: "ROT", title: "ROT r" + (r + 1), sub: "RY+RZ" });
    }
  }
  return L;
}

/* ---------------- charts (flat) ---------------- */
function drawConvergence(conv, classicalEnergy, bestEnergy, marks) {
  const o = ctx2d($("convChart")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 56, t: 12, r: 12, b: 24 };
  axes(c, W, H, pad);
  conv = conv || [];
  if ((!conv.length || conv.length < 2) && classicalEnergy !== null && classicalEnergy !== undefined) {
    const Y = H / 2;
    c.strokeStyle = RED; c.lineWidth = 2; c.setLineDash([6, 4]);
    c.beginPath(); c.moveTo(pad.l, Y); c.lineTo(W - pad.r, Y); c.stroke(); c.setLineDash([]);
    c.fillStyle = RED; c.font = "10px 'JetBrains Mono',monospace";
    c.fillText("classical " + Number(classicalEnergy).toFixed(3), pad.l + 6, Y - 6);
    if (!conv.length) { c.fillStyle = "#636363"; c.fillText("streaming live …", pad.l + 6, Y + 16); }
    return;
  }
  if (!conv.length) { c.fillStyle = "#636363"; c.font = "12px 'JetBrains Mono',monospace"; c.fillText("no data — press RUN", pad.l + 10, 40); return; }
  const ys = conv.map(d => d.energy).concat(classicalEnergy !== null && classicalEnergy !== undefined ? [classicalEnergy] : [])
    .concat(bestEnergy !== null && bestEnergy !== undefined ? [bestEnergy] : []);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const X = i => pad.l + i / Math.max(conv.length - 1, 1) * (W - pad.l - pad.r);
  const Y = v => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  c.strokeStyle = "#1c1c1c"; c.fillStyle = "#636363"; c.font = "10px 'JetBrains Mono',monospace";
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4;
    c.beginPath(); c.moveTo(pad.l, Y(v)); c.lineTo(W - pad.r, Y(v)); c.stroke(); c.fillText(v.toFixed(2), 2, Y(v) + 3); }
  if (classicalEnergy !== null && classicalEnergy !== undefined) {
    c.setLineDash([6, 4]); c.strokeStyle = RED; c.lineWidth = 2;
    c.beginPath(); c.moveTo(pad.l, Y(classicalEnergy)); c.lineTo(W - pad.r, Y(classicalEnergy)); c.stroke(); c.setLineDash([]);
    c.fillStyle = RED; c.fillText("classical " + Number(classicalEnergy).toFixed(2), W - 132, Y(classicalEnergy) - 6);
  }
  if (bestEnergy !== null && bestEnergy !== undefined) {
    c.setLineDash([2, 3]); c.strokeStyle = AMBER; c.lineWidth = 1.5;
    c.beginPath(); c.moveTo(pad.l, Y(bestEnergy)); c.lineTo(W - pad.r, Y(bestEnergy)); c.stroke(); c.setLineDash([]);
    c.fillStyle = AMBER; c.fillText("best sample " + Number(bestEnergy).toFixed(2), pad.l + 6, Y(bestEnergy) - 6);
  }
  (marks || []).forEach((m, k) => {
    if (k === 0) return; // first mark = run start, not a restart
    const idx = conv.findIndex(d => (d.iter !== undefined ? d.iter : -1) >= m);
    if (idx < 0) return;
    const xx = X(conv[idx].iter !== undefined ? conv[idx].iter : idx);
    c.strokeStyle = "#fff"; c.lineWidth = 1; c.setLineDash([4, 3]);
    c.beginPath(); c.moveTo(xx, pad.t); c.lineTo(xx, H - pad.b); c.stroke(); c.setLineDash([]);
    c.fillStyle = "#fff"; c.fillText("RESTART #" + (k + 1), Math.min(xx + 4, W - 92), pad.t + 10);
  });
  c.strokeStyle = CYAN; c.lineWidth = 2;
  c.beginPath();
  conv.forEach((d, i) => { const xi = X(d.iter !== undefined ? d.iter : i); i ? c.lineTo(xi, Y(d.energy)) : c.moveTo(xi, Y(d.energy)); });
  c.stroke();
  const last = conv[conv.length - 1];
  c.fillStyle = CYAN; c.fillRect(X(last.iter !== undefined ? last.iter : conv.length - 1) - 3, Y(last.energy) - 3, 6, 6);
}
function drawHistogram(hist, cvId, cutoff) {
  const o = ctx2d($(cvId || "histChart")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 40, t: 14, r: 10, b: 42 };
  axes(c, W, H, pad);
  if (!hist || !hist.length) { c.fillStyle = "#636363"; c.font = "12px 'JetBrains Mono',monospace"; c.fillText("no measurements yet", pad.l + 10, 40); return; }
  const top = hist.slice(0, 10);
  const mx = Math.max(...top.map(d => d.prob)) || 1;
  const feas = top.filter(d => d.feasible);
  const best = feas.length ? feas.reduce((a, b) => a.prob >= b.prob ? a : b) : null;
  const bw = (W - pad.l - pad.r) / top.length;
  c.font = "9px 'JetBrains Mono',monospace";
  top.forEach((d, i) => {
    const h = (H - pad.t - pad.b) * (d.prob / mx);
    const x = pad.l + i * bw + 4, y = H - pad.b - h;
    c.fillStyle = d.feasible ? "rgba(0,208,120,.85)" : "rgba(150,45,60,.55)";
    c.fillRect(x, y, bw - 8, h);
    if (cutoff !== null && cutoff !== undefined && d.energy <= cutoff) {
      c.fillStyle = AMBER; c.fillRect(x, y - 4, bw - 8, 3);
    }
    if (d.exact !== undefined && d.exact !== null) {
      const ye = H - pad.b - (H - pad.t - pad.b) * (d.exact / mx);
      c.fillStyle = "#fff"; c.fillRect(x, ye - 1, bw - 8, 2);
    }
    if (best && d.bitstring === best.bitstring) {
      c.strokeStyle = AMBER; c.lineWidth = 2; c.strokeRect(x, y, bw - 8, h);
      c.fillStyle = AMBER; c.fillText("BEST", x, y - 14);
    }
    c.fillStyle = d.feasible ? "#00d084" : "#ff7a8a";
    c.fillText((d.prob * 100).toFixed(1) + "%", x, y - 4);
    c.fillStyle = "#9a9a9a"; c.fillText(d.bitstring, x, H - pad.b + 12);
    c.fillStyle = d.feasible ? "#00d084" : "#ff7a8a"; c.fillText(d.feasible ? "K-ok" : "off-K", x, H - pad.b + 24);
  });
}
function drawFrontier(fr) {
  const o = ctx2d($("frontChart")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 44, t: 12, r: 12, b: 26 };
  axes(c, W, H, pad);
  const all = (fr.continuous || []).concat(fr.discrete || []).concat(fr.quantum ? [fr.quantum] : []);
  if (!all.length) return;
  const xs = all.map(p => p.x), ys = all.map(p => p.y);
  const x0 = Math.min(...xs) - 1, x1 = Math.max(...xs) + 1, y0 = Math.min(...ys) - 1, y1 = Math.max(...ys) + 1;
  const X = v => pad.l + (v - x0) / (x1 - x0) * (W - pad.l - pad.r);
  const Y = v => pad.t + (1 - (v - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  c.font = "10px 'JetBrains Mono',monospace"; c.fillStyle = "#636363";
  for (let k = 0; k <= 4; k++) c.fillText((x0 + (x1 - x0) * k / 4).toFixed(0) + "%", pad.l + (W - pad.l - pad.r) * k / 4 - 8, H - 8);
  (fr.continuous || []).forEach(p => { c.fillStyle = "rgba(154,154,154,.3)"; c.fillRect(X(p.x) - 1, Y(p.y) - 1, 2, 2); });
  (fr.discrete || []).forEach(p => { c.fillStyle = "#9a9a9a"; c.fillRect(X(p.x) - 1.5, Y(p.y) - 1.5, 3, 3); });
  if (fr.quantum) {
    const q = fr.quantum;
    c.strokeStyle = CYAN; c.lineWidth = 2.5;
    c.beginPath(); c.moveTo(X(q.x) - 8, Y(q.y)); c.lineTo(X(q.x) + 8, Y(q.y));
    c.moveTo(X(q.x), Y(q.y) - 8); c.lineTo(X(q.x), Y(q.y) + 8); c.stroke();
    c.fillStyle = CYAN; c.fillText("+ QUANTUM", Math.min(X(q.x) + 11, W - 80), Y(q.y) + 3);
  }
  c.fillStyle = "#636363"; c.fillText("RISK (vol %) ->", W - 112, H - 8);
}
function drawBacktest(port, spy) {
  const o = ctx2d($("btChart")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 46, t: 12, r: 12, b: 24 };
  axes(c, W, H, pad);
  if (!port || !port.length) return;
  const all = port.concat(spy || []);
  const lo = Math.min(...all), hi = Math.max(...all);
  const X = i => pad.l + i / (port.length - 1) * (W - pad.l - pad.r);
  const Y = v => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  c.font = "10px 'JetBrains Mono',monospace";
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4;
    c.fillStyle = "#636363"; c.fillText("$" + v.toFixed(0), 2, Y(v) + 3); }
  const line = (arr, col, w) => {
    c.strokeStyle = col; c.lineWidth = w; c.beginPath();
    arr.forEach((v, i) => i ? c.lineTo(X(i * (port.length - 1) / (arr.length - 1)), Y(v)) : c.moveTo(X(0), Y(v)));
    c.stroke();
  };
  if (spy && spy.length) line(spy, "#9a9a9a", 1.5);
  line(port, CYAN, 2);
  c.fillStyle = CYAN; c.fillText("Q $" + port[port.length - 1].toFixed(0), X(port.length - 1) - 52, Y(port[port.length - 1]) - 8);
  if (spy && spy.length) { c.fillStyle = GREY; c.fillText("S&P $" + spy[spy.length - 1].toFixed(0), X(spy.length - 1) - 60, Y(spy[spy.length - 1]) + 14); }
}

/* ---------------- run: WebSocket live, REST fallback ---------------- */
function setBusy(b, msg) {
  $("runBtn").disabled = b; $("cmpBtn").disabled = b;
  $("statusLine").innerHTML = b ? `<span class="spinner"></span> ${esc(msg)}` : `<span class="ok">●</span> ready · mock feed · seed 42`;
}
function reqBody() {
  return {
    tickers: state.tickers.slice(), K: parseInt($("kSlider").value),
    risk_q: parseFloat($("qSlider").value), algorithm: state.algo,
    p: parseInt($("pSlider").value), shots: parseInt($("shotsSel").value),
    optimizer: $("optSel").value, rebalance: $("rbSel").value,
    mixer: $("mixSel").value, noise: $("noiseSel").value,
    zne: $("zneChk").checked, cvar_alpha: parseFloat($("cvarSel").value),
    source: state.source, dataset_id: state.datasetId,
    yahoo_period: ($("yahooPeriod") || {}).value || "3y",
  };
}
$("runBtn").addEventListener("click", () => {
  if (state.tickers.length < 3) { alert("Select at least 3 stocks."); return; }
  const body = reqBody();
  if (body.K > body.tickers.length) { alert("K cannot exceed universe size."); return; }
  runLive(body);
});
function wsURL() { return (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws/optimize"; }
async function runLive(body) {
  setBusy(true, `running ${body.algorithm.toUpperCase()} · live stream …`);
  $("labLog").innerHTML = ""; $("progBar").style.width = "2%";
  state.classicalEnergy = null;
  goTab("lab");
  const skel = { n_qubits: body.tickers.length,
                 layers: skeletonLayers(body.algo, body.tickers.length, body.p, body.mixer),
                 flow: (body.algo === "qaoa" || body.algo === "vqe") ? null :
                   { type: "flow", title: "SOLVER FLOW (streaming…)", stages: [
                     { label: "INIT", detail: "starting" }, { label: "SEARCH", detail: "running" },
                     { label: "READ", detail: "…" }] } };
  drawCircuit(skel, body.tickers, 1);
  logLab(`dispatch -> WS /ws/optimize ${body.algorithm} · ${body.tickers.join(",")} · K=${body.K} q=${body.risk_q}`, "q");
  let finished = false, pts = [];
  const t0 = performance.now();
  const finish = (j, via) => {
    finished = true;
    state.last = j;
    $("timingLine").textContent = `solver ${j.seconds}s · wall ${((performance.now() - t0) / 1000).toFixed(1)}s · ${j.backend} · ${via}`;
    $("progBar").style.width = "100%";
    drawCircuit(j.circuit, body.tickers);
    renderRouteHUD(j);
    logLab(`measured ${body.shots} shots -> top bitstring ${j.best_bitstring}`, "ok");
    goTab("exec");
    drawConvergence(j.convergence || [], j.classical_energy, j.energy, j.restart_marks);
    drawHistogram(j.histogram || [], undefined, j.cvar_cutoff);
    const hx = j.histogram || [];
    $("histExplain").innerHTML = "<b style='color:#00d084'>Emerald = K-ok (feasible)</b> · <b style='color:#ff7a8a'>red = off-K (penalized)</b>. Bars = measured shots. <b style='color:#fff'>White ticks</b> = exact statevector probability (their gap is shot noise)." +
      ((j.cvar_alpha || 1) < 1 ? ` <b style="color:var(--amber)">Amber caps = CVaR α=${j.cvar_alpha} tail (E ≤ ${j.cvar_cutoff}).</b>` : "") +
      ((hx.length && !hx[0].feasible) ? ` <b style="color:var(--amber)">Note: an off-budget state out-voted the winner — the penalty landscape trapped this run. BEST (amber) is still the top valid portfolio; retry with the XY mixer for 100% feasibility.</b>` : "");
    renderAll(j);
    renderNoise(j); renderStates(j); renderSignature(j); renderBloch(j); renderSlicer(j); loadHistory();
    const hw = $("hwPill");
    if (j.noise && j.noise.hw_badge) { hw.style.display = ""; hw.textContent = "HW · EAGLE NOISE"; }
    else hw.style.display = "none";
    if (state.tour && state.tour.waitRun) { state.tour.waitRun = false; tourAdvance(); }
    goTab("results");
    $("execBanner").classList.remove("pending");
    $("execText").textContent = j.summary;
    setBusy(false);
  };
  try {
    const ws = new WebSocket(wsURL());
    const opened = await new Promise((res, rej) => { ws.onopen = () => res(true); ws.onerror = () => rej(new Error("ws")); setTimeout(() => rej(new Error("timeout")), 4000); });
    if (!opened) throw new Error("ws");
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "baseline") {
        state.classicalEnergy = m.classical_energy;
        logLab(`baseline classical E=${Number(m.classical_energy).toFixed(3)} · P=${m.penalty} · streaming iterations…`, "ok");
        goTab("exec"); drawConvergence([], m.classical_energy);
        goTab("lab");
      } else if (m.type === "progress") {
        pts.push(m);
        $("progBar").style.width = Math.min(95, 3 + pts.length) + "%";
        if (skel.layers.length) {
          const upto = Math.min(skel.layers.length, 1 + Math.floor(pts.length / 8));
          drawCircuit(skel, body.tickers, upto);
        }
        if (pts.length === 1 || pts.length % 10 === 0) logLab(`iter ${m.iter} · E=${Number(m.energy).toFixed(3)}`);
        if (pts.length % 3 === 0 && state.classicalEnergy !== null) { goTab("exec"); drawConvergence(pts, state.classicalEnergy); goTab("lab"); }
      } else if (m.type === "done") {
        try { ws.close(); } catch (e) {}
        finish(m.result, "websocket-live");
      } else if (m.type === "error") {
        try { ws.close(); } catch (e) {}
        if (!finished) restRun(body, t0, finish);
      }
    };
    ws.onerror = () => { if (!finished) { try { ws.close(); } catch (e) {} restRun(body, t0, finish); } };
    ws.onclose = () => { if (!finished) restRun(body, t0, finish); };
    ws.send(JSON.stringify(body));
  } catch (e) {
    restRun(body, t0, finish);
  }
}
async function restRun(body, t0, finish) {
  logLab("websocket unavailable — REST fallback (animated replay)", "q");
  try {
    const res = await fetch("/api/optimize", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await res.text());
    const j = await res.json();
    const layers = (j.circuit && j.circuit.layers) || [];
    for (let u = 1; u <= Math.max(layers.length, 1); u++) {
      drawCircuit(layers.length ? j.circuit : { n_qubits: body.tickers.length, layers: [], flow: j.circuit.flow }, body.tickers, u);
      await new Promise(r => setTimeout(r, 200));
      if (!layers.length) break;
    }
    finish(j, "rest-fallback");
  } catch (e) {
    $("execBanner").classList.remove("pending");
    $("execText").textContent = "Run failed: " + e.message;
    logLab("ERROR " + esc(e.message));
    setBusy(false);
  }
}
$("cmpBtn").addEventListener("click", async () => {
  setBusy(true, "comparing all 5 solvers …");
  try {
    const res = await fetch("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(reqBody()) });
    const j = await res.json();
    $("cmpBody").innerHTML = j.rows.map((r, i) =>
      `<tr class="${i === 0 ? "winner" : ""}"><td>${i === 0 ? "[*] " : ""}${esc(r.label)}</td><td>${r.bitstring || "--"}</td>` +
      `<td class="n" style="color:${i === 0 ? "var(--cyan)" : "#fff"}">${r.energy === null || r.energy === undefined ? "--" : Number(r.energy).toFixed(4)}</td>` +
      `<td class="n">${r.sharpe === null || r.sharpe === undefined ? "--" : r.sharpe}</td><td class="n">${r.seconds}s</td></tr>`).join("");
    renderH2H(j.rows);
    goTab("results");
  } catch (e) { alert("Compare failed: " + e.message); }
  setBusy(false);
});

function renderH2H(rows) {
  const el = $("h2h");
  const q = rows.find(r => r.algorithm === "qaoa");
  const xy = rows.find(r => r.algorithm === "qaoa_xy");
  if (!q || !q.weight_dist || !xy || !xy.weight_dist) {
    el.innerHTML = `<div style="font-size:11.5px;color:var(--dim)">Head-to-head needs QAOA + QAOA-XY weight data.</div>`;
    return;
  }
  const leak = (r) => r.leakage === null || r.leakage === undefined ? "n/a" : (r.leakage * 100).toFixed(2) + "%";
  const bars = (wd, K) => Object.keys(wd).sort((a, b) => a - b).map(w => {
    const v = Number(wd[w]), isK = Number(w) === K;
    return `<div class="wbar"><span class="wl">w=${w}${isK ? " ★" : ""}</span>` +
      `<span class="wt"><span class="wf${isK ? " k" : ""}" style="width:${(v * 100).toFixed(1)}%"></span></span>` +
      `<span class="wv">${(v * 100).toFixed(1)}%</span></div>`;
  }).join("");
  const K = state.last ? (state.last.subspace || {}).K : null;
  el.innerHTML =
    `<div style="font-size:11px;letter-spacing:1px;color:var(--amber);margin-bottom:4px">HEAD-TO-HEAD: SUBSPACE CONFINEMENT</div>` +
    `<div class="grid2"><div><b>STANDARD QAOA</b> · leakage <b style="color:var(--amber)">${leak(q)}</b>${bars(q.weight_dist, K)}</div>` +
    `<div><b>QAOA-XY</b> · leakage <b style="color:var(--green)">${leak(xy)}</b>${bars(xy.weight_dist, K)}</div></div>` +
    `<div style="font-size:11px;color:var(--mut)">XY wastes 0% of shots off-manifold; standard QAOA pays λ per leaked shot.</div>`;
}

/* ---------------- export ---------------- */
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: type }));
  a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
$("csvBtn").addEventListener("click", () => {
  if (!state.last) { alert("Run the optimizer first."); return; }
  const j = state.last;
  let csv = "ticker,weight_pct,mu_pct,sigma_pct\n" +
    j.selected.map(s => `${s.ticker},${s.weight_pct},${s.mu_pct},${s.sigma_pct}`).join("\n") +
    `\nbitstring,${j.best_bitstring}\nenergy,${j.energy}\nsharpe,${j.metrics.sharpe}\nsortino,${j.metrics.sortino}\nmax_dd,${j.metrics.max_dd}\nturnover_pct,${j.turnover_pct}\n`;
  download("quantum_portfolio.csv", csv, "text/csv");
});
$("jsonBtn").addEventListener("click", () => {
  if (!state.last) { alert("Run the optimizer first."); return; }
  download("quantum_portfolio.json", JSON.stringify(state.last, null, 1), "application/json");
});

/* ---------------- results render ---------------- */
function renderAll(j) {
  const m = j.metrics || {}, s = j.metrics_spy || {};
  $("mRet").textContent = (m.ann_return !== undefined ? m.ann_return + "%" : "—");
  $("mRetS").textContent = "vs S&P " + (s.ann_return !== undefined ? s.ann_return + "%" : "—");
  $("mSharpe").textContent = m.sharpe !== undefined ? m.sharpe : "—";
  $("mSharpeS").textContent = `quantum ${m.sharpe !== undefined ? m.sharpe : "—"} · S&P ${s.sharpe !== undefined ? s.sharpe : "—"}`;
  $("mSort").textContent = m.sortino !== undefined ? m.sortino : "—";
  $("mDD").textContent = (m.max_dd !== undefined ? m.max_dd + "%" : "—");
  $("mDDS").textContent = "turnover " + (j.turnover_pct !== undefined ? j.turnover_pct + "%" : "—");
  $("rbNote").textContent = "Mode: " + (j.rebalance === "monthly" ? "WALK-FWD monthly (turnover " + j.turnover_pct + "%)" : "BUY + HOLD") + ".";
  $("btExplain").textContent = `What $100 becomes (${j.rebalance === "monthly" ? "monthly rebalanced, turnover " + j.turnover_pct + "%" : "buy + hold"}). Cyan = quantum, grey = ${j.bench_label || "benchmark"}.`;
  $("holdCards").innerHTML = (j.selected || []).map(x =>
    `<div class="hold top"><b>${x.ticker}</b><div class="w">${x.weight_pct}%</div>` +
    `<small>MU ${x.mu_pct}% · SD ${x.sigma_pct}%</small><small>${j.best_bitstring}</small></div>`).join("");
  drawConvergence(j.convergence || [], j.classical_energy, j.energy, j.restart_marks);
  drawHistogram(j.histogram || [], undefined, j.cvar_cutoff);
  drawFrontier(j.frontier || {});
  drawBacktest(j.backtest.portfolio || [], j.backtest.spy || []);
  const M = j.math || {};
  const qcell = v => `<span style="color:${v < 0 ? "var(--cyan)" : "var(--red)"}">${(v >= 0 ? " " : "") + Number(v).toFixed(2)}</span>`;
  const qstr = (M.qubo || []).map(r => "  [" + r.map(qcell).join("<span style='color:var(--dim)'>,</span> ") + "]").join("\n");
  const J = M.ising_J || [];
  const pairs = [];
  J.forEach((row, i) => row.forEach((v, jj) => { if (jj > i && Math.abs(v) > 1e-9 && pairs.length < 14) pairs.push(`${state.tickers[i]}${state.tickers[jj]}:${Number(v).toFixed(2)}`); }));
  $("mathBox").innerHTML =
`<span class="am">MARKOWITZ MIQP</span>   ${esc(M.markowitz || "")}
penalty P = ${M.penalty} · risk q = ${M.risk_q} · K = ${M.K}

<span class="hl">QUBO (upper-triangular, order = ${(j.tickers || []).join(" ")})</span>
${qstr}

<span class="hl">ISING MAPPING</span>   ${esc(M.mapping || "")}
h = [${(M.ising_h || []).join(", ")}]
J pairs = ${esc(pairs.join("  "))}
offset = ${M.ising_offset}

<span class="rd">classical exact</span>  E=${Number(j.classical_energy).toFixed(4)}  x=${j.classical_bitstring}
<span class="hl">quantum (${esc(j.algorithm)})</span>  E=${Number(j.energy).toFixed(4)}  x=${j.best_bitstring} · ${esc(j.backend)}`;
  drawIsing(j);
  renderSignature(j); renderBloch(j); renderSlicer(j);
}

/* ---------------- data sources (mock / yahoo / csv) ---------------- */
function setUniverseData(assets, cov, label) {
  state.assets = assets; state.cov = cov;
  state.assets.forEach(a => { if (!(a.ticker in state.base)) state.base[a.ticker] = a.last; });
  state.tickers = assets.map(a => a.ticker);
  const tb = $("assetBody"); tb.innerHTML = "";
  for (const a of state.assets) {
    const tr = document.createElement("tr");
    tr.classList.add("sel");
    tr.innerHTML = `<td><input type="checkbox" checked data-t="${a.ticker}"></td>
      <td><b>${a.ticker}</b> <span style="color:var(--dim);font-size:10px">${a.name || ""}</span></td>
      <td class="n" data-c="last" data-t="${a.ticker}">${Number(a.last).toFixed(2)}</td>
      <td class="n ${a.chg_pct >= 0 ? "pos" : "neg"}" data-c="chg" data-t="${a.ticker}">${fmtChg(a.chg_pct)}</td>
      <td class="n">${Number(a.beta).toFixed(2)}</td>
      <td class="n">${(Number(a.sigma) * 100).toFixed(0)}%</td>`;
    tb.appendChild(tr);
  }
  $("srcPill").textContent = label;
  buildTape(); syncKSlider(); renderSetup();
}
async function loadUniverse() {
  const j = await (await fetch("/api/universe")).json();
  state.source = "mock"; state.datasetId = null;
  const tb = $("assetBody");
  // keep preset selection for mock
  state.assets = j.assets; state.cov = j.cov;
  state.assets.forEach(a => { state.base[a.ticker] = a.last; });
  tb.innerHTML = "";
  const pre = new Set(state.tickers);
  for (const a of state.assets) {
    const tr = document.createElement("tr");
    if (pre.has(a.ticker)) tr.classList.add("sel");
    tr.innerHTML = `<td><input type="checkbox" ${pre.has(a.ticker) ? "checked" : ""} data-t="${a.ticker}"></td>
      <td><b>${a.ticker}</b> <span style="color:var(--dim);font-size:10px">${a.name}</span></td>
      <td class="n" data-c="last" data-t="${a.ticker}">${a.last.toFixed(2)}</td>
      <td class="n ${a.chg_pct >= 0 ? "pos" : "neg"}" data-c="chg" data-t="${a.ticker}">${fmtChg(a.chg_pct)}</td>
      <td class="n">${a.beta.toFixed(2)}</td>
      <td class="n">${(a.sigma * 100).toFixed(0)}%</td>`;
    tb.appendChild(tr);
  }
  tb.addEventListener("change", universeChange);
  try {
    const hj = await (await fetch("/api/health")).json();
    state.backend = hj.qiskit ? "QISKIT AER" : "NUMPY FALLBACK";
  } catch { state.backend = "OFFLINE?"; }
  $("backendPill").textContent = "BACKEND · " + state.backend;
  $("srcPill").textContent = "MOCK FEED";
  buildTape(); syncKSlider(); renderSetup();
  setInterval(tickFeed, 2000);
}
function universeChange(e) {
  const cb = e.target.closest("input[type=checkbox]"); if (!cb) return;
  const t = cb.dataset.t;
  if (cb.checked && !state.tickers.includes(t)) state.tickers.push(t);
  if (!cb.checked) state.tickers = state.tickers.filter(x => x !== t);
  cb.closest("tr").classList.toggle("sel", cb.checked);
  state.tickers.sort((a, b) => state.assets.findIndex(x => x.ticker === a) - state.assets.findIndex(x => x.ticker === b));
  syncKSlider(); renderSetup();
}
$("srcSel").addEventListener("change", (e) => {
  const v = e.target.value;
  $("yahooBox").style.display = v === "yahoo" ? "" : "none";
  $("uploadBox").style.display = v === "upload" ? "" : "none";
  if (v === "mock") loadUniverse();
});
$("fetchBtn").addEventListener("click", async () => {
  const tk = $("yahooTick").value, per = $("yahooPeriod").value;
  setBusy(true, "fetching Yahoo Finance …");
  try {
    const r = await fetch(`/api/universe?source=yahoo&tickers=${encodeURIComponent(tk)}&period=${per}`);
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    state.source = "yahoo"; state.datasetId = null;
    setUniverseData(j.assets, j.cov, `YAHOO LIVE (shrink ${j.shrinkage})`);
    logLab(`live data: ${j.assets.length} tickers · Ledoit-Wolf δ=${j.shrinkage}`, "ok");
  } catch (e) { alert("Yahoo failed (offline?): " + e.message); $("srcSel").value = "mock"; loadUniverse(); }
  setBusy(false);
});
$("csvFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  setBusy(true, "parsing CSV …");
  try {
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch("/api/datasets", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    state.source = "upload"; state.datasetId = j.dataset_id;
    setUniverseData(j.assets, j.cov, `CSV: ${f.name} (${j.days}d)`);
    logLab(`csv dataset ${j.dataset_id}: ${j.assets.length} tickers · δ=${j.shrinkage}`, "ok");
  } catch (err) { alert("CSV failed: " + err.message); }
  setBusy(false);
});

/* ---------------- NISQ noise report + ZNE chart ---------------- */
function renderNoise(j) {
  const nz = j.noise || { mode: "ideal" };
  const el = $("noiseBody");
  if (nz.mode !== "eagle" || !nz.hw_badge) {
    el.innerHTML = `Mode: <b>IDEAL STATEVECTOR</b> (noiseless).<br>Expected energy &lt;H&gt; = <b>${j.expected_energy}</b> · feasibility ${(j.feasibility_rate * 100 || 0).toFixed(1)}%.<br>Select NISQ EAGLE EMULATION + RUN for the noisy comparison.`;
    $("zneChart").style.display = "none";
    return;
  }
  const z = nz.zne;
  el.innerHTML =
    `<b style="color:var(--amber)">${nz.hw_badge}</b><br>` +
    `Ideal &lt;H&gt; = <b style="color:var(--cyan)">${j.expected_energy}</b> → Noisy &lt;H&gt; = <b style="color:var(--red)">${nz.noisy_energy}</b>` +
    ` (decoherence cost <b>+${(nz.noisy_energy - j.expected_energy).toFixed(3)}</b>)<br>` +
    `Noisy feasibility = <b>${(nz.feasibility_rate * 100).toFixed(1)}%</b> (readout flips break K).<br>` +
    (z ? `ZNE folds λ=${z.points.map(p => p.scale).join(",")} → mitigated <b style="color:var(--green)">E(0)=${z.mitigated}</b> (slope ${z.slope}).`
       : `Tick ZNE + RUN for zero-noise extrapolation.`) +
    `<br><span style="color:var(--dim)">p1=${nz.profile.p1_depol} p2=${nz.profile.p2_depol} T1=${nz.profile.T1_us}us T2=${nz.profile.T2_us}us ro=${nz.profile.readout_flip}</span>`;
  if (z) { $("zneChart").style.display = ""; drawZNE(z, j.classical_energy); }
  else $("zneChart").style.display = "none";
}
function drawZNE(z, classicalEnergy) {
  const o = ctx2d($("zneChart")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 52, t: 10, r: 10, b: 22 };
  axes(c, W, H, pad);
  const xs = z.points.map(p => p.scale), ys = z.points.map(p => p.energy).concat([z.mitigated])
    .concat(classicalEnergy !== null && classicalEnergy !== undefined ? [classicalEnergy] : []);
  const x0 = 0, x1 = Math.max(...xs) + 1, y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = v => pad.l + v / (x1 - x0) * (W - pad.l - pad.r);
  const Y = v => pad.t + (1 - (v - y0) / Math.max(y1 - y0, 1e-9)) * (H - pad.t - pad.b);
  c.font = "10px 'JetBrains Mono',monospace"; c.fillStyle = "#636363";
  xs.forEach(x => c.fillText("x" + x, X(x) - 6, H - 6));
  // fit line through mitigated intercept
  c.strokeStyle = "#9a9a9a"; c.lineWidth = 1.5;
  c.beginPath(); c.moveTo(X(0), Y(z.mitigated)); c.lineTo(X(x1), Y(z.mitigated + z.slope * x1)); c.stroke();
  z.points.forEach(p => {
    c.fillStyle = RED; c.fillRect(X(p.scale) - 3, Y(p.energy) - 3, 6, 6);
    c.fillStyle = "#9a9a9a"; c.fillText(p.energy.toFixed(3), X(p.scale) - 18, Y(p.energy) - 8);
  });
  c.fillStyle = GREEN; c.fillRect(X(0) - 3, Y(z.mitigated) - 3, 6, 6);
  c.fillText("E(0)=" + z.mitigated, X(0) + 8, Y(z.mitigated) + 3);
  if (classicalEnergy !== null && classicalEnergy !== undefined) {
    c.setLineDash([6, 4]); c.strokeStyle = RED; c.lineWidth = 1.5;
    c.beginPath(); c.moveTo(pad.l, Y(classicalEnergy)); c.lineTo(W - pad.r, Y(classicalEnergy)); c.stroke(); c.setLineDash([]);
    c.fillStyle = RED; c.fillText("classical exact " + Number(classicalEnergy).toFixed(3), W - 168, Y(classicalEnergy) - 6);
  }
  c.fillStyle = "#636363"; c.fillText("noise scale λ →", W - 110, H - 6);
}

/* ---------------- quantum state density grid ---------------- */
function renderStates(j) {
  const g = $("stateGrid"); const states = j.states || [];
  if (!states.length) { g.innerHTML = `<span style="color:var(--dim)">No amplitudes (classical path).</span>`; return; }
  const K = (j.best_bitstring || "").length ? j.best_bitstring : "";
  const mx = Math.max(...states.map(s => s.prob));
  g.innerHTML = states.map(s => {
    const feas = K && s.bitstring.length === K.length && s.bitstring.split("").filter((ch, i) => ch === "1").length === (j.selected || []).length;
    const bright = 0.15 + 0.85 * (s.prob / (mx || 1));
    const hue = ((s.phase + Math.PI) / (2 * Math.PI) * 300) | 0;
    return `<div class="scell" title="${s.bitstring} p=${s.prob} φ=${s.phase}" style="background:hsla(${hue},80%,${(bright * 45).toFixed(0)}%,${bright.toFixed(2)});${feas ? "border-color:var(--cyan);" : ""}">${s.bitstring}<br>${(s.prob * 100).toFixed(1)}%</div>`;
  }).join("");
}

/* ---------------- derivation modal ---------------- */
let derivStep = 0;
function pauliStrings(j) {
  const M = (j && j.math) || {}; const tk = (j && j.tickers) || state.tickers;
  const out = [];
  (M.ising_h || []).forEach((h, i) => { if (Math.abs(h) > 1e-9) out.push(`${h >= 0 ? "+" : ""}${h} Z_${tk[i] || i}`); });
  const J = M.ising_J || [];
  J.forEach((row, i) => row.forEach((v, k) => { if (k > i && Math.abs(v) > 1e-9 && out.length < 14) out.push(`${v >= 0 ? "+" : ""}${v} Z_${tk[i]}Z_${tk[k]}`); }));
  return { terms: out, offset: M.ising_offset, P: M.penalty, q: M.risk_q, K: M.K };
}
$("derivBtn").addEventListener("click", () => { derivStep = 0; renderDeriv(); $("derivModal").style.display = ""; });
$("derivPrev").addEventListener("click", () => { derivStep = Math.max(0, derivStep - 1); renderDeriv(); });
$("derivNext").addEventListener("click", () => { derivStep = Math.min(3, derivStep + 1); renderDeriv(); });
function renderDeriv() {
  const j = state.last, ps = pauliStrings(j), tk = (j && j.tickers) || state.tickers;
  $("derivSteps").innerHTML = ["1 MARKOWITZ", "2 DISCRETIZE", "3 SUBSTITUTE", "4 PAULI FORM"]
    .map((s, i) => `<span class="${i === derivStep ? "on" : ""}">${s}</span>`).join("");
  const q = (j && j.math && j.math.risk_q) ?? parseFloat($("qSlider").value);
  const K = (j && j.math && j.math.K) ?? parseInt($("kSlider").value);
  const bodies = [
    `STEP 1 — CONTINUOUS MARKOWITZ (what finance wants)\n\n  minimize   ${q} · wᵀΣw  −  μᵀw\n\n  w = portfolio weights, Σ = covariance, μ = expected returns.\n  q = ${q} is YOUR slider value. Problem: w is continuous — a quantum\n  chip speaks binary. So we discretize: hold / don't hold each asset.`,
    `STEP 2 — BINARY + CARDINALITY PENALTY (the QUBO)\n\n  minimize   q·xᵀΣx − μᵀx + P·(Σxᵢ − K)²,   x ∈ {0,1}ⁿ\n\n  K = ${K} (your budget), P = ${ps.P ?? "…"} (auto-tuned punishment).\n  Diagonal absorbs the penalty: Q_ii = qΣ_ii − μᵢ + P(1−2K).\n  Off-diagonal: Q_ij = 2qΣ_ij + 2P. Violating K now costs energy.`,
    `STEP 3 — QUBIT SUBSTITUTION (the bridge)\n\n  xᵢ = (1 − Zᵢ)/2,   Zᵢ ∈ {+1,−1} Pauli-Z.\n\n  Plug into the QUBO and expand. Linear terms become single-Z\n  rotations (circuit RZ gates); quadratic terms become ZZ\n  couplings (circuit RZZ entanglement). A constant offset\n  ${ps.offset ?? "…"} shifts all energies equally.`,
    `STEP 4 — YOUR LIVE ISING HAMILTONIAN (what the chip minimizes)\n\n  H_C = ${ps.terms.length ? ps.terms.slice(0, 8).join("\n      ") + (ps.terms.length > 8 ? `\n      … +${ps.terms.length - 8} more ZZ terms` : "") : "run the optimizer first"}\n      + (${ps.offset ?? "…"})\n\n  Each Z term → one RZ gate, each ZZ term → one RZZ block.\n  That is literally the COST layer you watched being built.`,
  ];
  $("derivBody").textContent = bodies[derivStep];
}

/* ---------------- guided tour ---------------- */
const TOUR = [
  { tab: "setup", tag: "PHASE 1/5 · PROBLEM", title: "The cardinality cage",
    text: "We hold exactly K of N stocks — C(N,K) discrete portfolios, a non-convex MIQP no gradient method can touch. I set 8 stocks, K=3 (56 combos).",
    run() { state.tickers = state.assets.slice(0, 8).map(a => a.ticker); $("kSlider").value = 3; $("kVal").textContent = "3"; syncAssetChecks(); renderSetup(); } },
  { tab: "math", tag: "PHASE 2/5 · MATH", title: "Finance becomes physics",
    text: "Markowitz + penalty becomes QUBO, then x=(1−Z)/2 turns it into an Ising Hamiltonian. Open STEP-BY-STEP DERIVATION for the live numbers.",
    run() {} },
  { tab: "lab", tag: "PHASE 3/5 · EXECUTION", title: "Watch it learn — live",
    text: "Firing QAOA p=2 over WebSocket. Cyan dives toward the red classical line. This is real optimization streaming, not a replay.",
    run() { state.algo = "qaoa"; document.querySelectorAll(".algo").forEach(x => x.classList.toggle("sel", x.dataset.algo === "qaoa")); $("pSlider").value = 2; $("pVal").textContent = "2"; state.tour.waitRun = true; runLive(reqBody()); } },
  { tab: "exec", tag: "PHASE 4/5 · READOUT", title: "Collapse and decode",
    text: "Shots vote for bitstrings; the amber BEST respects K. The state grid below shows interference amplifying the winner.",
    run() {} },
  { tab: "results", tag: "PHASE 5/5 · VERIFY", title: "Does it pay?",
    text: "Frontier position, 3-year backtest vs benchmark, full metric HUD, and the 6-way showdown. Finish with DOSSIER for a printable report.",
    run() { openDossier(); } },
];
function syncAssetChecks() {
  document.querySelectorAll('#assetBody input[type=checkbox]').forEach(cb => {
    const on = state.tickers.includes(cb.dataset.t);
    cb.checked = on; cb.closest("tr").classList.toggle("sel", on);
  });
}
$("tourBtn").addEventListener("click", () => { state.tour = { i: 0, waitRun: false }; $("tourOverlay").style.display = ""; tourShow(); });
$("tourSkip").addEventListener("click", (e) => { e.preventDefault(); tourEnd(); });
$("tourBack").addEventListener("click", () => { if (state.tour.i > 0) { state.tour.i--; tourShow(); } });
$("tourNext").addEventListener("click", () => tourAdvance());
function tourShow() {
  const s = TOUR[state.tour.i];
  goTab(s.tab);
  $("tourTag").textContent = s.tag; $("tourTitle").textContent = s.title; $("tourText").textContent = s.text;
  $("tourNext").textContent = state.tour.i === TOUR.length - 1 ? "FINISH" : "NEXT →";
  s.run();
  if (!(state.tour.waitRun)) { /* static step */ }
}
function tourAdvance() {
  if (state.tour.i >= TOUR.length - 1) { tourEnd(); return; }
  state.tour.i++; tourShow();
}
function tourEnd() { $("tourOverlay").style.display = "none"; state.tour = null; }

/* ---------------- faculty dossier ---------------- */
$("dossierBtn").addEventListener("click", openDossier);
$("printBtn").addEventListener("click", () => window.print());
function openDossier() {
  if (!state.last) { alert("Run the optimizer first — the dossier prints your live results."); return; }
  buildDossier(state.last);
  $("dossierOverlay").style.display = "";
  document.querySelector("#dossierOverlay .modal").classList.add("print-area");
  document.body.classList.add("printing");
}
function row4(m) {
  const f = (v, suf) => (v === undefined || v === null) ? "—" : v + (suf || "");
  return `<td>${f(m.ann_return, "%")}</td><td>${f(m.ann_vol, "%")}</td><td>${f(m.sharpe)}</td><td>${f(m.sortino)}</td><td>${f(m.max_dd, "%")}</td>`;
}
function buildDossier(j) {
  const M = j.math, D = new Date().toLocaleString();
  const tbl = (rows) => `<table><tr><th>TICKER</th><th>μ %</th><th>σ %</th><th>WEIGHT %</th></tr>${rows}</table>`;
  const holdRows = j.selected.map(s => `<tr><td>${s.ticker}</td><td>${s.mu_pct}</td><td>${s.sigma_pct}</td><td>${s.weight_pct}</td></tr>`).join("");
  const top = (j.histogram || []).slice(0, 8).map(h => `<tr><td class="mono">${h.bitstring}</td><td>${(h.prob * 100).toFixed(2)}%</td><td>${h.feasible ? "yes" : "no"}</td><td>${h.energy}</td></tr>`).join("");
  const qi = j.qubit_info || [];
  const mw = qi.length ? (2 * (1 - qi.reduce((a, q) => a + q.purity, 0) / qi.length)).toFixed(3) : "n/a";
  const sub = j.subspace || {};
  $("dossierBody").innerHTML =
    `<h1>Quantum Portfolio Optimization — Faculty Dossier</h1>` +
    `<div>Generated ${D} · Q-TERMINAL · run #${j.run_id ?? "—"}</div>` +
    `<h2>1 · Configuration</h2><div class="mono">universe [${j.tickers.join(" ")}] · K=${M.K} · q=${M.risk_q} · source=${(j.source_info || {}).source} · algorithm=${j.algorithm} · mixer=${j.mixer} · p=${$("pSlider").value} · shots=${$("shotsSel").value} · optimizer=${$("optSel").value} · CVaR α=${j.cvar_alpha} · noise=${(j.noise || {}).mode}${j.noise && j.noise.zne ? " + ZNE" : ""} · backend=${j.backend} · ${j.seconds}s${(j.circuit || {}).routing ? " · routed CNOT " + j.circuit.routing.linear.physical_cnot_lb + "–" + ((j.circuit.routing.heavy_hex || {}).physical_cnot_ub || j.circuit.routing.linear.physical_cnot_lb) : ""}</div>` +
    `<h2>2 · Selected portfolio</h2>${tbl(holdRows)}` +
    `<h2>3 · Comparative metrics (3y backtest, ${j.rebalance})</h2>` +
    `<table><tr><th>PORTFOLIO</th><th>RET %</th><th>VOL %</th><th>SHARPE</th><th>SORTINO</th><th>MAXDD %</th></tr>` +
    `<tr><td>Quantum (${j.algorithm})</td>${row4(j.metrics)}</tr>` +
    `<tr><td>Classical exact</td>${row4(j.metrics_classical || {})}</tr>` +
    `<tr><td>Equal weight 1/N</td>${row4(j.metrics_eq || {})}</tr>` +
    `<tr><td>Benchmark (${j.bench_label})</td>${row4(j.metrics_spy)}</tr></table>` +
    `<h2>4 · Measurement outcomes</h2><table><tr><th>BITSTRING</th><th>PROB</th><th>FEASIBLE</th><th>ENERGY</th></tr>${top}</table>` +
    `<h2>5 · Math appendix</h2><div class="mono">QUBO diag: [${M.qubo.map((r, i) => r[i].toFixed(2)).join(", ")}]<br>h: [${M.ising_h.join(", ")}]<br>offset: ${M.ising_offset} · penalty P=${M.penalty}</div>` +
    `<h2>6 · Quantum signature</h2><div class="mono">approx ratio α=${j.approx_ratio} (answer-based, [0,1]) · distribution ratio=${j.approx_expect} · leakage η=${sub.leakage === null || sub.leakage === undefined ? "n/a" : (sub.leakage * 100).toFixed(2) + "%"} · Meyer-Wallach Q=${mw}${j.noise && j.noise.zne ? " · ZNE E(0)=" + j.noise.zne.mitigated : ""}${j.spectral && !j.spectral.skipped ? " · Δmin=" + j.spectral.delta_min + " @ s=" + j.spectral.s_star : ""}</div>` +
    `<h2>7 · Reviewer talking points</h2><div>` +
    `<b>Subspace vs penalty.</b> XY enforces [H<sub>M</sub>, ΣZ]=0 on a Dicke state: zero infeasible bitstrings by symmetry, no λ tuning.<br>` +
    `<b>Tail vs expectation.</b> CVaR<sub>α</sub> optimizes only the ground-state tail, filtering shot noise the mean must absorb.<br>` +
    `<b>Gap vs barrier.</b> Annealing time obeys t<sub>f</sub> >> 1/Δ<sub>min</sub><sup>2</sup>; tunneling wins where barriers are tall and narrow.<br>` +
    `<b>NISQ honesty.</b> Classical exact wins 10-asset instances in milliseconds. This platform studies landscape controllability, depth trade-offs and mitigation profiles for the fault-tolerant era — not supremacy.</div>` +
    `<h2>8 · Verdict</h2><div>${j.summary}</div>`;
}

/* ---------------- experiment history ---------------- */
async function loadHistory() {
  try {
    const j = await (await fetch("/api/runs?limit=20")).json();
    $("histBody").innerHTML = j.runs.length ? j.runs.map(r =>
      `<tr><td>${r.id}</td><td>${r.algorithm}${r.mixer === "xy" ? "+XY" : ""}</td><td class="n">${r.noise}</td><td class="n">${r.cvar}</td><td>${r.bitstring || "—"}</td><td class="n">${r.energy === null ? "—" : Number(r.energy).toFixed(3)}</td><td class="n">${r.sharpe === null ? "—" : r.sharpe}</td></tr>`).join("")
      : `<tr><td colspan="7" style="color:var(--dim)">No runs logged yet.</td></tr>`;
    drawRunsChart(j.runs);
  } catch (e) { /* offline */ }
}
function drawRunsChart(runs) {
  const o = ctx2d($("runsChart")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 52, t: 10, r: 52, b: 22 };
  axes(c, W, H, pad);
  const pts = (runs || []).slice().reverse()
    .filter(r => r.energy !== null && r.energy !== undefined);
  if (pts.length < 2) {
    c.fillStyle = "#636363"; c.font = "11px 'JetBrains Mono',monospace";
    c.fillText("need 2+ logged runs for a trend", pad.l + 8, 30); return;
  }
  const es = pts.map(r => r.energy), ss = pts.map(r => r.sharpe === null ? 0 : r.sharpe);
  const e0 = Math.min(...es), e1 = Math.max(...es), s0 = Math.min(...ss), s1 = Math.max(...ss);
  const X = i => pad.l + i / (pts.length - 1) * (W - pad.l - pad.r);
  const Ye = v => pad.t + (1 - (v - e0) / Math.max(e1 - e0, 1e-9)) * (H - pad.t - pad.b);
  const Ys = v => pad.t + (1 - (v - s0) / Math.max(s1 - s0, 1e-9)) * (H - pad.t - pad.b);
  c.font = "10px 'JetBrains Mono',monospace";
  c.fillStyle = CYAN; c.fillText(e0.toFixed(2), 2, Ye(e0) + 3); c.fillText(e1.toFixed(2), 2, Ye(e1) + 3);
  c.fillStyle = AMBER; c.fillText(s0.toFixed(2), W - pad.r + 4, Ys(s0) + 3); c.fillText(s1.toFixed(2), W - pad.r + 4, Ys(s1) + 3);
  const line = (vals, Y, col) => {
    c.strokeStyle = col; c.lineWidth = 1.5; c.beginPath();
    vals.forEach((v, i) => i ? c.lineTo(X(i), Y(v)) : c.moveTo(X(i), Y(v))); c.stroke();
    vals.forEach((v, i) => { c.fillStyle = col; c.fillRect(X(i) - 2, Y(v) - 2, 4, 4); });
  };
  line(es, Ye, CYAN); line(ss, Ys, AMBER);
  c.fillStyle = "#636363"; c.fillText("run # →", W - 70, H - 6);
}
$("histRefresh").addEventListener("click", loadHistory);
$("histClear").addEventListener("click", async () => { await fetch("/api/runs", { method: "DELETE" }); loadHistory(); });

/* ---------------- QPU modal ---------------- */
$("qpuBtn").addEventListener("click", () => { $("qpuModal").style.display = ""; });
$("qpuTest").addEventListener("click", async () => {
  $("qpuOut").textContent = "checking …";
  try {
    const j = await (await fetch("/api/qpu/status")).json();
    $("qpuOut").textContent = `connected: ${j.connected}\nruntime installed: ${j.runtime_installed}\n${j.message}`;
  } catch (e) { $("qpuOut").textContent = "backend unreachable"; }
});
document.addEventListener("click", (e) => {
  const c = e.target.closest("[data-close]"); if (c) $(c.dataset.close).style.display = "none";
});

/* ---------------- quantum signature panel ---------------- */
function mwQ(j) {
  const qi = j.qubit_info;
  if (!qi || !qi.length) return null;
  return 2 * (1 - qi.reduce((a, q) => a + q.purity, 0) / qi.length);
}
function weightBarsHTML(j) {
  const wd = j.weight_dist, K = (j.best_bitstring || "").length ? null : null;
  if (!wd) return "";
  const k = (j.subspace || {}).K;
  const mx = Math.max(...Object.values(wd).map(Number), 1e-9);
  return `<div style="margin-top:6px;font-size:11px;color:var(--mut)">HAMMING-WEIGHT MASS (sums to 1.000 — same distribution as histogram+grid):</div>` +
    Object.keys(wd).sort((a, b) => a - b).map(w => {
      const v = Number(wd[w]), isK = Number(w) === k;
      return `<div class="wbar"><span class="wl">w=${w}${isK ? " ★" : ""}</span>` +
        `<span class="wt"><span class="wf${isK ? " k" : ""}" style="width:${(v / mx * 100).toFixed(1)}%"></span></span>` +
        `<span class="wv">${v.toFixed(4)}</span></div>`;
    }).join("");
}
function renderSignature(j) {
  const el = $("sigBody"), cv = $("sigCanvas"), wb = $("weightBars");
  cv.style.display = "none"; wb.innerHTML = "";
  const fam = j.algorithm || "";
  const L = [];
  L.push(`<div class="sigline">SOLVER <b>${fam}</b> · backend ${j.backend}</div>`);
  if (j.approx_ratio !== null && j.approx_ratio !== undefined)
    L.push(`<div class="sigline">APPROX RATIO <b style="color:var(--cyan)">α=${j.approx_ratio}</b> = (E_best−Emax)/(Emin−Emax) on [${j.e_min_feas}, ${j.e_max_feas}]; 1.000 = exact optimum.</div>`);
  if (j.approx_expect !== null && j.approx_expect !== undefined)
    L.push(`<div class="sigline">DISTRIBUTION RATIO <b>${j.approx_expect}</b> (same formula on &lt;H&gt;; &lt;0 means leakage dominates).</div>`);
  const sub = j.subspace || {};
  if (sub.feasible_mass !== null && sub.feasible_mass !== undefined)
    L.push(`<div class="sigline">SUBSPACE LEAKAGE <b style="color:${sub.leakage === 0 ? "var(--green)" : "var(--amber)"}">η=${(sub.leakage * 100).toFixed(2)}%</b> (mass outside C(${sub.N},${sub.K})).</div>`);
  if (fam.indexOf("Classical") === 0) {
    L.push(`<div class="sigline">Enumerates all <b>2^${sub.N}=${sub.total}</b> portfolios — α=1.000 by construction. No superposition involved.</div>`);
  } else if (fam.indexOf("QAOA-XY") === 0) {
    L.push(`<div class="sigline">Dicke D(${sub.N},${sub.K}) + XY ring: [H<sub>M</sub><sup>XY</sup>, ΣZ]=0 confines the walk; penalty <b>${j.penalty_note || "none"}</b>.</div>`);
  } else if (fam.indexOf("QAOA") === 0) {
    L.push(`<div class="sigline">Trotterized U(C,γ)U(M,β) × p with RZZ→CNOT–RZ–CNOT entanglers; single-shot SEED breaks permutation symmetry.</div>`);
  } else if (fam.indexOf("VQE") === 0) {
    const q = mwQ(j);
    L.push(`<div class="sigline">EfficientSU2 ansatz. MEYER-WALLACH <b style="color:var(--cyan)">Q=${q === null ? "n/a" : q.toFixed(3)}</b> (0 = product, 1 = maximally entangled).</div>`);
    if ((j.cvar_alpha || 1) < 1) L.push(`<div class="sigline">CVaR α=${j.cvar_alpha}: optimizer saw only the tail below <b>E ≤ ${j.cvar_cutoff}</b> (amber caps on histogram).</div>`);
  } else if (fam.indexOf("Quantum Annealing") === 0) {
    L.push(`<div class="sigline">Transverse driver −A(s)ΣX vs problem B(s)H<sub>C</sub>; tunneling ∝ exp(−w√ΔV) beats thermal hopping on tall narrow barriers.</div>`);
  } else {
    L.push(`<div class="sigline">Classical thermal annealing (Metropolis) — no superposition or tunneling; the quantum control is QA/VQE/QAOA above.</div>`);
  }
  el.innerHTML = L.join("");
  if (j.weight_dist) wb.innerHTML = weightBarsHTML(j);
  if (j.landscape && fam.indexOf("VQE") !== 0) { cv.style.display = ""; drawContour(j.landscape); }
  if (j.spectral && !j.spectral.skipped) { cv.style.display = ""; drawSchedule(j.spectral); }
}
function drawContour(L) {
  const o = ctx2d($("sigCanvas")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 46, t: 10, r: 10, b: 26 };
  axes(c, W, H, pad);
  const G = L.gamma.length, B = L.beta.length;
  let lo = 1e18, hi = -1e18;
  L.Z.forEach(row => row.forEach(v => { lo = Math.min(lo, v); hi = Math.max(hi, v); }));
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const cw = (W - pad.l - pad.r) / G, ch = (H - pad.t - pad.b) / B;
  for (let j = 0; j < B; j++) for (let i = 0; i < G; i++) {
    const t = (hi - L.Z[j][i]) / (hi - lo);
    c.fillStyle = `rgba(0,229,255,${(0.06 + 0.9 * t).toFixed(2)})`;
    c.fillRect(pad.l + i * cw, pad.t + j * ch, cw, ch);
  }
  const X = g => pad.l + g / (2 * Math.PI) * (W - pad.l - pad.r);
  const Y = b => pad.t + (1 - b / Math.PI) * (H - pad.t - pad.b);
  c.font = "10px 'JetBrains Mono',monospace"; c.fillStyle = "#636363";
  c.fillText("γ 0", pad.l - 2, H - 8); c.fillText("2π", W - pad.r - 12, H - 8);
  c.fillText("β π", 4, pad.t + 8); c.fillText("0", 4, H - pad.b);
  c.fillText("p=1 ENERGY LANDSCAPE (bright = low) + COBYLA PATH (clipped to box)", pad.l + 6, pad.t + 12);
  const path = L.path || [];
  if (path.length > 1) {
    c.strokeStyle = AMBER; c.lineWidth = 2; c.beginPath();
    path.forEach((p, i) => i ? c.lineTo(X(p[0]), Y(p[1])) : c.moveTo(X(p[0]), Y(p[1])));
    c.stroke();
    c.fillStyle = GREEN; c.fillRect(X(path[0][0]) - 3, Y(path[0][1]) - 3, 6, 6);
    const e = path[path.length - 1];
    c.fillStyle = RED; c.fillRect(X(e[0]) - 3, Y(e[1]) - 3, 6, 6);
  }
}
function drawSchedule(sp) {
  const o = ctx2d($("sigCanvas")); const c = o.c, W = o.W, H = o.H;
  const pad = { l: 46, t: 10, r: 10, b: 22 };
  axes(c, W, H, pad);
  const n = sp.s.length;
  const X = i => pad.l + i / (n - 1) * (W - pad.l - pad.r);
  const mx = Math.max(...sp.A, ...sp.B, 1e-9);
  const Y = v => pad.t + (1 - v / mx) * (H - pad.t - pad.b);
  const line = (arr, col) => {
    c.strokeStyle = col; c.lineWidth = 2; c.beginPath();
    arr.forEach((v, i) => i ? c.lineTo(X(i), Y(v)) : c.moveTo(X(i), Y(v))); c.stroke();
  };
  line(sp.A, AMBER); line(sp.B, CYAN);
  c.font = "10px 'JetBrains Mono',monospace";
  c.fillStyle = AMBER; c.fillText("A(s) driver", pad.l + 6, pad.t + 12);
  c.fillStyle = CYAN; c.fillText("B(s) problem", pad.l + 6, pad.t + 24);
  const iStar = sp.s.indexOf(sp.s_star);
  c.strokeStyle = "#fff"; c.setLineDash([4, 3]);
  c.beginPath(); c.moveTo(X(iStar), pad.t); c.lineTo(X(iStar), H - pad.b); c.stroke(); c.setLineDash([]);
  c.fillStyle = "#fff"; c.fillText(`Δmin=${sp.delta_min} @ s=${sp.s_star} → tf >> 1/Δ²`, Math.min(X(iStar) + 6, W - 190), pad.t + 38);
}

/* ---------------- Bloch projection ---------------- */
/* ---------------- Bloch carousel (all qubits side-by-side) ---------------- */
function renderBloch(j) {
  const grid = $("blochGrid");
  const qi = j.qubit_info, tk = j.tickers || [], best = j.best_bitstring || "";
  if (!qi || !qi.length) {
    grid.innerHTML = "";
    $("blochRead").textContent = "Qubit states unavailable on this path (classical / annealer / fallback).";
    const o = ctx2d($("blochCanvas")); o.c.fillStyle = "#636363";
    o.c.font = "12px 'JetBrains Mono',monospace"; o.c.fillText("no quantum state", 20, 30);
    return;
  }
  const order = qi.map((q, i) => i).sort((a, b) => qi[a].bloch[2] - qi[b].bloch[2]);
  grid.innerHTML = order.map((m, rank) => {
    const q = qi[m];
    const leanHeld = q.bloch[2] < 0;
    const agree = best && ((leanHeld && best[m] === "1") || (!leanHeld && best[m] === "0"));
    return `<div class="bcell" data-m="${m}"><canvas id="mini${m}" width="120" height="104"></canvas>` +
      `<div class="bt"><b>#${rank + 1} ${tk[m] || ("q" + m)}</b> <span class="${agree ? "okq" : "badq"}">${agree ? "✓" : "✗"}</span></div>` +
      `<div class="bsub">z=${q.bloch[2]} |r|=${q.rlen} ${leanHeld ? "HELD-lean" : "SKIP-lean"}</div></div>`;
  }).join("");
  order.forEach(m => drawMiniBloch(j, m));
  grid.querySelectorAll(".bcell").forEach(cell => {
    cell.onclick = () => {
      grid.querySelectorAll(".bcell").forEach(x => x.classList.remove("sel"));
      cell.classList.add("sel");
      drawBloch(j, parseInt(cell.dataset.m));
    };
  });
  const first = grid.querySelector(".bcell");
  if (first) first.classList.add("sel");
  drawBloch(j, order[0]);
}
function drawMiniBloch(j, m) {
  const cv = $("mini" + m); if (!cv) return;
  const c = cv.getContext("2d");
  const cx = 60, cy = 50, R = 42;
  c.clearRect(0, 0, 120, 104);
  c.strokeStyle = "#3d3d3d"; c.lineWidth = 1;
  c.beginPath(); c.arc(cx, cy, R, 0, 7); c.stroke();
  const traj = j.bloch_traj || [];
  if (traj.length > 1) {
    c.strokeStyle = "rgba(255,255,255,.4)"; c.lineWidth = 1; c.beginPath();
    traj.forEach((f, i) => {
      const b = f.bloch[m], px = cx + b[0] * R, py = cy - b[2] * R;
      i ? c.lineTo(px, py) : c.moveTo(px, py);
    });
    c.stroke();
  }
  const q = j.qubit_info[m], b = q.bloch;
  c.strokeStyle = "#00d084"; c.lineWidth = 2;
  c.beginPath(); c.moveTo(cx, cy); c.lineTo(cx + b[0] * R, cy - b[2] * R); c.stroke();
  c.fillStyle = "#00d084"; c.beginPath(); c.arc(cx + b[0] * R, cy - b[2] * R, 3, 0, 7); c.fill();
}
function drawBloch(j, m) {
  const q = j.qubit_info[m]; if (!q) return;
  const o = ctx2d($("blochCanvas")); const c = o.c, W = o.W, H = o.H;
  const cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 26;
  c.strokeStyle = "#3d3d3d"; c.lineWidth = 1.5;
  c.beginPath(); c.arc(cx, cy, R, 0, 7); c.stroke();
  c.strokeStyle = "#2b2b2b";
  c.beginPath(); c.ellipse(cx, cy, R, R * 0.35, 0, 0, 7); c.stroke();
  c.beginPath(); c.ellipse(cx, cy, R * 0.35, R, 0, 0, 7); c.stroke();
  c.font = "10px 'JetBrains Mono',monospace"; c.fillStyle = "#636363";
  c.fillText("|0> skip", cx - 22, cy - R - 5); c.fillText("|1> hold", cx - 22, cy + R + 12);
  c.fillText("|+>", cx + R + 4, cy + 3); c.fillText("|->", cx - R - 20, cy + 3);
  const [x, y, z] = q.bloch;
  const ex = cx + x * R, ey = cy - z * R;
  const traj = j.bloch_traj || [];
  if (traj.length > 1) {
    c.strokeStyle = "rgba(255,255,255,.4)"; c.lineWidth = 1; c.beginPath();
    traj.forEach((f, i) => {
      const b = f.bloch[m], px = cx + b[0] * R, py = cy - b[2] * R;
      i ? c.lineTo(px, py) : c.moveTo(px, py);
    });
    c.stroke();
    c.fillStyle = "#636363"; c.font = "10px 'JetBrains Mono',monospace";
    c.fillText("trail: equator → final (" + traj.length + " frames)", cx - R, cy + R + 14);
  }
  c.strokeStyle = CYAN; c.lineWidth = 2.5;
  c.beginPath(); c.moveTo(cx, cy); c.lineTo(ex, ey); c.stroke();
  c.fillStyle = CYAN; c.beginPath(); c.arc(ex, ey, 4, 0, 7); c.fill();
  const sep = q.rlen >= 0.95;
  $("blochRead").innerHTML =
    `|r|=<b>${q.rlen}</b> purity=<b>${q.purity}</b> S=<b>${q.entropy}</b> nats (y=${y}) · ` +
    (sep ? `<b style="color:var(--green)">NEAR-SEPARABLE</b> — decide: ${z < 0 ? "leans HELD (|1>)" : "leans SKIPPED (|0>)"}.`
         : `<b style="color:var(--amber)">ENTANGLED</b> (mixed) — fate tied to other assets.`);
}

/* ---------------- Ising coupling network graph ---------------- */
function drawIsing(j) {
  const svg = $("isingGraph");
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const M = j.math || {}, tk = j.tickers || [];
  const n = tk.length;
  if (!n || !M.ising_h) {
    svg.setAttribute("width", 560); svg.setAttribute("height", 60);
    return;
  }
  const NS = "http://www.w3.org/2000/svg";
  const W = 560, H = 300;
  svg.setAttribute("width", W); svg.setAttribute("height", H);
  const mk = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    svg.appendChild(e); return e;
  };
  const h = M.ising_h.map(Number), J = (M.ising_J || []).map(r => r.map(Number));
  const mh = Math.max(...h.map(Math.abs), 1e-9);
  let mj = 1e-9;
  J.forEach((row, i) => row.forEach((v, k) => { if (k > i) mj = Math.max(mj, Math.abs(v)); }));
  const cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 52;
  const pos = tk.map((t, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [cx + R * Math.cos(a), cy + R * Math.sin(a)];
  });
  J.forEach((row, i) => row.forEach((v, k) => {
    if (k <= i || Math.abs(v) < 1e-9) return;
    const e = mk("line", { x1: pos[i][0], y1: pos[i][1], x2: pos[k][0], y2: pos[k][1],
      stroke: "#9a9a9a", "stroke-width": (0.75 + 3 * Math.abs(v) / mj).toFixed(1) });
    if (v < 0) e.setAttribute("stroke-dasharray", "5 3");
    const tt = document.createElementNS(NS, "title");
    tt.textContent = `J ${tk[i]}${tk[k]} = ${v}`;
    e.appendChild(tt);
  }));
  tk.forEach((t, i) => {
    const r = 8 + 14 * Math.abs(h[i]) / mh;
    const nd = mk("circle", { cx: pos[i][0], cy: pos[i][1], r: r.toFixed(1),
      fill: h[i] < 0 ? CYAN : RED, stroke: "#000", "stroke-width": 1.5 });
    const tt = document.createElementNS(NS, "title");
    tt.textContent = `h[${t}] = ${h[i]}`;
    nd.appendChild(tt);
    const lt = mk("text", { x: pos[i][0], y: pos[i][1] - r - 5, "text-anchor": "middle",
      fill: "#fff", "font-size": 11, "font-weight": "bold", "font-family": "'JetBrains Mono',monospace" });
    lt.textContent = t;
    const hv = mk("text", { x: pos[i][0], y: pos[i][1] + r + 13, "text-anchor": "middle",
      fill: "#9a9a9a", "font-size": 9, "font-family": "'JetBrains Mono',monospace" });
    hv.textContent = h[i].toFixed(2);
  });
  const cap = mk("text", { x: 10, y: H - 8, fill: "#636363", "font-size": 10, "font-family": "'JetBrains Mono',monospace" });
  cap.textContent = `h range [${Math.min(...h).toFixed(2)}, ${Math.max(...h).toFixed(2)}] · |J|max ${mj.toFixed(2)} · solid J>0 / dashed J<0`;
}

/* ---------------- subspace slicer (concentric graphic) ---------------- */
function renderSlicer(j) {
  const el = $("sliceBox"), sub = j.subspace || {};
  if (!sub.total) { el.textContent = "RUN first — mass split appears here."; return; }
  const inPct = ((sub.feasible_mass || 0) * 100).toFixed(2);
  const outPct = (100 - inPct).toFixed(2);
  const stars = (j.histogram || []).filter(h => h.feasible).slice(0, 5)
    .map(h => `★ ${h.bitstring} (${(h.prob * 100).toFixed(2)}%)`).join(" &nbsp; ");
  const W = 560, H = 200;
  const side = Math.sqrt(sub.feasible_count / sub.total) * (H - 70);
  const ix = (W - side) / 2, iy = 34 + (H - 70 - side) / 2;
  el.innerHTML =
    `<svg width="${W}" height="${H}" style="max-width:100%;background:#000;border:1px solid var(--line)">` +
    `<rect x="8" y="26" width="${W - 16}" height="${H - 66}" fill="none" stroke="#3d3d3d" stroke-width="1.5"/>` +
    `<text x="14" y="18" fill="#9a9a9a" font-size="10" font-family="'JetBrains Mono',monospace">2^${sub.N} = ${sub.total} states · outside mass ${outPct}% (penalty-suppressed)</text>` +
    `<rect x="${ix.toFixed(0)}" y="${iy.toFixed(0)}" width="${side.toFixed(0)}" height="${side.toFixed(0)}" fill="rgba(0,229,255,.07)" stroke="${CYAN}" stroke-width="2"/>` +
    `<text x="${(W / 2).toFixed(0)}" y="${(iy + side / 2 - 4).toFixed(0)}" text-anchor="middle" fill="${CYAN}" font-size="11" font-weight="bold" font-family="'JetBrains Mono',monospace">C(${sub.N},${sub.K}) = ${sub.feasible_count}</text>` +
    `<text x="${(W / 2).toFixed(0)}" y="${(iy + side / 2 + 12).toFixed(0)}" text-anchor="middle" fill="${CYAN}" font-size="11" font-family="'JetBrains Mono',monospace">inside mass ${inPct}%</text>` +
    `<rect x="8" y="${H - 28}" width="${((W - 16) * sub.feasible_mass).toFixed(0)}" height="8" fill="${CYAN}"/>` +
    `<rect x="${(8 + (W - 16) * sub.feasible_mass).toFixed(0)}" y="${H - 28}" width="${((W - 16) * (1 - sub.feasible_mass)).toFixed(0)}" height="8" fill="#5a1f28"/>` +
    `</svg><div style="margin-top:6px;font-size:12px">${stars || "—"}</div>` +
    `<div style="margin-top:4px;font-size:12px;color:var(--mut)">Standard QAOA spills into the outer box (leakage η=${((sub.leakage || 0) * 100).toFixed(2)}%). QAOA-XY never leaves the ball ([H<sub>M</sub>, ΣZ] = 0).</div>`;
}

/* ---------------- boot ---------------- */
loadUniverse().catch(e => { $("statusLine").textContent = "backend unreachable — run: uvicorn backend.main:app --port 8000 :: " + e.message; });
loadHistory();
