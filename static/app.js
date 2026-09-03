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
    <article class="node ${node.status === 'failed' ? 'failed' : ''} ${index === 2 ? 'selected' : ''}" aria-label="${node.name}, ${node.status}">
      <div class="node-icon">${icons[node.id]}</div>
      <strong class="node-name">${node.name}</strong>
      <span class="node-detail">${node.detail}</span>
      <div class="replicas" aria-label="${node.replicas} active instances">${'<i></i>'.repeat(node.replicas)}</div>
    </article>`).join('');
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
