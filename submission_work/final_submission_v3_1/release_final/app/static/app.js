/* app.js — 图谱交互：搜索/渐进展开/筛选/时间轴/最短路/证据抽屉/导出 */
"use strict";

const $ = (id) => document.getElementById(id);
const API = (p) => fetch(p).then((r) => r.json());

const TYPE_COLOR = { Person: "#d9a35c", Event: "#4fd1c5", Place: "#7fbf8e",
  Organization: "#6f9fd8", Institution: "#6f9fd8", Concept: "#a08fd8",
  Document: "#c8b98f", AdministrativeRegion: "#7fbf8e", Spirit: "#d88fb0" };
const colorOf = (t) => TYPE_COLOR[t] || "#8a96ad";
const TIER_STYLE = {
  STRICT:     { color: "#e2c37b", size: 3 },
  CONTEXTUAL: { color: "#5f7ea8", size: 1.5 },
  UNRESOLVED: { color: "#55607a", size: 1 },
};

const graph = new graphology.Graph({ multi: true, type: "directed" });
let renderer = null;
let selectedEntity = null;
let pathMode = false, pathSrc = null;
const filterState = { tiers: new Set(["strict_semantic"]), types: new Set(), preds: new Set(), t0: "", t1: "" };
const edgeIndex = new Map();   // fact_id -> edge key in graph

/* ---------- sigma 初始化 ---------- */
function initRenderer() {
  renderer = new Sigma(graph, $("graph"), {
    renderEdges: true, defaultEdgeType: "line",
    minCameraRatio: 0.08, maxCameraRatio: 12,
    labelDensity: 2.2, labelGridSize: 90, labelSize: "fixed",
    defaultLabelSize: 12, labelWeight: "600",
    defaultNodeColor: "#8a96ad", defaultEdgeColor: "#3a4763",
    labelRenderedSizeThreshold: 8,
    nodeReducer: (node, data) => {
      const res = { ...data };
      if (pathMode && node !== pathSrc) { res.color = "#3a4763"; res.size = Math.max(3, data.size * .7); }
      if (data._hl) { res.color = "#ffe9b0"; res.size = data.size * 1.5; res.forceLabel = true; }
      return res;
    },
    edgeReducer: (edge, data) => {
      const res = { ...data };
      if (data._hl) { res.color = "#ffd479"; res.size = 3; res.forceLabel = false; }
      return res;
    },
  });
  renderer.on("clickNode", ({ node }) => {
    const d = graph.getNodeAttribute(node, "kind");
    if (pathMode) { handlePathClick(node); return; }
    expandNode(node);
    openEntity(node);
  });
  renderer.on("clickEdge", ({ edge }) => openEvidence(edge));
  renderer.on("clickStage", () => { /* keep graph */ });
}

/* ---------- 节点/边操作 ---------- */
function upsertNode(id, name, type) {
  if (!id || graph.hasNode(id)) return;
  graph.addNode(id, {
    label: name || id, kind: { id, name, type },
    x: Math.cos(Math.random() * 6.28) * 40, y: Math.sin(Math.random() * 6.28) * 40,
    size: 6, color: colorOf(type),
  });
}
function upsertEdge(e) {
  if (!e.subject_id || !e.object_id || e.subject_id === e.object_id) return;
  if (edgeIndex.has(e.fact_id)) return;
  const s = TIER_STYLE[e.research_tier] || TIER_STYLE.UNRESOLVED;
  const key = graph.addEdge(e.subject_id, e.object_id, {
    factId: e.fact_id, predicate: e.predicate, tier: e.research_tier,
    color: s.color, size: s.size, label: "",
    hover_label: `${e.predicate} (${e.research_tier})`,
  });
  edgeIndex.set(e.fact_id, key);
  const sd = graph.getNodeAttribute(e.subject_id, "_deg") || 0;
  const od = graph.getNodeAttribute(e.object_id, "_deg") || 0;
  graph.setNodeAttribute(e.subject_id, "_deg", sd + 1);
  graph.setNodeAttribute(e.object_id, "_deg", od + 1);
  graph.setNodeAttribute(e.subject_id, "size", 6 + Math.min(14, sd * .8));
  graph.setNodeAttribute(e.object_id, "size", 6 + Math.min(14, od * .8));
}
function applyTierVisibility() {
  graph.forEachEdge((k, a) => {
    const visible = filterState.tiers.has(a.tier);
    graph.setEdgeAttribute(k, "hidden", !visible);
  });
  refreshCounts();
}
function refreshCounts() {
  $("st-nodes").textContent = `节点 ${graph.order}`;
  $("st-edges").textContent = `连线 ${graph.size}`;
}

/* ---------- 布局（内置力导向，≤2000 节点流畅） ---------- */
let layoutTimer = null;
function runLayout(iterations = 240, onDone = null) {
  const nodes = graph.nodes();
  if (nodes.length < 2) return;
  const N = nodes.length;
  const pos = new Map(nodes.map((n) => [n, { ...graph.getNodeAttributes(n) }]));
  let scale = Math.max(30, Math.sqrt(N) * 12);
  nodes.forEach((n, i) => { if (!pos.get(n).x) { pos.get(n).x = Math.cos(i / N * 6.28) * scale; pos.get(n).y = Math.sin(i / N * 6.28) * scale; } });
  let tick = 0;
  const step = () => {
    const cool = 1 - tick / iterations;
    const f = new Map(nodes.map((n) => [n, { x: 0, y: 0 }]));
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const a = pos.get(nodes[i]), b = pos.get(nodes[j]);
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy; if (d2 < 1e-4) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = 1e-4; }
      const rep = 900 / d2; const d = Math.sqrt(d2);
      f.get(nodes[i]).x += dx / d * rep; f.get(nodes[i]).y += dy / d * rep;
      f.get(nodes[j]).x -= dx / d * rep; f.get(nodes[j]).y -= dy / d * rep;
    }
    graph.forEachEdge((k, attr, s, t) => {
      const a = pos.get(s), b = pos.get(t); if (!a || !b) return;
      const dx = a.x - b.x, dy = a.y - b.y; const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1e-4);
      const att = d / 60;
      f.get(s).x -= dx / d * att; f.get(s).y -= dy / d * att;
      f.get(t).x += dx / d * att; f.get(t).y += dy / d * att;
    });
    nodes.forEach((n) => { const p = pos.get(n), fo = f.get(n); p.x += fo.x * .08 * cool; p.y += fo.y * .08 * cool; });
    tick++;
    nodes.forEach((n) => graph.setNodeAttribute(n, "x", pos.get(n).x));
    nodes.forEach((n) => graph.setNodeAttribute(n, "y", pos.get(n).y));
    renderer.refresh();
    if (tick < iterations) { layoutTimer = requestAnimationFrame(step); }
    else if (onDone) { onDone(); }
  };
  cancelAnimationFrame(layoutTimer);
  layoutTimer = requestAnimationFrame(step);
}

/* ---------- 数据载入 ---------- */
async function expandNode(nodeId) {
  const tiers = [...filterState.tiers].join(",") || "strict_semantic";
  const types = [...filterState.types].join(",");
  const preds = [...filterState.preds].join(",");
  const url = `/api/neighbors/${nodeId}?tiers=${tiers}&types=${types}&preds=${preds}` +
    `&t0=${filterState.t0}&t1=${filterState.t1}&limit=250`;
  const data = await API(url);
  const fresh = data.edges.filter((e) => !edgeIndex.has(e.fact_id));
  fresh.forEach((e) => {
    upsertNode(e.subject_id, e.subject_name, e.subject_type);
    upsertNode(e.object_id, e.object_name, e.object_type);
    upsertEdge(e);
  });
  if (fresh.length) runLayout(120);
  applyTierVisibility();
  if (data.truncated) toast("邻居较多，仅展示前 250 条（可用筛选缩小范围）");
}

async function loadEntity(id) {
  graph.clear(); edgeIndex.clear();
  selectedEntity = id;
  const r = await API(`/api/entity/${id}`);
  if (r.error) return toast("实体不存在");
  upsertNode(id, r.entity.canonical_name, r.entity.entity_type);
  await expandNode(id);
  runLayout(260, () => {
    // 布局收敛后再聚焦：相机坐标是归一化视口坐标，必须用 getNodeDisplayData
    if (renderer && graph.hasNode(id)) {
      const d = renderer.getNodeDisplayData(id);
      if (d) renderer.getCamera().animate({ x: d.x, y: d.y, ratio: 0.8 },
                                          { duration: 350 });
    }
  });
}

/* ---------- 证据抽屉 ---------- */
function openDrawer(html) {
  $("drawer-body").innerHTML = html;
  $("right").classList.remove("hidden");
  document.querySelectorAll(".copy-id").forEach((el) =>
    el.onclick = () => { navigator.clipboard.writeText(el.dataset.id); toast("已复制 " + el.dataset.id); });
}
function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
function tierBadge(t) { return `<span class="tier-badge ${(t || "").toUpperCase()}">${esc((t || "—").toUpperCase())}</span>`; }

async function openEntity(nodeId) {
  const r = await API(`/api/entity/${nodeId}`);
  if (r.error) return;
  const e = r.entity;
  let aliases = [];
  try { aliases = JSON.parse(e.aliases_json || "[]"); } catch (_) {}
  openDrawer(`
    <div class="sec"><h4>实体</h4>
      <div class="kv">
        <span class="k">标准名</span><span><b>${esc(e.canonical_name)}</b></span>
        <span class="k">类型</span><span>${esc(e.entity_type)} · ${esc(e.semantic_family || "")}</span>
        <span class="k">别名</span><span>${esc(aliases.slice(0, 8).join("、")) || "—"}</span>
        <span class="k">活动期</span><span>${esc(r.active_from || "—")} ~ ${esc(r.active_to || "—")}</span>
        <span class="k">严格层度</span><span>${r.degree}</span>
        <span class="k">entity_id</span><span class="copy-id" data-id="${esc(e.entity_id)}">${esc(e.entity_id)}</span>
      </div></div>
    <div class="sec"><h4>操作</h4>
      <button class="tool-btn" onclick="expandNode('${e.entity_id}')">展开一跳</button>
      <button class="tool-btn" onclick="showTimeline('${e.entity_id}')">时间轴</button>
    </div>`);
}

async function openEvidence(edgeKey) {
  const fid = graph.getEdgeAttribute(edgeKey, "factId");
  const r = await API(`/api/evidence/${fid}`);
  if (r.error) return;
  const a = r.assertion, v = r.verdict, g = r.gate;
  openDrawer(`
    <div class="sec"><h4>断言</h4>
      <div class="kv">
        <span class="k">三元组</span><span><b>${esc(a.subject_name)} — ${esc(a.predicate)} — ${esc(a.object_name)}</b></span>
        <span class="k">时间</span><span>${esc(a.time_raw || "—")}（${esc(a.normalized_time_label || "")}）</span>
        <span class="k">空间</span><span>${esc(a.place_raw || "—")}</span>
        <span class="k">发布层</span><span>${tierBadge(a.research_tier)}</span>
        <span class="k">fact_id</span><span class="copy-id" data-id="${esc(a.fact_id)}">${esc(a.fact_id)}</span>
      </div></div>
    <div class="sec"><h4>语义门判定</h4>
      ${v ? `<div class="kv">
        <span class="k">判定</span><span>${tierBadge(v.decision.includes("SUPPORTED") ? (v.decision === "FULLY_SUPPORTED" ? "STRICT" : "CONTEXTUAL") : "UNRESOLVED")} ${esc(v.decision)}</span>
        <span class="k">置信度</span><span>${v.confidence != null ? Number(v.confidence).toFixed(2) : "—"} ${v.salvaged ? "· <span title='解析兜底，带审计标志'>salvaged</span>" : ""}</span>
        <span class="k">门方法</span><span>${esc(g ? g.gate_method : "—")}</span>
      </div>
      ${v.evidence_quote ? `<div class="sec"><h4>证据引文</h4><div class="quote">「${esc(v.evidence_quote)}」</div></div>` : ""}
      ${v.explanation ? `<div class="sec"><h4>判定理由（模型原文）</h4><div class="explain">${esc(v.explanation)}</div></div>` : ""}`
      : `<div class="explain">该断言属于历史口径宇宙或未含语义门判定明细。</div>`}
    </div>
    <div class="sec"><h4>溯源指针</h4>
      ${(r.provenance || []).map((p) => `<div class="explain" style="margin-bottom:6px">
        ${esc(p.provenance_kind)} · ${esc(p.source_table || "")}<br>
        <span class="copy-id" data-id="${esc(p.evidence_ids_json || "")}">${esc((p.evidence_ids_json || "").slice(0, 90)) || "—"}</span>
      </div>`).join("") || '<span class="explain">—</span>'}
    </div>`);
}

async function showTimeline(eid) {
  const r = await API(`/api/timeline/${eid}`);
  const items = r.items.map((i) => `
    <div class="tl-item">
      <span class="y">${esc((i.time_start || i.time_end || "").slice(0, 10))}</span>
      <div class="t">${esc(i.subject_name)} — ${esc(i.predicate)} — ${esc(i.object_name)}</div>
      <div class="p">${esc(i.place_raw || "")} ${tierBadge(i.research_tier)}</div>
    </div>`).join("");
  const frames = r.frames.map((f) => `
    <div class="tl-item"><span class="y">EventFrame</span>
      <div class="t">${esc(f.event_name)}</div>
      <div class="p">${esc(f.observed_time_start || "")} ~ ${esc(f.observed_time_end || "")} · ${esc(f.frame_status || "")}</div>
    </div>`).join("");
  openDrawer(`<div class="sec"><h4>时间轴 · 断言</h4>${items || '<span class="explain">无带时间断言</span>'}</div>
    <div class="sec"><h4>相关 EventFrame</h4>${frames || '<span class="explain">—</span>'}</div>`);
}

/* ---------- 最短路 ---------- */
async function handlePathClick(node) {
  if (!pathSrc) { pathSrc = node; toast("已选起点，再点终点"); renderer.refresh(); return; }
  const dst = node;
  const r = await API(`/api/path?src=${pathSrc}&dst=${dst}`);
  pathMode = false; $("btn-path").classList.remove("active");
  if (!r.path || !r.path.length) { toast("严格层无可达路径"); pathSrc = null; renderer.refresh(); return; }
  graph.forEachNode((n, a) => graph.setNodeAttribute(n, "_hl", r.path.some((p) => p.entity_id === n)));
  graph.forEachEdge((k, a) => graph.setEdgeAttribute(k, "_hl", r.edges.some((e) => e.fact_id === a.factId)));
  toast(`最短路径 ${r.hops} 跳（严格层）`);
  $("st-path").textContent = "路径: " + r.path.map((p) => p.name).join(" → ");
  pathSrc = null; renderer.refresh();
}

/* ---------- 导出 ---------- */
function exportPNG() {
  renderer.refresh();
  const canvas = $("graph").querySelector("canvas");
  const a = document.createElement("a");
  a.download = "stkg_graph.png";
  a.href = canvas.toDataURL("image/png");
  a.click();
}
function exportCSV() {
  const rows = [["fact_id", "subject", "predicate", "object", "tier"]];
  graph.forEachEdge((k, a, s, t) => rows.push([a.factId, graph.getNodeAttribute(s, "label"),
    a.predicate, graph.getNodeAttribute(t, "label"), a.tier]));
  const csv = "\uFEFF" + rows.map((r) => r.map((c) => `"${(c || "").toString().replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.download = "stkg_edges.csv";
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.click();
}

/* ---------- 杂项 UI ---------- */
let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 2600);
}

async function initFilters() {
  const s = await API("/api/stats");
  const chips = $("type-chips");
  const types = ["Person", "Organization", "Event", "Place", "Document", "Concept"];
  types.forEach((t) => {
    const c = document.createElement("span");
    c.className = "chip"; c.textContent = t;
    c.onclick = () => { c.classList.toggle("on");
      filterState.types.has(t) ? filterState.types.delete(t) : filterState.types.add(t); };
    chips.appendChild(c);
  });
  const psel = $("pred-select");
  s.predicates.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.predicate; o.textContent = `${p.predicate} (${p.n})`;
    o.ondblclick = () => {};
    psel.appendChild(o);
  });
  psel.onchange = () => { filterState.preds = new Set([...psel.selectedOptions].map((o) => o.value)); };
  const y0 = parseInt(s.time_min || "1900"), y1 = parseInt(s.time_max || "2000");
  $("y0").value = y0; $("y1").value = y1;
  $("y0").onchange = () => { filterState.t0 = $("y0").value ? $("y0").value + "-01-01" : ""; };
  $("y1").onchange = () => { filterState.t1 = $("y1").value ? $("y1").value + "-12-31" : ""; };
  [["f-strict", "strict_semantic"], ["f-contextual", "contextual"], ["f-unresolved", "unresolved"]]
    .forEach(([id, tier]) => {
      $(id).onchange = () => {
        $(id).checked ? filterState.tiers.add(tier) : filterState.tiers.delete(tier);
        applyTierVisibility();
      };
    });
  $("ver-line").textContent = `FINAL · ${s.entities.toLocaleString()} 实体 · ${s.assertions.toLocaleString()} 断言 · STRICT ${((s.gate_universe.STRICT || 0)).toLocaleString()}`;
}

function initSearch() {
  const input = $("search"), pop = $("search-pop");
  let timer = null;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { pop.classList.add("hidden"); return; }
      const r = await API(`/api/search?q=${encodeURIComponent(q)}&limit=12`);
      pop.innerHTML = r.results.map((e) =>
        `<div class="pop-item" data-id="${e.entity_id}"><span class="t">${esc(e.canonical_name)}</span><span class="d">${esc(e.entity_type)} · ${e.degree}</span></div>`).join("");
      pop.classList.remove("hidden");
      pop.querySelectorAll(".pop-item").forEach((el) =>
        el.onclick = () => { pop.classList.add("hidden"); loadEntity(el.dataset.id); });
    }, 200);
  };
  input.onkeydown = (ev) => {
    if (ev.key === "Enter") {
      const first = pop.querySelector(".pop-item");
      if (first) { pop.classList.add("hidden"); loadEntity(first.dataset.id); }
    }
  };
  document.addEventListener("click", (ev) => {
    if (!pop.contains(ev.target) && ev.target !== input) pop.classList.add("hidden");
  });
}

function initButtons() {
  $("drawer-close").onclick = () => $("right").classList.add("hidden");
  $("btn-clear").onclick = () => { graph.clear(); edgeIndex.clear(); refreshCounts(); $("st-path").textContent = ""; $("graph-empty").classList.remove("hidden"); };
  $("btn-layout").onclick = () => runLayout(260);
  $("btn-export-png").onclick = exportPNG;
  $("btn-export-csv").onclick = exportCSV;
  $("btn-path").onclick = () => { pathMode = !pathMode; pathSrc = null;
    $("btn-path").classList.toggle("active", pathMode);
    toast(pathMode ? "最短路模式：先点起点，再点终点（严格层）" : "已退出最短路模式");
    renderer.refresh(); };
  $("btn-help").onclick = () => $("help-modal").classList.remove("hidden");
  $("help-close").onclick = () => $("help-modal").classList.add("hidden");
  $("btn-verify").onclick = async () => {
    const b = $("db-badge");
    b.textContent = "校验中…"; b.className = "badge";
    const r = await API("/api/verify");
    const ok = r.match === true;
    b.textContent = ok ? "DB ✓ 校验一致" : "DB ✗ 哈希不一致";
    b.className = "badge " + (ok ? "ok" : "bad");
    toast(ok ? "数据库哈希与 FINAL_NUMBERS 记录一致" : "哈希不一致！数据可能被改动");
  };
  document.querySelectorAll(".chk input").forEach((c) => c.onchange = applyTierVisibility);
}

/* ---------- 启动 ---------- */
window.addEventListener("DOMContentLoaded", async () => {
  initRenderer();
  initFilters();
  initSearch();
  initButtons();
  refreshCounts();
  const v = await API("/api/verify").catch(() => null);
  if (v) {
    $("db-badge").textContent = v.match ? "DB ✓" : "DB ✗";
    $("db-badge").className = "badge " + (v.match ? "ok" : "bad");
  }
  // 深链：/#entity=<id> 直载实体子图（可分享/可引用）
  const m = location.hash.match(/^#entity=(.+)$/);
  if (m) {
    $("graph-empty").classList.add("hidden");
    await loadEntity(decodeURIComponent(m[1]));
  }
});
window.addEventListener("hashchange", () => {
  const m = location.hash.match(/^#entity=(.+)$/);
  if (m) loadEntity(decodeURIComponent(m[1]));
});
