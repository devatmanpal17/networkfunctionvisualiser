const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const icons = {
  edge: '<svg viewBox="0 0 24 24"><path d="M5 16a7 7 0 0 1 14 0M8 16a4 4 0 0 1 8 0M11 16a1 1 0 0 1 2 0M12 20v.01"/></svg>',
  switch: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="3"/><path d="M7 12h.01M11 12h.01M15 12h2"/></svg>',
  firewall: '<svg viewBox="0 0 24 24"><path d="M4 9h16M4 15h16M8 4v5m8-5v5m-5 0v6m-4 0v5m10-5v5M4 4h16v16H4z"/></svg>',
  balancer: '<svg viewBox="0 0 24 24"><path d="M4 6h5m6 0h5M4 18h5m6 0h5M9 6l6 12M15 6 9 18"/><circle cx="4" cy="6" r="1"/><circle cx="20" cy="6" r="1"/><circle cx="4" cy="18" r="1"/><circle cx="20" cy="18" r="1"/></svg>',
  apps: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="6" rx="2"/><rect x="4" y="14" width="16" height="6" rx="2"/><path d="M8 7h.01M8 17h.01M12 7h5M12 17h5"/></svg>'
};

let currentState = null;
let selectedNode = 'firewall';
let chartValues = [42, 48, 45, 54, 52, 60, 57, 63, 59, 66, 62, 68];
let pollTimer;
let toastTimer;

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  };
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Unable to update the lab');
  return payload;
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function renderTopology(nodes) {
  $('#topology').innerHTML = nodes.map((node, index) => `
    <article class="node ${node.status === 'failed' ? 'failed' : ''} ${node.id === selectedNode ? 'selected' : ''}" aria-label="${node.name}, ${node.status}">
      <button class="node-icon" data-node="${node.id}" aria-label="Inspect ${node.name}">${icons[node.id]}</button>
      <strong class="node-name">${node.name}</strong>
      <span class="node-detail">${node.detail}</span>
      <div class="replicas" aria-label="${node.replicas} active instances">${'<i></i>'.repeat(node.replicas)}</div>
    </article>`).join('');
  $$('.node-icon').forEach(button => button.addEventListener('click', () => {
    selectedNode = button.dataset.node;
    renderTopology(currentState.nodes);
    renderSelectedNode(currentState.nodes.find(node => node.id === selectedNode));
  }));
}

function renderSelectedNode(node) {
  if (!node) return;
  const roles = {
    edge: ['Ingress gateway', '12 source peers', 'Anycast enabled'],
    switch: ['Datapath', 'OpenFlow 1.3', '18 installed rules'],
    firewall: ['Security VNF', 'TLS inspection', `${currentState.metrics.blocked_threats} threats blocked`],
    balancer: ['Traffic VNF', currentState.routing_mode + ' routing', 'Least-loaded scheduling'],
    apps: ['Service pool', '3 availability zones', 'Health checks passing']
  };
  $('#selected-node-detail').innerHTML = `<strong>${node.name}</strong>${roles[node.id].map(value => `<span>${value}</span>`).join('')}`;
}

function renderRegions(regions) {
  $('#region-sources').innerHTML = regions.map(region => `<span class="region-chip ${region.status}"><i></i><b>${region.code}</b>${region.share}% · ${region.latency} ms</span>`).join('');
  $('#region-table').innerHTML = regions.map(region => `<div class="region-row ${region.status}"><b><i></i>${region.name}</b><span>${region.share}% traffic</span><span>${region.latency} ms</span></div>`).join('');
}

function renderAnalysis(state) {
  const colorMap = {blue: 'var(--blue)', purple: '#9b6dff', green: 'var(--green)', gray: 'var(--tertiary)'};
  $('#traffic-legend').innerHTML = state.traffic_mix.map(item => `<div class="legend-item"><i style="--legend-color:${colorMap[item.color]}"></i><span>${item.name}</span><b>${item.value}%</b></div>`).join('');
  $('#decision-list').innerHTML = state.decisions.map(item => `<div class="decision"><span>${item.label}</span><b>${item.value}</b><small>${item.reason}</small></div>`).join('');
  $('#routing-mode').value = state.routing_mode;
  $('#encryption').checked = state.encryption;
  $('#packet-capture').checked = state.capture_enabled;
  setText('flow-count', `${state.metrics.active_flows.toLocaleString()} active flows`);
  setText('active-flows', state.metrics.active_flows.toLocaleString());
  setText('queue-depth', state.metrics.queue_depth);
  setText('energy-value', Math.round(state.metrics.energy));
  setText('cost-value', state.metrics.hourly_cost.toFixed(2));
  setText('mano-state', state.status === 'healthy' ? 'Policy converged' : 'Remediation active');
}

function renderEvents(events) {
  const marks = {alert: '!', recovery: '✓', scale: '↗', traffic: '↔', policy: 'P', system: '•'};
  $('#event-list').innerHTML = events.slice(0, 5).map(event => `
    <div class="event ${event.kind}">
      <time>${event.time} UTC</time>
      <span class="event-icon">${marks[event.kind] || '•'}</span>
      <span><strong>${event.title}</strong><small>${event.detail}</small></span>
    </div>`).join('');
}

function renderChart(value) {
  chartValues.push(Math.max(8, Math.min(100, value * 9 + Math.random() * 9)));
  chartValues = chartValues.slice(-14);
  $('#throughput-chart').innerHTML = chartValues.map(item => `<i style="height:${item}%"></i>`).join('');
}

function render(state, updateChart = true) {
  currentState = state;
  const m = state.metrics;
  setText('traffic-value', `${state.traffic}%`);
  $('#traffic').value = state.traffic;
  $('#traffic').style.setProperty('--progress', `${(state.traffic - 10) / .9}%`);
  $('#autoscale').checked = state.autoscale;

  setText('throughput', m.throughput.toFixed(1));
  setText('latency', m.latency.toFixed(1));
  setText('availability', m.availability.toFixed(2));
  setText('packet-loss', m.packet_loss.toFixed(2));
  setText('throughput-note', `${Math.round(m.throughput * 10)}% of line capacity`);
  setText('latency-note', m.latency < 12 ? 'Within 20 ms SLA' : 'Latency is elevated');
  setText('availability-note', state.status === 'healthy' ? 'No active incidents' : 'Recovery in progress');
  setText('loss-note', m.packet_loss < 1 ? 'Below policy threshold' : 'Above policy threshold');

  ['latency', 'availability', 'loss'].forEach(name => {
    const dot = document.querySelector(`#${name === 'loss' ? 'loss' : name}-note`)?.previousElementSibling;
    if (dot) dot.classList.toggle('bad', state.status !== 'healthy');
  });

  setText('cpu-value', `${m.cpu}%`); $('#cpu-bar').style.width = `${m.cpu}%`;
  setText('memory-value', `${m.memory}%`); $('#memory-bar').style.width = `${m.memory}%`;
  setText('network-value', `${m.network}%`); $('#network-bar').style.width = `${m.network}%`;
  setText('replica-label', `${state.firewall_replicas} replica${state.firewall_replicas === 1 ? '' : 's'}`);
  $('#replica-down').disabled = state.autoscale;
  $('#replica-up').disabled = state.autoscale;

  const failed = state.firewall_failed;
  $('#health-orb').classList.toggle('degraded', failed);
  setText('system-label', failed ? 'Service is degraded' : 'All systems normal');
  setText('system-detail', `5 nodes · ${state.nodes.reduce((sum, node) => sum + node.replicas, 0)} active instances`);
  $('#failure-button').textContent = failed ? 'Restore service' : 'Simulate failure';
  $('#failure-button').classList.toggle('restore', failed);

  $$('#profile-picker button').forEach(button => button.classList.toggle('selected', button.dataset.profile === state.profile));
  const profile = state.profiles[state.profile];
  setText('policy-name', profile.name);
  setText('policy-description', profile.description);
  setText('policy-target', `${state.policy_target}%`);

  renderTopology(state.nodes);
  renderSelectedNode(state.nodes.find(node => node.id === selectedNode));
  renderRegions(state.regions);
  renderAnalysis(state);
  renderEvents(state.events);
  if (updateChart) renderChart(m.throughput);
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2300);
}

async function update(path, body, message) {
  try {
    const state = await api(path, body);
    render(state);
    if (message) showToast(message);
  } catch (error) {
    showToast(error.message);
  }
}

let trafficDebounce;
$('#traffic').addEventListener('input', event => {
  const value = Number(event.target.value);
  setText('traffic-value', `${value}%`);
  event.target.style.setProperty('--progress', `${(value - 10) / .9}%`);
  clearTimeout(trafficDebounce);
  trafficDebounce = setTimeout(() => update('/api/traffic', {value}, `Traffic set to ${value}%`), 120);
});

$('#autoscale').addEventListener('change', event => update('/api/autoscale', {enabled: event.target.checked}, event.target.checked ? 'Autoscaling enabled' : 'Manual scaling enabled'));
$('#failure-button').addEventListener('click', () => update('/api/failure', {}, currentState?.firewall_failed ? 'Service restored' : 'Failure scenario running'));
$('#replica-down').addEventListener('click', () => update('/api/replicas', {delta: -1}, 'Capacity reduced'));
$('#replica-up').addEventListener('click', () => update('/api/replicas', {delta: 1}, 'Capacity increased'));

$('#routing-mode').addEventListener('change', event => update('/api/routing', {mode: event.target.value}, `Routing now optimizes for ${event.target.value}`));
$('#encryption').addEventListener('change', event => update('/api/security', {encryption: event.target.checked}, event.target.checked ? 'TLS inspection enabled' : 'TLS inspection bypassed'));
$('#packet-capture').addEventListener('change', event => update('/api/security', {capture: event.target.checked}, event.target.checked ? 'Diagnostic capture started' : 'Diagnostic capture stopped'));

$$('.scenario-buttons button').forEach(button => button.addEventListener('click', () => {
  const labels = {flash: 'Flash crowd scenario applied', ddos: 'DDoS mitigation active', link: 'Path outage injected', reset: 'Lab returned to baseline'};
  update('/api/scenario', {scenario: button.dataset.scenario}, labels[button.dataset.scenario]);
}));

$$('#profile-picker button').forEach(button => button.addEventListener('click', () => {
  update('/api/profile', {profile: button.dataset.profile}, `${button.textContent} profile applied`);
}));

$$('.nav-item').forEach(button => button.addEventListener('click', () => {
  $$('.nav-item').forEach(item => item.classList.toggle('active', item === button));
  document.querySelector(`[data-section="${button.dataset.view}"]`)?.scrollIntoView({behavior: 'smooth', block: 'start'});
}));

$('#theme-toggle').addEventListener('click', () => {
  const root = document.documentElement;
  const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  localStorage.setItem('arc-theme', next);
});

const savedTheme = localStorage.getItem('arc-theme');
if (savedTheme) document.documentElement.dataset.theme = savedTheme;

async function initialise() {
  try {
    render(await api('/api/state'));
    pollTimer = setInterval(async () => {
      if (document.hidden) return;
      try { render(await api('/api/state')); } catch (_) { /* retry on the next tick */ }
    }, 3500);
  } catch (error) {
    showToast('The Python service is not responding');
  }
}

window.addEventListener('pagehide', () => clearInterval(pollTimer));
initialise();
