'use strict';
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids) if (kid !== null && kid !== undefined && kid !== false) e.append(kid);
  return e;
}
/* ------------------------------------------------- langues (FR, EN) */
/* Le français est la langue source. En anglais, le catalogue /i18n/en.json traduit tout
   texte affiché (page, messages du serveur, fenêtres) : phrases exactes, puis modèles à
   variables ({1}...), puis phrase par phrase. Jamais traduits : conversations du chat,
   journaux, code, saisies. */
const LANGS = { fr: 'Français', en: 'English' };
const I18N = { lang: 'fr', exact: new Map(), patterns: [] };
try { const l = localStorage.getItem('ob-lang'); if (l && LANGS[l]) I18N.lang = l; } catch (e) { /* stockage indisponible */ }
const LOCALE = () => (I18N.lang === 'en' ? 'en-GB' : 'fr-FR');
const DEC = (x) => (I18N.lang === 'fr' ? String(x).replace('.', ',') : String(x));
const NO_I18N = '#chat-log, pre, code, textarea, .no-i18n, .think-body, .token';
function i18nLookup(k) {
  const v = I18N.exact.get(k);
  if (v !== undefined) return v;
  for (const [re, out] of I18N.patterns) {
    const m = re.exec(k);
    if (m) return out.replace(/\{(\d)\}/g, (_, i) => { const g = m[+i] || ''; const t = g && g !== k ? i18nLookup(g) : null; return t != null ? t : g; });
  }
  return null;
}
function trString(s) {
  if (I18N.lang === 'fr' || !s) return null;
  const key = s.replace(/\s+/g, ' ').trim();
  if (!key || !/[A-Za-zÀ-ÿ]/.test(key)) return null;
  const raw = s.trim();
  let out = raw !== key ? i18nLookup(raw) : null;   // texte tel quel d'abord (même méthode que l'assistant)
  if (out == null) out = i18nLookup(key);
  if (out == null) {   // phrases successives (messages composés par le serveur)
    const parts = key.split(/(?<=[.!?…])\s+(?=[A-ZÀ-Ý«(])/);
    if (parts.length > 1) {
      const tp = parts.map(i18nLookup);
      if (tp.some((x) => x != null)) out = parts.map((p, i) => (tp[i] != null ? tp[i] : p)).join(' ');
    }
  }
  return out == null ? null : s.match(/^\s*/)[0] + out + s.match(/\s*$/)[0];
}
const t = (s) => trString(s) || s;
function trNode(node) {
  if (node.nodeType === 3) {
    const p = node.parentElement;
    if (p && p.id === 'job-log') {   // journal des tâches : lignes de nos scripts, ligne par ligne
      const out = node.data.split('\n').map((l) => trString(l) || l).join('\n');
      if (out !== node.data) node.data = out;
      return;
    }
    if (!p || p.closest(NO_I18N)) return;
    const out = trString(node.data);
    if (out != null && out !== node.data) node.data = out;
  } else if (node.nodeType === 1) {
    const skip = node.closest(NO_I18N);
    if (skip && !(skip === node && node.tagName === 'TEXTAREA')) return;   // le texte saisi reste intact, mais l'indication (placeholder) d'une zone de texte se traduit
    for (const a of ['placeholder', 'title', 'aria-label']) {
      const v = node.getAttribute(a), out = v && trString(v);
      if (out && out !== v) node.setAttribute(a, out);
    }
    for (const c of node.childNodes) trNode(c);
  }
}
async function loadI18n() {
  let chosen = null;
  try { chosen = localStorage.getItem('ob-lang'); } catch (e) { /* vide */ }
  if (!chosen) {   // langue par défaut de l'appliance (choisie à l'installation)
    try { const d = await (await fetch('/api/ping', { cache: 'no-store' })).json(); if (d.lang && LANGS[d.lang]) I18N.lang = d.lang; } catch (e) { /* vide */ }
  }
  document.documentElement.lang = I18N.lang;
  $('#lang-switch').textContent = I18N.lang === 'en' ? 'FR' : 'EN';
  $('#lang-switch').title = I18N.lang === 'en' ? 'Afficher en français' : 'Show in English';
  if (I18N.lang === 'fr') return;
  try {
    const cat = await (await fetch('/i18n/' + I18N.lang + '.json', { cache: 'no-cache' })).json();
    for (const [k, v] of Object.entries(cat.exact)) I18N.exact.set(k, v);
    I18N.patterns = cat.patterns.map(([re, out]) => [new RegExp('^' + re + '$'), out]);
  } catch (e) { I18N.lang = 'fr'; return; }
  document.title = t(document.title);
  trNode(document.body);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === 'characterData') trNode(m.target);
      else if (m.type === 'attributes') trNode(m.target);
      else m.addedNodes.forEach(trNode);
    }
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label'] });
}
function switchLanguage() {
  try { localStorage.setItem('ob-lang', I18N.lang === 'en' ? 'fr' : 'en'); } catch (e) { /* vide */ }
  location.reload();
}

const fmtBytes = (n) => {
  if (n === null || n === undefined || isNaN(n)) return '-';
  const u = I18N.lang === 'en' ? ['B', 'KB', 'MB', 'GB', 'TB'] : ['o', 'Ko', 'Mo', 'Go', 'To']; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return DEC(n.toFixed(i ? 1 : 0)) + ' ' + u[i];
};
const fmtUptime = (s) => {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return (d ? d + ' j ' : '') + h + ' h ' + String(m).padStart(2, '0') + ' min';
};
const fmtDate = (x) => (x ? new Date(x * 1000).toLocaleString(LOCALE()) : '-');
const pct = (a, b) => (b ? Math.min(100, Math.round((100 * a) / b)) : 0);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, { method = 'GET', json, raw = false, signal } = {}) {
  const opts = { method, credentials: 'same-origin', headers: { 'X-OB': '1' }, signal };
  if (json !== undefined) {
    opts.method = method === 'GET' ? 'POST' : method;
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(json);
  }
  const r = await fetch(path, opts);
  if (r.status === 401 && path !== '/api/login') { showLogin(); throw new Error('Session expirée : reconnectez-vous.'); }
  if (raw) {
    if (!r.ok) { let d = {}; try { d = await r.json(); } catch (e) { /* vide */ } throw new Error(d.error || 'Erreur HTTP ' + r.status); }
    return r;
  }
  let data = {};
  try { data = await r.json(); } catch (e) { /* vide */ }
  if (!r.ok) throw new Error(data.error || 'Erreur HTTP ' + r.status);
  return data;
}

async function readNDJSON(resp, onObject) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) onObject(JSON.parse(line));
    }
  }
  if (buf.trim()) onObject(JSON.parse(buf));
}

async function ping(timeoutMs = 4000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch('/api/ping', { cache: 'no-store', signal: ctl.signal });
    return r.ok ? await r.json() : null;
  } catch (e) { return null; } finally { clearTimeout(t); }
}

/* ---------------------------------------------------------------- session */
const state = { timer: null, status: null, user: '', role: '', version: '' };
const isAdmin = () => state.role === 'admin';
const bell = { items: [], timer: null, fleetAt: 0 };

function showLogin() {
  $('#app').classList.add('hidden');
  $('#login').classList.remove('hidden');
  clearInterval(state.timer); clearInterval(bell.timer); bell.timer = null;
  ping().then((p) => { if (p) $('#login-version').textContent = 'OllamaBuntu ' + p.version; });
  setTimeout(() => $('#login-form [name=user]').focus(), 50);
}
function showApp(d) {
  state.user = d.user; state.role = d.role || 'utilisateur'; state.version = d.version || '';
  $('#who').textContent = d.user + (isAdmin() ? '' : ' (utilisateur)');
  $('#ver').textContent = 'v' + state.version;
  for (const e of $$('[data-admin]')) e.classList.toggle('hidden', !isAdmin());
  $('#login').classList.add('hidden');
  $('#app').classList.remove('hidden');
  startBell();
  route();
}

$('#login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  $('#login-error').textContent = '';
  try {
    const d = await api('/api/login', { json: { user: f.elements.user.value.trim(), password: f.elements.password.value } });
    f.elements.password.value = '';
    location.hash = d.role === 'admin' ? '#dashboard' : '#chat';
    showApp(d);
  } catch (e) { $('#login-error').textContent = e.message; }
});
$('#logout').addEventListener('click', async () => {
  try { await api('/api/logout', { json: {} }); } catch (e) { /* vide */ }
  showLogin();
});

/* ------------------------------------------------------------- navigation */
const VIEWS = ['dashboard', 'models', 'chat', 'gpu', 'perf', 'system', 'security', 'fleet', 'webui', 'users', 'logs', 'account', 'about'];
const ADMIN_VIEWS = ['dashboard', 'gpu', 'perf', 'system', 'webui', 'users', 'logs'];
function route() {
  let [v, sub] = location.hash.slice(1).split('/');
  if (!VIEWS.includes(v)) v = isAdmin() ? 'dashboard' : 'chat';
  if (ADMIN_VIEWS.includes(v) && !isAdmin()) v = 'chat';
  for (const name of VIEWS) $('#view-' + name).classList.toggle('hidden', name !== v);
  for (const a of $$('#nav a')) a.classList.toggle('active', a.getAttribute('href') === '#' + v);
  $('#nav-more-btn').classList.toggle('active', !!$('#nav-more-list a.active'));
  navMore(false);
  activateTab(v, sub);
  clearInterval(logsLive.timer); logsLive.timer = null; $('#log-live').setAttribute('aria-pressed', 'false');
  $('#job-card').classList.toggle('hidden', !(['gpu', 'system', 'webui'].includes(v) && jobs.current));
  clearInterval(state.timer); state.timer = null;
  if (v === 'dashboard') { loadDashboard(); loadPerf(); state.timer = setInterval(() => { loadDashboard(); loadPerf(); }, 10000); }
  if (v === 'models') { loadModels(); if (isAdmin()) { loadCustom(); loadContext(); if (currentTab('models') === 'disk') loadModelsDisk(); } }
  if (v === 'chat') loadChatModels();
  if (v === 'gpu') loadGpu();
  if (v === 'perf') loadPerformance();
  if (v === 'system') { loadSystem(); loadProm(); const tab = currentTab('system'); if (tab === 'hardware') loadHardware(); if (tab === 'audit') loadAudit(); if (tab === 'report') loadReport(); }
  if (v === 'webui') loadWebui();
  if (v === 'users') loadUsers();
  if (v === 'logs') { loadRequests(); loadReqSettings(); loadLogs(); if (currentTab('logs') === 'stats') loadStats(); state.timer = setInterval(() => { if ($('#req-live').checked && currentTab('logs') === 'requests') loadRequests(); }, 4000); }
  if (v === 'account') loadAccount();
  if (v === 'about') loadCredits();
  if (v === 'fleet') { loadFleet(); loadBalance(); state.timer = setInterval(() => { loadFleet(); loadBalance(); }, 10000); }
  if (v === 'security') { loadSecurity(); loadPolicy(); }
}
window.addEventListener('hashchange', route);
/* Menu « Plus » : les écrans moins fréquents (Serveurs, Journaux, Sécurité, Open WebUI, Utilisateurs, À propos) tiennent dans une liste déroulante pour garder une seule ligne de menu. */
function navMore(open) {
  $('#nav-more-list').classList.toggle('hidden', !open);
  $('#nav-more-btn').setAttribute('aria-expanded', open ? 'true' : 'false');
}
$('#nav-more-btn').addEventListener('click', (e) => { e.stopPropagation(); navMore($('#nav-more-list').classList.contains('hidden')); });
document.addEventListener('click', (e) => { if (!e.target.closest('.nav-more')) navMore(false); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#nav-more-list').classList.contains('hidden')) { navMore(false); $('#nav-more-btn').focus(); } });

function card(title, ...content) { return el('div', { class: 'card' }, el('h2', { text: title }), ...content); }
function kv(pairs) {
  const dl = el('dl', { class: 'kv' });
  for (const [k, v] of pairs) dl.append(el('dt', { text: k }), el('dd', {}, v instanceof Node ? v : document.createTextNode(String(v ?? '-'))));
  return dl;
}
function bar(p) { const i = el('i'); i.style.width = p + '%'; return el('div', { class: 'bar' }, i); }
function pill(text, kind) { return el('span', { class: 'pill ' + (kind || ''), text }); }
function setBanner(show) {
  $('#banner').classList.toggle('hidden', !show || !isAdmin());
  $('#banner-text').textContent = 'Un redémarrage du serveur est nécessaire pour terminer une installation.';
}
$('#banner-btn').addEventListener('click', () => power('reboot'));

/* ---------------------------------------------------------- tableau de bord */
function gpuSummary(g) {
  if (g.compute.length) return g.compute.map((c) => el('div', {}, pill(c.library, 'ok'), document.createTextNode(' ' + c.name + ' - ' + c.total)));
  const todo = g.devices.some((d) => d.actions.length);
  return [el('div', { class: 'big', text: 'Processeur' }),
    el('div', { class: 'muted small', text: g.devices.filter((d) => d.kind === 'gpu').length ? 'GPU détecté mais non utilisé par Ollama.' : 'Aucun GPU de calcul détecté.' }),
    todo ? el('p', {}, el('a', { href: '#gpu', text: 'Action possible dans l\'onglet GPU' })) : null];
}
/* Charge GPU : historique côté navigateur (60 mesures = 5 min à 5 s) et courbe SVG. */
const gpuHist = {};
const LOAD_KIND = (p) => (p >= 90 ? 'err' : p >= 70 ? 'warn' : 'ok');
function sparkline(values) {
  const W = 240, H = 44, n = 60, pts = values.slice(-n);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('class', 'spark'); svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Charge GPU des 5 dernières minutes');
  if (pts.length > 1) {
    const x = (i) => ((n - pts.length + i) / (n - 1)) * W, y = (v) => H - 2 - (Math.max(0, Math.min(100, v)) / 100) * (H - 4);
    const line = pts.map((v, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1)).join(' ');
    const area = document.createElementNS(svg.namespaceURI, 'path');
    area.setAttribute('d', line + ' L' + x(pts.length - 1).toFixed(1) + ' ' + H + ' L' + x(0).toFixed(1) + ' ' + H + ' Z'); area.setAttribute('class', 'area');
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', line); path.setAttribute('class', 'line ' + LOAD_KIND(pts[pts.length - 1]));
    svg.append(area, path);
  }
  return svg;
}
function gpuLoadCards(list) {
  return list.map((g) => {
    const h = (gpuHist[g.pci] = gpuHist[g.pci] || []);
    if (g.util != null) { h.push(g.util); if (h.length > 60) h.shift(); }
    const memPct = g.mem_total ? pct(g.mem_used, g.mem_total) : null;
    const extra = [g.temp != null ? DEC(g.temp.toFixed(0)) + ' °C' : null, g.power != null ? DEC(g.power.toFixed(0)) + ' W' + (g.power_limit ? ' / ' + DEC(g.power_limit.toFixed(0)) + ' W' : '') : null].filter(Boolean).join(' - ');
    return el('div', { class: 'card gpu-live' }, el('h2', { text: 'GPU - ' + g.name }),
      el('div', { class: 'big' }, g.util == null ? '-' : DEC(g.util.toFixed(0)) + ' %', ' ', el('span', { class: 'muted small', text: 'utilisation' })),
      sparkline(h),
      memPct == null ? null : el('div', { class: 'small', text: 'Mémoire vidéo : ' + fmtBytes(g.mem_used) + ' / ' + fmtBytes(g.mem_total) + ' (' + memPct + ' %)' }),
      memPct == null ? null : bar(memPct),
      extra ? el('div', { class: 'muted small', text: extra }) : null);
  });
}
async function loadDashboard() {
  loadDashRequests();
  loadDashFleet();
  let s;
  try { s = await api('/api/status'); } catch (e) { $('#dash-grid').replaceChildren(card('Erreur', el('p', { class: 'error', text: e.message }))); return; }
  state.status = s;
  setBanner(s.reboot_required);
  renderDashAlerts(s);
  $('#dash-host').textContent = s.hostname;
  $('#dash-version').textContent = 'OllamaBuntu v' + s.version;
  const memUsed = s.memory.total - s.memory.available;
  const ips = s.ips.length ? s.ips.map((i) => i.iface + ' : ' + i.addr).join('\n') : 'aucune adresse';
  const ol = s.ollama;
  const running = ol.running.length ? ol.running.map((m) => m.name + ' (' + fmtBytes(m.size_vram || m.size) + ')').join(', ') : 'aucun';
  $('#dash-grid').replaceChildren(
    card('Ollama', el('div', { class: 'big' }, pill(ol.service === 'active' ? 'en service' : ol.service, ol.service === 'active' ? 'ok' : 'err')),
      kv([['Version', ol.version || '-'], ['API réseau', ol.publication && ol.publication.enabled ? (ol.publication.tls ? 'HTTPS' : 'HTTP') + ' port ' + ol.publication.port + (ol.publication.auth ? ', clés d\'API' : ', sans clé') : 'locale uniquement'], ['En mémoire', running]])),
    card('Calcul', ...gpuSummary(s.gpu)),
    ...gpuLoadCards(s.gpu_live || []),
    card('Processeur', el('div', { class: 'big', text: s.cpu.usage === null ? '-' : DEC(s.cpu.usage) + ' %' }), bar(s.cpu.usage || 0),
      el('div', { class: 'muted small', text: `${s.cpu.cores} cœurs - charge ${s.cpu.load.map((x) => x.toFixed(2)).join(' / ')}` }),
      el('div', { class: 'muted small', text: s.cpu.model })),
    card('Mémoire', el('div', { class: 'big', text: fmtBytes(memUsed) + ' / ' + fmtBytes(s.memory.total) }), bar(pct(memUsed, s.memory.total))),
    card('Disque', el('div', { class: 'big', text: fmtBytes(s.disk.used) + ' / ' + fmtBytes(s.disk.total) }), bar(pct(s.disk.used, s.disk.total)),
      el('div', { class: 'muted small', text: 'Modèles : ' + fmtBytes(s.disk.models) + ' - libre : ' + fmtBytes(s.disk.free) })),
    card('Serveur', kv([['Nom', s.hostname], ['Adresses', ips], ['Système', s.os], ['OllamaBuntu', 'v' + s.version],
      ['Démarré le', fmtDate(s.boot_time)], ['Depuis', fmtUptime(s.uptime)]])),
  );
}

/* ----------------------------------------------------------------- modèles */
const FIT_KIND = { gpu: 'ok', cpu: 'info', mixte: 'warn', trop: 'err', incompatible: 'err' };
const UPD_KIND = { a_jour: 'ok', maj: 'warn', local: 'info', cloud: 'info', inconnu: '' };
/* Registre d'origine d'un modèle : hf.co/... = Hugging Face, un nom sans adresse = registre Ollama. */
function srcOf(name) { const h = name.includes('/') ? name.split('/')[0] : ''; return !h || h === 'registry.ollama.ai' ? 'Ollama' : (h === 'hf.co' || h === 'huggingface.co') ? 'Hugging Face' : h; }
function renderInstalled(models) {
  const box = $('#models-table');
  if (!models.length) { box.replaceChildren(el('p', { class: 'muted', text: 'Aucun modèle installé.' })); return; }
  const rich = models.some((m) => m.update);
  const tbody = el('tbody');
  for (const m of models) {
    const det = m.details || {};
    tbody.append(el('tr', {},
      el('td', {}, el('strong', { text: m.name }), ' ', el('span', { class: 'chip', text: m.source || srcOf(m.name) })),
      el('td', { text: (det.parameter_size || '-') + ' / ' + (det.quantization_level || '-') }),
      el('td', { class: 'nowrap', text: fmtBytes(m.size) }),
      rich ? el('td', {}, m.fit ? pill(m.fit.label, FIT_KIND[m.fit.level]) : null) : null,
      rich ? el('td', {}, m.update ? pill(m.update.label, UPD_KIND[m.update.state]) : null) : null,
      el('td', { text: m.modified_at ? new Date(m.modified_at).toLocaleDateString(LOCALE()) : '-' }),
      el('td', { class: 'nowrap' }, isAdmin() && m.update && m.update.state === 'maj' ? el('button', { class: 'btn sm primary', type: 'button', text: 'Mettre à jour', onclick: () => pullModel(m.name) }) : null,
        isAdmin() ? el('button', { class: 'btn danger sm', type: 'button', text: 'Supprimer', onclick: () => deleteModel(m.name) }) : null)));
  }
  const heads = ['Modèle', 'Paramètres / quantif.', 'Taille'].concat(rich ? ['Compatibilité', 'Mise à jour'] : [], ['Modifié le', '']);
  box.replaceChildren(el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, ...heads.map((h) => el('th', { text: h })))), tbody)));
}
async function loadModels() {
  let d;
  try { d = await api('/api/models'); } catch (e) { $('#models-table').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  renderInstalled((d.models || []).sort((a, b) => a.name.localeCompare(b.name)));
  if (isAdmin()) { loadInsights(false); loadTuning(); }
}
async function loadInsights(refresh) {
  $('#capacity').replaceChildren(el('h2', { text: 'Ce serveur' }), el('p', { class: 'muted', text: 'Interrogation du registre Ollama...' }));
  let d;
  try { d = await api('/api/models/insights' + (refresh ? '?refresh=1' : '')); } catch (e) { $('#capacity').replaceChildren(el('h2', { text: 'Ce serveur' }), el('p', { class: 'error', text: e.message })); return; }
  const c = d.capacity;
  $('#capacity').replaceChildren(el('h2', { text: 'Ce serveur' }),
    el('div', { class: 'big', text: c.vram ? 'GPU : ' + fmtBytes(c.vram) + ' de mémoire vidéo' : 'Processeur uniquement' }),
    el('div', { class: 'muted small', text: (c.gpus.length ? c.gpus.join(' - ') + ' - ' : '') + 'mémoire système : ' + fmtBytes(c.ram_total) + ' (' + fmtBytes(c.ram_available) + ' disponibles) - Ollama ' + (d.ollama || '?') }),
    d.registry.ok ? null : el('p', { class: 'error small', text: 'Un registre de modèles est injoignable : ' + d.registry.errors[0] + ' (accès Internet, proxy ?)' }));
  renderInstalled(d.installed.sort((a, b) => a.name.localeCompare(b.name)));
  catalogData = d;
  renderCatalog();
}
let catalogData = null;
/* Vue agrégée : tous les registres dans une seule liste, triée du plus adapté au moins adapté à ce serveur ; filtrable par source, adéquation et texte. */
function renderCatalog() {
  const d = catalogData; if (!d) return;
  const src = $('#cat-source').value, onlyFit = $('#cat-fit').checked, q = $('#cat-q').value.trim().toLowerCase();
  const items = d.catalog.filter((m) => (!src || m.source === src) && (!onlyFit || (m.available && ['gpu', 'cpu', 'mixte'].includes(m.fit.level)))
    && (!q || (m.name + ' ' + m.category + ' ' + (m.caps || []).join(' ') + ' ' + m.description).toLowerCase().includes(q)));
  const groups = {};
  for (const m of items) (groups[m.category] = groups[m.category] || []).push(m);
  const parts = Object.entries(d.sources || {}).map(([s, c]) => s + ' ' + c.available + '/' + c.total);
  $('#catalog-note').textContent = d.catalog.filter((m) => m.available).length + ' modèle(s) du catalogue disponible(s) (' + parts.join(', ') + '), tous registres confondus, triés du plus adapté au moins adapté à ce serveur. Catalogue modifiable : /etc/ollamabuntu/catalog.json';
  if (!items.length) { $('#catalog').replaceChildren(el('p', { class: 'muted', text: 'Aucun modèle ne correspond à ces filtres.' })); return; }
  $('#catalog').replaceChildren(...Object.entries(groups).map(([cat, list]) => el('div', { class: 'catalog-group' }, el('h3', { text: cat }),
    el('div', { class: 'cat-grid' }, ...list.map((m) => el('div', { class: 'cat-item' },
      el('div', { class: 'name', text: m.name }),
      el('div', { class: 'chips' }, el('span', { class: 'chip', text: m.source }), ...(m.caps || []).map((x) => el('span', { class: 'chip', text: x }))),
      el('p', { class: 'muted', text: m.description }),
      el('div', {}, m.available ? pill(m.fit.label, FIT_KIND[m.fit.level]) : pill(m.source === 'Hugging Face' ? 'Indisponible sur Hugging Face' : 'Indisponible sur le registre', ''),
        m.available ? document.createTextNode(' ' + fmtBytes(m.size) + (m.params ? ' - ' + m.params : '') + (m.quant ? ' ' + m.quant : '')) : null),
      el('div', { class: 'row' }, m.installed ? pill('Installé', 'ok') : (m.available && m.fit.level !== 'incompatible'
        ? el('button', { class: 'btn sm' + (['gpu', 'cpu'].includes(m.fit.level) ? ' primary' : ''), type: 'button', text: 'Télécharger', onclick: () => pullModel(m.name) }) : null))))))));
}
for (const id of ['#cat-source', '#cat-fit']) $(id).addEventListener('change', renderCatalog);
$('#cat-q').addEventListener('input', renderCatalog);
$('#insights-refresh').addEventListener('click', () => loadInsights(true));
async function checkModel() {
  const name = $('#check-name').value.trim(), out = $('#check-result');
  if (!name) return;
  out.replaceChildren(document.createTextNode('Interrogation du registre...'));
  try {
    const r = await api('/api/models/check', { json: { name } });
    if (!r.found) { out.replaceChildren(pill('Introuvable', 'err'), document.createTextNode(' « ' + name + ' » n\'existe pas sur le registre Ollama (vérifiez le nom et le tag).')); return; }
    if (r.cloud) { out.replaceChildren(pill('Modèle cloud', 'info'), document.createTextNode(' exécuté chez Ollama, pas sur ce serveur.')); return; }
    out.replaceChildren(el('div', {}, pill(r.fit.label, FIT_KIND[r.fit.level]), document.createTextNode(' ' + fmtBytes(r.size) + ' à télécharger, besoin estimé ' + fmtBytes(r.fit.need || 0))),
      el('div', { class: 'muted', text: [r.family, r.params, r.quant, r.vision ? 'vision' : '', r.draft ? 'décodage spéculatif' : '', r.requires ? 'Ollama ≥ ' + r.requires : ''].filter(Boolean).join(' - ') }),
      r.fit.level === 'incompatible' ? null : el('button', { class: 'btn sm primary', type: 'button', text: 'Télécharger ' + name, onclick: () => pullModel(name) }));
  } catch (e) { out.replaceChildren(el('span', { class: 'error', text: e.message })); }
}
$('#check-btn').addEventListener('click', checkModel);
$('#check-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') checkModel(); });
async function deleteModel(name) {
  if (!(await ask('Supprimer le modèle « ' + name + ' » ?'))) return;
  try { await api('/api/models/delete', { json: { name } }); } catch (e) { fail(e.message); }
  loadModels();
}
async function pullModel(given) {
  const name = (typeof given === 'string' ? given : $('#pull-name').value).trim();
  if (typeof given === 'string') { $('#pull-name').value = name; $('#pull-name').scrollIntoView({ block: 'center' }); }
  if (!name) return;
  const btn = $('#pull-btn'), barEl = $('#pull-bar'), txt = $('#pull-status');
  btn.disabled = true; $('#pull-progress').classList.remove('hidden'); barEl.style.width = '0%'; txt.textContent = 'Connexion...';
  try {
    const r = await api('/api/models/pull', { json: { name }, raw: true });
    await readNDJSON(r, (o) => {
      if (o.error) throw new Error(o.error);
      let s = o.status || '';
      if (o.total) {
        const p = pct(o.completed || 0, o.total);
        barEl.style.width = p + '%';
        s += ' - ' + p + ' % (' + fmtBytes(o.completed || 0) + ' / ' + fmtBytes(o.total) + ')';
      }
      txt.textContent = s;
    });
    barEl.style.width = '100%';
    txt.textContent = 'Modèle « ' + name + ' » prêt.';
    loadModels();
  } catch (e) { txt.textContent = 'Échec : ' + e.message; }
  btn.disabled = false;
}
$('#pull-btn').addEventListener('click', () => pullModel());
$('#pull-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') pullModel(); });
/* ------------------------------------------------- Hugging Face */
function hfNum(n) { return n >= 1e6 ? DEC((n / 1e6).toFixed(1)) + ' M' : n >= 1e3 ? DEC((n / 1e3).toFixed(0)) + ' k' : String(n); }
async function hfSearch() {
  const msg = $('#hf-msg'), out = $('#hf-results');
  $('#hf-quants').classList.add('hidden');
  msg.className = 'small muted'; msg.textContent = 'Recherche en cours...'; out.replaceChildren();
  try {
    const r = await api('/api/hf/search?q=' + encodeURIComponent($('#hf-q').value.trim()) + '&mode=' + encodeURIComponent($('#hf-mode').value));
    msg.textContent = r.models.length ? r.models.length + ' modèle(s), les plus téléchargés d\'abord.' : 'Aucun modèle trouvé.';
    out.replaceChildren(...r.models.map((m) => el('div', { class: 'row', style: 'align-items:center;justify-content:space-between;padding:4px 0' },
      el('div', {}, el('strong', { text: m.id }), ' ', m.uncensored ? pill('sans censure', 'warn') : null,
        el('div', { class: 'small muted', text: hfNum(m.downloads) + ' téléchargements - ' + m.likes + ' J\'aime - mis à jour le ' + m.updated })),
      el('button', { class: 'btn sm', type: 'button', text: 'Choisir', onclick: () => hfQuants(m.id) }))));
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
}
async function hfQuants(repo) {
  const box = $('#hf-quants'), msg = $('#hf-msg');
  msg.className = 'small muted'; msg.textContent = 'Lecture des quantifications...';
  try {
    const r = await api('/api/hf/files?repo=' + encodeURIComponent(repo));
    msg.textContent = '';
    box.classList.remove('hidden');
    box.replaceChildren(el('h3', { text: repo }),
      r.uncensored ? el('p', { class: 'small error', text: 'Version sans censure : les garde-fous du modèle d\'origine sont retirés. Son usage reste soumis à la politique d\'usage de l\'IA de votre organisation.' }) : null,
      r.quants.length ? el('div', { class: 'small muted', text: 'Plus la quantification est basse (Q2, Q3), plus le fichier est petit et la qualité réduite ; Q4_K_M est un bon compromis.' })
        : el('div', { class: 'small error', text: 'Aucune quantification GGUF exploitable dans ce dépôt.' }),
      el('div', { class: 'small muted', text: r.vram ? 'Mémoire vidéo de ce serveur : ' + fmtBytes(r.vram) : 'Ce serveur n\'a pas de GPU : le modèle tournera sur le processeur.' }),
      el('div', { class: 'actions' }, ...r.quants.map((q) => el('button', { class: 'btn sm', type: 'button', onclick: () => hfPull(repo, q.quant, r.uncensored, q.fit) }, q.quant + ' (' + fmtBytes(q.size) + ') ', pill(HF_FIT[q.fit][0], HF_FIT[q.fit][1])))));
    box.scrollIntoView({ block: 'nearest' });
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
}
const HF_FIT = { gpu: ['tient en VRAM', 'ok'], partial: ['déborde sur le processeur', 'warn'], no: ['trop gros', 'err'] };
async function hfPull(repo, quant, uncensored, fit) {
  const text = 'Télécharger « hf.co/' + repo + ':' + quant + ' » depuis Hugging Face ?' + (fit === 'no' ? ' Ce fichier est trop gros pour la mémoire de ce serveur.' : fit === 'partial' ? ' Il ne tiendra pas entièrement en mémoire vidéo : débit nettement réduit.' : '') + (uncensored ? ' Ce modèle est une version sans censure.' : '');
  if (!(await ask(text))) return;
  pullModel('hf.co/' + repo + ':' + quant);
}
$('#hf-search').addEventListener('click', hfSearch);
$('#hf-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') hfSearch(); });
$('#models-refresh').addEventListener('click', loadModels);

/* -------------------------------------------------------------------- chat */
const chat = { messages: [], controller: null };
async function loadChatModels() {
  const sel = $('#chat-model'), prev = sel.value;
  try {
    const d = await api('/api/models');
    const names = (d.models || []).map((m) => m.name).sort();
    sel.replaceChildren(...names.map((n) => el('option', { value: n, text: n })));
    if (!names.length) sel.append(el('option', { value: '', text: 'aucun modèle installé' }));
    if (names.includes(prev)) sel.value = prev;
  } catch (e) { $('#chat-info').textContent = e.message; }
}
function renderInline(target, text) {
  const re = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) target.append(document.createTextNode(text.slice(last, m.index)));
    const t = m[0];
    target.append(t[0] === '`' ? el('code', { text: t.slice(1, -1) }) : el('strong', { text: t.slice(2, -2) }));
    last = m.index + t.length;
  }
  if (last < text.length) target.append(document.createTextNode(text.slice(last)));
}
function renderMarkdown(target, src) {
  target.replaceChildren();
  src.split('```').forEach((part, i) => {
    if (i % 2) {
      const nl = part.indexOf('\n');
      target.append(el('pre', {}, el('code', { text: (nl >= 0 ? part.slice(nl + 1) : part).replace(/\n$/, '') })));
    } else renderInline(target, part);
  });
}
/* Raisonnement des modèles « thinking » : replié par défaut, la bulle n'affiche que le résultat.
   Deux formes : champ « thinking » séparé par Ollama, ou balises <think>…</think> dans la réponse. */
function splitThink(text) {
  const m = /^\s*<think>([\s\S]*?)(<\/think>|$)/.exec(text);
  if (!m) return { thinking: '', answer: text, open: false };
  return { thinking: m[1].trim(), answer: text.slice(m[0].length).replace(/^\s+/, ''), open: !m[2] };
}
function bubble(role, text) {
  const log = $('#chat-log');
  if (log.querySelector('p.center')) log.replaceChildren();
  const think = el('details', { class: 'think hidden' }, el('summary', {}, el('span', { class: 't-label', text: 'Raisonnement' }), ' ', el('span', { class: 't-meta' })),
    el('div', { class: 'think-body' }));
  const content = el('div', { class: 'content' });
  const b = el('div', { class: 'msg ' + role }, think, content);
  if (role === 'user') content.textContent = text; else renderMarkdown(content, text);
  log.append(b); log.scrollTop = log.scrollHeight;
  return b;
}
function chatBusy(busy) {
  $('#chat-send').classList.toggle('hidden', busy);
  $('#chat-stop').classList.toggle('hidden', !busy);
  $('#chat-model').disabled = busy;
}
async function sendChat() {
  const input = $('#chat-text'), text = input.value.trim(), model = $('#chat-model').value;
  if (!text || !model || chat.controller) return;
  input.value = '';
  chat.messages.push({ role: 'user', content: text });
  bubble('user', text);
  const b = bubble('assistant', ''), content = b.querySelector('.content'), think = b.querySelector('.think');
  const thinkBody = think.querySelector('.think-body'), thinkLabel = think.querySelector('.t-label'), thinkMeta = think.querySelector('.t-meta');
  content.replaceChildren(el('span', { class: 'typing', 'aria-label': 'Réponse en cours' }, el('i'), el('i'), el('i')));
  let answer = '', thinking = '', raw = '', thinkStart = 0, thinkEnd = 0;
  const showThink = (txt, running) => {
    if (!txt) return;
    if (!thinkStart) thinkStart = performance.now();
    if (!running && !thinkEnd) thinkEnd = performance.now();
    think.classList.remove('hidden');
    const near = thinkBody.scrollHeight - thinkBody.scrollTop - thinkBody.clientHeight < 30;
    thinkBody.textContent = txt;
    if (near) thinkBody.scrollTop = thinkBody.scrollHeight;
    think.classList.toggle('running', running);
    thinkLabel.textContent = running ? 'Réflexion en cours…' : 'Raisonnement';
    const words = txt.split(/\s+/).filter(Boolean).length;
    thinkMeta.textContent = running ? '' : '(' + (((thinkEnd || performance.now()) - thinkStart) / 1000).toFixed(0) + ' s, ' + words + ' mots)';
  };
  const t0 = performance.now();
  chat.controller = new AbortController();
  chatBusy(true);
  $('#chat-info').textContent = '';
  try {
    const ctx = Number($('#chat-ctx').value) || undefined;   // taille du contexte de la conversation (sinon réglage du modèle)
    const r = await api('/api/chat', { json: { model, messages: chat.messages, num_ctx: ctx }, raw: true, signal: chat.controller.signal });
    await readNDJSON(r, (o) => {
      if (o.error) throw new Error(o.error);
      const msg = o.message || {};
      if (msg.thinking) { thinking += msg.thinking; showThink(thinking, !answer); }
      if (msg.content) {
        raw += msg.content;
        const s = splitThink(raw);   // balises <think> dans la réponse (selon le modèle)
        if (s.thinking) showThink((thinking ? thinking + '\n' : '') + s.thinking, s.open);
        answer = s.answer;
        if (answer) { if (thinking && !s.open) showThink(thinking + (s.thinking ? '\n' + s.thinking : ''), false); renderMarkdown(content, answer); }
      }
      if (o.done && o.eval_count && o.eval_duration) {
        $('#chat-info').textContent = model + ' - ' + DEC((o.eval_count / (o.eval_duration / 1e9)).toFixed(1)) + ' jetons/s';
      }
      $('#chat-log').scrollTop = $('#chat-log').scrollHeight;
    });
    if (!think.classList.contains('hidden') && think.classList.contains('running')) showThink(thinkBody.textContent, false);
    if (!answer) content.textContent = '(réponse vide)';
    chat.messages.push({ role: 'assistant', content: answer });
  } catch (e) {
    if (e.name === 'AbortError') {
      if (think.classList.contains('running')) showThink(thinkBody.textContent, false);
      if (answer) chat.messages.push({ role: 'assistant', content: answer }); else content.replaceChildren();
      content.append(el('em', { class: 'muted', text: ' [interrompu]' }));
    }
    else { b.classList.add('error'); content.textContent = 'Erreur : ' + e.message; chat.messages.pop(); }
  } finally {
    chat.controller = null; chatBusy(false);
    if (!$('#chat-info').textContent) $('#chat-info').textContent = model + ' - ' + ((performance.now() - t0) / 1000).toFixed(1) + ' s';
  }
}
$('#chat-send').addEventListener('click', sendChat);
$('#chat-stop').addEventListener('click', () => chat.controller && chat.controller.abort());
$('#chat-text').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } });
$('#chat-clear').addEventListener('click', () => {
  if (chat.controller) chat.controller.abort();
  chat.messages = []; $('#chat-info').textContent = '';
  $('#chat-log').replaceChildren(el('p', { class: 'muted center', text: 'Nouvelle conversation.' }));
});

/* --------------------------------------------------------------------- GPU */
const GPU_ACTIONS = {
  'install-nvidia': { label: 'Installer le pilote NVIDIA', job: true, confirm: 'Installer le pilote NVIDIA (accès Internet nécessaire) ?' },
  'install-vulkan': { label: 'Activer Vulkan (pilote Mesa)', job: true, confirm: 'Installer le pilote Vulkan Mesa (accès Internet nécessaire) ?' },
  'install-rocm': { label: 'Installer ROCm pour Ollama (~1 Go)', job: true, confirm: 'Télécharger le module AMD ROCm d\'Ollama (environ 1 Go) ?' },
  'enable-igpu': { label: 'Autoriser le GPU intégré', action: true },
  'restart-ollama': { label: 'Redémarrer Ollama', action: true },
  reboot: { label: 'Redémarrer le serveur', power: true },
};
async function runAction(id) {
  const a = GPU_ACTIONS[id] || { job: true };
  if (a.power) return power(id);
  if (a.confirm && !(await ask(a.confirm))) return;
  try {
    if (a.job) { const d = await api('/api/action', { json: { action: id } }); followJob(d.job); }
    else { await api('/api/action', { json: { action: id } }); await sleep(1500); }
  } catch (e) { fail(e.message); }
  if (location.hash === '#gpu') loadGpu();
}
/* --------------------------------------------- groupes de GPU et épinglage */
const placement = { data: null, editing: null };
async function loadPlacement() {
  let d, models = [];
  try {
    d = await api('/api/gpu/placement');
    models = ((await api('/api/models')).models || []).map((m) => m.name).filter((n) => !/-gpu\d+$/.test(n));
  } catch (e) { $('#pools-list').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  placement.data = d; placement.models = models;
  const gname = (g) => (g.description || g.key) + ' (' + g.library + (g.total ? ', ' + g.total : '') + ')';
  $('#pools-list').replaceChildren(...(d.pools.length ? d.pools.map((p) => el('div', { class: 'pool' },
    el('div', { class: 'head' }, el('strong', { text: p.name }),
      el('span', {}, pill(p.state === 'active' ? 'en service' : p.state, p.state === 'active' ? 'ok' : 'err'), ' ',
        el('button', { class: 'btn sm', type: 'button', text: 'Modifier', onclick: () => editPool(p) }), ' ',
        el('button', { class: 'btn sm danger', type: 'button', text: 'Supprimer', onclick: () => deletePool(p) }))),
    el('div', { class: 'small' }, 'GPU : ', ...p.gpu_details.map((g, i) => el('span', {}, i ? ', ' : '', gname(g), g.seen === false && p.state === 'active' ? el('span', { class: 'error', text: ' (non vu par l\'instance)' }) : ''))),
    el('div', { class: 'small' }, 'Modèles : ' + (p.models.join(', ') || 'aucun')),
    el('div', { class: 'small muted' }, 'Instance 127.0.0.1:' + p.port + (p.loaded && p.loaded.length ? ' - en mémoire : ' + p.loaded.join(', ') : '')))) :
    [el('p', { class: 'muted', text: 'Aucun groupe : tous les modèles se partagent tous les GPU (placement automatique d\'Ollama).' })]),
    ...(d.pools.length ? [el('p', { class: 'small' }, 'Instance principale (modèles hors groupe) : ',
      d.main_free.length ? d.main_free.map(gname).join(', ') : el('span', { class: 'warn-text', text: 'aucun GPU restant, ces modèles tournent sur processeur' }),
      ' - routeur : ', pill(d.router === 'active' ? 'en service' : d.router, d.router === 'active' ? 'ok' : 'err'))] : []));
  renderPoolForm();
  $('#pin-model').replaceChildren(...models.map((m) => el('option', { value: m, text: m })));
  $('#pin-gpu').replaceChildren(...d.main_gpus.map((g) => el('option', { value: g.index, text: 'GPU ' + g.index + ' : ' + g.description + ' (' + g.library + ', ' + g.total + ')' })));
  $('#pin-btn').disabled = !models.length || !d.main_gpus.length;
  $('#pin-msg').textContent = d.main_gpus.length ? '' : 'Aucun GPU utilisé par l\'instance principale.';
  $('#pins-list').replaceChildren(...(d.pins.length ? [el('div', { class: 'table-wrap' }, el('table', {},
    el('thead', {}, el('tr', {}, ...['Variante', 'Modèle', 'GPU', 'État', ''].map((t) => el('th', { text: t })))),
    el('tbody', {}, ...d.pins.map((p) => el('tr', {}, el('td', { class: 'name', text: p.variant }), el('td', { text: p.base }),
      el('td', { text: 'GPU ' + p.index + ' : ' + p.description }),
      el('td', {}, p.ok ? pill('correct', 'ok') : pill('à revoir : le GPU ' + p.index + ' est maintenant ' + (p.current || 'absent'), 'warn')),
      el('td', {}, el('button', { class: 'btn sm danger', type: 'button', text: 'Supprimer', onclick: () => unpin(p.variant) })))))))] : []));
}

function renderPoolForm() {
  const d = placement.data, ed = placement.editing;
  const others = d.pools.filter((p) => !ed || p.id !== ed.id);
  const takenG = new Set(others.flatMap((p) => p.gpus)), takenM = new Set(others.flatMap((p) => p.models.map((m) => m.toLowerCase())));
  const box = (name, value, label, checked, off, title) => el('label', { class: off ? 'off' : '', title: title || '' },
    el('input', { type: 'checkbox', name, value, checked: checked || null, disabled: off || null }), label);
  $('#pool-gpus').replaceChildren(...(d.inventory.length ? d.inventory.map((g) => box('gpu', g.key, (g.description || g.key) + ' (' + g.library + ', ' + (g.total || '?') + ')',
    ed && ed.gpus.includes(g.key), takenG.has(g.key) || (g.library === 'Vulkan' && g.ordinal == null), takenG.has(g.key) ? 'déjà dans un autre groupe' : '')) :
    [el('span', { class: 'muted small', text: 'Aucun GPU de calcul détecté par Ollama.' })]));
  const names = [...new Set([...placement.models, ...(ed ? ed.models : [])])];
  $('#pool-models').replaceChildren(...(names.length ? names.map((m) => box('model', m, m, ed && ed.models.includes(m), takenM.has(m.toLowerCase()), takenM.has(m.toLowerCase()) ? 'déjà dans un autre groupe' : '')) :
    [el('span', { class: 'muted small', text: 'Aucun modèle installé.' })]));
  $('#pool-form-title').textContent = ed ? 'Modifier le groupe « ' + ed.name + ' »' : 'Nouveau groupe';
  $('#pool-submit').textContent = ed ? 'Enregistrer' : 'Créer le groupe';
  $('#pool-cancel').classList.toggle('hidden', !ed);
  $('#pool-form').elements.name.value = ed ? ed.name : '';
}
function editPool(p) { placement.editing = p; renderPoolForm(); $('#pool-form').scrollIntoView({ behavior: 'smooth' }); }
$('#pool-cancel').addEventListener('click', () => { placement.editing = null; renderPoolForm(); });
$('#pool-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, ed = placement.editing;
  const body = { name: f.elements.name.value.trim(), gpus: [...f.querySelectorAll('input[name=gpu]:checked')].map((i) => i.value),
    models: [...f.querySelectorAll('input[name=model]:checked')].map((i) => i.value) };
  if (ed) body.id = ed.id;
  $('#pool-msg').className = 'small'; $('#pool-msg').textContent = 'Application (redémarrage des instances Ollama)...';
  $('#pool-submit').disabled = true;
  try {
    await api(ed ? '/api/gpu/pools/update' : '/api/gpu/pools/create', { json: body });
    placement.editing = null; await loadPlacement();
    $('#pool-msg').className = 'small okmsg'; $('#pool-msg').textContent = ed ? 'Groupe modifié.' : 'Groupe créé.';
  } catch (e) { $('#pool-msg').className = 'small error'; $('#pool-msg').textContent = e.message; }
  $('#pool-submit').disabled = false;
});
async function deletePool(p) {
  if (!(await ask('Supprimer le groupe « ' + p.name + ' » ?\nSes GPU reviennent à l\'instance principale ; aucun modèle n\'est supprimé.'))) return;
  try { await api('/api/gpu/pools/delete', { json: { id: p.id } }); placement.editing = null; await loadPlacement(); } catch (e) { fail(e.message); }
}
$('#pin-btn').addEventListener('click', async () => {
  const name = $('#pin-model').value, index = Number($('#pin-gpu').value);
  $('#pin-msg').className = 'small'; $('#pin-msg').textContent = 'Création de la variante...'; $('#pin-btn').disabled = true;
  try {
    const r = await api('/api/models/pin', { json: { name, index } });
    await loadPlacement();
    $('#pin-msg').className = 'small okmsg'; $('#pin-msg').textContent = 'Variante « ' + r.variant + ' » créée.';
  } catch (e) { $('#pin-msg').className = 'small error'; $('#pin-msg').textContent = e.message; }
  $('#pin-btn').disabled = false;
});
async function unpin(variant) {
  if (!(await ask('Supprimer la variante « ' + variant + ' » ? Le modèle d\'origine est conservé.'))) return;
  try { await api('/api/models/unpin', { json: { variant } }); await loadPlacement(); } catch (e) { fail(e.message); }
}

async function loadGpu() {
  let g;
  try { g = await api('/api/gpu'); } catch (e) { $('#gpu-summary').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  setBanner(g.reboot_required);
  const sum = [el('h2', { text: 'Ollama calcule sur' })];
  if (g.compute.length) for (const c of g.compute) sum.push(el('div', { class: 'big' }, pill(c.library, 'ok'), document.createTextNode(' ' + c.name)), el('div', { class: 'muted small', text: 'Mémoire GPU : ' + c.total }));
  else sum.push(el('div', { class: 'big', text: 'Processeur uniquement' }), el('div', { class: 'muted small', text: g.discovered ? 'Aucun GPU retenu par Ollama lors de son dernier démarrage.' : 'Détection d\'Ollama introuvable (service arrêté ?).' }));
  sum.push(el('p', { class: 'muted small', text: 'Vulkan (Mesa) : ' + (g.vulkan_installed ? 'installé' : 'non installé') + ' - ROCm : ' + (g.rocm_installed ? 'installé' : 'non installé') +
    (g.nvidia_package ? ' - pilote NVIDIA : ' + g.nvidia_package : '') + (g.secure_boot ? ' - Secure Boot actif' : '') }));
  $('#gpu-summary').replaceChildren(...sum);
  const STATE = { ok: ['OK', 'ok'], warn: ['À traiter', 'warn'], info: ['Information', 'info'] };
  $('#gpu-devices').replaceChildren(...(g.devices.length ? g.devices.map((d) => {
    const st = STATE[d.state] || STATE.info;
    const m = d.metrics;
    return el('div', { class: 'card gpu-dev ' + d.state },
      el('div', {}, pill(st[0], st[1]), document.createTextNode(' ' + d.vendor)),
      el('div', { class: 'name', text: d.name }),
      kv([['Emplacement PCI', d.slot], ['Pilote noyau', d.driver || 'aucun']].concat(m ? [
        ['Charge', (m.util != null ? DEC(m.util.toFixed(0)) + ' %' : '-') + (m.temp != null ? ' - ' + DEC(m.temp.toFixed(0)) + ' °C' : '') + (m.power != null ? ' - ' + DEC(m.power.toFixed(0)) + ' W' : '')],
        ['Mémoire vidéo', m.mem_total ? fmtBytes(m.mem_used) + ' / ' + fmtBytes(m.mem_total) : '-']] : [])),
      el('p', { class: 'small', text: d.message }),
      d.actions.length ? el('div', { class: 'actions' }, ...d.actions.map((id) => el('button', { class: 'btn ' + (id.startsWith('install') ? 'primary' : ''), type: 'button', text: (GPU_ACTIONS[id] || { label: id }).label, onclick: () => runAction(id) }))) : null);
  }) : [card('Aucune carte', el('p', { class: 'muted', text: 'Aucune carte graphique ou accélérateur détecté.' }))]));
  loadEnv();
  loadPlacement();
  loadGuard();
  resumeJob();
}
$('#gpu-refresh').addEventListener('click', loadGpu);
async function loadEnv() {
  try {
    const d = await api('/api/ollama-env');
    $('#env-fields').replaceChildren(...d.settings.map((s) => el('label', {}, el('code', { text: s.key }), el('br'), document.createTextNode(s.label),
      el('input', { name: s.key, value: s.value, placeholder: 'par défaut', pattern: '[A-Za-z0-9.,:_+\\-]{0,64}' }))));
  } catch (e) { $('#env-msg').textContent = e.message; }
}
$('#env-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const values = {};
  for (const i of $$('#env-fields input')) values[i.name] = i.value.trim();
  const out = $('#env-msg'); out.className = 'small'; out.textContent = 'Enregistrement...';
  try { await api('/api/ollama-env', { json: { values } }); out.textContent = 'Enregistré, Ollama redémarré.'; out.classList.add('okmsg'); setTimeout(loadGpu, 4000); }
  catch (e) { out.textContent = e.message; out.classList.add('error'); }
});

/* ------------------------------------------------- publication de l'API */
const PERM_LABEL = { inference: 'Utiliser les modèles (chat, génération, embeddings)', read: 'Consulter (liste des modèles, version)', manage: 'Gérer les modèles (télécharger, supprimer, créer)' };
const PERM_SHORT = { inference: 'utilisation', read: 'consultation', manage: 'gestion' };
const DENY_LABEL = { vision: 'Images et vidéos en entrée', audio: 'Audio (synthèse, transcription)', tools: 'Outils (appels de fonctions)' };
const DENY_SHORT = { vision: 'sans images', audio: 'sans audio', tools: 'sans outils' };
const pubState = { models: [] };
function checkList(sel, name, items, checked, labels) {
  $(sel).replaceChildren(...items.map((v) => el('label', {}, el('input', { type: 'checkbox', name, value: v, checked: checked.includes(v) || null }), (labels && labels[v]) || v)));
}
const checkedValues = (form, name) => [...form.querySelectorAll('input[name=' + name + ']:checked')].map((i) => i.value);
async function loadPublication() {
  let p;
  try { p = await api('/api/publication'); pubState.models = ((await api('/api/models')).models || []).map((m) => m.name); }
  catch (e) { $('#pub-urls').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  pubState.data = p;
  try { pubState.limits = Object.fromEntries(((await api('/api/limits')).keys || []).map((k) => [k.id, k])); } catch (e) { pubState.limits = {}; }
  const f = $('#pub-form');
  f.elements.enabled.checked = p.enabled; f.elements.tls.value = p.tls ? '1' : '0'; f.elements.port.value = p.port;
  f.elements.auth.checked = p.auth; f.elements.allow.value = (p.allow || []).join('\n');
  checkList('#pub-anon-perms', 'anon', Object.keys(PERM_LABEL), p.anonymous.perms || [], PERM_LABEL);
  $('#pub-anon').classList.toggle('hidden', f.elements.auth.checked);
  $('#pub-warn').replaceChildren(...(p.enabled && !p.auth ? [el('div', { class: 'notice' },
    el('strong', { text: 'API publiée sans clé. ' }), 'Toute machine ' + (p.allow.length ? 'des réseaux autorisés' : 'du réseau') + ' peut : ' + (p.anonymous.perms.map((x) => PERM_SHORT[x]).join(', ') || 'rien') + '.' +
    (p.migrated ? ' Réglage repris de la version précédente : créez des clés puis exigez-les.' : ''))] : []));
  const url = p.urls[0];
  $('#pub-urls').replaceChildren(...(p.enabled ? [el('div', {}, 'Adresse : ' + p.urls.join(', ') + ' - API compatible OpenAI : ' + url + '/v1'),
    el('pre', { class: 'example', text: 'curl ' + (p.tls ? '-k ' : '') + url + '/api/chat' + (p.auth ? ' -H "Authorization: Bearer <clé>"' : '') +
      ' -d \'{"model": "' + (pubState.models[0] || 'llama3.2:3b') + '", "messages": [{"role": "user", "content": "Bonjour"}]}\'' }),
    p.tls ? el('div', { class: 'muted', text: 'Certificat autosigné de la console : importez-le dans vos clients, ou désactivez la vérification (-k) pour un essai.' }) : null] :
    [el('div', { class: 'muted', text: 'Accès réseau désactivé : l\'API n\'est utilisable que depuis le serveur.' })]));
  $('#pub-keys').replaceChildren(...(p.keys.length ? [el('div', { class: 'table-wrap' }, el('table', {},
    el('thead', {}, el('tr', {}, ...['Nom', 'Clé', 'Droits', 'Modèles', 'Limites et consommation', 'Dernière utilisation', 'État', ''].map((t) => el('th', { text: t })))),
    el('tbody', {}, ...p.keys.map((k) => el('tr', {}, el('td', { class: 'name', text: k.name }), el('td', { class: 'small', text: k.prefix + '…' }),
      el('td', { class: 'small', text: k.perms.map((x) => PERM_SHORT[x]).concat((k.deny || []).map((x) => DENY_SHORT[x])).join(', ') }), el('td', { class: 'small', text: k.models.length ? k.models.join(', ') : 'tous' }),
      el('td', { class: 'small' }, ...keyLimits(k, (pubState.limits || {})[k.id]).map((x) => el('div', { text: x }))),
      el('td', { class: 'small', text: k.usage && k.usage.last ? fmtDate(k.usage.last) + ' (' + k.usage.count + ' requêtes)' : 'jamais' }),
      el('td', {}, k.enabled ? pill('active', 'ok') : pill('désactivée', 'warn'), keyExpiryPill(k)),
      el('td', { class: 'nowrap' }, el('button', { class: 'btn sm', type: 'button', text: k.enabled ? 'Désactiver' : 'Activer', onclick: () => keyToggle(k) }), ' ',
        el('button', { class: 'btn sm', type: 'button', text: 'Échéance', onclick: () => keyExpiry(k) }), ' ', el('button', { class: 'btn sm', type: 'button', text: 'Plafonds', onclick: () => keyCaps(k) }), ' ',
        el('button', { class: 'btn sm danger', type: 'button', text: 'Supprimer', onclick: () => keyDelete(k) })))))))] :
    [el('p', { class: 'muted small', text: 'Aucune clé. Créez une clé par application : vous pourrez la désactiver sans toucher aux autres.' })]));
  const kf = $('#key-form');
  if (!kf.dataset.ready) {
    checkList('#key-perms', 'perm', Object.keys(PERM_LABEL), ['inference', 'read'], PERM_LABEL);
    checkList('#key-deny', 'deny', Object.keys(DENY_LABEL), [], DENY_LABEL);
    kf.dataset.ready = '1';
  }
  const keep = checkedValues(kf, 'model');
  checkList('#key-models', 'model', pubState.models, keep);
}
$('#pub-form').elements.auth.addEventListener('change', (e) => $('#pub-anon').classList.toggle('hidden', e.target.checked));
$('#pub-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const body = { enabled: f.elements.enabled.checked, tls: f.elements.tls.value === '1', port: Number(f.elements.port.value), auth: f.elements.auth.checked,
    allow: f.elements.allow.value.split('\n').map((x) => x.trim()).filter(Boolean), anonymous: { perms: checkedValues(f, 'anon'), models: [] } };
  if (body.enabled && !body.auth && !(await modal({ title: 'Publier sans clé ?', message: 'Toute machine ' + (body.allow.length ? 'des réseaux autorisés' : 'du réseau') +
      ' pourra : ' + (body.anonymous.perms.map((x) => PERM_SHORT[x]).join(', ') || 'rien') + ', sans s\'identifier.', ok: 'Publier sans clé', danger: true }))) return;
  $('#pub-msg').className = 'small'; $('#pub-msg').textContent = 'Enregistrement...';
  try { await api('/api/publication', { json: body }); await loadPublication(); $('#pub-msg').className = 'small okmsg'; $('#pub-msg').textContent = 'Enregistré.'; }
  catch (e) { $('#pub-msg').className = 'small error'; $('#pub-msg').textContent = e.message; }
});
$('#key-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  try {
    const r = await api('/api/publication/keys/create', { json: { name: f.elements.name.value.trim(), perms: checkedValues(f, 'perm'), models: checkedValues(f, 'model'), deny: checkedValues(f, 'deny'),
      max_concurrent: Number(f.elements.max_concurrent.value) || 0, max_ctx: Number(f.elements.max_ctx.value) || 0, max_output: Number(f.elements.max_output.value) || 0, quota_day: Number(f.elements.quota_day.value) || 0, quota_month: Number(f.elements.quota_month.value) || 0, expires: f.elements.expires.value } });
    f.elements.name.value = ''; f.elements.expires.value = ''; $('#key-msg').textContent = '';
    await loadPublication();
    const code = el('code', { class: 'token', text: r.token });
    const copied = el('span', { class: 'small okmsg' });
    await modal({ title: 'Clé « ' + r.key.name + ' » créée', message: 'Copiez-la maintenant : elle ne sera plus jamais affichée (seule son empreinte est conservée).',
      body: el('div', {}, code, el('button', { class: 'btn sm', type: 'button', text: 'Copier', onclick: async () => {
        try { await navigator.clipboard.writeText(r.token); copied.textContent = ' Copiée.'; }
        catch (e) { const rg = document.createRange(); rg.selectNodeContents(code); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(rg); copied.textContent = ' Sélectionnée : Ctrl+C pour copier.'; } } }), copied),
      ok: 'J\'ai copié la clé', cancel: null });
  } catch (e) { $('#key-msg').className = 'small error'; $('#key-msg').textContent = e.message; }
});
async function keyToggle(k) {
  if (k.enabled && !(await ask('Désactiver la clé « ' + k.name + ' » ? Les applications qui l\'utilisent n\'auront plus accès, jusqu\'à sa réactivation.', { ok: 'Désactiver', danger: true }))) return;
  try { await api('/api/publication/keys/update', { json: { id: k.id, enabled: !k.enabled } }); await loadPublication(); } catch (e) { fail(e.message); }
}
async function keyDelete(k) {
  if (!(await ask('Supprimer la clé « ' + k.name + ' » ? Les applications qui l\'utilisent perdront l\'accès définitivement.'))) return;
  try { await api('/api/publication/keys/delete', { json: { id: k.id } }); await loadPublication(); } catch (e) { fail(e.message); }
}

/* ---------------------------------------------------------------- sécurité */
async function loadSecurity() {
  let d;
  try { d = await api('/api/security'); } catch (e) { $('#sec-audit').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const okCount = d.audit.filter((c) => c.ok).length;
  $('#sec-audit').replaceChildren(el('div', { class: 'small', text: okCount + ' contrôle(s) conforme(s) sur ' + d.audit.length }),
    el('div', { class: 'audit' }, ...d.audit.map((c) => el('div', { class: 'item' }, pill(c.ok ? 'conforme' : 'à traiter', c.ok ? 'ok' : 'warn'),
      el('span', { text: c.label }), c.detail ? el('span', { class: 'detail', text: c.detail }) : null))));
  $('#sec-install').classList.toggle('hidden', d.firewall.available && d.updates.installed);
  const fw = d.firewall;
  $('#fw-state').replaceChildren(el('p', {}, fw.active ? pill('actif', 'ok') : pill(fw.available ? 'inactif' : 'nftables absent', 'warn'),
    ' Refus par défaut en entrée' + (fw.drops != null ? ' - ' + fw.drops + ' paquet(s) refusé(s) depuis le démarrage' : '')));
  $('#fw-ports').replaceChildren(el('div', { class: 'table-wrap' }, el('table', {},
    el('thead', {}, el('tr', {}, ...['Port', 'Service', 'Origines autorisées'].map((t) => el('th', { text: t })))),
    el('tbody', {}, ...fw.ports.map((p) => el('tr', {}, el('td', { class: 'name', text: 'TCP ' + p.port }), el('td', { text: p.service }),
      el('td', { class: 'small', text: p.sources.length ? p.sources.join(', ') : 'toutes' })))))),
    el('p', { class: 'muted small', text: 'Tous les autres ports sont fermés depuis le réseau, dont Ollama, les groupes de GPU et Open WebUI en HTTP (3000).' }));
  const f = $('#fw-form');
  f.elements.admin.value = (fw.admin_allow || []).join('\n'); f.elements.log.checked = fw.log_drops; f.elements.enabled.checked = fw.enabled;
  const u = d.updates, uf = $('#uu-form');
  uf.elements.enabled.checked = u.enabled; uf.elements.time.value = u.time; uf.elements.reboot.checked = u.reboot; uf.elements.reboot_time.value = u.reboot_time;
  uf.querySelectorAll('input, button').forEach((i) => { i.disabled = !u.installed; });
  $('#uu-info').textContent = !u.installed ? 'unattended-upgrades n\'est pas installé : utilisez « Installer les paquets de sécurité ».' :
    (u.enabled ? 'Prochaine exécution : ' + (u.next || 'inconnue') : 'Mises à jour automatiques désactivées.') + (u.log.length ? ' - dernières lignes du journal :' : '');
  $('#uu-log').textContent = u.log.join('\n');
}
$('#sec-refresh').addEventListener('click', () => { loadSecurity(); loadPolicy(); });
$('#fw-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, body = { enabled: f.elements.enabled.checked, log_drops: f.elements.log.checked,
    admin_allow: f.elements.admin.value.split('\n').map((x) => x.trim()).filter(Boolean) };
  if (!body.enabled && !(await modal({ title: 'Désactiver le pare-feu ?', message: 'Tous les ports en écoute deviendront joignables depuis le réseau, dont Open WebUI en HTTP (3000).', ok: 'Désactiver le pare-feu', danger: true }))) return;
  $('#fw-msg').className = 'small'; $('#fw-msg').textContent = 'Application des règles...';
  try { await api('/api/security/firewall', { json: body }); await loadSecurity(); $('#fw-msg').className = 'small okmsg'; $('#fw-msg').textContent = 'Règles appliquées.'; }
  catch (e) { $('#fw-msg').className = 'small error'; $('#fw-msg').textContent = e.message; }
});
$('#uu-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  try {
    await api('/api/security/updates', { json: { enabled: f.elements.enabled.checked, time: f.elements.time.value, reboot: f.elements.reboot.checked, reboot_time: f.elements.reboot_time.value } });
    await loadSecurity(); $('#uu-msg').className = 'small okmsg'; $('#uu-msg').textContent = 'Enregistré.';
  } catch (e) { $('#uu-msg').className = 'small error'; $('#uu-msg').textContent = e.message; }
});

/* ------------------------------------------------ usages de l'IA (politique) */
async function loadPolicy() {
  let p;
  try { p = await api('/api/security/policy'); } catch (e) { $('#pol-msg').className = 'small error'; $('#pol-msg').textContent = e.message; return; }
  const f = $('#pol-form');
  f.elements.cloud.checked = p.cloud; f.elements.ollama_internet.checked = p.ollama_internet; f.elements.webui_locked.checked = p.webui_locked;
  $('#pol-webui-list').replaceChildren(...p.webui_features.map((x) => el('label', {}, el('input', { type: 'checkbox', name: 'webui', value: x.key, checked: p.webui[x.key] || null }), x.label)));
  $('#pol-webui').querySelector('.muted').textContent = p.webui_deployed ? 'Open WebUI : fonctions autorisées' : 'Open WebUI (appliqué lors de son déploiement) : fonctions autorisées';
}
$('#pol-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, webui = {};
  f.querySelectorAll('input[name=webui]').forEach((i) => { webui[i.value] = i.checked; });
  const body = { cloud: f.elements.cloud.checked, ollama_internet: f.elements.ollama_internet.checked, webui_locked: f.elements.webui_locked.checked, webui };
  if (body.cloud && !(await modal({ title: 'Autoriser les fonctions cloud ?', message: 'Les requêtes vers les modèles « :cloud » et la recherche web sont traitées par Ollama, hors de ce serveur : les données envoyées quittent votre infrastructure.', ok: 'Autoriser', danger: true }))) return;
  $('#pol-msg').className = 'small'; $('#pol-msg').textContent = 'Application...';
  try {
    const r = await api('/api/security/policy', { json: body });
    await loadPolicy();
    $('#pol-msg').className = 'small okmsg'; $('#pol-msg').textContent = r.job ? 'Appliqué ; Open WebUI est recréé avec ces réglages (voir la tâche).' : 'Appliqué.';
    if (r.job) followJob(r.job);
  } catch (e) { $('#pol-msg').className = 'small error'; $('#pol-msg').textContent = e.message; }
});

/* ------------------------------------------------- modèles personnalisés */
async function loadCustom() {
  let d, installed;
  try { d = await api('/api/models/custom'); installed = ((await api('/api/models')).models || []).map((m) => m.name); } catch (e) { $('#cm-list').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const custom = new Set(d.custom.map((c) => c.name));
  const sel = $('#cm-form').elements.base, keep = sel.value;
  sel.replaceChildren(...installed.filter((m) => !custom.has(m)).map((m) => el('option', { value: m, text: m })));
  if (keep) sel.value = keep;
  $('#cm-list').replaceChildren(...(d.custom.length ? [el('div', { class: 'table-wrap' }, el('table', {},
    el('thead', {}, el('tr', {}, ...['Nom', 'Modèle de base', 'Prompt système', 'Paramètres', ''].map((x) => el('th', { text: x })))),
    el('tbody', {}, ...d.custom.map((c) => el('tr', {}, el('td', { class: 'name', text: c.name }), el('td', { text: c.base }),
      el('td', { class: 'small', text: c.system ? (c.system.length > 90 ? c.system.slice(0, 90) + '…' : c.system) : '-' }),
      el('td', { class: 'small', text: Object.entries(c.params || {}).map(([k, v]) => k + ' = ' + v).join(', ') || '-' }),
      el('td', { class: 'nowrap' }, el('button', { class: 'btn sm', type: 'button', text: 'Modifier', onclick: () => editCustom(c) }), ' ',
        el('button', { class: 'btn sm danger', type: 'button', text: 'Supprimer', onclick: () => deleteCustom(c.name) }))))))) ] :
    [el('p', { class: 'muted small', text: 'Aucun modèle personnalisé.' })]));
  const pre = new Set(d.preload);
  $('#pl-list').replaceChildren(...installed.map((m) => el('label', {}, el('input', { type: 'checkbox', name: 'preload', value: m, checked: pre.has(m) || null }), m,
    pre.has(m) && d.preload_state[m] ? el('span', { class: 'muted small', text: ' (' + d.preload_state[m] + ')' }) : null)));
}
function editCustom(c) {
  const f = $('#cm-form');
  f.elements.name.value = c.name; f.elements.base.value = c.base; f.elements.system.value = c.system || '';
  for (const k of ['temperature', 'num_ctx', 'top_p', 'repeat_penalty']) f.elements[k].value = c.params && c.params[k] != null ? c.params[k] : '';
  f.scrollIntoView({ behavior: 'smooth' });
}
$('#cm-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, params = {};
  for (const k of ['temperature', 'num_ctx', 'top_p', 'repeat_penalty']) if (f.elements[k].value !== '') params[k] = Number(f.elements[k].value);
  $('#cm-msg').className = 'small'; $('#cm-msg').textContent = 'Création...';
  try {
    const r = await api('/api/models/custom/create', { json: { name: f.elements.name.value.trim(), base: f.elements.base.value, system: f.elements.system.value, params } });
    await loadCustom(); loadModels();
    $('#cm-msg').className = 'small okmsg'; $('#cm-msg').textContent = 'Modèle « ' + r.name + ' » prêt.';
  } catch (e) { $('#cm-msg').className = 'small error'; $('#cm-msg').textContent = e.message; }
});
async function deleteCustom(name) {
  if (!(await ask('Supprimer le modèle personnalisé « ' + name + ' » ? Le modèle de base est conservé.'))) return;
  try { await api('/api/models/custom/delete', { json: { name } }); await loadCustom(); loadModels(); } catch (e) { fail(e.message); }
}
$('#pl-save').addEventListener('click', async () => {
  const models = [...$$('#pl-list input:checked')].map((i) => i.value);
  try { await api('/api/models/preload', { json: { models } }); $('#pl-msg').className = 'small okmsg'; $('#pl-msg').textContent = models.length ? 'Enregistré : chargement en cours.' : 'Préchargement désactivé.'; setTimeout(loadCustom, 3000); }
  catch (e) { $('#pl-msg').className = 'small error'; $('#pl-msg').textContent = e.message; }
});

/* ------------------------------------------------- parc de serveurs */
const FLEET_KIND = { 'en ligne': 'ok', 'hors ligne': 'err', 'certificat changé': 'err', 'jeton refusé': 'err', 'en attente': 'info' };
function fleetAlerts(d) {
  const a = [];
  if (!d) return a;
  if (d.reboot_required) a.push('Redémarrage requis pour appliquer des correctifs');
  if (d.firewall_active === false) a.push('Pare-feu inactif');
  if (d.autoupdates === false) a.push('Mises à jour de sécurité automatiques désactivées');
  if (d.ollama && d.ollama.service !== 'active') a.push('Ollama : ' + d.ollama.service);
  if (d.disk && d.disk.total && d.disk.used / d.disk.total > 0.9) a.push('Disque occupé à plus de 90 %');
  for (const g of d.gpu_live || []) if (g.temp != null && g.temp >= 85) a.push('GPU ' + g.name + ' : ' + DEC(g.temp.toFixed(0)) + ' °C');
  if (d.jobs && d.jobs.length) a.push(d.jobs.length + ' tâche(s) en cours : ' + d.jobs.map((j) => j.title).join(', '));
  return a;
}
const fleetUnmapped = (s, mine, theirs) => (s.model_map && s.model_map['*']) ? [] : fleetMissing(mine, theirs).filter((m) => !(s.model_map || {})[m]);
const fleetMissing = (mine, theirs) => (mine || []).filter((m) => !(theirs || []).includes(m));
async function loadFleet() {
  let v;
  try { v = await api('/api/fleet/servers'); } catch (e) { $('#fleet-summary').textContent = e.message; return; }
  loadRules(v);
  const on = v.servers.filter((s) => s.state === 'en ligne');
  const gpus = on.flatMap((s) => (s.data && s.data.gpu_live) || []);
  fleetState.kinds = v.sync_kinds;
  const routed = v.servers.filter((s) => s.route).length;
  $('#fleet-summary').textContent = v.servers.length ? v.servers.length + ' serveur(s) - ' + on.length + ' en ligne - répartition de charge sur ' + routed + ' serveur(s) - ' + gpus.length + ' GPU mesuré(s)' +
    (gpus.length ? ', charge moyenne ' + DEC((gpus.reduce((t, g) => t + (g.util || 0), 0) / gpus.length).toFixed(0)) + ' %' : '') :
    'Aucun serveur enregistré : ajoutez-en un ci-dessous.';
  $('#fleet-grid').replaceChildren(...v.servers.map((s) => {
    const d = s.data, alerts = fleetAlerts(d);
    const acts = s.state === 'en ligne' ? Object.entries(v.actions).map(([id, label]) => el('button', { class: 'btn sm', type: 'button', text: label, onclick: () => fleetAction(s, id, label) })) : [];
    if (s.state === 'en ligne') {
      acts.push(el('button', { class: 'btn sm', type: 'button', text: s.route ? 'Désactiver la répartition' : 'Activer la répartition de charge', onclick: () => fleetRoute(s) }));
      if (s.route) acts.push(el('button', { class: 'btn sm', type: 'button', text: 'Modèles de remplacement...', onclick: () => fleetModelMap(s) }));
      acts.push(el('button', { class: 'btn sm', type: 'button', text: 'Synchroniser...', onclick: () => fleetSync(s.id, s.name, v.sync_kinds) }));
    }
    if (s.state === 'certificat changé') acts.push(el('button', { class: 'btn sm danger', type: 'button', text: 'Examiner le nouveau certificat', onclick: () => fleetRepin(s) }));
    return el('div', { class: 'card fleet' + (s.state === 'en ligne' ? '' : ' offline') },
      el('div', { class: 'head' }, el('h2', { text: s.name }), el('span', {}, s.route ? pill('répartition', 'info') : null, ' ', pill(s.state, FLEET_KIND[s.state] || 'warn'))),
      kv([['Adresse', s.url], ['Version', d ? 'OllamaBuntu ' + d.version : '-'], ['Ollama', d && d.ollama ? (d.ollama.version || '?') + ' - ' + d.ollama.service : '-'],
        ['Modèles', d && d.models ? d.models.count + ' (' + fmtBytes(d.models.size) + ')' : '-'],
        ['En mémoire', d && d.ollama && d.ollama.running.length ? d.ollama.running.map((m) => m.name).join(', ') : 'aucun'],
        ['Dernier contact', s.last_ok ? fmtDate(s.last_ok) : '-'], ['Dernière synchronisation', s.last_sync ? fmtDate(s.last_sync.at) : 'jamais']]),
      d && (d.gpu_live || []).length ? el('div', { class: 'gpus' }, ...d.gpu_live.map((g) => el('div', { class: 'g' }, el('div', {}, el('div', { class: 'small', text: g.name }), bar(g.util || 0)), el('div', { class: 'small', text: g.util == null ? '-' : DEC(g.util.toFixed(0)) + ' %' })))) : null,
      d ? el('div', { class: 'small muted', text: 'Processeur ' + (d.cpu.usage == null ? '-' : DEC(d.cpu.usage) + ' %') + ' - mémoire ' + pct(d.memory.total - d.memory.available, d.memory.total) + ' % - disque ' + pct(d.disk.used, d.disk.total) + ' %' }) : null,
      s.route && s.state === 'en ligne' && d && d.model_tags && fleetUnmapped(s, v.local_models, d.model_tags.map((m) => String(m.name))).length
        ? el('div', { class: 'small error' }, el('div', { text: 'Modèles absents de ce serveur (il ne reçoit pas leurs requêtes) :' }), el('div', { text: fleetUnmapped(s, v.local_models, d.model_tags.map((m) => String(m.name))).join(', ') }), el('div', { text: 'Installez-les (Synchroniser > Modèles) ou choisissez un modèle de remplacement si ses GPU sont différents.' })) : null,
      alerts.length ? el('ul', { class: 'alerts' }, ...alerts.map((x) => el('li', { text: x }))) : null,
      s.error ? el('div', { class: 'small error', text: s.error }) : null,
      el('div', { class: 'actions' }, ...acts, el('a', { class: 'btn sm', href: s.url + '/', target: '_blank', rel: 'noopener', text: 'Ouvrir sa console' }),
        el('button', { class: 'btn sm danger', type: 'button', text: 'Retirer', onclick: () => fleetRemove(s) })));
  }));
}
$('#fleet-refresh').addEventListener('click', loadFleet);
const fleetState = { kinds: {} };
async function fleetRoute(s) {
  const on = !s.route;
  if (!(await modal({ title: on ? 'Activer la répartition de charge' : 'Désactiver la répartition de charge',
    message: on ? 'Les requêtes reçues par cette console pour un modèle présent sur « ' + s.name + ' » pourront y être envoyées, selon la charge de chaque serveur. « ' + s.name + ' » délivre pour cela un jeton limité à l\'utilisation des modèles ; sa propre politique d\'usage de l\'IA continue de s\'appliquer.'
      : 'Les requêtes ne seront plus envoyées à « ' + s.name + ' » ; son jeton de routage est révoqué.', ok: on ? 'Activer' : 'Désactiver', danger: !on }))) return;
  try { await api('/api/fleet/servers/route', { json: { id: s.id, enabled: on } }); loadFleet(); } catch (e) { fail(e.message); }
}
function syncReport(results) {
  return Object.entries(results).map(([name, r]) => {
    if (r.error) return name + ' : échec - ' + r.error;
    const parts = [];
    if (r.policy) parts.push('politique ' + r.policy);
    if (r.keys != null) parts.push(r.keys + ' clé(s) d\'API');
    if (r.pull) parts.push(r.pull.models.length ? r.pull.models.length + ' modèle(s) en téléchargement' : 'modèles déjà présents');
    if (r.custom) parts.push(r.custom.created.length + ' modèle(s) personnalisé(s) créé(s)' + (r.custom.waiting.length ? ', ' + r.custom.waiting.length + ' en attente de leur modèle de base' : ''));
    return name + ' : ' + (parts.join(', ') || 'rien à faire');
  }).join('\n');
}
async function fleetModelMap(s) {
  const ta = el('textarea', { rows: 6, class: 'mono', style: 'width:100%', placeholder: 'gemma4:12b = granite4.2:8b' });
  ta.value = Object.entries(s.model_map || {}).map(([k, v]) => k + ' = ' + v).join('\n');
  const go = await modal({ title: 'Modèles de remplacement de « ' + s.name + ' »',
    message: 'Si ce serveur ne peut pas faire tourner un modèle (GPU différents), indiquez le modèle qu\'il utilisera à la place : une ligne « modèle demandé = modèle de remplacement ». Écrivez « * = modèle » pour remplacer tous les modèles absents. Les réponses viendront alors d\'un autre modèle, donc leur qualité et leur style peuvent différer.', body: ta, ok: 'Enregistrer' });
  if (!go) return;
  const map = {};
  for (const line of ta.value.split('\n')) {
    const t = line.trim();
    if (!t) continue;
    const i = t.indexOf('=');
    if (i < 1) { fail('Ligne invalide : ' + t); return; }
    map[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  try { await api('/api/fleet/servers/modelmap', { json: { id: s.id, map } }); loadFleet(); } catch (e) { fail(e.message); }
}
async function fleetSync(id, name, kinds) {
  kinds = kinds || fleetState.kinds;
  const box = el('div', { class: 'checks col' }, ...Object.entries(kinds).map(([k, label]) => el('label', {}, el('input', { type: 'checkbox', name: 'sync', value: k, checked: k !== 'models' || null }), label)));
  const go = await modal({ title: 'Synchroniser ' + (id === 'all' ? 'tout le parc' : '« ' + name + ' »'),
    message: 'Copier depuis cette console vers ' + (id === 'all' ? 'tous les serveurs en ligne' : '« ' + name + ' »') + ' :', body: box, ok: 'Synchroniser' });
  if (!go) return;
  const sel = [...box.querySelectorAll('input:checked')].map((i) => i.value);
  try {
    const r = await api('/api/fleet/servers/sync', { json: { id, kinds: sel } });
    await notify(syncReport(r.results), { title: 'Synchronisation terminée' });
    loadFleet();
  } catch (e) { fail(e.message); }
}
$('#fleet-sync-all').addEventListener('click', () => fleetSync('all', '', null));
$('#fleet-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, url = f.elements.url.value.trim();
  $('#fleet-msg').className = 'small'; $('#fleet-msg').textContent = 'Vérification du serveur...';
  let pr;
  try { pr = await api('/api/fleet/servers/probe', { json: { url } }); } catch (e) { $('#fleet-msg').className = 'small error'; $('#fleet-msg').textContent = e.message; return; }
  $('#fleet-msg').textContent = '';
  const okFp = await modal({ title: 'Vérifier le certificat', message: 'Serveur OllamaBuntu ' + pr.version + ' à l\'adresse ' + pr.url + '.\nComparez cette empreinte avec celle affichée sur le serveur (Système > Gestion centralisée). Si elles diffèrent, n\'ajoutez pas ce serveur.',
    body: el('code', { class: 'fp token', text: pr.fingerprint }), ok: 'Les empreintes sont identiques' });
  if (!okFp) return;
  try {
    const added = await api('/api/fleet/servers/add', { json: { name: f.elements.name.value.trim(), url: pr.url, token: f.elements.token.value.trim(), fingerprint: pr.fingerprint } });
    const wantRoute = f.elements.route.checked;
    f.reset(); $('#fleet-msg').className = 'small okmsg'; $('#fleet-msg').textContent = 'Serveur ajouté.';
    if (wantRoute) {
      try { await api('/api/fleet/servers/route', { json: { id: added.id, enabled: true } }); $('#fleet-msg').textContent = 'Serveur ajouté, répartition de charge activée.'; }
      catch (e) { $('#fleet-msg').className = 'small error'; $('#fleet-msg').textContent = 'Serveur ajouté, mais la répartition n\'a pas pu être activée : ' + e.message; }
    }
    loadFleet(); loadBalance();
  } catch (e) { $('#fleet-msg').className = 'small error'; $('#fleet-msg').textContent = e.message; }
});
async function fleetAction(s, id, label) {
  if (!(await ask(label + ' sur « ' + s.name + ' » ?', { ok: label }))) return;
  try { await api('/api/fleet/servers/action', { json: { id: s.id, action: id } }); notify('Action envoyée à « ' + s.name + ' » : ' + label + '.'); setTimeout(loadFleet, 1500); } catch (e) { fail(e.message); }
}
async function fleetRemove(s) {
  if (!(await ask('Retirer « ' + s.name + ' » de cette console ? Pensez aussi à révoquer l\'accès sur le serveur lui-même.', { ok: 'Retirer', danger: true }))) return;
  try { await api('/api/fleet/servers/remove', { json: { id: s.id } }); loadFleet(); } catch (e) { fail(e.message); }
}
async function fleetRepin(s) {
  const yes = await modal({ title: 'Certificat changé', message: 'Le certificat de « ' + s.name + ' » ne correspond plus à celui approuvé. C\'est normal après une réinstallation ou un renouvellement ; sinon, quelqu\'un pourrait s\'interposer. Comparez la nouvelle empreinte avec celle affichée sur le serveur.',
    body: el('code', { class: 'fp token', text: s.new_fingerprint }), ok: 'Approuver ce certificat', danger: true });
  if (!yes) return;
  try { await api('/api/fleet/servers/repin', { json: { id: s.id, fingerprint: s.new_fingerprint } }); loadFleet(); } catch (e) { fail(e.message); }
}

/* -------------------------------------------- gestion centralisée (serveur géré) */
async function loadMember() {
  let m;
  try { m = await api('/api/fleet/member'); } catch (e) { $('#fm-msg').textContent = e.message; return; }
  $('#fm-fp').replaceChildren('Empreinte du certificat de ce serveur : ', el('code', { class: 'fp', text: m.fingerprint || '?' }),
    m.last_sync ? el('div', { class: 'muted', text: 'Dernière synchronisation reçue de « ' + m.last_sync.from + ' » : ' + fmtDate(m.last_sync.at) }) : null);
  $('#fm-list').replaceChildren(...(m.consoles.length ? [el('div', { class: 'table-wrap' }, el('table', {}, el('tbody', {}, ...m.consoles.map((c) => el('tr', {},
    el('td', { class: 'name', text: c.name }), el('td', { class: 'small', text: c.prefix + '…' }), el('td', { class: 'small', text: 'dernier contact : ' + (c.last_seen ? fmtDate(c.last_seen) : 'jamais') + (c.route ? ' - répartition de charge autorisée' : '') }),
    el('td', {}, el('button', { class: 'btn sm danger', type: 'button', text: 'Révoquer', onclick: () => memberRevoke(c) }))))))) ] :
    [el('p', { class: 'muted small', text: 'Aucune console principale autorisée.' })]));
}
$('#fm-add').addEventListener('click', async () => {
  const name = $('#fm-name').value.trim() || 'Console principale';
  try {
    const r = await api('/api/fleet/member/create', { json: { name } });
    $('#fm-name').value = ''; await loadMember();
    await modal({ title: 'Console principale autorisée', message: 'Saisissez ce jeton dans la console principale (Serveurs > Ajouter un serveur). Il ne sera plus jamais affiché.',
      body: el('div', {}, el('code', { class: 'token', text: r.token }), el('div', { class: 'small muted', text: 'Empreinte du certificat à vérifier lors de l\'ajout :' }), el('code', { class: 'fp', text: r.fingerprint })),
      ok: 'J\'ai copié le jeton', cancel: null });
  } catch (e) { $('#fm-msg').className = 'small error'; $('#fm-msg').textContent = e.message; }
});
async function memberRevoke(c) {
  if (!(await ask('Révoquer l\'accès de « ' + c.name + ' » ? Cette console principale ne pourra plus superviser ce serveur.', { ok: 'Révoquer', danger: true }))) return;
  try { await api('/api/fleet/member/revoke', { json: { id: c.id } }); loadMember(); } catch (e) { fail(e.message); }
}

/* ------------------------------------------------- boîtes de dialogue */
/* Fenêtres de la console (aucune fenêtre système) : file d'attente, focus piégé,
   Échap / clic extérieur = annuler, Entrée = valider. */
const dialogs = { chain: Promise.resolve() };
const DANGER_VERBS = /^(Supprimer|Éteindre|Redémarrer|Tout supprimer|Réinitialiser|Révoquer)/;
function modal({ title, message, ok = 'OK', cancel = 'Annuler', danger = false, kind = '', body = null }) {
  const run = () => new Promise((resolve) => {
    const box = $('#modal'), okB = $('#modal-ok'), noB = $('#modal-cancel'), prev = document.activeElement;
    $('#modal-title').textContent = title;
    $('#modal-text').textContent = message || '';
    $('#modal-extra').replaceChildren(...(body ? [body] : []));
    box.className = 'modal ' + kind;
    okB.textContent = ok; okB.className = 'btn ' + (danger ? 'danger' : 'primary');
    noB.textContent = cancel || ''; noB.classList.toggle('hidden', !cancel);
    const done = (v) => {
      box.classList.add('hidden'); document.removeEventListener('keydown', key, true);
      okB.onclick = noB.onclick = box.onclick = null;
      if (prev && prev.focus) prev.focus();
      resolve(v);
    };
    const key = (ev) => {
      if (ev.key === 'Escape') { ev.preventDefault(); done(false); }
      else if (ev.key === 'Enter' && ev.target.tagName !== 'TEXTAREA') { ev.preventDefault(); done(true); }
      else if (ev.key === 'Tab') {   // le focus reste dans la fenêtre
        const f = [...box.querySelectorAll('button:not(.hidden), input, textarea, select, a[href]')];
        const i = f.indexOf(document.activeElement);
        ev.preventDefault(); f[(i + (ev.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      }
    };
    okB.onclick = () => done(true); noB.onclick = () => done(false);
    box.onclick = (ev) => { if (ev.target === box) done(false); };
    document.addEventListener('keydown', key, true);
    okB.focus();
  });
  const p = dialogs.chain.then(run);
  dialogs.chain = p.catch(() => {});
  return p;
}
function ask(message, opts = {}) {
  const verb = (String(message).match(DANGER_VERBS) || [])[1];
  return modal({ title: opts.title || 'Confirmation', message, ok: opts.ok || verb || 'Confirmer', danger: opts.danger ?? !!verb });
}
const notify = (message, opts = {}) => modal({ title: opts.title || 'Information', message, cancel: null, body: opts.body || null });
const fail = (message) => modal({ title: 'Erreur', message, cancel: null, kind: 'error' });

/* ----------------------------------------------------------- tâches longues */
const jobs = { current: null, timer: null };
function followJob(id) {
  clearTimeout(jobs.timer);
  jobs.current = id;
  $('#job-card').classList.remove('hidden');
  const tick = async () => {
    try {
      const [j, list] = await Promise.all([api('/api/jobs/' + encodeURIComponent(jobs.current)), api('/api/jobs')]);
      const pending = list.jobs.filter((x) => !x.done).sort((a, b) => (a.queued - b.queued) || ((a.position || 0) - (b.position || 0)));
      $('#job-queue').replaceChildren(...(pending.length > 1 || (pending.length === 1 && pending[0].id !== j.id) ? [
        el('div', { class: 'small muted', text: 'File des tâches système (exécutées une à la fois) :' }),
        ...pending.map((x) => el('div', { class: 'q' },
          el('span', {}, x.queued ? pill('en attente n°' + (x.position || '?'), 'info') : pill('en cours', 'ok'), ' ' + x.title),
          x.queued ? el('button', { class: 'btn sm', type: 'button', text: 'Annuler', onclick: () => cancelJob(x) }) : null))] : []));
      $('#job-title').textContent = j.title + (j.done ? (j.rc === 0 ? ' - terminé' : j.rc === 130 ? ' - annulée' : ' - échec (code ' + j.rc + ')')
        : j.queued ? ' - en attente (n°' + (j.position || '?') + ' dans la file)' : ' - en cours...');
      const pre = $('#job-log'); pre.textContent = j.output || (j.queued ? 'En attente de la fin des tâches précédentes...' : '...'); pre.scrollTop = pre.scrollHeight;
      if (!j.done) { jobs.timer = setTimeout(tick, 2000); return; }
      if (location.hash === '#gpu') loadGpu();
      else if (location.hash === '#webui') loadWebui();
      else if (location.hash === '#system') loadUpdates(true);
      else if (location.hash === '#security') loadSecurity();
      const next = pending.find((x) => !x.queued) || pending[0];   // enchaîner sur la tâche suivante
      if (next) { jobs.current = next.id; jobs.timer = setTimeout(tick, 2500); }
    } catch (e) { $('#job-title').textContent = e.message; }
  };
  tick();
}
async function cancelJob(x) {
  if (!(await modal({ title: 'Annuler une tâche', message: 'Retirer « ' + x.title + ' » de la file d\'attente ?', ok: 'Retirer de la file', cancel: 'Garder', danger: true }))) return;
  try { await api('/api/jobs/cancel', { json: { id: x.id } }); } catch (e) { fail(e.message); }
}
async function resumeJob() {
  if (jobs.current) return;
  try { const running = (await api('/api/jobs')).jobs.find((j) => !j.done); if (running) followJob(running.id); } catch (e) { /* vide */ }
}
$('#job-close').addEventListener('click', () => { clearTimeout(jobs.timer); jobs.current = null; $('#job-card').classList.add('hidden'); });

/* ----------------------------------------------------------------- système */
async function loadSystem() {
  try {
    const [s, a] = await Promise.all([api('/api/status'), api('/api/about')]);
    state.status = s;
    setBanner(s.reboot_required);
    $('#sys-ollama').textContent = 'Ollama ' + (s.ollama.version || '?') + ' - service : ' + s.ollama.service;
    loadPublication();
    loadAlerts();
    loadRollback();
    loadMember();
    const b = a.build || {};
    $('#about').replaceChildren(...kv([
      ['OllamaBuntu', 'v' + a.version], ['Construit le', b.build_date || '-'], ['Base Ubuntu', b.ubuntu || a.os],
      ['Ollama', (a.ollama || '?') + (b.ollama ? ' (installé : ' + b.ollama + ')' : '')], ['Modèles embarqués', b.models || 'aucun'],
      ['Noyau', a.kernel], ['Machine', a.hostname], ['Démarré le', fmtDate(a.boot_time)]]).childNodes);
    $('#update-history').replaceChildren(...(a.updates && a.updates.length ? [el('div', { text: 'Historique :' }), ...a.updates.slice().reverse().map((l) => el('div', { text: l }))] : [el('div', { text: 'Aucune mise à jour appliquée depuis l\'installation.' })]));
    $('#sys-update-note').replaceChildren(...(s.update_available && isAdmin() ? [pill('mise à jour disponible', 'warn'), document.createTextNode(' OllamaBuntu v' + s.update_available + ' est publié. '), el('a', { href: '#system/appliance', text: 'Voir' })] : []));
    resumeJob();
    loadUpdates(false);
    loadOnlineUpdate();
  } catch (e) { $('#sys-ollama').textContent = e.message; }
}
for (const b of $$('[data-action]')) b.addEventListener('click', async () => { b.disabled = true; await runAction(b.dataset.action); b.disabled = false; loadSystem(); });
for (const b of $$('[data-job]')) b.addEventListener('click', async () => {
  if (!(await ask(b.textContent + ' ?'))) return;
  try { const d = await api('/api/action', { json: { action: b.dataset.job } }); followJob(d.job); } catch (e) { fail(e.message); }
});
for (const b of $$('[data-power]')) b.addEventListener('click', () => power(b.dataset.power));

/* Redémarrage / arrêt : suivi réel de l'état du serveur (empreinte du démarrage) */
function overlay(title, text, mode) {
  $('#overlay').classList.remove('hidden');
  $('#ov-title').textContent = title; $('#ov-text').textContent = text || '';
  $('#ov-spin').className = 'spinner' + (mode ? ' ' + mode : '');
  $('#ov-close').classList.toggle('hidden', !mode);
}
$('#ov-close').addEventListener('click', () => $('#overlay').classList.add('hidden'));
async function power(act) {
  const reboot = act === 'reboot';
  if (!(await ask((reboot ? 'Redémarrer' : 'Éteindre') + ' le serveur maintenant ?'))) return;
  const before = await ping();
  overlay(reboot ? 'Redémarrage demandé...' : 'Arrêt demandé...', 'Envoi de la commande au serveur.');
  try {
    await api('/api/action', { json: { action: act } });
  } catch (e) {
    if (!(e instanceof TypeError)) { overlay('Commande refusée', e.message, 'fail'); return; }   // TypeError = connexion déjà coupée
  }
  clearInterval(state.timer);
  const t0 = Date.now(); let down = false;
  for (;;) {
    await sleep(3000);
    const p = await ping();
    const secs = Math.round((Date.now() - t0) / 1000);
    if (!p) {
      down = true;
      overlay(reboot ? 'Le serveur redémarre...' : 'Arrêt en cours...', 'Serveur hors ligne depuis ' + secs + ' s.' + (reboot ? ' Un serveur physique peut mettre plusieurs minutes.' : ''));
      if (!reboot && secs > 20) { overlay('Serveur éteint', 'Le serveur ne répond plus.', 'done'); return; }
    } else if (before && p.boot !== before.boot) {
      overlay('Le serveur a redémarré', 'Nouveau démarrage confirmé (' + new Date().toLocaleTimeString(LOCALE()) + '). Reconnectez-vous.', 'done');
      setTimeout(() => { $('#overlay').classList.add('hidden'); showLogin(); }, 3000);
      return;
    } else if (!down && secs > 90) {
      overlay('Le redémarrage n\'a pas eu lieu', 'Le serveur répond toujours avec le même démarrage. Consultez Journaux > Console web.', 'fail');
      return;
    }
    if (secs > 1200) { overlay('Le serveur ne répond plus', 'Aucune réponse depuis 20 minutes : vérifiez la console du serveur.', 'fail'); return; }
  }
}


/* Mise à jour de l'appliance depuis un CD/ISO : la console redémarre à la fin (session perdue),
   on suit donc la tâche puis la version publique (/api/ping) jusqu'au nouveau démarrage. */
async function applianceUpdate(opt = {}) {
  if (!(await ask(opt.confirm || 'Mettre à jour l\'appliance depuis le CD/ISO ou la clé USB connectés ?\nLes services IA redémarrent ; comptes, réglages et modèles sont conservés.'))) return;
  const before = (await ping()) || {};
  let jid;
  try { jid = (await api('/api/action', { json: { action: opt.action || 'appliance-update', tag: opt.tag, file: opt.file } })).job; } catch (e) { fail(e.message); return; }
  overlay('Mise à jour de l\'appliance...', opt.intro || 'Recherche du CD/ISO ou de la clé USB, puis application de la mise à jour.');
  clearInterval(state.timer);
  const t0 = Date.now();
  for (;;) {
    await sleep(3000);
    let j = null;
    try { const r = await fetch('/api/jobs/' + encodeURIComponent(jid), { credentials: 'same-origin', headers: { 'X-OB': '1' } }); if (r.ok) j = await r.json(); } catch (e) { /* console en cours de redémarrage */ }
    if (j && j.done && j.rc !== 0) { overlay('La mise à jour a échoué', (j.output || '').trim().split('\n').slice(-6).join('\n'), 'fail'); return; }
    if (j) $('#ov-text').textContent = (j.output || '').trim().split('\n').slice(-6).join('\n') || '...';   // étapes et progression
    const p = await ping();
    if (p && before.version && p.version !== before.version) {
      overlay('Mise à jour terminée', 'OllamaBuntu ' + before.version + ' → ' + p.version + '. Reconnectez-vous.', 'done');
      setTimeout(() => location.reload(), 3500);
      return;
    }
    if (j && j.done && j.rc === 0 && p && p.version === before.version && Date.now() - t0 > 30000) {
      overlay('Aucun changement', opt.same || 'La version de l\'ISO est identique à la version installée.', 'done'); return;
    }
    if (Date.now() - t0 > 30 * 60000) { overlay('Délai dépassé', 'Consultez Journaux > Système et /var/log/ollamabuntu-update.log.', 'fail'); return; }
  }
}
$('#appliance-update').addEventListener('click', () => applianceUpdate());

/* ------------------------------------------- mise à jour depuis Internet (GitHub) */
function renderOnlineUpdate(d) {
  const l = d.latest, c = d.config;
  const status = !c.repo ? pill('dépôt non configuré', 'warn') : d.error ? pill('vérification impossible', 'err') : !d.checked_at ? pill('jamais vérifié', 'info')
    : d.available ? pill('nouvelle version disponible', 'warn') : pill('à jour', 'ok');
  $('#ou-state').replaceChildren(kv([
    ['Version installée', 'v' + d.installed],
    ['Version publiée', l ? 'v' + l.version + (l.prerelease ? ' (préversion)' : '') : '-'],
    ['Dépôt', c.repo ? 'github.com/' + c.repo : '-'],
    ['État', el('span', {}, status, d.checked_at ? el('span', { class: 'muted small', text: ' Dernière vérification : ' + fmtDate(d.checked_at) }) : null)]]));
  $('#ou-notes').replaceChildren(...(d.available && l ? [
    l.notes ? el('div', {}, el('div', { class: 'muted', text: 'Notes de la version' }), el('pre', { class: 'log small', text: l.notes })) : null,
    l.url ? el('p', {}, el('a', { href: l.url, target: '_blank', rel: 'noopener noreferrer', text: 'Voir la version sur GitHub' })) : null].filter(Boolean) : []));
  const ap = $('#ou-apply');
  ap.classList.toggle('hidden', !d.available || !d.signed);
  if (l) ap.textContent = 'Mettre à jour vers v' + l.version;
  const f = $('#ou-form');
  f.elements.auto_check.checked = c.auto_check; f.elements.repo.value = c.repo; f.elements.channel.value = c.channel;
  f.elements.token.value = ''; f.elements.token.placeholder = d.token_set ? 'Jeton enregistré (laisser vide pour le conserver)' : 'Aucun jeton enregistré';
  $('#ou-token-clear').disabled = !d.token_set;
  $('#ou-msg').className = 'small' + (d.error ? ' error' : '');
  $('#ou-msg').textContent = d.error || (!d.signed ? 'Clé de vérification absente de cette appliance : mise à jour en ligne impossible.' : '');
}
async function loadOnlineUpdate() {
  if (!isAdmin()) return;
  try { renderOnlineUpdate(await api('/api/update/online')); } catch (e) { $('#ou-msg').className = 'small error'; $('#ou-msg').textContent = e.message; }
}
$('#ou-check').addEventListener('click', async () => {
  const b = $('#ou-check');
  b.disabled = true; $('#ou-msg').className = 'small'; $('#ou-msg').textContent = 'Recherche en cours...';
  try {
    const d = await api('/api/update/online/check', { json: {} });
    renderOnlineUpdate(d);
    if (!d.error) { $('#ou-msg').className = 'small okmsg'; $('#ou-msg').textContent = d.available ? 'Une nouvelle version est disponible.' : d.latest ? 'Cette appliance est à jour.' : 'Aucune version publiée dans ce dépôt.'; }
  } catch (e) { $('#ou-msg').className = 'small error'; $('#ou-msg').textContent = e.message; }
  b.disabled = false;
});
$('#ou-apply').addEventListener('click', () => {
  api('/api/update/online').then((d) => {
    if (!d.available || !d.latest) { renderOnlineUpdate(d); return null; }
    return applianceUpdate({ action: 'appliance-update-online', tag: d.latest.tag,
      confirm: 'Mettre à jour l\'appliance de v' + d.installed + ' vers v' + d.latest.version + ' depuis Internet ?\nL\'archive est téléchargée depuis GitHub puis sa signature est vérifiée. Les services IA redémarrent ; comptes, réglages et modèles sont conservés.',
      intro: 'Téléchargement depuis GitHub, vérification de la signature, puis application de la mise à jour.',
      same: 'La version publiée est identique à la version installée.' });
  }).catch((e) => fail(e.message));
});
$('#ou-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, msg = $('#ou-cfg-msg');
  try {
    const d = await api('/api/update/online/config', { json: { repo: f.elements.repo.value, channel: f.elements.channel.value, auto_check: f.elements.auto_check.checked, token: f.elements.token.value } });
    renderOnlineUpdate(d); msg.className = 'small okmsg'; msg.textContent = 'Enregistré.';
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
});
$('#ou-token-clear').addEventListener('click', async () => {
  if (!(await ask('Retirer le jeton d\'accès enregistré ?', { ok: 'Retirer', danger: true }))) return;
  const f = $('#ou-form');
  try { renderOnlineUpdate(await api('/api/update/online/config', { json: { repo: f.elements.repo.value, channel: f.elements.channel.value, auto_check: f.elements.auto_check.checked, clear_token: true } })); $('#ou-cfg-msg').className = 'small okmsg'; $('#ou-cfg-msg').textContent = 'Jeton retiré.'; }
  catch (e) { $('#ou-cfg-msg').className = 'small error'; $('#ou-cfg-msg').textContent = e.message; }
});

/* ------------------------------------------------------ mises à jour système */
const KIND_LABEL = { securite: ['Sécurité', 'err'], correctif: ['Correctif', 'info'], retroportage: ['Rétroportage', ''], tiers: ['Tiers', 'warn'] };
const PRIO_LABEL = { critical: ['critique', 'err'], high: ['haute', 'err'], medium: ['moyenne', 'warn'], low: ['faible', 'info'], negligible: ['négligeable', 'info'] };
function advLink(a) {
  const id = a.id || '';
  const url = id.startsWith('USN-') ? 'https://ubuntu.com/security/notices/' + id : id.startsWith('UBUNTU-CVE-') ? 'https://ubuntu.com/security/' + id.slice(7) : 'https://osv.dev/vulnerability/' + id;
  return el('a', { class: 'adv', href: url, target: '_blank', rel: 'noopener', text: id, title: a.summary || '' });
}
async function loadUpdates(refresh) {
  const box = $('#updates');
  let u;
  try { u = await api('/api/updates' + (refresh ? '?refresh=1' : '')); } catch (e) { box.replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  setBanner(u.reboot_required);
  const head = el('div', { class: 'sum-row' });
  if (!u.count) head.append(pill('Système à jour', 'ok'));
  else {
    head.append(el('strong', { text: u.count + ' paquet(s) en attente :' }));
    for (const [k, [lbl, kind]] of Object.entries(KIND_LABEL)) if (u.summary[k]) head.append(pill(u.summary[k] + ' ' + lbl.toLowerCase(), kind));
  }
  const sp = u.security_priority, prios = Object.entries(PRIO_LABEL).filter(([k]) => sp[k]);   // du plus critique au moins critique
  const prioLine = u.summary.securite ? el('div', { class: 'sum-row' }, el('span', { class: 'muted small', text: 'Criticité des correctifs de sécurité (avis Ubuntu) :' }),
    ...prios.map(([k, [lbl, kind]]) => pill(sp[k] + ' ' + lbl, kind)), sp.inconnue ? pill(sp.inconnue + ' non déterminée', '') : null) : null;
  const meta = el('p', { class: 'muted small', text: 'Dernière recherche : ' + fmtDate(u.last_check) + ' - criticité : ' + (u.osv === 'ok' ? 'OSV.dev (' + u.ecosystem + ')' : u.osv) +
    (u.phased.length ? ' - ' + u.phased.length + ' différée(s) par le déploiement progressif d\'Ubuntu' : '') + (u.kernel ? ' - inclut un nouveau noyau (redémarrage à prévoir)' : '') });
  const tbody = el('tbody');
  for (const p of u.packages.slice(0, 300)) {
    const [kl, kk] = KIND_LABEL[p.kind];
    const pr = p.priority ? PRIO_LABEL[p.priority] : null;
    tbody.append(el('tr', {},
      el('td', {}, el('strong', { text: p.name }), p.kernel ? el('span', { class: 'chip', text: 'noyau' }) : null),
      el('td', { class: 'small', text: (p.current || 'nouveau') + ' → ' + p.candidate }),
      el('td', { class: 'small', text: p.origins.map((o) => o.split('/').pop()).join(', ') }),
      el('td', {}, pill(kl, kk)),
      el('td', {}, pr ? pill(pr[0], pr[1]) : (p.kind === 'securite' ? el('span', { class: 'muted small', text: 'non déterminée' }) : null),
        el('div', {}, ...(p.advisories || []).slice(0, 3).map(advLink)))));
  }
  box.replaceChildren(head, prioLine, meta, u.count ? el('div', { class: 'table-wrap' }, el('table', {},
    el('thead', {}, el('tr', {}, ...['Paquet', 'Version', 'Dépôt', 'Type', 'Criticité'].map((h) => el('th', { text: h })))), tbody)) : null);
}

/* ------------------------------------------------------------- Open WebUI */
async function loadWebui() {
  let w;
  try { w = await api('/api/webui'); } catch (e) { $('#webui-status').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const deployed = w.container !== null;
  const url = 'https://' + location.hostname + ':' + w.tls_port + '/';
  const rows = [['Docker', w.docker ? 'installé' : 'non installé'], ['Conteneur', w.container || 'absent']];
  if (deployed) rows.push(['Version', (w.version || '?') + (w.latest && w.version && w.latest !== w.version ? ' (version ' + w.latest + ' disponible)' : '')],
    ['Démarré le', w.started || '-'], ['Administrateur', w.admin_email || '-'], ['Adresse', url]);
  const btn = (label, act, cls) => el('button', { class: 'btn ' + (cls || ''), type: 'button', text: label, onclick: () => webuiAction(act, label) });
  $('#webui-status').replaceChildren(el('h2', { text: 'État' }),
    el('div', { class: 'big' }, pill(w.running ? (w.healthy ? 'en service' : 'démarrage...') : deployed ? 'arrêté' : 'non déployé', w.running && w.healthy ? 'ok' : deployed ? 'warn' : '')),
    kv(rows),
    deployed ? el('div', { class: 'row' },
      w.running ? el('a', { class: 'btn primary', href: url, target: '_blank', rel: 'noopener', text: 'Ouvrir Open WebUI' }) : null,
      btn('Mettre à jour', 'webui-update'), w.running ? btn('Redémarrer', 'webui-restart') : null,
      w.running ? btn('Arrêter', 'webui-stop') : btn('Démarrer', 'webui-start'),
      btn('Supprimer (garder les données)', 'webui-remove', 'danger'), btn('Tout supprimer', 'webui-purge', 'danger')) : null,
    deployed ? el('p', { class: 'muted small', text: 'Le certificat est celui de la console (auto-signé). Les comptes Open WebUI sont propres à Open WebUI.' }) : null);
  $('#webui-deploy').classList.toggle('hidden', deployed);
  resumeJob();
}
async function webuiAction(act, label) {
  const warn = act === 'webui-purge' ? '\nToutes les conversations, documents et comptes Open WebUI seront définitivement effacés.' : '';
  if (!(await ask(label + ' ?' + warn))) return;
  try {
    const d = await api('/api/action', { json: { action: act } });
    if (d.job) followJob(d.job); else await sleep(1500);
  } catch (e) { fail(e.message); }
  loadWebui();
}
$('#webui-refresh').addEventListener('click', loadWebui);
$('#webui-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, out = $('#webui-msg');
  out.className = 'small';
  if (f.elements.password.value !== f.elements.confirm.value) { out.textContent = 'Les deux mots de passe ne sont pas identiques.'; out.classList.add('error'); return; }
  try {
    const d = await api('/api/webui/deploy', { json: { email: f.elements.email.value.trim(), name: f.elements.name.value.trim(), password: f.elements.password.value } });
    f.elements.password.value = ''; f.elements.confirm.value = '';
    out.textContent = 'Déploiement lancé (plusieurs minutes).'; out.classList.add('okmsg');
    followJob(d.job);
  } catch (e) { out.textContent = e.message; out.classList.add('error'); }
});

/* ------------------------------------------------------------ utilisateurs */
async function loadUsers() {
  const box = $('#users-table');
  let d;
  try { d = await api('/api/users'); } catch (e) { box.replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const tbody = el('tbody');
  for (const u of d.users) {
    const me = u.user === state.user;
    const role = me ? el('span', { text: (u.role === 'admin' ? 'Administrateur' : 'Utilisateur') + ' (vous)' })
      : el('select', { onchange: (e) => updateUser(u.user, { role: e.target.value }) },
        el('option', { value: 'admin', text: 'Administrateur', selected: u.role === 'admin' }),
        el('option', { value: 'utilisateur', text: 'Utilisateur', selected: u.role === 'utilisateur' }));
    const pwBox = el('span', { class: 'inline-pw hidden' });
    const pwInput = el('input', { type: 'password', placeholder: 'nouveau mot de passe', minlength: '8', autocomplete: 'new-password' });
    pwBox.append(pwInput, el('button', { class: 'btn sm primary', type: 'button', text: 'OK', onclick: () => updateUser(u.user, { password: pwInput.value }) }));
    tbody.append(el('tr', {},
      el('td', {}, el('strong', { text: u.user })),
      el('td', {}, role),
      el('td', { text: u.linux ? 'oui (console + SSH)' : 'non' }),
      el('td', { text: fmtDate(u.created) }),
      el('td', {}, el('div', { class: 'row' },
        el('button', { class: 'btn sm', type: 'button', text: 'Mot de passe', onclick: () => { pwBox.classList.toggle('hidden'); pwInput.focus(); } }), pwBox,
        me ? null : el('button', { class: 'btn sm danger', type: 'button', text: 'Supprimer', onclick: () => deleteUser(u) })))));
  }
  box.replaceChildren(el('div', { class: 'table-wrap' }, el('table', {},
    el('thead', {}, el('tr', {}, ...['Identifiant', 'Rôle', 'Accès Linux', 'Créé le', ''].map((h) => el('th', { text: h })))), tbody)));
}
async function updateUser(user, changes) {
  try { await api('/api/users/update', { json: { user, ...changes } }); if (changes.password) notify('Mot de passe de « ' + user + ' » modifié.'); }
  catch (e) { fail(e.message); }
  loadUsers();
}
async function deleteUser(u) {
  if (!(await ask('Supprimer le compte « ' + u.user + ' » ?' + (u.linux ? '\nSon compte Linux sera supprimé (dossier personnel conservé).' : '')))) return;
  try { await api('/api/users/delete', { json: { user: u.user } }); } catch (e) { fail(e.message); }
  loadUsers();
}
$('#user-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, out = $('#user-msg');
  out.className = 'small';
  if (f.elements.password.value !== f.elements.confirm.value) { out.textContent = 'Les deux mots de passe ne sont pas identiques.'; out.classList.add('error'); return; }
  try {
    await api('/api/users/create', { json: { user: f.elements.user.value.trim(), password: f.elements.password.value, role: f.elements.role.value, linux: f.elements.linux.checked } });
    out.textContent = 'Compte « ' + f.elements.user.value.trim() + ' » créé.'; out.classList.add('okmsg'); f.reset(); loadUsers();
  } catch (e) { out.textContent = e.message; out.classList.add('error'); }
});

/* ---------------------------------------------------------------- à propos */
async function loadCredits() {
  $('#about-version').textContent = 'OllamaBuntu v' + state.version;
  let d;
  try { d = await api('/api/credits'); } catch (e) { $('#credits').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const groups = {};
  for (const c of d.items) (groups[c.category] = groups[c.category] || []).push(c);
  const blocks = [];
  for (const [cat, items] of Object.entries(groups)) {
    const rows = items.map((c) => el('tr', {},
      el('td', {}, el('a', { href: c.url, target: '_blank', rel: 'noopener', text: c.name })),
      el('td', { text: c.role }),
      el('td', { class: 'small muted', text: c.license })));
    blocks.push(el('div', { class: 'catalog-group' }, el('h3', { text: cat }),
      el('div', { class: 'table-wrap' }, el('table', {}, el('tbody', {}, ...rows)))));
  }
  $('#credits').replaceChildren(...blocks);
}

/* -------------------------------------------------------------- mon compte */
function loadAccount() {
  $('#account-info').replaceChildren(...kv([['Identifiant', state.user], ['Rôle', isAdmin() ? 'Administrateur' : 'Utilisateur'], ['OllamaBuntu', 'v' + state.version]]).childNodes);
}
$('#pw-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, out = $('#pw-msg');
  out.className = 'small';
  if (f.elements.new.value !== f.elements.confirm.value) { out.textContent = 'Les deux saisies ne sont pas identiques.'; out.classList.add('error'); return; }
  try {
    await api('/api/password', { json: { current: f.elements.current.value, new: f.elements.new.value } });
    out.textContent = 'Mot de passe modifié.'; out.classList.add('okmsg'); f.reset();
  } catch (e) { out.textContent = e.message; out.classList.add('error'); }
});

/* ---------------------------------------------------------------- journaux */
/* ------------------------------------------------ répartition de charge : diagnostic et test */
const BAL_ISSUE = {
  'route-off': 'La répartition n\'est pas activée pour ce serveur : utilisez « Activer la répartition de charge » sur sa carte (onglet Parc).',
  'offline': 'Le serveur est hors ligne.',
  'old-version': 'Ce serveur n\'annonce pas ses modèles : mettez-le à jour avec la dernière ISO.',
  'no-common-model': 'Aucun modèle en commun avec ce serveur : installez les mêmes modèles (Parc > Synchroniser > Modèles).',
};
const BAL_HELP = {
  spread: 'Chaque requête va au serveur qui en traite le moins à cet instant ; à égalité, les serveurs se relaient. Un modèle est chargé sur chaque serveur à sa première utilisation, ce qui prend du temps pour un gros modèle. Sans l\'option ci-dessous, une conversation peut changer de serveur d\'une réponse à l\'autre.',
  warm: 'Chaque requête va de préférence au serveur qui a déjà le modèle en mémoire, tant qu\'il n\'est pas occupé par plusieurs requêtes. Les autres serveurs ne servent qu\'en cas de forte demande ou de panne : avec un seul utilisateur, tout reste sur le même serveur.',
};
const balState = { multi: [] };
async function loadBalance() {
  let d;
  try { d = await api('/api/fleet/balance'); } catch (e) { $('#bal-msg').className = 'small error'; $('#bal-msg').textContent = e.message; return; }
  const sel = $('#bal-strategy');
  if (w_active() !== sel) sel.value = d.strategy;
  if (w_active() !== $('#bal-affinity')) $('#bal-affinity').checked = d.affinity !== false;
  $('#bal-strategy-help').textContent = BAL_HELP[sel.value] || '';
  const items = [];
  if (!d.servers.length) items.push(el('li', { text: 'Aucun serveur dans le parc : ajoutez-en un (onglet « Ajouter un serveur »).' }));
  for (const s of d.servers) for (const code of s.issues) items.push(el('li', {}, el('strong', { text: s.name }), ' ', el('span', { text: BAL_ISSUE[code] })));
  const usable = d.servers.filter((s) => !s.issues.length).length;
  if (d.servers.length && !items.length) items.push(el('li', { class: 'okmsg', text: 'La répartition est active : ' + usable + ' serveur(s) peuvent recevoir des requêtes.' }));
  $('#bal-issues').replaceChildren(...items);
  const rows = [{ name: 'Ce serveur', models: d.local.models, served: d.local.served, last: d.local.last }].concat(d.servers);
  $('#bal-servers').replaceChildren(el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Serveur', 'État', 'Répartition', 'Modèles en commun', 'Requêtes servies (24 h)', 'Dernière requête'].map((c, i) => el('th', { class: i >= 3 ? 'num' : '', text: c })))),
    el('tbody', {}, ...rows.map((r, i) => el('tr', {},
      el('td', { class: 'name', text: r.name }),
      el('td', {}, i ? pill(r.state, FLEET_KIND[r.state] || 'warn') : pill('en ligne', 'ok')),
      el('td', {}, i ? (r.route ? pill('activée', 'ok') : pill('désactivée', 'warn')) : '-'),
      el('td', { class: 'num', text: i ? r.common + ' / ' + r.models : String(r.models) }),
      el('td', { class: 'num', text: String(r.served) }),
      el('td', { class: 'num', text: r.last ? fmtDate(r.last) : '-' })))))));
  const multi = d.models.filter((m) => m.on.length > 1);
  balState.multi = multi.map((m) => m.name);
  $('#bal-models').replaceChildren(d.models.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Modèle', 'Présent sur', 'Répartissable'].map((c) => el('th', { text: c })))),
    el('tbody', {}, ...d.models.map((m) => el('tr', {}, el('td', { class: 'name', text: m.name }),
      el('td', {}, ...m.on.flatMap((x, i) => [i ? ', ' : '', x === 'local' ? 'Ce serveur' : x])),
      el('td', { text: m.on.length > 1 ? 'oui' : 'non (un seul serveur)' })))))) : el('p', { class: 'muted small', text: 'Aucun modèle installé.' }));
  $('#bal-test').disabled = !usable || !multi.length;
}
const w_active = () => document.activeElement;
$('#bal-strategy').addEventListener('change', async () => {
  $('#bal-strategy-help').textContent = BAL_HELP[$('#bal-strategy').value] || '';
  try { await api('/api/fleet/balance/strategy', { json: { strategy: $('#bal-strategy').value } }); $('#bal-msg').className = 'small okmsg'; $('#bal-msg').textContent = 'Enregistré.'; }
  catch (e) { $('#bal-msg').className = 'small error'; $('#bal-msg').textContent = e.message; }
});
$('#bal-test').addEventListener('click', async () => {
  if (!balState.multi.length) { fail('Aucun modèle n\'est présent sur plusieurs serveurs : le test est impossible.'); return; }
  const pick = el('select', { 'aria-label': 'Modèle à tester' }, ...balState.multi.map((m) => el('option', { value: m, text: m })));
  const go = await modal({ title: 'Tester la répartition', message: 'Envoie 4 petites requêtes en même temps au modèle choisi, pour voir quels serveurs répondent. Le modèle sera chargé sur chaque serveur concerné, ce qui peut prendre du temps pour un gros modèle.',
    body: el('label', {}, 'Modèle à tester ', pick), ok: 'Lancer le test' });
  if (!go) return;
  const model = pick.value;
  $('#bal-msg').className = 'small'; $('#bal-msg').textContent = 'Test en cours...'; $('#bal-test').disabled = true;
  try {
    const r = await api('/api/fleet/balance/test', { json: { model } });
    $('#bal-msg').textContent = '';
    await modal({ title: 'Résultat du test', message: r.count + ' requêtes envoyées en même temps, ' + r.ok + ' réussie(s).',
      body: el('ul', {}, ...Object.entries(r.by).map(([name, c]) => el('li', {}, el('strong', { text: name === '' ? 'Ce serveur' : name }), el('span', { text: ' ' + c + ' requête(s)' })))), ok: 'Fermer', cancel: null });
  } catch (e) { $('#bal-msg').className = 'small error'; $('#bal-msg').textContent = e.message; }
  loadBalance();
});

/* ------------------------------------------------ extrait de la demande (journal des requêtes) */
async function loadReqSettings() {
  let s;
  try { s = await api('/api/requests/settings'); } catch (e) { return; }
  $('#req-excerpt').checked = s.prompt_excerpt; $('#req-chars').value = String(s.chars); $('#req-days').value = String(s.days);
}
async function saveReqSettings(patch) {
  $('#req-settings-msg').className = 'small'; $('#req-settings-msg').textContent = '';
  try { await api('/api/requests/settings', { json: patch }); $('#req-settings-msg').className = 'small okmsg'; $('#req-settings-msg').textContent = 'Enregistré.'; loadRequests(); loadDashRequests(); return true; }
  catch (e) { $('#req-settings-msg').className = 'small error'; $('#req-settings-msg').textContent = e.message; return false; }
}
$('#req-excerpt').addEventListener('change', async () => {
  const box = $('#req-excerpt');
  if (box.checked && !(await ask('Enregistrer le début de la dernière question de chaque requête ? Il sera conservé sur ce serveur et visible des administrateurs de cette console ; les clés, jetons, IBAN, numéros de carte et adresses e-mail sont masqués.', { ok: 'Activer' }))) { box.checked = false; return; }
  if (!(await saveReqSettings({ prompt_excerpt: box.checked }))) box.checked = !box.checked;
});
$('#req-chars').addEventListener('change', () => saveReqSettings({ chars: Number($('#req-chars').value) }));
$('#req-days').addEventListener('change', () => saveReqSettings({ days: Number($('#req-days').value) }));
$('#req-clear').addEventListener('click', async () => {
  if (!(await ask('Effacer tout l\'historique des requêtes ? Cette action est définitive.', { ok: 'Effacer', danger: true }))) return;
  try { await api('/api/requests/clear', { json: {} }); $('#req-settings-msg').className = 'small okmsg'; $('#req-settings-msg').textContent = 'Historique effacé.'; loadRequests(); loadDashRequests(); }
  catch (e) { $('#req-settings-msg').className = 'small error'; $('#req-settings-msg').textContent = e.message; }
});

/* ------------------------------------------------ taille du contexte */
const CTX_PRESETS = [2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144];
const fmtTok = (n) => (n >= 1024 && n % 1024 === 0 ? (n / 1024) + ' K' : DEC(n)) + ' jetons';
function ctxMemory(m, n, d) {   // cache des clés et valeurs : octets par jeton x jetons x requêtes parallèles
  if (!m.bytes_per_token || !n) return '-';
  return '≈ ' + fmtBytes(m.bytes_per_token * n * (d.parallel || 1)) + (d.parallel > 1 ? ' (' + d.parallel + ' requêtes parallèles)' : '');
}
async function loadContext() {
  let d;
  try { d = await api('/api/models/context'); } catch (e) { $('#ctx-models').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  $('#ctx-default').value = d.default ? String(d.default) : '';
  if (d.default && !CTX_PRESETS.includes(d.default)) $('#ctx-default').append(el('option', { value: String(d.default), text: fmtTok(d.default) })), $('#ctx-default').value = String(d.default);
  if (!d.models.length) { $('#ctx-models').replaceChildren(el('p', { class: 'muted small', text: 'Aucun modèle installé.' })); return; }
  $('#ctx-models').replaceChildren(el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Modèle', 'Maximum du modèle', 'Contexte appliqué', 'Mémoire du contexte'].map((c, i) => el('th', { class: i === 1 || i === 3 ? 'num' : '', text: c })))),
    el('tbody', {}, ...d.models.map((m) => {
      const presets = CTX_PRESETS.filter((n) => !m.max || n <= m.max);
      if (m.ctx && !presets.includes(m.ctx)) presets.push(m.ctx);
      if (m.max && !presets.includes(m.max)) presets.push(m.max);   // le maximum du modèle, toujours proposé
      const sel = el('select', { 'aria-label': 'Contexte de ' + m.name },
        el('option', { value: '', text: d.default ? 'Défaut du serveur (' + fmtTok(d.default) + ')' : 'Défaut du serveur' }),
        ...presets.sort((a, b) => a - b).map((n) => el('option', { value: String(n), text: fmtTok(n) + (n === m.max ? ' (maximum)' : '') })));
      sel.value = m.ctx ? String(m.ctx) : '';
      const mem = el('td', { class: 'num', text: ctxMemory(m, m.ctx || d.default, d) }), state = el('span', { class: 'small', 'aria-live': 'polite' });
      sel.addEventListener('change', async () => {
        mem.textContent = ctxMemory(m, Number(sel.value) || d.default, d);
        try { await api('/api/models/context', { json: { model: m.name, num_ctx: Number(sel.value) || null } }); state.className = 'small okmsg'; state.textContent = ' Enregistré.'; }
        catch (e) { state.className = 'small error'; state.textContent = ' ' + e.message; }
      });
      return el('tr', {}, el('td', { class: 'name', text: m.name }), el('td', { class: 'num', text: m.max ? fmtTok(m.max) : '-' }), el('td', {}, sel, state), mem);
    })))));
}
$('#ctx-default-save').addEventListener('click', async () => {
  const n = Number($('#ctx-default').value) || null;
  if (!(await ask('Appliquer ' + (n ? fmtTok(n) : 'la valeur par défaut d\'Ollama') + ' à tous les modèles ? Ollama redémarre : les requêtes en cours sont interrompues.', { ok: 'Appliquer' }))) return;
  $('#ctx-default-msg').className = 'small'; $('#ctx-default-msg').textContent = 'Application (redémarrage d\'Ollama)...';
  try { await api('/api/models/context/default', { json: { num_ctx: n } }); $('#ctx-default-msg').className = 'small okmsg'; $('#ctx-default-msg').textContent = 'Appliqué.'; loadContext(); }
  catch (e) { $('#ctx-default-msg').className = 'small error'; $('#ctx-default-msg').textContent = e.message; }
});

/* ------------------------------------------------ onglets internes des écrans */
/* Les éléments marqués data-panel sont regroupés en onglets ; l'adresse #écran/onglet
   permet un lien direct, et l'onglet choisi est mémorisé. */
const TABS = {};
const TAB_ORDER = { system: ['overview', 'appliance', 'updates', 'api', 'central', 'alerts', 'report', 'hardware', 'audit', 'backup'], models: ['installed', 'context', 'add', 'hf', 'tuning', 'disk', 'catalog', 'custom'], perf: ['bench', 'profiles', 'warmup', 'guard', 'tune'], gpu: ['cards', 'availability', 'placement', 'advanced'], logs: ['requests', 'stats', 'system'], fleet: ['fleet', 'balance', 'rules', 'add'] };
function setupTabs() {
  for (const sec of $$('section.view')) {
    const items = [...sec.querySelectorAll('[data-panel]')];
    if (!items.length) continue;
    const v = sec.id.slice(5), panels = {}, order = [];
    for (const it of items) {
      const key = it.dataset.panel;
      if (!panels[key]) { panels[key] = el('div', { class: 'panel', 'data-key': key, role: 'tabpanel', id: 'panel-' + v + '-' + key, 'aria-labelledby': 'tab-' + v + '-' + key }); order.push([key, it.dataset.label || key]); }
      panels[key].append(it);
    }
    for (const g of sec.querySelectorAll('.grid')) if (!g.children.length && !g.id) g.remove();
    if (TAB_ORDER[v]) order.sort((x, y) => TAB_ORDER[v].indexOf(x[0]) - TAB_ORDER[v].indexOf(y[0]));   // du plus courant au plus rare
    const bar = el('nav', { class: 'subtabs', role: 'tablist' }, ...order.map(([key, label]) => el('a', { href: '#' + v + '/' + key, role: 'tab', 'data-key': key, id: 'tab-' + v + '-' + key, 'aria-controls': 'panel-' + v + '-' + key, text: label })));
    bar.addEventListener('keydown', (ev) => {   // flèches gauche/droite entre onglets
      if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
      const tabs = [...bar.querySelectorAll('a')], i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      ev.preventDefault(); const nx = tabs[(i + (ev.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]; nx.focus(); nx.click();
    });
    let anchor = sec.querySelector('.section-title');
    anchor.after(bar); anchor = bar;
    for (const [key] of order) { anchor.after(panels[key]); anchor = panels[key]; }
    TABS[v] = order.map(([k]) => k);
  }
}
function currentTab(v) { const a = $('#view-' + v + ' > .subtabs a.active'); return a ? a.dataset.key : null; }
function activateTab(v, sub) {
  if (!TABS[v]) return;
  let key = TABS[v][0];
  try {
    if (sub && TABS[v].includes(sub)) { key = sub; localStorage.setItem('ob-tab-' + v, sub); }
    else { const s = localStorage.getItem('ob-tab-' + v); if (s && TABS[v].includes(s)) key = s; }
  } catch (e) { if (sub && TABS[v].includes(sub)) key = sub; }
  for (const p of $$('#view-' + v + ' > .panel')) p.classList.toggle('hidden', p.dataset.key !== key);
  for (const a of $$('#view-' + v + ' > .subtabs a')) { const on = a.dataset.key === key; a.classList.toggle('active', on); a.setAttribute('aria-selected', on ? 'true' : 'false'); a.tabIndex = on ? 0 : -1; }
}

/* ------------------------------------------------ graphiques (SVG, sans bibliothèque) */
function niceMax(v) { if (!v || v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p; return 10 * p; }
const fmtTime = (t, withSec) => new Date(t * 1000).toLocaleTimeString(LOCALE(), withSec ? {} : { hour: '2-digit', minute: '2-digit' });
function lineChart({ title, unit, series, max, span, decimals = 0 }) {
  const W = 560, H = 150, L = 40, R = 8, T = 8, Bm = 20, NS = 'http://www.w3.org/2000/svg';
  const now = Date.now() / 1000, t0 = now - span;
  const all = series.flatMap((s) => s.points.map((p) => p[1]).filter((x) => x != null));
  const ymax = max || niceMax(Math.max(...all, 0) * 1.1);
  const x = (t) => L + ((t - t0) / span) * (W - L - R), y = (v) => T + (1 - Math.min(v, ymax) / ymax) * (H - T - Bm);
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('role', 'img');
  const fmtV = (v) => (v == null ? '-' : DEC(Number(v).toFixed(decimals)) + (unit ? ' ' + unit : ''));
  const last = series.map((s) => { const p = s.points.filter((q) => q[1] != null); return p.length ? p[p.length - 1][1] : null; });
  const tx = (x) => trString(x) || x;   // résumé pour les lecteurs d'écran, dans la langue affichée
  svg.setAttribute('aria-label', tx(title) + (I18N.lang === 'fr' ? ' : ' : ': ') + series.map((s, i) => tx(s.name) + ' ' + fmtV(last[i])).join(', '));
  const add = (tag, attrs, text) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text != null) n.textContent = text; svg.append(n); return n; };
  for (const f of [0, 0.5, 1]) {
    const yy = y(ymax * f); add('line', { x1: L, x2: W - R, y1: yy, y2: yy, class: 'gridl' });
    add('text', { x: L - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis' }, DEC(+(ymax * f).toFixed(ymax * f < 10 && f ? 1 : 0)));
  }
  for (const f of [0, 0.5, 1]) add('text', { x: L + f * (W - L - R), y: H - 4, 'text-anchor': f === 0 ? 'start' : f === 1 ? 'end' : 'middle', class: 'axis' }, fmtTime(t0 + f * span));
  series.forEach((s, i) => {
    let d = '', pen = false;
    const pts = s.points;
    pts.forEach(([t, v], k) => {
      if (v == null) { pen = false; return; }
      d += (pen ? 'L' : 'M') + x(t).toFixed(1) + ' ' + y(v).toFixed(1);
      const alone = (k === 0 || pts[k - 1][1] == null) && (k === pts.length - 1 || pts[k + 1][1] == null);
      if (alone) add('circle', { cx: x(t).toFixed(1), cy: y(v).toFixed(1), r: 2.5, class: 'dot c' + ((i % 6) + 1) });   // point isolé : visible
      pen = true;
    });
    if (d) add('path', { d, class: 'ln c' + ((i % 6) + 1) });
  });
  if (!all.length) add('text', { x: (L + W) / 2, y: H / 2, 'text-anchor': 'middle', class: 'empty' }, 'Pas encore de données sur cette période');
  const cur = add('line', { x1: 0, x2: 0, y1: T, y2: H - Bm, class: 'cursor', visibility: 'hidden' });
  const tip = el('div', { class: 'tip hidden' });
  const box = el('div', { class: 'chart' }, el('div', { class: 'ct' }, el('strong', { text: title }), el('span', { class: 'now muted', text: series.length === 1 ? fmtV(last[0]) : '' })),
    el('div', { class: 'legend' }, ...(series.length > 1 ? series.map((s, i) => el('span', {}, el('i', { class: 'c' + ((i % 6) + 1) }), s.name + ' : ' + fmtV(last[i]))) : [])), svg, tip);
  svg.addEventListener('mousemove', (ev) => {   // valeurs au survol
    const r = svg.getBoundingClientRect(); if (!r.width) return;
    const t = t0 + ((ev.clientX - r.left) / r.width * W - L) / (W - L - R) * span;
    const near = series.map((s) => s.points.reduce((b, p) => (b == null || Math.abs(p[0] - t) < Math.abs(b[0] - t) ? p : b), null));
    const p0 = near.find(Boolean); if (!p0) return;
    cur.setAttribute('x1', x(p0[0])); cur.setAttribute('x2', x(p0[0])); cur.setAttribute('visibility', 'visible');
    tip.replaceChildren(el('div', { class: 'muted', text: fmtTime(p0[0], true) }), ...series.map((s, i) => el('div', {}, el('i', { class: 'c' + ((i % 6) + 1), style: 'display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px' }), s.name + ' : ' + fmtV(near[i] && near[i][1]))));
    tip.classList.remove('hidden'); tip.style.left = Math.min(ev.clientX - box.getBoundingClientRect().left + 12, box.clientWidth - 160) + 'px'; tip.style.top = '36px';
  });
  svg.addEventListener('mouseleave', () => { cur.setAttribute('visibility', 'hidden'); tip.classList.add('hidden'); });
  return box;
}
const perf = { span: 3600, at: 0 };
async function loadPerf(force) {
  if (!force && Date.now() - perf.at < 9000) return;
  perf.at = Date.now();
  let m;
  try { m = await api('/api/metrics?span=' + perf.span); } catch (e) { $('#perf-note').textContent = e.message; return; }
  const S = m.series, pts = (f) => S.map((p) => [p.t, f(p)]), gp = Object.entries(m.gpus);
  $('#perf-charts').replaceChildren(
    lineChart({ title: 'Charge GPU', unit: '%', max: 100, span: m.span, series: gp.map(([pci, name]) => ({ name, points: pts((p) => p.gpus[pci] && p.gpus[pci].u) })) }),
    lineChart({ title: 'Mémoire vidéo occupée', unit: '%', max: 100, span: m.span, series: gp.map(([pci, name]) => ({ name, points: pts((p) => p.gpus[pci] && p.gpus[pci].m) })) }),
    lineChart({ title: 'Température GPU', unit: '°C', max: 100, span: m.span, series: gp.map(([pci, name]) => ({ name, points: pts((p) => p.gpus[pci] && p.gpus[pci].t) })) }),
    lineChart({ title: 'Puissance GPU', unit: 'W', span: m.span, series: gp.map(([pci, name]) => ({ name, points: pts((p) => p.gpus[pci] && p.gpus[pci].p) })) }),
    lineChart({ title: 'Processeur et mémoire', unit: '%', max: 100, span: m.span, series: [{ name: 'Processeur', points: pts((p) => p.cpu) }, { name: 'Mémoire', points: pts((p) => p.mem) }] }),
    lineChart({ title: 'Requêtes par minute', unit: '', span: m.span, decimals: 1, series: [{ name: 'Requêtes', points: pts((p) => p.rpm) }] }),
    lineChart({ title: 'Jetons par seconde', unit: 't/s', span: m.span, decimals: 1, series: [{ name: 'Vitesse par requête', points: pts((p) => p.tps) }, { name: 'Débit total', points: pts((p) => p.tok_s) }] }),
    lineChart({ title: 'Temps avant le premier jeton', unit: 'ms', span: m.span, series: [{ name: 'Premier jeton', points: pts((p) => p.ttft) }] }));
  $('#perf-note').textContent = gp.length ? '' : 'Aucun GPU mesurable (NVIDIA ou AMD) : les graphiques GPU restent vides.';
}
for (const b of $$('#perf-range button')) b.addEventListener('click', () => {
  perf.span = Number(b.dataset.span);
  for (const x of $$('#perf-range button')) { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); }
  loadPerf(true);
});

/* ------------------------------------------------ requêtes vers les modèles */
const fmtMs = (v) => (v == null ? '-' : v >= 10000 ? DEC((v / 1000).toFixed(1)) + ' s' : v + ' ms');
const reqWhere = (r) => ((r.instance || '').startsWith('serveur:') ? r.instance.slice(8) : 'Ce serveur');
function reqTable(list, compact) {
  if (!list.length) return el('p', { class: 'muted small', text: 'Aucune requête enregistrée pour le moment.' });
  const cols = compact ? ['Heure', 'Modèle', 'Client', 'Serveur', 'Demande', 'Durée', 't/s'] : ['Heure', 'Client', 'Modèle', 'Demande', 'Serveur', 'Point d\'API', 'Statut', 'Durée', '1er jeton', 'Jetons (entrée / sortie)', 't/s'];
  const numFrom = compact ? 5 : 7;
  const prompt = (r) => el('td', { class: 'prompt', title: r.prompt || '' }, r.prompt ? r.prompt : el('span', { class: 'muted', title: rq.excerpt ? '' : 'Extrait désactivé : Journaux > Requêtes', text: rq.excerpt ? '-' : 'non enregistré' }));
  return el('div', { class: 'table-wrap' }, el('table', { class: 'dense' }, el('thead', {}, el('tr', {}, ...cols.map((c, i) => el('th', { class: i >= numFrom ? 'num' : '', text: c })))),
    el('tbody', {}, ...list.map((r) => el('tr', {},
      el('td', { class: 'nowrap', text: fmtTime(r.ts, true) }),
      ...(compact ? [el('td', { class: 'name', text: r.model || '-' }), el('td', { text: r.client }), el('td', { text: reqWhere(r) }), prompt(r)] :
        [el('td', { text: r.client }), el('td', { class: 'name', text: r.model || '-' }), prompt(r), el('td', { text: reqWhere(r) }),
          el('td', { class: 'small', text: r.path }), el('td', {}, r.aborted ? pill('interrompue', 'warn') : pill(String(r.status), r.status === 200 ? 'ok' : 'err'))]),
      el('td', { class: 'num', text: fmtMs(r.ms) }),
      ...(compact ? [] : [el('td', { class: 'num', text: fmtMs(r.ttft_ms) }), el('td', { class: 'num', text: (r.in_tok == null ? '-' : r.in_tok) + ' / ' + (r.out_tok == null ? '-' : r.out_tok) })]),
      el('td', { class: 'num', text: r.tps ? DEC(r.tps) : '-' }))))));
}
const rq = { list: [], excerpt: false };
function reqFiltered() {
  const q = $('#rf-q').value.trim().toLowerCase(), st = $('#rf-status').value;
  return rq.list.filter((r) => (!q || [r.model, r.client, r.prompt, r.path, reqWhere(r)].some((x) => String(x || '').toLowerCase().includes(q))) &&
    (!st || ((r.status === 200 && !r.aborted) === (st === 'ok'))));
}
function renderReqList() {
  const f = reqFiltered(), filtered = !!($('#rf-q').value.trim() || $('#rf-status').value);
  $('#req-list').replaceChildren(reqTable(f.slice(0, 200), false));
  $('#rf-count').textContent = filtered ? f.length + ' résultat(s) sur ' + rq.list.length : '';
}
$('#rf-q').addEventListener('input', renderReqList);
$('#rf-status').addEventListener('change', renderReqList);
$('#rf-export').addEventListener('click', async () => {
  const p = new URLSearchParams(), q = $('#rf-q').value.trim(), st = $('#rf-status').value;
  if (q) p.set('q', q);
  if (st) p.set('status', st);
  try { await downloadBlob('/api/requests/export' + (p.toString() ? '?' + p : ''), 'requetes-' + new Date().toISOString().slice(0, 10) + '.csv'); }
  catch (e) { fail(e.message); }
});
async function downloadBlob(path, name) {
  const r = await api(path, { raw: true }), url = URL.createObjectURL(await r.blob());
  const a = el('a', { href: url, download: name });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
}
async function loadRequests() {
  let d;
  try { d = await api('/api/requests?limit=500'); } catch (e) { $('#req-list').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  $('#req-summary').replaceChildren(d.summary.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Modèle', 'Requêtes', 'Erreurs', 'Jetons générés', 't/s moyen', '1er jeton moyen', 'Durée médiane', 'Durée p95'].map((c, i) => el('th', { class: i ? 'num' : '', text: c })))),
    el('tbody', {}, ...d.summary.map((s) => el('tr', {}, el('td', { class: 'name', text: s.model }), el('td', { class: 'num', text: s.count }), el('td', { class: 'num', text: s.errors }),
      el('td', { class: 'num', text: s.tok }), el('td', { class: 'num', text: s.tps ? DEC(s.tps) : '-' }), el('td', { class: 'num', text: fmtMs(s.ttft_ms) }),
      el('td', { class: 'num', text: fmtMs(s.p50_ms) }), el('td', { class: 'num', text: fmtMs(s.p95_ms) })))))) : el('p', { class: 'muted small', text: 'Aucune requête dans la dernière heure.' }));
  rq.list = d.requests; rq.excerpt = !!d.prompt_excerpt;
  renderReqList();
}
async function loadDashRequests() {
  try {
    const d = await api('/api/requests?limit=6');
    rq.excerpt = !!d.prompt_excerpt;
    $('#dash-requests').replaceChildren(reqTable(d.requests, true));
    const note = $('#dash-req-note');
    note.classList.toggle('hidden', !!d.prompt_excerpt);
    note.replaceChildren('Le contenu des demandes n\'est pas enregistré. ', el('a', { href: '#logs/requests', text: 'Activer l\'extrait de la demande' }));
  } catch (e) { /* vide */ }
}

/* ------------------------------------------------ journaux : suivi en direct */
const logsLive = { timer: null, cursor: '', lines: [] };
const LOG_LEVEL = (l) => (/\b(error|erreur|err|fail|failed|échec|panic|fatal|critical)\b/i.test(l) ? 'l-err' : /\b(warn|warning|avertissement)\b/i.test(l) ? 'l-warn' : '');
function renderLogLines(newLines, reset) {
  const box = $('#log-text'), stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40, f = $('#log-filter').value.trim().toLowerCase();
  if (reset) { box.replaceChildren(); logsLive.lines = []; }
  const frag = document.createDocumentFragment();
  for (const l of newLines) { const d = el('div', { class: LOG_LEVEL(l) + (f && !l.toLowerCase().includes(f) ? ' hide' : ''), text: l }); frag.append(d); logsLive.lines.push(d); }
  box.append(frag);
  while (logsLive.lines.length > 3000) logsLive.lines.shift().remove();   // 3 000 lignes au plus à l'écran
  if (stick || reset) box.scrollTop = box.scrollHeight;   // défilement suivi, sauf si l'on remonte lire
}
async function loadLogs() {
  logsLive.cursor = '';
  $('#log-state').textContent = 'Chargement...';
  try {
    const d = await api('/api/logs/live?source=' + encodeURIComponent($('#log-source').value));
    logsLive.cursor = d.cursor; renderLogLines((d.text || '').split('\n').filter(Boolean), true);
    $('#log-state').textContent = logsLive.timer ? 'en direct' : '';
  } catch (e) { $('#log-state').textContent = e.message; }
}
async function pollLogs() {
  try {
    const d = await api('/api/logs/live?source=' + encodeURIComponent($('#log-source').value) + '&after=' + encodeURIComponent(logsLive.cursor));
    logsLive.cursor = d.cursor || logsLive.cursor;
    const nl = (d.text || '').split('\n').filter(Boolean);
    if (nl.length) renderLogLines(nl, false);
    $('#log-state').textContent = 'en direct - ' + fmtTime(Date.now() / 1000, true);
  } catch (e) { $('#log-state').textContent = e.message; }
}
$('#log-live').addEventListener('click', () => {
  const on = !logsLive.timer;
  clearInterval(logsLive.timer); logsLive.timer = on ? setInterval(pollLogs, 2000) : null;
  $('#log-live').setAttribute('aria-pressed', on ? 'true' : 'false');
  $('#log-state').textContent = on ? 'en direct' : 'suivi arrêté';
  if (on) pollLogs();
});
$('#log-filter').addEventListener('input', () => { const f = $('#log-filter').value.trim().toLowerCase(); for (const d of logsLive.lines) d.classList.toggle('hide', !!f && !d.textContent.toLowerCase().includes(f)); });
$('#log-refresh').addEventListener('click', loadLogs);
$('#log-source').addEventListener('change', () => { loadLogs(); });

/* --------------------------------------------------------------- démarrage */
$('#lang-switch').addEventListener('click', switchLanguage);
setupTabs();
(async () => {
  await loadI18n();
  try { const d = await api('/api/session'); showApp(d); } catch (e) { showLogin(); }
})();


/* ------------------------------------------------ alertes du tableau de bord */
function renderDashAlerts(s) {
  const items = (s.alerts || []).map((x) => ({ sev: x.severity, text: x.text }));
  for (const m of s.offload || []) if (!items.some((x) => x.text.startsWith(m.name + ' tourne'))) items.push({ sev: 'warning', text: m.name + ' tourne à ' + m.cpu_pct + ' % sur le processeur : débit fortement réduit' });
  $('#dash-alerts').replaceChildren(...(items.length ? [el('div', { class: 'notice' }, el('strong', { text: items.length === 1 ? 'Alerte' : items.length + ' alertes' }),
    el('ul', { class: 'alerts' }, ...items.map((x) => el('li', { text: x.text }))),
    (s.offload || []).length && isAdmin() ? el('div', { class: 'small' }, el('a', { href: '#models', text: 'Voir le réglage recommandé du contexte et du parallélisme' })) : null)] : []));
}

/* ------------------------------------------------ réglage automatique (modèles) */
async function loadTuning() {
  const box = $('#tuning-body');
  let t;
  try { t = await api('/api/tuning'); } catch (e) { box.replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  if (!t.vram) { box.replaceChildren(el('p', { class: 'muted', text: 'Aucune mémoire vidéo détectée : ce réglage ne s\'applique qu\'aux serveurs avec GPU.' })); return; }
  const cur = t.current;
  const rows = t.models.map((m) => {
    const rec = !m.known ? pill('inconnu', '') : !m.fits ? pill('ne tient pas en VRAM', 'err') : m.tight ? pill('serré', 'warn') : pill('tient', 'ok');
    const curTokens = (cur.ctx || 4096) * cur.parallel;
    const over = m.known && m.fits && curTokens > m.tokens;
    return el('tr', {}, el('td', {}, el('strong', { text: m.name })), el('td', { class: 'nowrap', text: fmtBytes(m.weights) }), el('td', { text: m.max ? DEC(m.max) : '-' }),
      el('td', {}, m.known && m.fits ? m.parallel + ' en parallèle, contexte ' + DEC(m.ctx) : '-', ' ', rec, over ? el('div', { class: 'small error', text: 'Le réglage actuel dépasse la mémoire disponible pour ce modèle.' }) : null),
      el('td', {}, m.known && m.fits && m.ctx ? el('button', { class: 'btn sm primary', type: 'button', text: 'Appliquer', onclick: () => tuningApply(m) }) : null));
  });
  box.replaceChildren(el('div', { class: 'small muted', text: 'Mémoire vidéo : ' + fmtBytes(t.vram) + ' (' + t.gpus.join(', ') + ') - réglage actuel : contexte ' + (cur.ctx ? DEC(cur.ctx) : 'par défaut') + ', ' + cur.parallel + ' en parallèle, cache ' + cur.kv_type }),
    t.models.length ? el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, ...['Modèle', 'Poids', 'Contexte maximal', 'Recommandation', ''].map((x) => el('th', { text: x })))), el('tbody', {}, ...rows))) : el('p', { class: 'muted', text: 'Aucun modèle installé.' }));
}
async function tuningApply(m) {
  if (!(await ask('Appliquer à tous les modèles : ' + m.parallel + ' en parallèle, contexte ' + m.ctx + ' jetons ? Ollama redémarre et les modèles chargés sont déchargés.', { ok: 'Appliquer' }))) return;
  try { await api('/api/tuning/apply', { json: { parallel: m.parallel, ctx: m.ctx } }); setTimeout(loadTuning, 4000); await notify('Réglage appliqué : Ollama redémarre.', { title: 'Réglage automatique' }); } catch (e) { fail(e.message); }
}
$('#tuning-refresh').addEventListener('click', loadTuning);

/* ------------------------------------------------ limites des clés */
function keyLimits(k, u) {
  const n = (x) => (x >= 1e6 ? DEC((x / 1e6).toFixed(1)) + ' M' : x >= 1e3 ? DEC((x / 1e3).toFixed(0)) + ' k' : String(x));
  const parts = [];
  if (k.max_concurrent) {
    parts.push('au plus ' + k.max_concurrent + ' simultanée(s)');
    if (u && (u.running || u.waiting)) parts.push(u.running + ' en cours, ' + u.waiting + ' en attente');
  }
  if (k.quota_day) parts.push('jour : ' + n((u && u.day) || 0) + ' / ' + n(k.quota_day) + ' jetons');
  if (k.quota_month) parts.push('mois : ' + n((u && u.month) || 0) + ' / ' + n(k.quota_month) + ' jetons');
  if (k.max_ctx) parts.push('contexte ≤ ' + n(k.max_ctx) + ' jetons');
  if (k.max_output) parts.push('réponse ≤ ' + n(k.max_output) + ' jetons');
  if (!parts.length && u && u.total) parts.push(n(u.total) + ' jetons au total');
  return parts.length ? parts : ['sans limite'];
}

/* ------------------------------------------------ alertes (configuration) */
async function loadAlerts() {
  if (!isAdmin()) return;
  let v;
  try { v = await api('/api/alerts'); } catch (e) { $('#al-msg').className = 'small error'; $('#al-msg').textContent = e.message; return; }
  const f = $('#al-form'), c = v.config;
  f.elements.enabled.checked = c.enabled; f.elements.webhook.value = c.webhook.url || '';
  f.elements.smtp_host.value = c.smtp.host || ''; f.elements.smtp_port.value = c.smtp.port || 587; f.elements.smtp_starttls.checked = c.smtp.starttls !== false;
  f.elements.smtp_user.value = c.smtp.user || ''; f.elements.smtp_password.value = ''; f.elements.smtp_password.placeholder = c.smtp.has_password ? 'Mot de passe enregistré (laisser vide pour le conserver)' : 'Aucun mot de passe enregistré';
  f.elements.smtp_from.value = c.smtp.from || ''; f.elements.smtp_to.value = (c.smtp.to || []).join('\n');
  f.elements.disk_pct.value = c.disk_pct; f.elements.gpu_temp.value = c.gpu_temp; f.elements.tps_min.value = c.tps_min;
  checkList('#al-events', 'event', Object.keys(v.events), c.events, v.events);
  $('#al-active').replaceChildren(...(v.active.length ? [el('ul', { class: 'alerts' }, ...v.active.map((x) => el('li', { text: x.text })))] : [el('p', { class: 'muted small', text: 'Aucune alerte active.' })]),
    ...(v.last_error ? [el('p', { class: 'small error', text: 'Dernier échec d\'envoi : ' + v.last_error })] : []));
}
function alertsBody(f) {
  return { enabled: f.elements.enabled.checked, webhook: { url: f.elements.webhook.value.trim() },
    smtp: { host: f.elements.smtp_host.value.trim(), port: Number(f.elements.smtp_port.value) || 587, starttls: f.elements.smtp_starttls.checked, user: f.elements.smtp_user.value.trim(),
      password: f.elements.smtp_password.value, from: f.elements.smtp_from.value.trim(), to: f.elements.smtp_to.value.split('\n').map((x) => x.trim()).filter(Boolean) },
    events: checkedValues(f, 'event'), disk_pct: Number(f.elements.disk_pct.value), gpu_temp: Number(f.elements.gpu_temp.value), tps_min: Number(f.elements.tps_min.value) || 0 };
}
$('#al-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const msg = $('#al-msg');
  try { await api('/api/alerts/config', { json: alertsBody(ev.target) }); msg.className = 'small okmsg'; msg.textContent = 'Enregistré.'; loadAlerts(); }
  catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
});
$('#al-test').addEventListener('click', async () => {
  const msg = $('#al-msg');
  try {
    await api('/api/alerts/config', { json: alertsBody($('#al-form')) });
    const r = await api('/api/alerts/test', { json: {} });
    msg.className = 'small'; msg.textContent = '';
    await notify(Object.entries(r.results).map(([k, v]) => k + ' : ' + (v === 'ok' ? 'envoyé' : 'échec - ' + v)).join('\n'), { title: 'Message de test' });
    loadAlerts();
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
});

/* ------------------------------------------------ sauvegarde de la configuration */
$('#bk-export').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const msg = $('#bk-msg'), f = ev.target;
  try {
    const r = await api('/api/backup/export', { json: { passphrase: f.elements.passphrase.value }, raw: true });
    const url = URL.createObjectURL(await r.blob());
    const a = el('a', { href: url, download: 'ollamabuntu-config-' + new Date().toISOString().slice(0, 10) + '.obbk' });
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    f.elements.passphrase.value = ''; msg.className = 'small okmsg'; msg.textContent = 'Fichier exporté : conservez-le avec la phrase secrète, séparément.';
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
});
$('#bk-import').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const msg = $('#bk-import-msg'), f = ev.target, file = f.elements.file.files[0];
  if (!file) return;
  msg.className = 'small'; msg.textContent = 'Lecture...';
  try {
    const buf = new Uint8Array(await file.arrayBuffer());
    let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    const body = { data: btoa(bin), passphrase: f.elements.passphrase.value };
    const r = await api('/api/backup/import', { json: body });
    msg.textContent = '';
    if (!(await ask('Restaurer la configuration de la version ' + r.summary.version + ' (' + r.summary.created + ') ?\nFichiers : ' + r.summary.files.join(', ') + '.\nLa configuration actuelle de ces fichiers sera remplacée, puis Ollama, le routeur et la console redémarrent.', { ok: 'Restaurer', danger: true }))) return;
    await api('/api/backup/import', { json: Object.assign(body, { apply: true }) });
    f.elements.passphrase.value = '';
    await notify('Configuration restaurée : la console redémarre, reconnectez-vous.', { title: 'Restauration' });
    setTimeout(() => location.reload(), 4000);
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
});

/* ------------------------------------------------ retour à une version précédente */
async function loadRollback() {
  if (!isAdmin()) return;
  let d;
  try { d = await api('/api/update/backups'); } catch (e) { $('#rb-list').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const stampDate = (s) => s.slice(6, 8) + '/' + s.slice(4, 6) + '/' + s.slice(0, 4) + ' ' + s.slice(9, 11) + ':' + s.slice(11, 13);
  $('#rb-list').replaceChildren(...(d.backups.length ? [el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, ...['Version', 'Sauvegardée le', ''].map((x) => el('th', { text: x })))),
    el('tbody', {}, ...d.backups.map((b) => el('tr', {}, el('td', {}, el('strong', { text: 'v' + b.version }), b.version === d.installed ? ' ' : '', b.version === d.installed ? pill('installée', 'info') : null),
      el('td', { text: stampDate(b.stamp) }),
      el('td', {}, b.version === d.installed ? null : el('button', { class: 'btn sm', type: 'button', text: 'Revenir à cette version', onclick: () => rollbackTo(b, d.installed) })))))))]
    : [el('p', { class: 'muted small', text: 'Aucune sauvegarde : la première mise à jour en créera une.' })]));
}
function rollbackTo(b, installed) {
  return applianceUpdate({ action: 'appliance-rollback', file: b.file,
    confirm: 'Revenir de v' + installed + ' à v' + b.version + ' ?\nLes fichiers de l\'appliance de cette version sont restaurés ; comptes, réglages d\'Ollama et modèles sont conservés. Les services IA redémarrent.',
    intro: 'Restauration des fichiers de la version précédente.' });
}

/* ------------------------------------------------ règles de routage et vérification du parc */
async function loadRules(v) {
  if (!isAdmin()) return;
  let r, p;
  try { r = (await api('/api/fleet/rules')).rules; p = await api('/api/publication'); } catch (e) { return; }
  const keyName = Object.fromEntries(p.keys.map((k) => [k.id, k.name]));
  const srv = Object.fromEntries(v.servers.filter((s) => s.route).map((s) => [s.id, s.name]));
  rulesState.rules = r;
  const f = $('#rules-form');
  f.elements.key.replaceChildren(el('option', { value: '*', text: 'Tous les clients' }), ...p.keys.map((k) => el('option', { value: k.id, text: k.name })));
  f.elements.server.replaceChildren(el('option', { value: 'local', text: 'Ce serveur' }), ...Object.entries(srv).map(([id, n]) => el('option', { value: id, text: n })));
  $('#rules-list').replaceChildren(...(r.length ? [el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, ...['Client', 'Modèle', 'Règle', 'Serveur', ''].map((x) => el('th', { text: x })))),
    el('tbody', {}, ...r.map((x, i) => el('tr', {}, el('td', { text: x.key === '*' ? 'Tous les clients' : (keyName[x.key] || '(clé supprimée)') }), el('td', { text: x.model }),
      el('td', { text: x.mode === 'only' ? 'Uniquement sur' : 'Jamais sur' }), el('td', { text: x.server === 'local' ? 'Ce serveur' : (srv[x.server] || '(serveur retiré)') }),
      el('td', {}, el('button', { class: 'btn sm danger', type: 'button', text: 'Retirer', onclick: () => rulesSave(r.filter((_, j) => j !== i)) })))))))]
    : [el('p', { class: 'muted small', text: 'Aucune règle : le routeur choisit selon la charge.' })]));
}
const rulesState = { rules: [] };
async function rulesSave(rules) {
  const msg = $('#rules-msg');
  try { await api('/api/fleet/rules', { json: { rules } }); msg.className = 'small okmsg'; msg.textContent = 'Enregistré.'; loadFleet(); }
  catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
}
$('#rules-form').addEventListener('submit', (ev) => {
  ev.preventDefault();
  const f = ev.target;
  rulesSave(rulesState.rules.concat([{ key: f.elements.key.value, model: f.elements.model.value.trim(), server: f.elements.server.value, mode: f.elements.mode.value }]));
});
$('#bal-check').addEventListener('click', async () => {
  const msg = $('#bal-msg');
  msg.className = 'small'; msg.textContent = 'Vérification en cours (chaque serveur génère quelques mots)...'; $('#bal-check').disabled = true;
  try {
    const r = await api('/api/fleet/check', { json: {} });
    msg.textContent = '';
    await modal({ title: 'Vérification du parc', message: 'Modèle de référence : ' + r.model,
      body: el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, ...['Serveur', 'Résultat', 'Détail', 'Durée', 'Débit'].map((x) => el('th', { text: x })))),
        el('tbody', {}, ...r.results.map((x) => el('tr', {}, el('td', {}, el('strong', { text: x.server })), el('td', {}, x.ok ? pill('répond', 'ok') : pill('échec', 'err')),
          el('td', { class: 'small', text: x.ok ? x.note : x.error }), el('td', { class: 'nowrap', text: x.ms ? DEC((x.ms / 1000).toFixed(1)) + ' s' : '-' }), el('td', { class: 'nowrap', text: x.tps ? DEC(x.tps) + ' t/s' : '-' })))))), ok: 'Fermer', cancel: null });
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
  $('#bal-check').disabled = false;
});

/* ================================================== second lot : interface ==== */

/* ------------------------------------------------ thème (automatique, clair, sombre) */
const THEMES = ['auto', 'light', 'dark'];
const THEME_LABEL = { auto: 'Thème : automatique', light: 'Thème : clair', dark: 'Thème : sombre' };
const themeNow = { v: 'auto' };
/* Icônes vectorielles de l'en-tête (les symboles Unicode s'affichent trop petits ou différemment selon les polices). */
const ICONS = {
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5"/>',
  auto: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16z" fill="currentColor"/>',
  light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/>',
  dark: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"/>',
};
function setIcon(btn, name) {
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('width', '18'); svg.setAttribute('height', '18'); svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2'); svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
  const g = document.createElementNS(NS, 'g');
  new DOMParser().parseFromString('<svg xmlns="' + NS + '">' + ICONS[name] + '</svg>', 'image/svg+xml').documentElement.childNodes.forEach((c) => g.append(document.importNode(c, true)));
  svg.append(g); btn.replaceChildren(svg);
}
setIcon($('#palette-btn'), 'search');
function applyTheme(th) {
  themeNow.v = THEMES.includes(th) ? th : 'auto';
  const r = document.documentElement;
  if (themeNow.v === 'auto') r.removeAttribute('data-theme'); else r.setAttribute('data-theme', themeNow.v);
  const b = $('#theme-btn');
  setIcon(b, themeNow.v);
  b.setAttribute('title', THEME_LABEL[themeNow.v]); b.setAttribute('aria-label', THEME_LABEL[themeNow.v]);
}
function cycleTheme() {
  const next = THEMES[(THEMES.indexOf(themeNow.v) + 1) % THEMES.length];
  try { localStorage.setItem('ob-theme', next); } catch (e) { /* vide */ }
  applyTheme(next);
}
$('#theme-btn').addEventListener('click', cycleTheme);
(() => { let th = 'auto'; try { th = localStorage.getItem('ob-theme') || 'auto'; } catch (e) { /* vide */ } applyTheme(th); })();

/* ------------------------------------------------ cloche d'alertes */
async function pollBell() {
  if (!isAdmin() || document.hidden || $('#app').classList.contains('hidden')) return;
  try { const v = await api('/api/alerts'); bell.items = v.active || []; renderBell(); } catch (e) { /* vide */ }
}
function startBell() {
  clearInterval(bell.timer); bell.timer = null;
  if (!isAdmin()) return;
  pollBell(); bell.timer = setInterval(pollBell, 30000);
}
function renderBell() {
  const n = bell.items.length, badge = $('#bell-n');
  badge.textContent = n > 99 ? '99+' : String(n);
  badge.classList.toggle('hidden', !n);
  badge.classList.toggle('info', n > 0 && bell.items.every((x) => x.severity === 'info'));
  const label = n ? n + ' alerte(s) active(s)' : 'Aucune alerte';
  $('#bell').setAttribute('title', label); $('#bell').setAttribute('aria-label', label);
  const sev = { critical: 'err', warning: 'warn', info: 'info' }, name = { critical: 'critique', warning: 'attention', info: 'info' };
  $('#bell-pop').replaceChildren(el('h3', { text: 'Alertes actives' }),
    n ? el('ul', {}, ...bell.items.map((x) => el('li', {}, pill(name[x.severity] || x.severity, sev[x.severity] || ''), el('span', { text: x.text })))) : el('p', { class: 'muted small', text: 'Aucune alerte active.' }),
    el('a', { class: 'small', href: '#system/alerts', text: 'Configurer les alertes', onclick: () => closeBell() }));
}
function closeBell() { $('#bell-pop').classList.add('hidden'); $('#bell').setAttribute('aria-expanded', 'false'); }
$('#bell').addEventListener('click', (ev) => {
  ev.stopPropagation();
  const open = $('#bell-pop').classList.contains('hidden');
  if (open) renderBell();
  $('#bell-pop').classList.toggle('hidden', !open); $('#bell').setAttribute('aria-expanded', open ? 'true' : 'false');
});
document.addEventListener('click', (ev) => { if (!ev.target.closest('#bell-wrap')) closeBell(); });
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeBell(); });

/* ------------------------------------------------ tableau de bord : parc de serveurs */
async function loadDashFleet() {
  if (!isAdmin() || Date.now() - bell.fleetAt < 25000) return;
  bell.fleetAt = Date.now();
  let d;
  try { d = await api('/api/fleet/servers'); } catch (e) { return; }
  const list = d.servers || [];
  const kind = (s) => (s.state === 'en ligne' ? 'ok' : s.state === 'en attente' ? 'info' : 'err');
  const mini = (s) => {
    const x = s.data || {}, g = (x.gpu_live || [])[0], run = ((x.ollama || {}).running || []).map((m) => m.name);
    return el('div', { class: 'srv' }, el('div', { class: 'nm' }, el('span', { text: s.name }), pill(s.state, kind(s))),
      s.state === 'en ligne' ? el('div', { class: 'small muted' },
        g && g.util != null ? 'GPU ' + DEC(g.util.toFixed(0)) + ' %' + (g.mem_total ? ' - ' + fmtBytes(g.mem_used) + ' / ' + fmtBytes(g.mem_total) : '') : (x.cpu && x.cpu.usage != null ? 'Processeur ' + DEC(x.cpu.usage) + ' %' : ''),
        el('br'), run.length ? 'En mémoire : ' + run.join(', ') : 'Aucun modèle en mémoire') : el('div', { class: 'small muted', text: s.error || '' }),
      s.route ? el('div', { class: 'small' }, pill('répartition', 'info')) : null);
  };
  $('#dash-fleet').replaceChildren(...(list.length ? [el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', { text: 'Parc de serveurs' }), el('a', { class: 'small', href: '#fleet', text: 'Gérer les serveurs' })),
    el('div', { class: 'fleet-mini' }, ...list.map(mini)))] : []));
}

/* ------------------------------------------------ statistiques d'utilisation */
const stats = { span: 86400 };
function usageBars(buckets, span, width) {
  const NS = 'http://www.w3.org/2000/svg', W = Math.max(width || 0, 320) || 560, H = 150, L = 34, B = 18, T = 6, n = buckets.length, bw = (W - L) / n;
  const ymax = niceMax(Math.max(...buckets.map((b) => b.count), 1) * 1.05);
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('class', 'bars-svg'); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Requêtes par tranche : ' + buckets.reduce((a, b) => a + b.count, 0) + ' au total');
  const add = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; svg.append(e); return e; };
  for (const f of [0, 0.5, 1]) {
    const y = T + (1 - f) * (H - T - B);
    add('line', { x1: L, x2: W, y1: y, y2: y, stroke: 'currentColor', 'stroke-opacity': '.12' });
    add('text', { x: L - 4, y: y + 3, 'text-anchor': 'end', class: 'axis' }, DEC(+(ymax * f).toFixed(ymax * f < 10 && f ? 1 : 0)));
  }
  const fmtB = (t) => (span > 86400 ? new Date(t * 1000).toLocaleDateString(LOCALE(), { day: '2-digit', month: '2-digit' }) : fmtTime(t));
  buckets.forEach((b, i) => {
    const h = (b.count / ymax) * (H - T - B), he = (b.errors / ymax) * (H - T - B), x = L + i * bw + 1;
    const ok = add('rect', { x: x.toFixed(1), y: (H - B - h).toFixed(1), width: Math.max(bw - 2, 1).toFixed(1), height: Math.max(h - he, 0).toFixed(1), class: 'bar-ok' });
    ok.append(Object.assign(document.createElementNS(NS, 'title'), { textContent: fmtB(b.t) + ' : ' + b.count + ' requête(s)' + (b.errors ? ', ' + b.errors + ' en erreur' : '') }));
    if (he > 0) add('rect', { x: x.toFixed(1), y: (H - B - h).toFixed(1), width: Math.max(bw - 2, 1).toFixed(1), height: he.toFixed(1), class: 'bar-err' });
  });
  for (const f of [0, 0.5, 1]) add('text', { x: L + f * (W - L), y: H - 4, 'text-anchor': f === 0 ? 'start' : f === 1 ? 'end' : 'middle', class: 'axis' }, fmtB(buckets[Math.min(n - 1, Math.round(f * (n - 1)))].t));
  return svg;
}
function hbars(rows, unit) {
  const max = Math.max(...rows.map((r) => r.count), 1), tok = (r) => r.in_tok + r.out_tok;
  const n = (x) => (x >= 1e6 ? DEC((x / 1e6).toFixed(1)) + ' M' : x >= 1e3 ? DEC((x / 1e3).toFixed(1)) + ' k' : String(x));
  if (!rows.length) return el('p', { class: 'muted small', text: 'Aucune requête sur cette période.' });
  return el('div', { class: 'hbars' }, ...rows.map((r) => {
    const i = el('i'); i.style.width = Math.max(2, (r.count / max) * 100) + '%';
    return el('div', { class: 'hbar' }, el('span', { class: 'nm', title: r.name, text: r.name }), el('span', { class: 'tr' }, i),
      el('span', { class: 'vl', text: r.count + ' - ' + n(tok(r)) + ' ' + unit }));
  }));
}
async function loadStats() {
  let u;
  try { u = await api('/api/usage?span=' + stats.span); } catch (e) { $('#st-body').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const t = u.total, rate = t.count ? Math.round((100 * t.errors) / t.count) : 0, avg = t.count ? Math.round(t.ms / t.count) : null;
  const kpi = (label, value) => el('div', { class: 'card' }, el('h2', { text: label }), el('div', { class: 'big', text: value }));
  const nn = (x) => Number(x).toLocaleString(LOCALE());
  $('#st-body').replaceChildren(
    el('div', { class: 'grid kpis' }, kpi('Requêtes', nn(t.count)), kpi('Taux d\'erreur', rate + ' %'), kpi('Jetons en entrée', nn(t.in_tok)), kpi('Jetons générés', nn(t.out_tok)), kpi('Durée moyenne', fmtMs(avg))),
    el('div', { class: 'chart' }, el('div', { class: 'ct' }, el('strong', { text: 'Requêtes dans le temps' }), el('span', { class: 'muted small', text: 'rouge : en erreur' })), usageBars(u.buckets, u.span, $('#st-body').clientWidth - 26)),
    el('div', { class: 'cols2' }, el('div', {}, el('h3', { text: 'Par modèle' }), hbars(u.models, 'jetons')), el('div', {}, el('h3', { text: 'Par client' }), hbars(u.clients, 'jetons'))));
}
for (const b of $$('#st-range button')) b.addEventListener('click', () => {
  stats.span = Number(b.dataset.span);
  for (const x of $$('#st-range button')) { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); }
  loadStats();
});

/* ------------------------------------------------ clés d'API : échéance */
function keyExpiryPill(k) {
  if (k.days_left == null) return null;
  const d = k.days_left;
  return el('div', {}, d < 0 ? pill('expirée', 'err') : d <= 7 ? pill(d === 0 ? 'expire aujourd\'hui' : 'expire dans ' + d + ' j', 'warn') : pill('expire le ' + k.expires, ''));
}
async function keyExpiry(k) {
  const inp = el('input', { type: 'date', value: k.expires || '', 'aria-label': 'Date d\'expiration' });
  const ok = await modal({ title: 'Échéance de la clé « ' + k.name + ' »', message: 'La clé reste valable jusqu\'à la fin de ce jour. Laissez vide pour qu\'elle n\'expire jamais.', body: inp, ok: 'Enregistrer' });
  if (!ok) return;
  try { await api('/api/publication/keys/update', { json: { id: k.id, expires: inp.value } }); await loadPublication(); } catch (e) { fail(e.message); }
}

/* ------------------------------------------------ export Prometheus */
async function loadProm() {
  if (!isAdmin()) return;
  let p;
  try { p = await api('/api/prom'); } catch (e) { $('#prom-state').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  $('#prom-state').replaceChildren(
    p.enabled ? el('p', {}, pill('actif', 'ok'), ' ' + 'Jeton créé le ' + fmtDate(p.created)) : el('p', { class: 'muted small', text: 'Export désactivé : aucun jeton.' }),
    p.enabled ? el('pre', { class: 'example', text: 'scrape_configs:\n  - job_name: ollamabuntu\n    scheme: https\n    metrics_path: ' + p.path + '\n    authorization:\n      credentials: <jeton>\n    tls_config:\n      insecure_skip_verify: true\n    static_configs:\n      - targets: ["' + location.host + '"]' }) : null);
  $('#prom-create').textContent = p.enabled ? 'Remplacer le jeton' : 'Générer un jeton';
  $('#prom-revoke').classList.toggle('hidden', !p.enabled);
}
$('#prom-create').addEventListener('click', async () => {
  const had = !$('#prom-revoke').classList.contains('hidden');
  if (had && !(await ask('Remplacer le jeton ? L\'ancien cessera de fonctionner immédiatement.', { ok: 'Remplacer', danger: true }))) return;
  try {
    const r = await api('/api/prom/token', { json: { action: 'create' } });
    const code = el('code', { class: 'token', text: r.token }), copied = el('span', { class: 'small okmsg' });
    await loadProm();
    await modal({ title: 'Jeton Prometheus créé', message: 'Copiez-le maintenant : il ne sera plus jamais affiché (seule son empreinte est conservée).',
      body: el('div', {}, code, el('button', { class: 'btn sm', type: 'button', text: 'Copier', onclick: async () => {
        try { await navigator.clipboard.writeText(r.token); copied.textContent = ' Copié.'; }
        catch (e) { const rg = document.createRange(); rg.selectNodeContents(code); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(rg); copied.textContent = ' Sélectionné : Ctrl+C pour copier.'; } } }), copied),
      ok: 'J\'ai copié le jeton', cancel: null });
  } catch (e) { fail(e.message); }
});
$('#prom-revoke').addEventListener('click', async () => {
  if (!(await ask('Révoquer le jeton Prometheus ? Les collectes en cours échoueront.', { ok: 'Révoquer', danger: true }))) return;
  try { await api('/api/prom/token', { json: { action: 'revoke' } }); await loadProm(); } catch (e) { fail(e.message); }
});

/* ------------------------------------------------ disponibilité des GPU pour Ollama */
const GG_CODE = { driver_down: 'Pilote inactif', ollama_blind: 'Carte non vue par Ollama', gpu_unused: 'Modèle sur le processeur', gpu_error_log: 'Erreur GPU dans le journal d\'Ollama', restricted: 'Visibilité limitée' };
const GG_STEP = { 'load-driver': 'pilote rechargé', 'load-uvm': 'module UVM vérifié', 'restart-ollama': 'Ollama redémarré' };
const GG_STATE = { ok: ['Toutes les cartes sont disponibles', 'ok'], info: ['Information', 'info'], warning: ['À surveiller', 'warn'], critical: ['Carte indisponible', 'err'], none: ['Aucune carte de calcul détectée', 'info'] };
let ggTimer = null;
async function loadGuard() {
  let g;
  try { g = await api('/api/gpu/guard'); } catch (e) { $('#gg-body').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  clearTimeout(ggTimer);
  if (g.repairing) ggTimer = setTimeout(() => { if (location.hash.startsWith('#gpu')) loadGuard(); }, 4000);
  const st = GG_STATE[g.state] || GG_STATE.ok, flag = (v) => (v ? pill('oui', 'ok') : pill('non', 'err'));
  $('#gg-body').replaceChildren(
    el('p', {}, pill(st[0], st[1]), g.repairing ? ' ' : null, g.repairing ? pill('réparation en cours...', 'info') : null),
    g.checks.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
      el('thead', {}, el('tr', {}, ...['Carte', 'Emplacement PCI', 'Pilote actif', 'Utilisée par Ollama'].map((c) => el('th', { text: c })))),
      el('tbody', {}, ...g.checks.map((c) => el('tr', {}, el('td', { class: 'name', text: c.name }), el('td', { class: 'small', text: c.pci }), el('td', {}, flag(c.driver)), el('td', {}, flag(c.ollama))))))) : null,
    g.issues.length ? el('ul', { class: 'alerts' }, ...g.issues.map((i) => el('li', {}, i.text, i.fix === 'reboot' ? ' Un redémarrage du serveur est nécessaire.' : ''))) : null);
  const fixable = g.issues.some((i) => i.fix === 'reload-driver' || i.fix === 'restart-ollama');
  $('#gg-repair').classList.toggle('hidden', !fixable); $('#gg-repair').disabled = !!g.repairing;
  if (w_active() !== $('#gg-auto')) $('#gg-auto').checked = !!g.auto;
  $('#gg-events').replaceChildren(g.events.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Date', 'Déclenchée par', 'Problème', 'Étapes', 'Résultat'].map((c) => el('th', { text: c })))),
    el('tbody', {}, ...g.events.map((e) => el('tr', {}, el('td', { class: 'small', text: fmtDate(e.t) }), el('td', { text: e.who }),
      el('td', { text: (e.codes || []).map((c) => GG_CODE[c] || c).join(', ') }), el('td', { class: 'small', text: (e.steps || []).map((s) => GG_STEP[s] || s).join(', ') }),
      el('td', {}, e.result === 'résolu' ? pill('résolu', 'ok') : pill('non résolu', 'err'), (e.remaining || []).length ? el('div', { class: 'small muted', text: e.remaining[0] }) : null))))))
    : el('p', { class: 'muted small', text: 'Aucune réparation effectuée.' }));
}
$('#gg-repair').addEventListener('click', async () => {
  if (!(await ask('Recharger le pilote NVIDIA si nécessaire et redémarrer Ollama ? Les modèles chargés sont déchargés et les requêtes en cours interrompues.', { ok: 'Réparer' }))) return;
  try { await api('/api/gpu/guard/repair', { json: {} }); $('#gg-msg').className = 'small okmsg'; $('#gg-msg').textContent = 'Réparation lancée.'; setTimeout(loadGuard, 1500); } catch (e) { fail(e.message); }
});
$('#gg-auto').addEventListener('change', async () => {
  try { await api('/api/gpu/guard/config', { json: { auto: $('#gg-auto').checked } }); $('#gg-msg').className = 'small okmsg'; $('#gg-msg').textContent = 'Enregistré.'; } catch (e) { fail(e.message); }
});

/* ------------------------------------------------ performance : mesure, profils, préchauffage, garde-fou, réglages système */
const pf = { data: null, models: [], timer: null };
const ENV_LABEL = { OLLAMA_FLASH_ATTENTION: 'Flash attention', OLLAMA_KV_CACHE_TYPE: 'Cache de contexte', OLLAMA_NUM_PARALLEL: 'Requêtes en parallèle', OLLAMA_KEEP_ALIVE: 'Maintien en mémoire', OLLAMA_MAX_LOADED_MODELS: 'Modèles chargés', OLLAMA_CONTEXT_LENGTH: 'Contexte par défaut' };
const envShow = (k, v) => (v === '' || v == null ? 'défaut' : k === 'OLLAMA_FLASH_ATTENTION' ? (v === '1' ? 'activée' : 'désactivée') : v);
const DAYS_SHORT = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'];
const deltaPill = (pctv, higherIsBetter) => (pctv == null ? null : pill((pctv > 0 ? '+' : '') + DEC(pctv) + ' %', pctv === 0 ? '' : (pctv > 0) === higherIsBetter ? 'ok' : 'err'));
function tpsBars(values) {
  const W = 120, H = 28, n = values.length, mx = Math.max(...values, 1);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('class', 'spark'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Évolution du débit');
  const bw = W / Math.max(n, 1);
  values.forEach((v, i) => {
    const r = document.createElementNS(svg.namespaceURI, 'rect'), h = Math.max(2, (v / mx) * (H - 2));
    r.setAttribute('x', (i * bw + 1).toFixed(1)); r.setAttribute('y', (H - h).toFixed(1)); r.setAttribute('width', Math.max(2, bw - 2).toFixed(1)); r.setAttribute('height', h.toFixed(1));
    r.setAttribute('class', 'line ' + (i === n - 1 ? 'ok' : 'info')); svg.append(r);
  });
  return svg;
}
function renderBench(d) {
  const b = d.bench, sel = $('#pf-model');
  if (w_active() !== sel) {
    const cur = sel.value;
    sel.replaceChildren(...pf.models.map((m) => el('option', { value: m, text: m })));
    if (cur && pf.models.includes(cur)) sel.value = cur; else if (b.model && pf.models.includes(b.model)) sel.value = b.model;
  }
  $('#pf-run').disabled = b.running || !pf.models.length;
  const s = $('#pf-state');
  s.className = 'small' + (b.error ? ' error' : '');
  s.textContent = b.running ? 'Mesure en cours : passe ' + b.step + ' sur ' + b.runs + ' (' + b.model + ')...' : (b.error || '');
  const last = b.history[0];
  const kpi = (label, value, extra) => el('div', { class: 'card' }, el('h2', { text: label }), el('div', { class: 'big', text: value }), extra || null);
  $('#pf-result').replaceChildren(last ? el('div', { class: 'grid kpis' },
    kpi('Débit (' + last.model + ')', DEC(last.tps) + ' jetons/s', last.delta ? el('div', { class: 'small' }, deltaPill(last.delta.tps_pct, true), ' par rapport à la mesure précédente') : null),
    kpi('Délai avant le 1er jeton', fmtMs(last.ttft_ms), last.delta && last.delta.ttft_pct != null ? el('div', { class: 'small' }, deltaPill(last.delta.ttft_pct, false)) : null),
    kpi('Dans la mémoire vidéo', last.vram_pct == null ? '-' : last.vram_pct + ' %', last.vram_pct != null && last.vram_pct < 100 ? el('div', { class: 'small', text: 'le reste tourne sur le processeur' }) : null),
    kpi('Chargement à froid', fmtMs(last.load_ms))) : el('p', { class: 'muted small', text: 'Aucune mesure : choisissez un modèle et lancez-la.' }));
  const series = (name) => b.history.filter((h) => h.model === name).map((h) => h.tps).reverse();
  $('#pf-history').replaceChildren(b.history.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Date', 'Modèle', 'Débit', 'Évolution', '1er jeton', 'Mémoire vidéo', 'Réglages'].map((c, i) => el('th', { class: i >= 2 && i !== 3 ? 'num' : '', text: c })))),
    el('tbody', {}, ...b.history.map((h) => el('tr', {}, el('td', { class: 'small', text: fmtDate(h.t) }), el('td', { class: 'name', text: h.model }),
      el('td', { class: 'num' }, DEC(h.tps) + ' j/s ', h.delta ? deltaPill(h.delta.tps_pct, true) : null), el('td', {}, tpsBars(series(h.model))),
      el('td', { class: 'num', text: fmtMs(h.ttft_ms) }), el('td', { class: 'num', text: h.vram_pct == null ? '-' : h.vram_pct + ' %' }),
      el('td', { class: 'small', text: (h.profile ? PF_LABEL(h.profile) + ' - ' : '') + 'cache ' + h.cfg.kv + ', parallèle ' + h.cfg.parallel })))))) : el('p', { class: 'muted small', text: 'Aucune mesure enregistrée.' }));
}
const PF_LABEL = (id) => (pf.data && (pf.data.profiles.find((p) => p.id === id) || {}).label) || id;
function renderProfiles(d) {
  $('#pf-profiles').replaceChildren(...d.profiles.map((p) => el('div', { class: 'card' + (d.current === p.id ? ' gpu-dev ok' : '') },
    el('h2', { text: p.label }), d.current === p.id ? pill('profil actuel', 'ok') : null,
    el('p', { class: 'small', text: p.help }),
    p.diff.length ? el('ul', { class: 'small' }, ...p.diff.map((c) => el('li', { text: (ENV_LABEL[c.key] || c.key) + ' : ' + envShow(c.key, c.from) + ' → ' + envShow(c.key, c.to) }))) : el('p', { class: 'okmsg small', text: 'Ces réglages sont déjà appliqués.' }),
    el('button', { class: 'btn' + (p.diff.length ? ' primary' : ''), type: 'button', disabled: p.diff.length ? null : true, text: 'Appliquer ce profil', onclick: () => applyProfile(p) }))),
  d.current ? null : el('p', { class: 'muted small', text: 'Réglages actuels personnalisés : aucun profil ne correspond exactement.' }));
}
async function applyProfile(p) {
  if (!(await ask('Appliquer le profil « ' + p.label + ' » ?\n' + p.diff.map((c) => '• ' + (ENV_LABEL[c.key] || c.key) + ' : ' + envShow(c.key, c.from) + ' → ' + envShow(c.key, c.to)).join('\n') + '\nOllama redémarre et les modèles chargés sont déchargés.', { ok: 'Appliquer' }))) return;
  try { await api('/api/perf/profile', { json: { id: p.id, apply: true } }); await notify('Profil appliqué : Ollama redémarre. Refaites une mesure pour comparer.', { title: 'Profil de performance' }); setTimeout(loadPerformance, 3000); loadPerformance(); } catch (e) { fail(e.message); }
}
function modelChecks(selected) {
  return el('div', { class: 'checks mods' }, ...(pf.models.length ? pf.models.map((m) => el('label', { class: 'check' }, el('input', { type: 'checkbox', value: m, checked: (selected || []).includes(m) || null }), ' ' + m)) : [el('span', { class: 'muted small', text: 'Aucun modèle installé.' })]));
}
function warmRow(t) {
  const days = t.days || [0, 1, 2, 3, 4, 5, 6];
  const row = el('div', { class: 'warm-row' },
    el('input', { type: 'time', value: t.at || '07:30', required: true, 'aria-label': 'Heure' }),
    el('div', { class: 'checks days' }, ...DAYS_SHORT.map((d, i) => el('label', { class: 'check' }, el('input', { type: 'checkbox', value: String(i), checked: days.includes(i) || null }), ' ' + d))),
    modelChecks(t.models), el('button', { class: 'btn sm', type: 'button', text: 'Retirer', onclick: () => row.remove() }));
  return row;
}
function renderWarmup(d) {
  $('#pf-warm-boot').replaceChildren(...modelChecks(d.warmup.boot).children);
  $('#pf-warm-times').replaceChildren(...d.warmup.times.map(warmRow));
  $('#pf-warm-log').replaceChildren(d.warmup.log.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Date', 'Modèle', 'Déclencheur', 'Résultat'].map((c) => el('th', { text: c })))),
    el('tbody', {}, ...d.warmup.log.map((l) => el('tr', {}, el('td', { class: 'small', text: fmtDate(l.t) }), el('td', { class: 'name', text: l.model }), el('td', { class: 'small', text: l.why }),
      el('td', {}, l.ok ? pill('chargé', 'ok') : pill('échec', 'err'), l.error ? el('div', { class: 'small muted', text: l.error }) : null)))))) : el('p', { class: 'muted small', text: 'Aucun préchauffage depuis le démarrage de la console.' }));
}
$('#pf-warm-add').addEventListener('click', () => $('#pf-warm-times').append(warmRow({})));
$('#pf-warm-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const boot = [...$('#pf-warm-boot').querySelectorAll('input:checked')].map((i) => i.value);
  const times = [...$('#pf-warm-times').children].map((r) => ({ at: r.querySelector('input[type=time]').value, days: [...r.querySelectorAll('.days input:checked')].map((i) => Number(i.value)), models: [...r.querySelectorAll('.mods input:checked')].map((i) => i.value) }));
  try { await api('/api/perf/warmup', { json: { boot, times } }); $('#pf-warm-msg').className = 'small okmsg'; $('#pf-warm-msg').textContent = 'Enregistré.'; } catch (e) { $('#pf-warm-msg').className = 'small error'; $('#pf-warm-msg').textContent = e.message; }
});
$('#pf-warm-now').addEventListener('click', async () => {
  const models = [...$('#pf-warm-boot').querySelectorAll('input:checked')].map((i) => i.value);
  if (!models.length) { fail('Cochez au moins un modèle « au démarrage du serveur ».'); return; }
  try { await api('/api/perf/warmup/run', { json: { models } }); $('#pf-warm-msg').className = 'small okmsg'; $('#pf-warm-msg').textContent = 'Chargement lancé.'; setTimeout(loadPerformance, 6000); } catch (e) { fail(e.message); }
});
function renderPfGuard(d) {
  const a = d.alert;
  $('#pf-alert').replaceChildren(a ? el('div', { class: 'notice' }, el('strong', { text: a.kind === 'offload' ? 'Modèle partiellement sur le processeur' : 'Chute de débit' }), el('p', { text: a.text }),
    a.fix ? el('button', { class: 'btn primary', type: 'button', text: 'Appliquer la suggestion', onclick: applySuggestion }) : null) : el('p', { class: 'okmsg small', text: d.guard.mode === 'off' ? 'Garde-fou désactivé.' : 'Débit normal : rien à signaler.' }));
  if (w_active() !== $('#pf-guard-mode')) $('#pf-guard-mode').value = d.guard.mode;
  if (w_active() !== $('#pf-guard-drop')) $('#pf-guard-drop').value = String(d.guard.drop_pct);
  $('#pf-events').replaceChildren(d.events.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Date', 'Par', 'Réglage'].map((c) => el('th', { text: c })))),
    el('tbody', {}, ...d.events.map((e) => el('tr', {}, el('td', { class: 'small', text: fmtDate(e.t) }), el('td', { text: e.who }), el('td', { class: 'small', text: e.text })))))) : el('p', { class: 'muted small', text: 'Aucun réglage appliqué.' }));
}
async function applySuggestion() {
  if (!(await ask('Appliquer le réglage suggéré ? Ollama redémarre.', { ok: 'Appliquer' }))) return;
  try { await api('/api/perf/apply-suggestion', { json: {} }); await notify('Réglage appliqué : Ollama redémarre.', { title: 'Garde-fou de débit' }); setTimeout(loadPerformance, 3000); } catch (e) { fail(e.message); }
}
async function saveGuardMode() {
  try { await api('/api/perf/guard', { json: { mode: $('#pf-guard-mode').value, drop_pct: Number($('#pf-guard-drop').value) } }); $('#pf-guard-msg').className = 'small okmsg'; $('#pf-guard-msg').textContent = 'Enregistré.'; } catch (e) { fail(e.message); }
}
$('#pf-guard-mode').addEventListener('change', saveGuardMode);
$('#pf-guard-drop').addEventListener('change', saveGuardMode);
const CHECK_KIND = { ok: 'ok', warn: 'warn', info: 'info' }, CHECK_WORD = { ok: 'OK', warn: 'À traiter', info: 'Conseil' };
function renderPfChecks(d) {
  $('#pf-checks').replaceChildren(d.checks.length ? el('ul', { class: 'checks-list' }, ...d.checks.map((c) => el('li', {}, pill(CHECK_WORD[c.state], CHECK_KIND[c.state]), ' ', c.text, ' ',
    c.fix ? el('button', { class: 'btn sm', type: 'button', text: 'Corriger', onclick: () => sysFix(c) }) : null))) : el('p', { class: 'muted small', text: 'Aucun contrôle disponible.' }));
}
async function sysFix(c) {
  let value;
  if (c.fix === 'webui_mem') {
    const sel = el('select', { 'aria-label': 'Plafond de mémoire' }, ...['1g', '2g', '4g', '8g'].map((v) => el('option', { value: v, text: v.replace('g', ' Go') })));
    sel.value = '2g';
    if (!(await modal({ title: 'Plafonner la mémoire d\'Open WebUI', message: 'Le conteneur sera limité sans être recréé ; il est tué par le système s\'il dépasse ce plafond.', body: sel, ok: 'Appliquer' }))) return;
    value = sel.value;
  } else if (!(await ask(c.fix === 'governor' ? 'Passer tous les cœurs en mode « performance » ? La consommation au repos augmente légèrement.' : 'Régler vm.swappiness à 10 ?', { ok: 'Corriger' }))) return;
  try { await api('/api/perf/fix', { json: { id: c.fix, value } }); loadPerformance(); } catch (e) { fail(e.message); }
}
async function loadPerformance() {
  let d;
  try {
    [d] = await Promise.all([api('/api/perf'), api('/api/models').then((m) => { pf.models = (m.models || []).map((x) => x.name).filter((n) => !n.endsWith('-cloud')).sort(); }).catch(() => {})]);
  } catch (e) { $('#pf-result').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const first = !pf.data;
  pf.data = d;
  renderBench(d); renderProfiles(d); renderPfGuard(d); renderPfChecks(d);
  if (first || !$('#pf-warm-form').contains(w_active())) renderWarmup(d);
  clearInterval(pf.timer); pf.timer = null;
  if (d.bench.running) pf.timer = setInterval(async () => {
    if (location.hash.split('/')[0] !== '#perf') { clearInterval(pf.timer); return; }
    try { const x = await api('/api/perf'); pf.data = x; renderBench(x); if (!x.bench.running) { clearInterval(pf.timer); pf.timer = null; } } catch (e) { /* nouvel essai */ }
  }, 3000);
}
$('#pf-refresh').addEventListener('click', loadPerformance);
$('#pf-run').addEventListener('click', async () => {
  try { await api('/api/bench/run', { json: { model: $('#pf-model').value, runs: Number($('#pf-runs').value) } }); await loadPerformance(); } catch (e) { fail(e.message); }
});
$('#pf-clear').addEventListener('click', async () => {
  if (!(await ask('Effacer tout l\'historique des mesures ?', { ok: 'Effacer', danger: true }))) return;
  try { await api('/api/bench/clear', { json: {} }); loadPerformance(); } catch (e) { fail(e.message); }
});

/* ------------------------------------------------ santé du matériel */
const HW_KIND = { ok: ['sain', 'ok'], warning: ['à surveiller', 'warn'], critical: ['défaillant', 'err'] };
async function loadHardware(refresh) {
  let h;
  try { h = await api('/api/hw' + (refresh ? '?refresh=1' : '')); } catch (e) { $('#hw-body').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const gb = (b) => (b ? fmtBytes(b) : '-');
  const bad = h.issues.filter((i) => i.severity !== 'info');
  $('#hw-body').replaceChildren(
    el('p', {}, bad.length ? pill(bad.length + ' problème(s)', 'err') : pill('Aucun problème détecté', 'ok'), ' ', el('span', { class: 'muted small', text: 'Vérifié le ' + fmtDate(h.checked) })),
    bad.length ? el('ul', { class: 'alerts' }, ...bad.map((i) => el('li', { text: i.text }))) : null,
    el('h3', { text: 'Disques (SMART)' }),
    !h.smartctl ? el('div', {}, el('p', { class: 'muted small', text: 'smartmontools n\'est pas installé : la santé des disques ne peut pas être lue.' }),
      el('button', { class: 'btn primary', type: 'button', text: 'Installer smartmontools', onclick: installSmart })) :
    h.disks.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
      el('thead', {}, el('tr', {}, ...['Disque', 'Type', 'Modèle', 'Taille', 'Température', 'Heures', 'Usure', 'État'].map((c, i) => el('th', { class: i >= 3 && i < 7 ? 'num' : '', text: c })))),
      el('tbody', {}, ...h.disks.map((d) => el('tr', {}, el('td', { class: 'name', text: d.name }), el('td', { text: d.type }), el('td', { class: 'small', text: d.model }), el('td', { class: 'num', text: gb(d.size) }),
        el('td', { class: 'num', text: d.temp == null ? '-' : d.temp + ' °C' }), el('td', { class: 'num', text: d.hours == null ? '-' : Number(d.hours).toLocaleString(LOCALE()) + ' h' }),
        el('td', { class: 'num', text: d.wear == null ? '-' : d.wear + ' %' }), el('td', {}, pill(...(HW_KIND[d.state] || HW_KIND.ok)), ...(d.issues || []).map((i) => el('div', { class: 'small muted', text: i.text })))))))) : el('p', { class: 'muted small', text: 'Aucun disque lisible.' }),
    el('h3', { text: 'RAID logiciel' }),
    h.raid.length ? el('ul', {}, ...h.raid.map((r) => el('li', {}, el('strong', { text: r.name }), ' ' + r.level + ' - ', r.degraded ? pill('dégradée', 'err') : pill('saine', 'ok'),
      r.progress ? ' ' + r.progress.action + ' ' + DEC(r.progress.percent) + ' %' : '', ' (' + r.members.join(', ') + ')'))) : el('p', { class: 'muted small', text: 'Aucune grappe RAID.' }),
    el('h3', { text: 'Erreurs de la carte graphique (24 h)' }),
    h.xid.length ? el('ul', {}, ...h.xid.map((x) => el('li', {}, pill(x.severity === 'info' ? 'info' : x.severity === 'critical' ? 'critique' : 'attention', x.severity === 'info' ? 'info' : x.severity === 'critical' ? 'err' : 'warn'),
      ' ' + x.pci + ' - Xid ' + x.xid + (x.text ? ' : ' + x.text : '')))) : el('p', { class: 'muted small', text: 'Aucune erreur Xid.' }));
}
async function installSmart() {
  try { const d = await api('/api/action', { json: { action: 'install-smart' } }); followJob(d.job); } catch (e) { fail(e.message); }
}
$('#hw-refresh').addEventListener('click', () => loadHardware(true));

/* ------------------------------------------------ journal d'audit */
let auTimer = null;
const auQuery = () => { const p = new URLSearchParams(); for (const [k, id] of [['q', '#au-q'], ['user', '#au-user'], ['status', '#au-status']]) if ($(id).value) p.set(k, $(id).value); return p.toString(); };
async function loadAudit() {
  let a;
  try { a = await api('/api/audit?' + auQuery()); } catch (e) { $('#au-table').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  const sel = $('#au-user'), cur = sel.value;
  if (w_active() !== sel) { sel.replaceChildren(el('option', { value: '', text: 'Tous' }), ...a.users.map((u) => el('option', { value: u, text: u }))); sel.value = a.users.includes(cur) ? cur : ''; }
  $('#au-count').textContent = a.total + ' action(s)' + (a.total > a.entries.length ? ', ' + a.entries.length + ' affichées' : '');
  $('#au-table').replaceChildren(a.entries.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Date', 'Utilisateur', 'Action', 'Détail', 'Adresse', 'Résultat'].map((c) => el('th', { text: c })))),
    el('tbody', {}, ...a.entries.map((e) => el('tr', {}, el('td', { class: 'small nowrap', text: fmtDate(e.ts) }), el('td', { class: 'name', text: e.user }), el('td', { text: e.label }), el('td', { class: 'small', text: e.detail }),
      el('td', { class: 'small', text: e.ip }), el('td', {}, e.ok ? pill('ok', 'ok') : pill('refusé ' + e.status, 'err'))))))) : el('p', { class: 'muted small', text: 'Aucune action enregistrée.' }));
}
$('#au-q').addEventListener('input', () => { clearTimeout(auTimer); auTimer = setTimeout(loadAudit, 300); });
$('#au-user').addEventListener('change', loadAudit);
$('#au-status').addEventListener('change', loadAudit);
$('#au-export').addEventListener('click', () => downloadBlob('/api/audit/export?' + auQuery(), 'audit-ollamabuntu.csv').catch((e) => fail(e.message)));
$('#au-clear').addEventListener('click', async () => {
  if (!(await ask('Effacer tout le journal d\'audit ? Cette action sera elle-même consignée.', { ok: 'Effacer', danger: true }))) return;
  try { await api('/api/audit/clear', { json: {} }); loadAudit(); } catch (e) { fail(e.message); }
});

/* ------------------------------------------------ rapport hebdomadaire */
const rpForm = $('#rp-form');
$('#rp-hour').replaceChildren(...Array.from({ length: 24 }, (_, h) => el('option', { value: String(h), text: String(h).padStart(2, '0') + ' h' })));
async function loadReport() {
  let r;
  try { r = await api('/api/report'); } catch (e) { $('#rp-preview').textContent = e.message; return; }
  if (!rpForm.contains(w_active())) { rpForm.elements.enabled.checked = !!r.config.enabled; rpForm.elements.day.value = String(r.config.day); rpForm.elements.hour.value = String(r.config.hour); }
  $('#rp-warn').classList.toggle('hidden', r.smtp);
  $('#rp-preview').textContent = r.text;
  if (r.last_error) { $('#rp-msg').className = 'small error'; $('#rp-msg').textContent = 'Dernier envoi : ' + r.last_error; }
}
rpForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  try { await api('/api/report/config', { json: { enabled: rpForm.elements.enabled.checked, day: Number(rpForm.elements.day.value), hour: Number(rpForm.elements.hour.value) } }); $('#rp-msg').className = 'small okmsg'; $('#rp-msg').textContent = 'Enregistré.'; } catch (e) { $('#rp-msg').className = 'small error'; $('#rp-msg').textContent = e.message; }
});
$('#rp-test').addEventListener('click', async () => {
  $('#rp-msg').className = 'small'; $('#rp-msg').textContent = 'Envoi...';
  try { await api('/api/report/send', { json: {} }); $('#rp-msg').className = 'small okmsg'; $('#rp-msg').textContent = 'Rapport d\'essai envoyé.'; } catch (e) { $('#rp-msg').className = 'small error'; $('#rp-msg').textContent = e.message; }
});

/* ------------------------------------------------ espace disque des modèles */
const mdState = { unused: [] };
function mdUpdateButton() { $('#md-delete').disabled = !$$('#md-table input[type=checkbox]:checked').length; }
async function loadModelsDisk() {
  let d;
  try { d = await api('/api/models/disk?days=' + $('#md-days').value); } catch (e) { $('#md-table').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  mdState.unused = d.models.filter((m) => m.unused).map((m) => m.name);
  $('#md-summary').replaceChildren(el('div', { class: 'grid kpis' },
    ...[['Modèles installés', fmtBytes(d.total)], ['Récupérable', fmtBytes(d.reclaimable)], ['Disque libre', fmtBytes(d.disk.free) + ' / ' + fmtBytes(d.disk.total)]]
      .map(([l, v]) => el('div', { class: 'card' }, el('h2', { text: l }), el('div', { class: 'big', text: v })))));
  const ago = (m) => (m.last_used ? 'il y a ' + m.idle_days + ' j' : 'jamais vu depuis ' + d.journal_days + ' j');
  $('#md-table').replaceChildren(d.models.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, el('th', {}), ...['Modèle', 'Taille', 'Installé depuis', 'Dernière requête', 'État'].map((c, i) => el('th', { class: i === 1 || i === 2 ? 'num' : '', text: c })))),
    el('tbody', {}, ...d.models.map((m) => el('tr', {}, el('td', {}, el('input', { type: 'checkbox', value: m.name, 'aria-label': 'Sélectionner ' + m.name, disabled: m.loaded ? true : null, onchange: mdUpdateButton })),
      el('td', { class: 'name', text: m.name }), el('td', { class: 'num', text: fmtBytes(m.size) }), el('td', { class: 'num', text: m.installed_days == null ? '-' : m.installed_days + ' j' }),
      el('td', { class: 'small', text: ago(m) }), el('td', {}, m.loaded ? pill('en mémoire', 'info') : null, m.pinned ? pill('préchauffé ou réservé', 'info') : null, m.unused ? pill('inutilisé', 'warn') : null))))))
    : el('p', { class: 'muted small', text: 'Aucun modèle installé.' }));
  mdUpdateButton();
}
$('#md-days').addEventListener('change', loadModelsDisk);
$('#md-select').addEventListener('click', () => { for (const c of $$('#md-table input[type=checkbox]')) c.checked = mdState.unused.includes(c.value); mdUpdateButton(); });
$('#md-delete').addEventListener('click', async () => {
  const names = $$('#md-table input[type=checkbox]:checked').map((c) => c.value);
  if (!names.length || !(await ask('Supprimer définitivement ' + names.length + ' modèle(s) ?\n' + names.map((n) => '• ' + n).join('\n') + '\nLes télécharger de nouveau prendra du temps.', { ok: 'Supprimer', danger: true }))) return;
  let done = 0;
  for (const name of names) {
    $('#md-msg').className = 'small'; $('#md-msg').textContent = 'Suppression ' + (done + 1) + ' sur ' + names.length + '...';
    try { await api('/api/models/delete', { json: { name } }); done++; } catch (e) { $('#md-msg').className = 'small error'; $('#md-msg').textContent = name + ' : ' + e.message; break; }
  }
  if (done === names.length) { $('#md-msg').className = 'small okmsg'; $('#md-msg').textContent = done + ' modèle(s) supprimé(s).'; }
  loadModelsDisk();
});

/* ------------------------------------------------ clés d'API : plafonds de contexte et de sortie */
async function keyCaps(k) {
  const ctx = el('input', { type: 'number', min: '0', max: '2000000', value: String(k.max_ctx || 0), 'aria-label': 'Contexte maximal' });
  const out = el('input', { type: 'number', min: '0', max: '1000000', value: String(k.max_output || 0), 'aria-label': 'Réponse maximale' });
  const ok = await modal({ title: 'Plafonds de la clé « ' + k.name + ' »', message: 'Ramène les demandes qui dépassent ces valeurs au plafond (en-tête de réponse X-OllamaBuntu-Clamped). 0 = sans plafond. Le contexte n\'est plafonné que s\'il est demandé explicitement.',
    body: el('div', { class: 'row' }, el('label', {}, 'Contexte maximal (jetons) ', ctx), el('label', {}, 'Réponse maximale (jetons) ', out)), ok: 'Enregistrer' });
  if (!ok) return;
  try { await api('/api/publication/keys/update', { json: { id: k.id, max_ctx: Number(ctx.value) || 0, max_output: Number(out.value) || 0 } }); await loadPublication(); } catch (e) { fail(e.message); }
}
$('#bal-affinity').addEventListener('change', async () => {
  try { await api('/api/fleet/balance/strategy', { json: { affinity: $('#bal-affinity').checked } }); $('#bal-msg').className = 'small okmsg'; $('#bal-msg').textContent = 'Enregistré.'; } catch (e) { $('#bal-msg').className = 'small error'; $('#bal-msg').textContent = e.message; }
});

/* ------------------------------------------------ palette de commandes (Ctrl+K) */
const pal = { items: [], shown: [], sel: 0, prev: null };
const fold = (s) => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
function paletteCommands() {
  const cmds = [], go = (h) => () => { location.hash = h; };
  for (const a of $$('#nav a')) {
    if (a.classList.contains('hidden')) continue;
    const v = a.getAttribute('href').slice(1), name = a.textContent.trim();
    cmds.push({ label: name, hint: 'Écran', run: go('#' + v) });
    for (const k of TABS[v] || []) { const tab = $('#tab-' + v + '-' + k); if (tab) cmds.push({ label: name + ' › ' + tab.textContent.trim(), hint: 'Onglet', run: go('#' + v + '/' + k) }); }
  }
  cmds.push({ label: $('#who').textContent.trim() || 'Mon compte', hint: 'Compte', run: go('#account') });
  cmds.push({ label: 'Changer de thème', hint: 'Action', run: cycleTheme });
  cmds.push({ label: 'Changer de langue', hint: 'Action', run: switchLanguage });
  if (isAdmin()) cmds.push({ label: 'Actualiser le tableau de bord', hint: 'Action', run: () => { go('#dashboard')(); loadDashboard(); loadPerf(true); } });
  cmds.push({ label: 'Se déconnecter', hint: 'Action', run: () => $('#logout').click() });
  return cmds;
}
function paletteRender() {
  const words = fold($('#pal-q').value).split(/\s+/).filter(Boolean);
  pal.shown = pal.items.filter((c) => words.every((w) => fold(c.label + ' ' + c.hint).includes(w))).slice(0, 40);
  pal.sel = Math.min(pal.sel, Math.max(pal.shown.length - 1, 0));
  $('#pal-list').replaceChildren(...(pal.shown.length ? pal.shown.map((c, i) => el('li', { role: 'option', id: 'pal-' + i, class: i === pal.sel ? 'on' : '', 'aria-selected': i === pal.sel ? 'true' : 'false',
    onclick: () => paletteRun(i) }, el('span', { text: c.label }), el('small', { text: c.hint }))) : [el('li', { class: 'muted', text: 'Aucun résultat.' })]));
  $('#pal-q').setAttribute('aria-activedescendant', pal.shown.length ? 'pal-' + pal.sel : '');
  const on = $('#pal-list .on'); if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
}
function paletteOpen() {
  if ($('#app').classList.contains('hidden')) return;
  pal.prev = document.activeElement; pal.items = paletteCommands(); pal.sel = 0;
  $('#pal-q').value = ''; $('#palette').classList.remove('hidden'); paletteRender(); $('#pal-q').focus();
}
function paletteClose() { $('#palette').classList.add('hidden'); if (pal.prev && pal.prev.focus) pal.prev.focus(); }
function paletteRun(i) { const c = pal.shown[i]; if (!c) return; paletteClose(); c.run(); }
$('#pal-q').addEventListener('input', () => { pal.sel = 0; paletteRender(); });
$('#pal-q').addEventListener('keydown', (ev) => {
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); const n = pal.shown.length || 1; pal.sel = (pal.sel + (ev.key === 'ArrowDown' ? 1 : -1) + n) % n; paletteRender(); }
  else if (ev.key === 'Enter') { ev.preventDefault(); paletteRun(pal.sel); }
  else if (ev.key === 'Escape') { ev.preventDefault(); paletteClose(); }
});
$('#palette').addEventListener('click', (ev) => { if (ev.target === $('#palette')) paletteClose(); });
$('#palette-btn').addEventListener('click', paletteOpen);
document.addEventListener('keydown', (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key.toLowerCase() === 'k') {
    ev.preventDefault();
    if ($('#palette').classList.contains('hidden')) paletteOpen(); else paletteClose();
  }
});
