// Mise à jour des modèles avec retour arrière (Modèles > Mises à jour) : jsdom, FR et EN.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/modelupdate_ui_test.js
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
const now = Math.floor(Date.now() / 1000);
const H = (t, model, status, detail, extra) => Object.assign({ t, model, status, who: 'automatique', reason: 'planifiée', detail }, extra);
const st = { running: false, cfg: { enabled: true, days: [6], start: '03:00', window: 180, scope: 'all', suite: 's1', keep_days: 7, drop_pct: 30 }, saved: null };
const doc = () => ({ config: st.cfg, history: [H(now - 100, 'gemma4:12b', 'rolled_back', 'débit en baisse de 75 %', { tps_before: 60, tps_after: 15 }), H(now - 5000, 'llama3.2:3b', 'updated', 'nouvelle version conservée ; l\'ancienne reste disponible 7 jour(s)'), H(now - 9000, 'granite4.2:8b', 'unchanged', 'déjà à jour'), H(now - 9500, 'x:1b', 'failed', 'téléchargement : connexion refusée')],
  prev: { 'llama3.2:3b': { prev: 'ob-prev/llama3.2:3b', t: now - 5000, from: 'a', to: 'b' } }, state: { running: st.running, model: 'gemma4:12b', step: 'téléchargement', done: 0, total: 2, error: '' },
  suites: [{ id: 's1', name: 'Contrôle RH' }], models: ['gemma4:12b', 'granite4.2:8b', 'llama3.2:3b'] });
const CHECK = [{ name: 'gemma4:12b', size: 8 * GB, update: { state: 'maj', label: 'Mise à jour disponible (2.1 Go à télécharger)' } }, { name: 'granite4.2:8b', size: 5 * GB, update: { state: 'a_jour', label: 'À jour' } },
  { name: 'llama3.2:3b', size: 2 * GB, update: { state: 'a_jour', label: 'À jour' } }];
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/mu') return json(doc());
  if (p === '/api/mu/check') return json({ models: CHECK });
  if (p === '/api/mu/config') { st.saved = body.config; st.cfg = body.config; return json({ ok: true }); }
  if (p === '/api/mu/run' || p === '/api/mu/rollback') return json({ ok: true });
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
  w.eval(js);
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|cas|jeu|jeux|modèle|modèles)\b|[éèêëàâùûîïôç]/i;
const SAME = new Set(['Ollama', 'GPU', 'gemma4:12b', 'granite4.2:8b', 'llama3.2:3b']);
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style, textarea')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !SAME.has(s) && !/Contrôle RH|connexion refusée/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v) && !SAME.has(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  st.running = false; st.cfg = { enabled: true, days: [6], start: '03:00', window: 180, scope: 'all', suite: 's1', keep_days: 7, drop_pct: 30 }; st.saved = null; calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#models/updates';
  ok(await until(() => $$('#mu-days input').length === 7), L('onglet « Mises à jour » chargé', 'EN: updates tab loaded'));
  ok([...$$('#view-models > .subtabs a')].map((a) => a.dataset.key).join().includes('tuning,updates,disk'), L('onglet placé avant « Espace disque »', 'EN: tab order'));
  const f = $('#mu-form').elements;
  ok(f.enabled.checked && f.start.value === '03:00' && f.window.value === '180' && f.drop_pct.value === '30' && f.keep_days.value === '7' && f.suite.value === 's1' && $$('#mu-days input:checked').map((i) => i.value).join() === '6', L('formulaire rempli avec la configuration', 'EN: form prefilled'));
  ok([...f.suite.options].map((o) => o.text).join('|') === L('Test rapide seulement|Contrôle RH', 'Quick test only|Contrôle RH'), L('liste des jeux de tests de validation', 'EN: suites list'));
  const hist = T('#mu-history');
  ok($$('#mu-history tbody tr').length === 4 && hist.includes(L('ancienne version rétablie', 'previous version restored')) && hist.includes(L('débit 60 → 15 jetons/s', 'throughput 60 → 15 tokens/s')) && hist.includes(L('mise à jour faite', 'update done')) && hist.includes(L('échec', 'failed')), L('historique : retour automatique, mise à jour, échec', 'EN: history'));
  // enregistrement
  f.scope.value = 'some'; f.scope.dispatchEvent(new w.Event('change'));
  ok(!$('#mu-scope').classList.contains('hidden') && $$('#mu-scope input').length === 3, L('« seulement ceux que je coche » : liste des modèles', 'EN: scope list'));
  $$('#mu-scope input')[1].checked = true; $$('#mu-days input')[5].checked = true; f.start.value = '23:30'; f.window.value = '360'; f.suite.value = ''; f.enabled.checked = false;
  $('#mu-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => st.saved), L('configuration envoyée', 'EN: config sent'));
  ok(JSON.stringify(st.saved) === JSON.stringify({ enabled: false, days: [5, 6], start: '23:30', window: 360, scope: ['granite4.2:8b'], suite: '', keep_days: 7, drop_pct: 30 }), L('contenu : jours, heure, fenêtre, modèles cochés, sans jeu de tests', 'EN: payload'));
  ok(await until(() => T('#mu-msg') === L('Enregistré.', 'Saved.')), L('confirmation « Enregistré. »', 'EN: saved message'));
  // vérification et mise à jour
  ok(T('#mu-models').includes(L('Vérifier maintenant', 'Check now')), L('invite à vérifier', 'EN: check prompt'));
  $('#mu-check').click();
  ok(await until(() => $$('#mu-models tbody tr').length === 3), L('tableau des modèles après vérification', 'EN: check table'));
  const boxes = $$('#mu-models input[type=checkbox]');
  ok(!boxes[0].disabled && boxes[1].disabled && boxes[2].disabled && $('#mu-run').disabled, L('seul le modèle à mettre à jour est cochable ; bouton bloqué sans sélection', 'EN: only updatable selectable'));
  ok(T('#mu-models').includes(L('ancienne version gardée jusqu\'au', 'previous version kept until')), L('copie de sécurité signalée', 'EN: kept copy'));
  boxes[0].checked = true; boxes[0].dispatchEvent(new w.Event('change'));
  ok(!$('#mu-run').disabled, L('sélection : bouton actif', 'EN: run enabled'));
  $('#mu-run').click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal-text').includes('gemma4:12b'), L('confirmation avant de lancer', 'EN: confirmation'));
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/mu/run' && JSON.stringify(c[2].models) === '["gemma4:12b"]')), L('mise à jour lancée pour le modèle coché', 'EN: run sent'));
  // retour arrière
  $$('#mu-models button').find((b) => b.textContent === L('Revenir à l\'ancienne version', 'Go back to the previous version')).click();
  await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/mu/rollback' && c[2].model === 'llama3.2:3b')), L('retour à l\'ancienne version demandé', 'EN: rollback sent'));
  // en cours
  st.running = true; w.location.hash = '#models/installed'; await sleep(50); w.location.hash = '#models/updates';
  ok(await until(() => T('#mu-state').includes(L('Mise à jour en cours : gemma4:12b (téléchargement), 0 sur 2', 'Update in progress: gemma4:12b (download), 0 of 2'))), L('progression affichée', 'EN: progress'));
  st.running = false;
  if (lang === 'en') {
    const r = [...new Set(leftovers(w, '#view-models'))].filter((x) => !/^Mettre à jour|^Avant chaque/.test(x) || true);
    ok(r.length === 0, 'EN: aucun texte français dans l\'onglet Mises à jour' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
