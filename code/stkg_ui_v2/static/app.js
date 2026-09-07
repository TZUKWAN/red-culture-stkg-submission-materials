const $ = (selector) => document.querySelector(selector);
const numberFormat = new Intl.NumberFormat('zh-CN');
let cy;

const typeLabel = {
  Event: '事件', Person: '人物', Place: '地点', AdministrativeRegion: '行政区', CulturalSite: '文化场所',
  Organization: '组织', Institution: '机构', SocialGroup: '社会群体', Spirit: '红色精神', ValueFacet: '价值维度',
  CreativeWork: '文艺作品', Document: '文献', Artifact: '代表性物品', Concept: '概念', Position: '职务',
  TimePeriod: '时期', CultureForm: '文化形态'
};

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error((await response.json()).detail || `请求失败 ${response.status}`);
  return response.json();
}

function nodeClass(data) {
  const type = data.entityType;
  if (type === 'Event') return 'event';
  if (type === 'Person') return 'person';
  if (['Place', 'AdministrativeRegion', 'CulturalSite'].includes(type)) return 'place';
  if (['Spirit', 'ValueFacet', 'CreativeWork', 'Document', 'Artifact'].includes(type) || data.kind === 'CultureForm') return 'culture';
  if (['Organization', 'Institution', 'SocialGroup'].includes(type)) return 'collective';
  return 'other';
}

function initGraph() {
  cy = cytoscape({
    container: $('#graph'),
    elements: [],
    minZoom: .15,
    maxZoom: 2.2,
    style: [
      { selector: 'node', style: {
        'label': 'data(label)', 'font-family': 'Microsoft YaHei, sans-serif', 'font-size': 11,
        'text-wrap': 'wrap', 'text-max-width': 110, 'text-valign': 'bottom', 'text-margin-y': 7,
        'color': '#252b31', 'background-color': '#7b8290', 'width': 30, 'height': 30,
        'border-width': 2, 'border-color': '#fff', 'overlay-opacity': 0
      }},
      { selector: 'node.event', style: { 'background-color': '#a9231d', 'shape': 'round-rectangle', 'width': 38, 'height': 30 }},
      { selector: 'node.person', style: { 'background-color': '#356fa3' }},
      { selector: 'node.place', style: { 'background-color': '#28785c', 'shape': 'diamond' }},
      { selector: 'node.culture', style: { 'background-color': '#b7791f', 'shape': 'hexagon' }},
      { selector: 'node.collective', style: { 'background-color': '#247c86', 'shape': 'round-rectangle' }},
      { selector: 'node:selected', style: { 'border-width': 4, 'border-color': '#20252b', 'font-weight': 700 }},
      { selector: 'edge', style: {
        'curve-style': 'bezier', 'width': 1.15, 'line-color': '#b6bcc3', 'target-arrow-color': '#b6bcc3',
        'target-arrow-shape': 'triangle', 'arrow-scale': .7, 'opacity': .72, 'overlay-opacity': 0
      }},
      { selector: 'edge[type="PUBLISHED_EVOLUTION"]', style: {
        'line-color': '#a9231d', 'target-arrow-color': '#a9231d', 'width': 3, 'opacity': 1,
        'label': 'data(label)', 'font-size': 10, 'color': '#7e1714', 'text-background-color': '#fff',
        'text-background-opacity': .9, 'text-background-padding': 2
      }},
      { selector: 'edge:selected', style: { 'line-color': '#20252b', 'target-arrow-color': '#20252b', 'width': 3,
        'label': 'data(label)', 'font-size': 10, 'text-background-color': '#fff', 'text-background-opacity': 1 } }
    ]
  });
  cy.on('tap', 'node', (event) => {
    const data = event.target.data();
    if (data.kind === 'Entity' || data.entityType) loadEntity(event.target.id());
  });
}

function renderGraph(payload, title) {
  const elements = [
    ...payload.nodes.map(node => ({ data: node, classes: nodeClass(node) })),
    ...payload.edges.map(edge => ({ data: edge }))
  ];
  cy.elements().remove();
  cy.add(elements);
  const layoutName = payload.nodes.length > 75 ? 'cose' : 'concentric';
  cy.layout({ name: layoutName, animate: false, fit: true, padding: 42, avoidOverlap: true,
    nodeRepulsion: 9000, idealEdgeLength: 95, componentSpacing: 90 }).run();
  $('#viewTitle').textContent = title;
  $('#graphCount').textContent = `${payload.nodes.length} 个实体 · ${payload.edges.length} 条关系`;
}

function setLoading(value) { $('#loading').hidden = !value; }

async function loadOverview() {
  setLoading(true);
  try { renderGraph(await api('/api/overview'), '可信演进总览'); }
  finally { setLoading(false); }
}

async function loadMeta() {
  const [health, meta] = await Promise.all([api('/api/health'), api('/api/meta')]);
  $('#connectionStatus').textContent = 'V2 数据库已连接 · 中文研究视图';
  $('#metricStrip').innerHTML = Object.entries(health.counts).map(([label, value]) =>
    `<div class="metric"><strong>${numberFormat.format(value)}</strong><span>${label}</span></div>`).join('');
  for (const item of meta.stages) $('#stageSelect').add(new Option(item.label, item.value));
  for (const item of meta.regions) $('#regionSelect').add(new Option(item.label, item.value));
  for (const item of meta.forms) $('#formSelect').add(new Option(item.label, item.value));
  for (const item of meta.mediaTypes) $('#mediaSelect').add(new Option(`${item.label}（${item.count}）`, item.value));
  for (const item of meta.tiers) $('#tierSelect').add(new Option(item.label, item.value));
}

async function applyFilters() {
  const params = new URLSearchParams({ stage: $('#stageSelect').value, region: $('#regionSelect').value,
    form: $('#formSelect').value, media: $('#mediaSelect').value, tier: $('#tierSelect').value });
  setLoading(true);
  try {
    const tierName = $('#tierSelect').selectedOptions[0]?.text || '可信事件时空';
    renderGraph(await api(`/api/explore?${params}`), `状态筛选 · ${tierName}`);
  } finally { setLoading(false); }
}

function showSearchResults(results) {
  const box = $('#searchResults');
  box.hidden = false;
  box.innerHTML = results.length ? results.map(item =>
    `<button class="result-item" data-id="${item.id}">${item.name}<span>${typeLabel[item.entityType] || item.entityType || '实体'}${item.mediaType ? ` · ${item.mediaType}` : ''}</span></button>`
  ).join('') : '<div class="empty-detail">未找到实体</div>';
  box.querySelectorAll('[data-id]').forEach(button => button.addEventListener('click', () => loadEntity(button.dataset.id)));
}

async function searchEntities(event) {
  event.preventDefault();
  const q = $('#searchInput').value.trim();
  if (!q) return;
  showSearchResults((await api(`/api/search?q=${encodeURIComponent(q)}`)).results);
}

function displayValue(value) {
  if (value === null || value === undefined || value === '') return '未标注';
  if (Array.isArray(value)) return value.join('、') || '未标注';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

async function loadEntity(id) {
  setLoading(true);
  try {
    const data = await api(`/api/entity/${encodeURIComponent(id)}`);
    renderGraph(data.graph, data.entity.label);
    $('#emptyDetail').hidden = true;
    $('#entityDetail').hidden = false;
    $('#entityType').textContent = typeLabel[data.entity.entityType] || data.entity.entityType || data.entity.kind;
    $('#entityName').textContent = data.entity.label;
    const props = data.entity.properties || {};
    const factRows = [
      ['实体类型', typeLabel[data.entity.entityType] || data.entity.entityType],
      ...(data.entity.entityType === 'CreativeWork' ? [
        ['媒介类型', displayValue(props.media_type)],
        ['媒介分类', displayValue(props.media_method)],
        ['媒介置信度', displayValue(props.media_confidence)]
      ] : []),
      ['作为主语', `${numberFormat.format(data.factCounts.subjectFacts || 0)} 条事实`],
      ['作为宾语', `${numberFormat.format(data.factCounts.objectFacts || 0)} 条事实`],
      ['别名', displayValue(props.aliases)],
      ['语义状态', displayValue(props.status || data.entity.status)]
    ];
    $('#entityFacts').innerHTML = factRows.map(([key, value]) => `<dt>${key}</dt><dd>${value || '未标注'}</dd>`).join('');
    $('#timeline').innerHTML = data.timeline.length ? data.timeline.map(item => {
      const klass = item.tier === 'trusted_event_spacetime' ? 'trusted' : item.tier === 'asserted_event_spacetime' ? 'candidate' : '';
      return `<div class="timeline-item ${klass}"><strong>${item.stage} · ${item.province}</strong><br>${item.form} · ${item.facts} 条支持</div>`;
    }).join('') : '<div class="empty-detail">暂无时空状态</div>';
    $('#relationList').innerHTML = data.relations.length ? data.relations.slice(0, 40).map(item =>
      `<div class="relation-item"><strong>${item.direction === 'out' ? item.label + ' →' : '← ' + item.label}</strong> ${item.name}<br><span>${typeLabel[item.entityType] || item.entityType}</span></div>`
    ).join('') : '<div class="empty-detail">暂无直接关系</div>';
  } finally { setLoading(false); }
}

function resetFilters() {
  $('#stageSelect').value = '';
  $('#regionSelect').value = '';
  $('#formSelect').value = '';
  $('#mediaSelect').value = '';
  $('#tierSelect').value = 'trusted_event_spacetime';
  $('#searchResults').hidden = true;
  loadOverview();
}

document.addEventListener('DOMContentLoaded', async () => {
  initGraph();
  $('#searchForm').addEventListener('submit', searchEntities);
  $('#applyFilters').addEventListener('click', applyFilters);
  $('#resetButton').addEventListener('click', resetFilters);
  $('#overviewButton').addEventListener('click', loadOverview);
  $('#fitButton').addEventListener('click', () => cy.fit(undefined, 38));
  try { await loadMeta(); await loadOverview(); }
  catch (error) { $('#connectionStatus').textContent = `连接失败：${error.message}`; console.error(error); }
});
