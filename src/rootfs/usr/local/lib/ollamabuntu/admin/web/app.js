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
    if (node.closest(NO_I18N)) return;
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

function showLogin() {
  $('#app').classList.add('hidden');
  $('#login').classList.remove('hidden');
  clearInterval(state.timer);
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
const VIEWS = ['dashboard', 'models', 'chat', 'gpu', 'system', 'security', 'fleet', 'webui', 'users', 'logs', 'account', 'about'];
const ADMIN_VIEWS = ['dashboard', 'gpu', 'system', 'webui', 'users', 'logs'];
function route() {
  let [v, sub] = location.hash.slice(1).split('/');
  if (!VIEWS.includes(v)) v = isAdmin() ? 'dashboard' : 'chat';
  if (ADMIN_VIEWS.includes(v) && !isAdmin()) v = 'chat';
  for (const name of VIEWS) $('#view-' + name).classList.toggle('hidden', name !== v);
  for (const a of $$('#nav a')) a.classList.toggle('active', a.getAttribute('href') === '#' + v);
  activateTab(v, sub);
  clearInterval(logsLive.timer); logsLive.timer = null; $('#log-live').setAttribute('aria-pressed', 'false');
  $('#job-card').classList.toggle('hidden', !(['gpu', 'system', 'webui'].includes(v) && jobs.current));
  clearInterval(state.timer); state.timer = null;
  if (v === 'dashboard') { loadDashboard(); loadPerf(); state.timer = setInterval(() => { loadDashboard(); loadPerf(); }, 10000); }
  if (v === 'models') { loadModels(); if (isAdmin()) { loadCustom(); loadContext(); } }
  if (v === 'chat') loadChatModels();
  if (v === 'gpu') loadGpu();
  if (v === 'system') loadSystem();
  if (v === 'webui') loadWebui();
  if (v === 'users') loadUsers();
  if (v === 'logs') { loadRequests(); loadReqSettings(); loadLogs(); state.timer = setInterval(() => { if ($('#req-live').checked && currentTab('logs') === 'requests') loadRequests(); }, 4000); }
  if (v === 'account') loadAccount();
  if (v === 'about') loadCredits();
  if (v === 'fleet') { loadFleet(); loadBalance(); state.timer = setInterval(() => { loadFleet(); loadBalance(); }, 10000); }
  if (v === 'security') { loadSecurity(); loadPolicy(); }
}
window.addEventListener('hashchange', route);

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
  let s;
  try { s = await api('/api/status'); } catch (e) { $('#dash-grid').replaceChildren(card('Erreur', el('p', { class: 'error', text: e.message }))); return; }
  state.status = s;
  setBanner(s.reboot_required);
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
function renderInstalled(models) {
  const box = $('#models-table');
  if (!models.length) { box.replaceChildren(el('p', { class: 'muted', text: 'Aucun modèle installé.' })); return; }
  const rich = models.some((m) => m.update);
  const tbody = el('tbody');
  for (const m of models) {
    const det = m.details || {};
    tbody.append(el('tr', {},
      el('td', {}, el('strong', { text: m.name })),
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
  if (isAdmin()) loadInsights(false);
}
async function loadInsights(refresh) {
  $('#capacity').replaceChildren(el('h2', { text: 'Ce serveur' }), el('p', { class: 'muted', text: 'Interrogation du registre Ollama...' }));
  let d;
  try { d = await api('/api/models/insights' + (refresh ? '?refresh=1' : '')); } catch (e) { $('#capacity').replaceChildren(el('h2', { text: 'Ce serveur' }), el('p', { class: 'error', text: e.message })); return; }
  const c = d.capacity;
  $('#capacity').replaceChildren(el('h2', { text: 'Ce serveur' }),
    el('div', { class: 'big', text: c.vram ? 'GPU : ' + fmtBytes(c.vram) + ' de mémoire vidéo' : 'Processeur uniquement' }),
    el('div', { class: 'muted small', text: (c.gpus.length ? c.gpus.join(' - ') + ' - ' : '') + 'mémoire système : ' + fmtBytes(c.ram_total) + ' (' + fmtBytes(c.ram_available) + ' disponibles) - Ollama ' + (d.ollama || '?') }),
    d.registry.ok ? null : el('p', { class: 'error small', text: 'Registre Ollama injoignable : ' + d.registry.errors[0] + ' (accès Internet, proxy ?)' }));
  renderInstalled(d.installed.sort((a, b) => a.name.localeCompare(b.name)));
  const groups = {};
  for (const m of d.catalog) (groups[m.category] = groups[m.category] || []).push(m);
  const avail = d.catalog.filter((m) => m.available).length;
  $('#catalog-note').textContent = avail + ' modèle(s) du catalogue disponible(s) sur le registre, triés du plus adapté au moins adapté à ce serveur. Catalogue modifiable : /etc/ollamabuntu/catalog.json';
  $('#catalog').replaceChildren(...Object.entries(groups).map(([cat, items]) => el('div', { class: 'catalog-group' }, el('h3', { text: cat }),
    el('div', { class: 'cat-grid' }, ...items.map((m) => el('div', { class: 'cat-item' },
      el('div', { class: 'name', text: m.name }),
      el('div', { class: 'chips' }, ...(m.caps || []).map((x) => el('span', { class: 'chip', text: x }))),
      el('p', { class: 'muted', text: m.description }),
      el('div', {}, m.available ? pill(m.fit.label, FIT_KIND[m.fit.level]) : pill('Indisponible sur le registre', ''),
        m.available ? document.createTextNode(' ' + fmtBytes(m.size) + (m.params ? ' - ' + m.params : '') + (m.quant ? ' ' + m.quant : '')) : null),
      el('div', { class: 'row' }, m.installed ? pill('Installé', 'ok') : (m.available && m.fit.level !== 'incompatible'
        ? el('button', { class: 'btn sm' + (['gpu', 'cpu'].includes(m.fit.level) ? ' primary' : ''), type: 'button', text: 'Télécharger', onclick: () => pullModel(m.name) }) : null))))))));
}
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
      el('div', { class: 'actions' }, ...r.quants.map((q) => el('button', { class: 'btn sm', type: 'button', text: q.quant + ' (' + fmtBytes(q.size) + ')', onclick: () => hfPull(repo, q.quant, r.uncensored) }))));
    box.scrollIntoView({ block: 'nearest' });
  } catch (e) { msg.className = 'small error'; msg.textContent = e.message; }
}
async function hfPull(repo, quant, uncensored) {
  const text = 'Télécharger « hf.co/' + repo + ':' + quant + ' » depuis Hugging Face ?' + (uncensored ? ' Ce modèle est une version sans censure.' : '');
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
    el('thead', {}, el('tr', {}, ...['Nom', 'Clé', 'Droits', 'Modèles', 'Dernière utilisation', 'État', ''].map((t) => el('th', { text: t })))),
    el('tbody', {}, ...p.keys.map((k) => el('tr', {}, el('td', { class: 'name', text: k.name }), el('td', { class: 'small', text: k.prefix + '…' }),
      el('td', { class: 'small', text: k.perms.map((x) => PERM_SHORT[x]).concat((k.deny || []).map((x) => DENY_SHORT[x])).join(', ') }), el('td', { class: 'small', text: k.models.length ? k.models.join(', ') : 'tous' }),
      el('td', { class: 'small', text: k.usage && k.usage.last ? fmtDate(k.usage.last) + ' (' + k.usage.count + ' requêtes)' : 'jamais' }),
      el('td', {}, k.enabled ? pill('active', 'ok') : pill('désactivée', 'warn')),
      el('td', { class: 'nowrap' }, el('button', { class: 'btn sm', type: 'button', text: k.enabled ? 'Désactiver' : 'Activer', onclick: () => keyToggle(k) }), ' ',
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
    const r = await api('/api/publication/keys/create', { json: { name: f.elements.name.value.trim(), perms: checkedValues(f, 'perm'), models: checkedValues(f, 'model'), deny: checkedValues(f, 'deny') } });
    f.elements.name.value = ''; $('#key-msg').textContent = '';
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
  try { jid = (await api('/api/action', { json: { action: opt.action || 'appliance-update', tag: opt.tag } })).job; } catch (e) { fail(e.message); return; }
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
  spread: 'Chaque requête va au serveur qui en traite le moins à cet instant ; à égalité, les serveurs se relaient. Un modèle est chargé sur chaque serveur à sa première utilisation, ce qui prend du temps pour un gros modèle. Une conversation peut changer de serveur d\'une réponse à l\'autre.',
  warm: 'Chaque requête va de préférence au serveur qui a déjà le modèle en mémoire, tant qu\'il n\'est pas occupé par plusieurs requêtes. Les autres serveurs ne servent qu\'en cas de forte demande ou de panne : avec un seul utilisateur, tout reste sur le même serveur.',
};
const balState = { multi: [] };
async function loadBalance() {
  let d;
  try { d = await api('/api/fleet/balance'); } catch (e) { $('#bal-msg').className = 'small error'; $('#bal-msg').textContent = e.message; return; }
  const sel = $('#bal-strategy');
  if (w_active() !== sel) sel.value = d.strategy;
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
const TAB_ORDER = { system: ['overview', 'appliance', 'updates', 'api', 'central'], models: ['installed', 'context', 'add', 'catalog', 'custom'], logs: ['requests', 'system'], fleet: ['fleet', 'balance', 'add'] };
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
  const prompt = (r) => el('td', { class: 'prompt', title: r.prompt || '' }, r.prompt ? r.prompt : el('span', { class: 'muted', text: '-' }));
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
async function loadRequests() {
  let d;
  try { d = await api('/api/requests?limit=100'); } catch (e) { $('#req-list').replaceChildren(el('p', { class: 'error', text: e.message })); return; }
  $('#req-summary').replaceChildren(d.summary.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'dense' },
    el('thead', {}, el('tr', {}, ...['Modèle', 'Requêtes', 'Erreurs', 'Jetons générés', 't/s moyen', '1er jeton moyen', 'Durée médiane', 'Durée p95'].map((c, i) => el('th', { class: i ? 'num' : '', text: c })))),
    el('tbody', {}, ...d.summary.map((s) => el('tr', {}, el('td', { class: 'name', text: s.model }), el('td', { class: 'num', text: s.count }), el('td', { class: 'num', text: s.errors }),
      el('td', { class: 'num', text: s.tok }), el('td', { class: 'num', text: s.tps ? DEC(s.tps) : '-' }), el('td', { class: 'num', text: fmtMs(s.ttft_ms) }),
      el('td', { class: 'num', text: fmtMs(s.p50_ms) }), el('td', { class: 'num', text: fmtMs(s.p95_ms) })))))) : el('p', { class: 'muted small', text: 'Aucune requête dans la dernière heure.' }));
  $('#req-list').replaceChildren(reqTable(d.requests, false));
}
async function loadDashRequests() {
  try {
    const d = await api('/api/requests?limit=6');
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
