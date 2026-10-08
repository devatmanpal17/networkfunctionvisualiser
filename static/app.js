'use strict';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const icons = {
  edge: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 16a7 7 0 0 1 14 0M8 16a4 4 0 0 1 8 0M11 16a1 1 0 0 1 2 0M12 20v.01"/></svg>',
  switch: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="3"/><path d="M7 12h.01M11 12h.01M15 12h2"/></svg>',
  firewall: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7zM8 12l3 3 5-6"/></svg>',
  balancer: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h5m6 0h5M4 18h5m6 0h5M9 6l6 12M15 6 9 18"/><circle cx="4" cy="6" r="1"/><circle cx="20" cy="6" r="1"/><circle cx="4" cy="18" r="1"/><circle cx="20" cy="18" r="1"/></svg>',
  apps: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="6" rx="2"/><rect x="4" y="14" width="16" height="6" rx="2"/><path d="M8 7h.01M8 17h.01M12 7h5M12 17h5"/></svg>'
};
const nodeNotes = {
  edge: 'The edge gateway receives traffic from simulated clients. The load slider sets their legitimate demand on a 10 Gbps ingress line.',
  switch: 'The virtual switch forwards traffic through the service chain. SDN control decides the path; the switch represents the forwarding plane.',
  firewall: 'The virtual firewall checks traffic before it reaches applications. Each healthy replica supplies 29 load units. A failed replica is excluded from capacity.',
  balancer: 'The virtual load balancer distributes requests. Its replica count follows the firewall pool; routing objectives also change regional traffic weights.',
  apps: 'The application pool represents destinations in Mumbai, Singapore, and Frankfurt. Regional latency is a fixed multiplier of the modeled chain latency.'
};
const chartConfig = {
  throughput: {label: 'Throughput', unit: 'Gbps', minimum: 10},
  latency: {label: 'Latency', unit: 'ms', minimum: 24, threshold: 20},
  packet_loss: {label: 'Packet loss', unit: '%', minimum: 2, threshold: 1}
};
let currentState = null;
let selectedNode = 'firewall';
let chartMetric = 'throughput';
let baseline = null;
let pollTimer, toastTimer, trafficDebounce;
let polling = false, connected = false, pending = 0, failures = 0, trafficPending = false;
let commandQueue = Promise.resolve();
let topologyKey = '';
let previousCompleted = [];
let missionsInitialised = false;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element && element.textContent !== String(value)) element.textContent = value;
}

function formatTime(seconds) {
  return String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
}

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* The lab works without preference storage. */ }
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
    signal: AbortSignal.timeout(8000)
  });
  if (!response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('The service returned an unexpected response. Check that Flask is running.');
  }
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Unable to update the lab.');
  return payload;
}

function syncControls() {
  const disabled = !connected || pending > 0 || trafficPending;
  $$('.control-strip input, #profile-picker button, .scenario-buttons button, .section-actions button, #routing-mode, .security-controls input, #pause-button, [data-launch], #pin-baseline')
    .forEach(element => { element.disabled = disabled; });
  // Keep a drag responsive during debounce, while other commands wait for it.
  $('#traffic').disabled = !connected || pending > 0;
  $('#replica-down').disabled = disabled || currentState?.autoscale || currentState?.firewall_replicas <= 1;
  $('#replica-up').disabled = disabled || currentState?.autoscale || currentState?.firewall_replicas >= 5;
}

function setConnection(value) {
  connected = value;
  const indicator = $('#connection-state');
  indicator.classList.toggle('offline', !value);
  indicator.classList.toggle('paused', value && Boolean(currentState?.paused));
  setText('connection-label', !value ? 'Reconnecting' : currentState?.paused ? 'Paused' : 'Live model');
  syncControls();
}

function renderTopology(nodes) {
  const key = JSON.stringify([nodes, selectedNode]);
  if (key === topologyKey) return;
  topologyKey = key;
  const focusNode = document.activeElement?.dataset.node;
  $('#topology').innerHTML = nodes.map(node => `
    <article class="node ${escapeHtml(node.status)} ${node.id === selectedNode ? 'selected' : ''}">
      <button class="node-icon" data-node="${node.id}" aria-label="Inspect ${escapeHtml(node.name)}, ${node.status}" aria-pressed="${node.id === selectedNode}">${icons[node.id]}</button>
      <strong class="node-name">${escapeHtml(node.name)}</strong><span class="node-detail">${escapeHtml(node.detail)}</span>
      <div class="replicas" aria-label="${node.replicas} active instances">${'<i></i>'.repeat(node.replicas)}</div>
    </article>`).join('');
  if (focusNode) $(`[data-node="${focusNode}"]`)?.focus({preventScroll: true});
}

function renderSelectedNode() {
  const node = currentState.nodes.find(item => item.id === selectedNode);
  if (!node) return;
  const detail = selectedNode === 'firewall' ? `${currentState.encryption ? 'TLS inspection on' : 'TLS inspection off'} · ${currentState.metrics.blocked_threats} modeled blocks`
    : selectedNode === 'balancer' ? `${currentState.routing_mode} routing` : node.detail;
  $('#selected-node-detail').innerHTML = `<strong>${escapeHtml(node.name)}</strong><span>${node.replicas} active instances</span><span>${escapeHtml(detail)}</span>`;
  setText('node-explanation', nodeNotes[selectedNode]);
}

function renderRegions(regions) {
  $('#region-sources').innerHTML = regions.map(region => `<span class="region-chip ${region.status === 'healthy' ? 'healthy' : 'degraded'}"><i></i><b>${region.code}</b>${region.share}% · ${region.latency} ms</span>`).join('');
  $('#region-table').innerHTML = regions.map(region => `<div class="region-row ${region.status === 'healthy' ? 'healthy' : 'degraded'}"><b><i></i>${region.name}</b><span>${region.share}% traffic</span><span>${region.latency} ms</span></div>`).join('');
}

function renderAnalysis(state) {
  const colors = {blue: 'var(--blue)', purple: '#ac9cec', green: '#70b6c9', gray: 'var(--tertiary)', red: 'var(--red)'};
  let offset = 0;
  const segments = state.traffic_mix.map(item => {
    const start = offset;
    offset += item.value;
    return `${colors[item.color]} ${start}% ${offset}%`;
  });
  $('#traffic-donut').style.background = `conic-gradient(${segments.join(',')})`;
  $('#traffic-legend').innerHTML = state.traffic_mix.map(item => `<div class="legend-item"><i style="--legend-color:${colors[item.color]}"></i><span>${item.name}</span><b>${item.value}%</b></div>`).join('');
  $('#decision-list').innerHTML = state.decisions.map(item => `<div class="decision"><span>${escapeHtml(item.label)}</span><b>${escapeHtml(item.value)}</b><small>${escapeHtml(item.reason)}</small></div>`).join('');
  $('#routing-mode').value = state.routing_mode;
  $('#encryption').checked = state.encryption;
  $('#packet-capture').checked = state.capture_enabled;
  setText('flow-count', `${state.metrics.active_flows.toLocaleString()} modeled flows`);
  setText('active-flows', state.metrics.active_flows.toLocaleString());
  setText('queue-depth', state.metrics.queue_depth);
  setText('energy-value', state.metrics.energy);
  setText('cost-value', state.metrics.hourly_cost.toFixed(2));
  setText('mano-state', !state.autoscale ? 'Manual capacity' : state.firewall_replicas === state.desired_replicas ? 'Policy converged' : `Scaling toward ${state.desired_replicas}`);
  setText('cooldown-value', state.cooldown_remaining ? `${state.cooldown_remaining}s remaining` : '6 simulated seconds');
  setText('policy-mode', state.autoscale ? 'Managed by modeled MANO' : 'Manual capacity control');
}

function renderEvents() {
  const filter = $('#event-filter').value;
  const marks = {alert: '!', recovery: '✓', scale: '↗', traffic: '↔', policy: 'P', system: '•', route: 'R', security: 'S'};
  const events = currentState.events.filter(event => filter === 'all' || (filter === 'policy' ? ['policy', 'route', 'security'].includes(event.kind) : event.kind === filter)).slice(0, 6);
  $('#event-list').innerHTML = events.length ? events.map(event => `
    <div class="event ${event.kind}">
      <time datetime="${event.time}" title="${escapeHtml(new Date(event.time).toLocaleString())}">${formatTime(event.elapsed)} lab</time>
      <span class="event-icon" aria-hidden="true">${marks[event.kind] || '•'}</span>
      <span><strong>${escapeHtml(event.title)}</strong><small>${escapeHtml(event.detail)}</small></span>
    </div>`).join('') : '<p class="empty-state">No matching events yet. Try an experiment.</p>';
}

function renderChart() {
  const config = chartConfig[chartMetric];
  const history = currentState.history;
  const max = Math.max(config.minimum, ...history.map(item => item[chartMetric] * 1.15));
  const first = history[0].elapsed;
  const last = history.at(-1).elapsed;
  const span = Math.max(20, last - first);
  const width = Math.max(280, $('#telemetry-chart').clientWidth);
  const right = width - 18;
  const x = time => 52 + (time - first) / span * (right - 52);
  const y = value => 158 - value / max * 140;
  const points = history.map(item => `${x(item.elapsed).toFixed(1)},${y(item[chartMetric]).toFixed(1)}`).join(' ');
  const grid = [0, .5, 1].map(ratio => `<line class="chart-grid" x1="52" y1="${y(max * ratio)}" x2="${right}" y2="${y(max * ratio)}"/><text class="chart-label" x="0" y="${y(max * ratio) + 4}">${(max * ratio).toFixed(chartMetric === 'packet_loss' ? 1 : 0)}</text>`).join('');
  const end = history.at(-1);
  $('#telemetry-chart').innerHTML = `<svg viewBox="0 0 ${width} 190" preserveAspectRatio="none" aria-hidden="true">${grid}
    ${config.threshold ? `<line class="chart-threshold" x1="52" x2="${right}" y1="${y(config.threshold)}" y2="${y(config.threshold)}"/><text class="chart-label" x="${right}" y="${y(config.threshold) - 6}" text-anchor="end">SLA ${config.threshold} ${config.unit}</text>` : ''}
    <polygon class="chart-area" points="52,158 ${points} ${x(end.elapsed)},158"/>
    <polyline class="chart-line" points="${points}"/><circle class="chart-point" cx="${x(end.elapsed)}" cy="${y(end[chartMetric])}" r="3"/>
    <text class="chart-label" x="52" y="183">${formatTime(first)}</text><text class="chart-label" x="${right}" y="183" text-anchor="end">${formatTime(first + span)} lab time</text>
  </svg>`;
  $('#telemetry-chart').setAttribute('aria-label', `${config.label} history: ${history.length} samples, current ${end[chartMetric]} ${config.unit}, from ${formatTime(first)} to ${formatTime(last)} lab time.`);
  setText('chart-summary', `${config.label} / ${config.unit} · ${history.length} actual model sample${history.length === 1 ? '' : 's'} · 2s intervals${currentState.paused ? ' · clock paused' : ''}`);
  $('#throughput-chart').innerHTML = history.slice(-14).map(item => `<i style="height:${item.throughput * 10}%"></i>`).join('');
}

function renderComparison() {
  $('#comparison-results').hidden = !baseline;
  $('#clear-baseline').hidden = !baseline;
  setText('pin-baseline', baseline ? 'Replace baseline +' : 'Pin baseline +');
  if (!baseline) {
    setText('baseline-label', 'Pin this moment, change a setting, compare the result.');
    return;
  }
  setText('baseline-label', `Pinned at ${formatTime(baseline.elapsed)} · ${baseline.profile_name} · ${baseline.traffic}% load`);
  const specs = [['throughput', 'Throughput', 'Gbps', 1], ['latency', 'Latency', 'ms', -1], ['packet_loss', 'Packet loss', '%', -1], ['hourly_cost', 'Run rate', '$/hr', -1]];
  $('#comparison-results').innerHTML = specs.map(([key, label, unit, direction]) => {
    const before = baseline.metrics[key], now = currentState.metrics[key], delta = now - before;
    const result = Math.abs(delta) < .005 ? 'unchanged' : delta * direction > 0 ? 'improved' : 'worse';
    return `<div class="comparison-item"><span>${label}</span><b>${before.toFixed(2)} → ${now.toFixed(2)} ${unit}</b><small class="${result}">${delta >= 0 ? '+' : ''}${delta.toFixed(2)} ${unit} · ${result === 'unchanged' ? 'unchanged' : result === 'improved' ? 'favorable' : 'trade-off'}</small></div>`;
  }).join('');
}

function renderPackets(state) {
  setText('capture-status', state.capture_enabled ? state.paused ? 'Capture paused' : `Capturing · ${state.packets.length} retained` : 'Capture is off');
  $('#packet-rows').innerHTML = state.packets.length ? state.packets.slice(0, 6).map(packet => `<tr><td>${formatTime(packet.elapsed)}</td><td>${escapeHtml(packet.source)}</td><td>${packet.protocol}</td><td>${packet.bytes} B</td><td><span class="packet-badge ${packet.action.toLowerCase()}">${packet.action}</span></td></tr>`).join('')
    : `<tr><td colspan="5" class="empty-state">${state.capture_enabled ? 'Waiting for the next sample. Resume the clock if paused.' : 'Enable diagnostic capture to collect synthetic samples.'}</td></tr>`;
}

function renderMissions(state) {
  const scenarioFor = {scale: 'flash', resilience: 'link', security: 'ddos'};
  $$('[data-mission]').forEach(card => {
    const completed = state.completed.includes(card.dataset.mission);
    card.classList.toggle('completed', completed);
    const status = completed ? '✓ Completed' : scenarioFor[card.dataset.mission] === state.scenario ? 'Experiment running' : 'Ready to explore';
    card.querySelector('.mission-status').textContent = status;
  });
  setText('mission-progress', `${state.completed.length} / 3 completed`);
  if (missionsInitialised && state.completed.some(id => !previousCompleted.includes(id))) showToast('Mission complete. Your experiment met its goal.');
  previousCompleted = [...state.completed];
  missionsInitialised = true;
}

function render(state) {
  if (currentState && state.lab_id !== currentState.lab_id) {
    currentState = null;
    baseline = null;
    previousCompleted = [];
    missionsInitialised = false;
    topologyKey = '';
    showToast('A fresh lab session started.');
  }
  if (currentState && (state.revision < currentState.revision || (state.revision === currentState.revision && state.elapsed < currentState.elapsed))) return;
  currentState = state;
  const m = state.metrics;
  if (!trafficPending) {
    setText('traffic-value', `${state.traffic}%`);
    $('#traffic').value = state.traffic;
    $('#traffic').style.setProperty('--progress', `${(state.traffic - 10) / .9}%`);
  }
  $('#autoscale').checked = state.autoscale;
  setText('throughput', m.throughput.toFixed(1));
  setText('latency', m.latency.toFixed(1));
  setText('availability', m.availability.toFixed(2));
  setText('packet-loss', m.packet_loss.toFixed(2));
  setText('throughput-note', `${Math.round(m.throughput * 10)}% of 10 Gbps capacity`);
  setText('latency-note', state.sla.latency ? 'Within 20 ms model SLA' : '20 ms model SLA exceeded');
  setText('availability-note', state.sla.availability ? 'Within 99% model SLA' : '99% model SLA missed');
  setText('loss-note', state.sla.loss ? 'Below 1% model threshold' : '1% model threshold exceeded');
  ['latency', 'availability', 'loss'].forEach(key => $(`#${key}-note`).previousElementSibling.classList.toggle('bad', !state.sla[key]));
  ['cpu', 'memory', 'network'].forEach(key => {
    setText(`${key}-value`, `${m[key]}%`);
    $(`#${key}-bar`).style.width = `${m[key]}%`;
    $(`#${key}-bar`).classList.toggle('high', m[key] > 85);
  });
  setText('replica-label', `${state.firewall_replicas} / VNF`);
  $('#health-orb').classList.toggle('degraded', state.status !== 'healthy');
  setText('system-label', {healthy: 'The chain is healthy', degraded: 'The chain is degraded', offline: 'No firewall capacity'}[state.status]);
  setText('system-detail', `5 nodes · ${state.nodes.reduce((sum, node) => sum + node.replicas, 0)} active instances`);
  setText('failure-button', state.firewall_failed ? 'Restore replica' : 'Simulate failure');
  $('#failure-button').classList.toggle('restore', state.firewall_failed);
  $$('#profile-picker button').forEach(button => {
    const selected = button.dataset.profile === state.profile;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', selected);
  });
  $$('.scenario-buttons button').forEach(button => {
    const selected = button.dataset.scenario === state.scenario;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', selected);
  });
  setText('policy-name', state.profile_name);
  setText('policy-description', state.profiles[state.profile].description);
  setText('policy-target', `${state.policy_target}%`);
  setText('elapsed-time', formatTime(state.elapsed));
  setText('pause-button', state.paused ? 'Resume clock' : 'Pause clock');
  $('#pause-button').setAttribute('aria-pressed', state.paused);
  document.documentElement.dataset.paused = state.paused;
  document.documentElement.dataset.offline = state.status === 'offline';
  $('#topology').style.setProperty('--flow-speed', `${3.5 - state.traffic * .025}s`);
  renderTopology(state.nodes);
  renderSelectedNode();
  renderRegions(state.regions);
  renderAnalysis(state);
  renderEvents();
  renderChart();
  renderComparison();
  renderPackets(state);
  renderMissions(state);
  setConnection(true);
}

function showToast(message) {
  setText('toast', message);
  $('#toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 4000);
}

function update(path, body, message) {
  pending += 1;
  syncControls();
  const task = commandQueue.then(async () => {
    try {
      const state = await api(path, body);
      render(state);
      if (message) showToast(message);
      return state;
    } catch (error) {
      if (currentState) render(currentState);
      if (error.name === 'TypeError' || error.name === 'TimeoutError') setConnection(false);
      showToast(error.message);
      return null;
    } finally {
      pending -= 1;
      syncControls();
    }
  });
  commandQueue = task;
  return task;
}

async function poll() {
  clearTimeout(pollTimer);
  if (polling) return;
  if (!document.hidden && pending === 0) {
    polling = true;
    try {
      render(await api('/api/state'));
      failures = 0;
    } catch {
      failures += 1;
      setConnection(false);
      if (failures === 1) showToast('Connection lost. Retrying the Python service automatically.');
    } finally { polling = false; }
  }
  pollTimer = setTimeout(poll, Math.min(10000, 2000 * (failures + 1)));
}

async function launchMission(id) {
  if (!currentState) return;
  if (currentState.paused && !await update('/api/playback', {paused: false})) return;
  if (!currentState.autoscale && !await update('/api/autoscale', {enabled: true})) return;
  const scenario = {scale: 'flash', resilience: 'link', security: 'ddos'}[id];
  if (await update('/api/scenario', {scenario}, 'Experiment launched. Follow the chart and decision engine.')) {
    $('.workspace').scrollIntoView({behavior: 'smooth', block: 'start'});
  }
}

function openGuide() { $('#help-dialog').showModal(); }

function bindEvents() {
  $('#topology').addEventListener('click', event => {
    const button = event.target.closest('[data-node]');
    if (!button || !currentState) return;
    selectedNode = button.dataset.node;
    renderTopology(currentState.nodes);
    renderSelectedNode();
  });
  $('#traffic').addEventListener('input', event => {
    const value = Number(event.target.value);
    trafficPending = true;
    setText('traffic-value', `${value}%`);
    event.target.style.setProperty('--progress', `${(value - 10) / .9}%`);
    clearTimeout(trafficDebounce);
    syncControls();
    trafficDebounce = setTimeout(async () => {
      await update('/api/traffic', {value});
      trafficPending = false;
      if (currentState) render(currentState);
    }, 180);
  });
  $('#autoscale').addEventListener('change', event => update('/api/autoscale', {enabled: event.target.checked}));
  $('#failure-button').addEventListener('click', () => update('/api/failure', {}));
  $('#replica-down').addEventListener('click', () => update('/api/replicas', {delta: -1}));
  $('#replica-up').addEventListener('click', () => update('/api/replicas', {delta: 1}));
  $('#routing-mode').addEventListener('change', event => update('/api/routing', {mode: event.target.value}));
  $('#encryption').addEventListener('change', event => update('/api/security', {encryption: event.target.checked}));
  $('#packet-capture').addEventListener('change', event => update('/api/security', {capture: event.target.checked}));
  $('#pause-button').addEventListener('click', () => update('/api/playback', {paused: !currentState.paused}));
  $$('.scenario-buttons button').forEach(button => button.addEventListener('click', () => update('/api/scenario', {scenario: button.dataset.scenario})));
  $$('#profile-picker button').forEach(button => button.addEventListener('click', () => update('/api/profile', {profile: button.dataset.profile})));
  $$('[data-launch]').forEach(button => button.addEventListener('click', () => launchMission(button.dataset.launch)));
  $$('[data-chart]').forEach(button => button.addEventListener('click', () => {
    chartMetric = button.dataset.chart;
    $$('[data-chart]').forEach(item => { item.classList.toggle('selected', item === button); item.setAttribute('aria-pressed', item === button); });
    if (currentState) renderChart();
  }));
  $('#pin-baseline').addEventListener('click', () => {
    baseline = structuredClone(currentState);
    renderComparison();
    showToast('Baseline pinned. Change a setting to compare its effect.');
  });
  $('#clear-baseline').addEventListener('click', () => { baseline = null; renderComparison(); });
  $('#event-filter').addEventListener('change', () => { if (currentState) renderEvents(); });
  $$('.nav-item').forEach(button => button.addEventListener('click', () => {
    $$('.nav-item').forEach(item => item.classList.toggle('active', item === button));
    $(`[data-section="${button.dataset.view}"]`)?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }));
  $('#theme-toggle').addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    $('#theme-toggle').setAttribute('aria-label', `Switch to ${next === 'dark' ? 'light' : 'dark'} mode`);
    storageSet('arc-theme', next);
  });
  $('#help-open').addEventListener('click', openGuide);
  $('#footer-help').addEventListener('click', openGuide);
  $('#help-close').addEventListener('click', () => $('#help-dialog').close());
  $('#help-dialog').addEventListener('click', event => {
    if (event.target !== $('#help-dialog')) return;
    const bounds = event.target.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.target.close();
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  window.addEventListener('pagehide', () => { clearTimeout(pollTimer); clearTimeout(trafficDebounce); trafficPending = false; });
  window.addEventListener('pageshow', event => { if (event.persisted) poll(); });
  window.addEventListener('resize', () => { if (currentState) renderChart(); });
}

function initialise() {
  const theme = storageGet('arc-theme');
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  $('#theme-toggle').setAttribute('aria-label', `Switch to ${document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'} mode`);
  bindEvents();
  syncControls();
  poll();
}

initialise();
