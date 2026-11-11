// File d'attente avec priorités (Serveurs > File d'attente, priorité d'une clé) : jsdom, FR et EN.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/queue_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', (e) => { if (process.env.DBG) console.log('REJ', e && e.stack); });
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const calls = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
const st = { settings: { max_active: 4, max_queue: 20 }, waiting: [], live: true };
const doc = () => ({ settings: st.settings, active: 3, parallel: 2, live: st.live, keys: [],
  waits: { n: 7, avg: 12.4, max: 95, by_prio: { 1: { n: 2, avg: 1.5 }, 3: { n: 5, avg: 40 } } }, waiting: st.waiting });
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/queue') return json(doc());
  if (p === '/api/queue/config') { st.settings = { max_active: body.max_active, max_queue: body.max_queue }; return json({ ok: true, settings: st.settings }); }
  if (p === '/api/publication/keys/create') return json({ ok: true, token: 'ob_secret', key: { name: body.name } });
  if (p === '/api/publication/keys/update') return json({ ok: true });
  if (p === '/api/fleet/balance') return json({ strategy: 'spread', affinity: true, rescued: { count: 0, lost: 0 }, local: { models: 1, served: 0, last: null, failures: 0 }, servers: [], models: [], active: false });
  if (p === '/api/fleet') return json({ servers: [] });
  if (p === '/api/status') return json({ version: 'v', hostname: 'srv', os: 'Ubuntu', kernel: 'k', uptime: 10, boot_time: 1, ips: [], cpu: { model: 'x', cores: 1, load: [0, 0, 0], usage: 0 },
    memory: { total: 1, available: 1 }, disk: { total: 1, used: 0, free: 1, models: 0 }, gpu: { devices: [], compute: [], reboot_required: false }, gpu_live: [],
    ollama: { version: '0.1', service: 'active', exposed: false, running: [], publication: {} }, reboot_required: false, update_available: null, offload: [], alerts: [] });
  return json({});
}
const EN = JSON.parse(fs.readFileSync(path.join(WEB, 'i18n', 'en.json'), 'utf8'));
function make(lang) {
  const dom = new JSDOM(html, { url: 'https://srv/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  if (lang) w.localStorage.setItem('ob-lang', lang);
  w.fetch = async (p, o) => (p === '/i18n/en.json' ? json(EN) : fakeFetch(p, o));
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {};
  w.eval(js + '\nwindow.__t = { keyLimits, keyCaps };');
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|requête|requêtes|priorité|attente|file)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style, textarea')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(Direction|Fond|Batch|llama3\.2:3b)/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  st.settings = { max_active: 4, max_queue: 20 }; st.live = true; calls.length = 0;
  st.waiting = [{ who: 'Direction', model: 'llama3.2:3b', prio: 1, eff: 1, waited: 3.2 }, { who: 'Fond', model: 'llama3.2:3b', prio: 3, eff: 2, waited: 130 }, { who: 'Batch', model: 'llama3.2:3b', prio: 3, eff: 3, waited: 20 }];
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#fleet/queue';
  ok(await until(() => $$('#queue-list tbody tr').length === 3), L('onglet « File d\'attente » chargé', 'EN: queue tab loaded'));
  ok([...$$('#view-fleet > .subtabs a')].map((a) => a.dataset.key).join() === 'fleet,balance,queue,power,rules,add', L('onglet placé après « Répartition de charge »', 'EN: tab order'));
  const rows = $$('#queue-list tbody tr').map((r) => [...r.children].map((c) => c.textContent.trim()));
  ok(rows[0][1] === 'Direction' && rows[1][1] === 'Fond' && rows[2][1] === 'Batch' && rows[0][0] === '1' && rows[2][0] === '3', L('file affichée dans l\'ordre reçu du routeur, avec le numéro de passage', 'EN: order kept'));
  ok(rows[0][3].startsWith(L('haute', 'high')) && rows[2][3].startsWith(L('basse', 'low')), L('priorité de chaque requête', 'EN: priority'));
  ok(rows[1][3].includes(L('monte à normale', 'rising to normal')) && !rows[2][3].includes(L('monte', 'rising')), L('une requête qui a vieilli est signalée « monte à normale »', 'EN: ageing hint'));
  ok(rows[0][4] === L('3,2 s', '3.2 s') && rows[1][4] === L('2 min', '2 min'), L('durées d\'attente lisibles (3,2 s ; 2 min)', 'EN: waits'));
  const s = T('#queue-state');
  ok(s.includes(L('En cours :', 'Running:')) && s.includes('3 / 4') && s.includes(L('En attente :', 'Waiting:')) && s.includes(L('7 requête(s) ont attendu', '7 request(s) had to wait')), L('état : 3 en cours sur 4, 3 en attente, statistiques de la dernière heure', 'EN: state'));
  ok(s.includes(L('priorité haute : 1,5 s en moyenne', 'high priority: 1.5 s on average')) && s.includes(L('priorité basse : 40 s en moyenne', 'low priority: 40 s on average')), L('attente moyenne par priorité', 'EN: per priority'));
  ok(T('#queue-hint').includes(L('Ollama traite déjà 2 requête(s) en parallèle', 'Ollama already processes 2 request(s) in parallel')) && T('#queue-hint').includes('4 ' + L('à', 'to') + ' 8'), L('suggestion de plafond d\'après le parallélisme d\'Ollama', 'EN: hint'));
  const f = $('#queue-form').elements;
  ok(f.max_active.value === '4' && f.max_queue.value === '20', L('formulaire rempli avec les réglages', 'EN: form prefilled'));
  f.max_active.value = '6'; f.max_queue.value = '0';
  $('#queue-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/queue/config' && c[2].max_active === 6 && c[2].max_queue === 0)), L('réglages envoyés', 'EN: settings sent'));
  ok(await until(() => T('#queue-msg') === L('Enregistré.', 'Saved.')), L('confirmation « Enregistré. »', 'EN: saved'));
  st.waiting = []; $('#queue-refresh').click();
  ok(await until(() => T('#queue-list').includes(L('Rien n\'attend', 'Nothing is waiting'))), L('file vide : message dédié', 'EN: empty'));
  st.live = false; $('#queue-refresh').click();
  ok(await until(() => T('#queue-list').includes(L('Aucune donnée du routeur', 'No data from the router'))), L('routeur muet : on ne prétend pas que la file est vide', 'EN: no data'));
  // priorité d'une clé
  const sel = $('#key-form').elements.priority;
  ok(sel.value === '2' && [...sel.options].map((o) => o.text).join('|') === L('Haute (passe en premier)|Normale|Basse (traitements de fond)', 'High (goes first)|Normal|Low (background jobs)'), L('création de clé : priorité normale par défaut', 'EN: new key priority'));
  $('#key-form').elements.name.value = 'Fond'; sel.value = '3';
  $('#key-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/publication/keys/create' && c[2].priority === 3 && c[2].name === 'Fond')), L('priorité envoyée à la création de la clé', 'EN: priority on create'));
  await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(w.__t.keyLimits({ priority: 1 }).includes('priorité haute') && !w.__t.keyLimits({ priority: 2, max_concurrent: 1 }).join().includes('priorité') && w.__t.keyLimits({ priority: 3 }).includes('priorité basse'),
    L('colonne des limites : la priorité n\'apparaît que si elle n\'est pas « normale »', 'EN: limits column'));
  const pr = w.__t.keyCaps({ id: 'k1', name: 'RH', priority: 3, max_ctx: 0, max_output: 0 });
  ok(await until(() => !$('#modal').classList.contains('hidden') && $('#modal select')), L('fenêtre « Plafonds » avec la priorité', 'EN: caps modal'));
  ok($('#modal select').value === '3', L('priorité actuelle présélectionnée', 'EN: current priority selected'));
  $('#modal select').value = '1'; $('#modal-ok').click(); await pr;
  ok(calls.some((c) => c[1] === '/api/publication/keys/update' && c[2].id === 'k1' && c[2].priority === 1), L('nouvelle priorité enregistrée', 'EN: priority saved'));
  if (lang === 'en') {
    const r = [...new Set(leftovers(w, '#view-fleet [data-panel=queue], #view-fleet .panel[data-key=queue]'))];
    ok(r.length === 0, 'EN: aucun texte français dans l\'onglet File d\'attente' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
    ok(!/[éèà]/.test($('#key-form').elements.priority.parentElement.textContent), 'EN: formulaire de clé sans français');
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
