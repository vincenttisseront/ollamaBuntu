// Parc : modèles de remplacement choisis dans des listes déroulantes (modèles de cette console → modèles détectés sur le serveur), avec proposition automatique.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/modelmap_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', (e) => { if (process.env.DBG) console.log('REJ', e && e.stack); });
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const GB = 1024 ** 3, calls = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
let srv = { id: 's1', name: 'vmesx10', state: 'en ligne', route: true, model_map: {}, data: { gpu_live: [], cpu: { usage: 10 }, memory: { total: 8 * GB, available: 4 * GB }, disk: { used: 1, total: 10 }, ollama: { running: [], service: 'active' }, model_tags: [{ name: 'granite4.2:8b', size: 5 * GB }, { name: 'llama3.2:1b', size: 1.3 * GB }] } };
const LOCAL = [{ name: 'gemma4:12b', size: 8 * GB }, { name: 'llama3.2:3b', size: 2 * GB }, { name: 'granite4.2:8b', size: 5 * GB }, { name: 'nomic-embed-text', size: 0.3 * GB }];
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/fleet/servers') return json({ servers: [srv], actions: [], sync_kinds: [], local_models: LOCAL.map((x) => x.name), local_details: LOCAL });
  if (p === '/api/fleet/servers/modelmap') { srv = Object.assign({}, srv, { model_map: body.map }); return json({ ok: true }); }
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
  w.addEventListener('error', (e) => console.log('ERR', e.message)); w.eval(js);
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune)\b|[éèêëàâùûîïôç]/i;
async function scenario(lang) {
  srv = Object.assign({}, srv, { model_map: {} }); calls.length = 0;
  const w = make(lang);
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  const L = (fr, en) => (lang === 'en' ? en : fr);
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: console shown'));
  w.location.hash = '#fleet';
  const btn = () => $$('#view-fleet button').find((b) => b.textContent === L('Modèles de remplacement...', 'Replacement models...'));
  if (process.env.DBG) { await sleep(800); console.log('DBG', calls.map((c) => c[1]).join(' '), '|', $('#fleet-summary').textContent, '|', $$('#view-fleet button').map((b) => b.textContent).join(';')); }
  ok(await until(btn), L('bouton « Modèles de remplacement »', 'EN: replacement button'));
  btn().click();
  ok(await until(() => $$('#modal-extra .map-row').length === 2), L('proposition automatique : une ligne par modèle absent (gemma4:12b, llama3.2:3b ; l\'embedding n\'a pas d\'équivalent)', 'EN: two proposed rows'));
  const rows = () => $$('#modal-extra .map-row').map((r) => [...r.querySelectorAll('select')].map((s) => s.value));
  ok(JSON.stringify(rows()) === JSON.stringify([['gemma4:12b', 'granite4.2:8b'], ['llama3.2:3b', 'llama3.2:1b']]), L('propositions : gemma → plus gros modèle du serveur qui tient en taille, llama3.2:3b → même famille llama3.2:1b', 'EN: proposals') + ' ' + JSON.stringify(rows()));
  const first = $$('#modal-extra .map-row')[0].querySelectorAll('select');
  ok([...first[0].options].map((o) => o.value).join() === '*,gemma4:12b,llama3.2:3b,granite4.2:8b,nomic-embed-text' && [...first[1].options].map((o) => o.value).join() === 'granite4.2:8b,llama3.2:1b', L('listes : modèles de cette console / modèles détectés sur le serveur', 'EN: dropdown contents'));
  ok(first[0].options[0].textContent === L('Tous les modèles absents du serveur', 'All models missing on the server') && first[1].options[0].textContent.includes('GB') || first[1].options[0].textContent.includes('Go'), L('option « tous » et tailles affichées', 'EN: wildcard option and sizes'));
  if (lang === 'en') ok(first[0].getAttribute('aria-label') === 'Requested model' && $('#modal-extra').textContent.includes('Automatic proposal for 2 model(s)') && $$('#modal-extra button').some((b) => b.textContent === 'Add a pairing'), 'EN: textes traduits');
  else ok($('#modal-extra').textContent.includes('Proposition automatique pour 2 modèle(s)') && !$('#modal-extra textarea'), 'plus de zone de texte libre ; message de proposition');
  // retirer la 2e ligne, passer la 1re en « tous les modèles absents »
  $$('#modal-extra .map-row')[1].querySelector('button').click();
  first[0].value = '*';
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/fleet/servers/modelmap' && c[2].id === 's1' && JSON.stringify(c[2].map) === JSON.stringify({ '*': 'granite4.2:8b' }))), L('enregistré : { "*": "granite4.2:8b" }', 'EN: saved'));
  // réouverture : l'association existante est préremplie, plus de proposition (le joker couvre tout)
  ok(await until(() => btn()), 'liste rechargée'); await sleep(100);
  btn().click();
  ok(await until(() => $$('#modal-extra .map-row').length === 1), L('réouverture : une seule ligne (existante)', 'EN: reopen one row'));
  ok(JSON.stringify(rows()) === JSON.stringify([['*', 'granite4.2:8b']]), L('association existante préremplie', 'EN: prefilled'));
  // auto-remplacement refusé
  const r = $$('#modal-extra .map-row')[0].querySelectorAll('select');
  r[0].value = 'granite4.2:8b'; r[1].value = 'granite4.2:8b';
  calls.length = 0; $('#modal-ok').click();
  await sleep(300);
  ok(!calls.some((c) => c[1] === '/api/fleet/servers/modelmap'), L('un modèle ne peut pas se remplacer lui-même : rien n\'est envoyé', 'EN: self replacement blocked'));
  const err = $$('#toast, .toast, #notify, [role=alert], #modal').map((e) => e.textContent).join(' ');
  ok(err.includes(L('ne peut pas se remplacer lui-même', 'cannot replace itself')), L('message d\'erreur affiché', 'EN: error shown'));
  if (lang === 'en') {
    const rest = [];
    for (const nd of w.document.querySelectorAll('#modal *')) for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.trim(); if (s && FR_WORDS.test(s) && !/granite|llama|gemma/.test(s)) rest.push(s); }
    ok(rest.length === 0, 'EN: aucun texte français dans la fenêtre' + (rest.length ? ' ' + JSON.stringify(rest) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
