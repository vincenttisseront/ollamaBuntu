// Laboratoire : comparateur de modèles et jeux de tests de non-régression (jsdom, FR et EN).
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/lab_ui_test.js
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
const MODELS = ['gemma4:12b', 'granite4.2:8b', 'llama3.2:3b'];
const row = (model, p, text, tps, extra) => Object.assign({ model, prompt: p, response: text, tokens: 100, tps, ttft_ms: 400, load_ms: 3000, total_ms: 2000, size: 5 * GB, vram_pct: 100, truncated: false }, extra);
const CMP = { t: now - 600, models: ['gemma4:12b', 'granite4.2:8b'], prompts: ['Explique le SSD.', 'Combien font 2+2 ?'], num_predict: 200,
  rows: [row('gemma4:12b', 0, 'Un SSD est rapide.', 50), row('gemma4:12b', 1, 'Quatre.', 52), row('granite4.2:8b', 0, 'Un SSD est une mémoire flash.', 80), row('granite4.2:8b', 1, '4', 78, { error: undefined })],
  summary: { reference: 'gemma4:12b', best: { tps: 'granite4.2:8b', ttft: 'gemma4:12b' }, models: [
    { model: 'gemma4:12b', tps: 52, ttft_ms: 400, load_ms: 3000, size: 8 * GB, vram_pct: 100, chars: 14, similarity: null, errors: 0 },
    { model: 'granite4.2:8b', tps: 80, ttft_ms: 900, load_ms: 2000, size: 5 * GB, vram_pct: 80, chars: 15, similarity: 42, errors: 0 }] } };
const SUITE = { id: 's1', name: 'Contrôle RH', model: 'gemma4:12b', auto: true, cases: [{ name: 'Capitale', prompt: 'Capitale ?', expect: { contains: ['Paris'] } }, { name: 'JSON', prompt: 'Donne du JSON', expect: { json: true } }] };
const RUNS = [
  { id: 'r2', suite: 's1', suite_name: 'Contrôle RH', model: 'gemma4:12b', t: now - 100, who: 'automatique', reason: 'le profil « Latence minimale »', summary: { total: 2, passed: 1, errors: 0, tps: 40, ttft_ms: 300 },
    diff: { regressions: ['JSON'], fixed: [], tps_pct: -20, previous: now - 5000, degraded: true },
    results: [{ name: 'Capitale', ok: true, why: [], response: 'Paris.', tps: 40 }, { name: 'JSON', ok: false, why: ['ce n\'est pas du JSON valide', '« Lyon » absent'], response: 'voici', tps: 40 }] },
  { id: 'r1', suite: 's1', suite_name: 'Contrôle RH', model: 'gemma4:12b', t: now - 5000, who: 'adm', reason: 'manuel', summary: { total: 2, passed: 2, errors: 0, tps: 50, ttft_ms: 300 }, diff: null,
    results: [{ name: 'Capitale', ok: true, why: [], response: 'Paris.', tps: 50 }, { name: 'JSON', ok: true, why: [], response: '{}', tps: 50 }] }];
const st = { suites: [JSON.parse(JSON.stringify(SUITE))], runs: RUNS, compare: CMP, cmp: { running: false, step: 0, total: 0, error: '' }, evalst: { running: false, step: 0, total: 0, error: '', model: '' }, saved: null };
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/lab') return json({ models: MODELS, suites: st.suites, runs: st.runs, compare: st.compare, cmp_state: Object.assign({ models: [], prompts: [] }, st.cmp), eval_state: Object.assign({ suite: '' }, st.evalst), default_prompts: ['Q1 par défaut', 'Q2 par défaut', 'Q3 par défaut'] });
  if (p === '/api/lab/suite') { st.saved = body.suite; if (!body.suite.id) st.suites.push(Object.assign({}, body.suite, { id: 's2' })); return json({ ok: true, id: 's2' }); }
  if (p === '/api/lab/suite/delete') { st.suites = st.suites.filter((x) => x.id !== body.id); return json({ ok: true }); }
  if (p === '/api/lab/run' || p === '/api/lab/compare') return json({ ok: true });
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
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !SAME.has(s) && !/Contrôle RH|Mon contrôle|Ollama est arrêté|Explique le SSD|Combien font/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v) && !SAME.has(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  st.suites = [JSON.parse(JSON.stringify(SUITE))]; st.runs = RUNS; st.compare = CMP; st.cmp = { running: false, step: 0, total: 0, error: '' }; st.evalst = { running: false, step: 0, total: 0, error: '', model: '' }; calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr);
  const T = (s) => $(s).textContent;
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  ok($$('#nav-more-list a').some((a) => a.getAttribute('href') === '#lab' && a.textContent === L('Laboratoire', 'Lab')), L('menu « Plus » : Laboratoire', 'EN: menu Lab'));
  w.location.hash = '#lab';
  ok(await until(() => $('#lab-m1').options.length === 3), L('liste des modèles installés dans les 3 listes', 'EN: model lists'));
  ok([...$$('#view-lab > .subtabs a')].map((a) => a.dataset.key).join() === 'compare,tests', L('onglets Comparateur et Tests', 'EN: tabs'));
  ok($('#lab-m1').value === 'gemma4:12b' && $('#lab-m2').value === 'granite4.2:8b' && $('#lab-m3').value === '' && $('#lab-prompts').value === 'Explique le SSD.\nCombien font 2+2 ?', L('préremplissage avec la dernière comparaison', 'EN: prefilled from last comparison'));
  // résultat de la dernière comparaison
  const tbl = T('#lab-cmp-result'); if (process.env.DBG) console.log(JSON.stringify(tbl.slice(0, 600)));
  ok(tbl.includes('52') && tbl.includes('42 %') && tbl.includes(L('le meilleur', 'best')) && tbl.includes(L('référence', 'reference')), L('tableau : débit, recouvrement, « le meilleur », « référence »', 'EN: summary table'));
  ok($$('#lab-cmp-result .lab-ans pre').map((p) => p.textContent).join('|') === 'Un SSD est rapide.|Un SSD est une mémoire flash.|Quatre.|4', L('réponses côte à côte, question par question', 'EN: side-by-side answers'));
  // lancer une comparaison
  $('#lab-m3').value = 'llama3.2:3b'; $('#lab-prompts').value = 'Une question\n\n  Deux  '; $('#lab-len').value = '320';
  $('#lab-cmp-run').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/lab/compare' && JSON.stringify(c[2]) === JSON.stringify({ models: MODELS.slice().sort((a, b) => 0).filter((x) => ['gemma4:12b', 'granite4.2:8b', 'llama3.2:3b'].includes(x)), prompts: ['Une question', 'Deux'], num_predict: 320 }))), L('comparaison lancée : 3 modèles, questions nettoyées, 320 jetons', 'EN: comparison started'));
  calls.length = 0; $('#lab-m2').value = 'gemma4:12b';
  $('#lab-cmp-run').click(); await sleep(150);
  ok(!calls.some((c) => c[1] === '/api/lab/compare') && T('#modal-text').includes(L('différents', 'different')), L('même modèle deux fois : refusé avec message', 'EN: duplicate model refused'));
  $('#modal-ok').click();
  st.cmp = { running: true, step: 2, total: 6, error: '', models: [], prompts: [] };
  $('#lab-refresh').click();
  ok(await until(() => T('#lab-cmp-state').includes(L('Comparaison en cours : 2 réponse(s) sur 6', 'Comparison in progress: 2 answer(s) of 6'))) && $('#lab-cmp-run').disabled, L('comparaison en cours : progression et bouton bloqué', 'EN: progress'));
  st.cmp = { running: false, step: 0, total: 0, error: 'Ollama est arrêté', models: [], prompts: [] }; $('#lab-refresh').click();
  ok(await until(() => T('#lab-cmp-state') === L('Ollama est arrêté', 'Ollama is stopped') || T('#lab-cmp-state') === 'Ollama est arrêté'), L('erreur de comparaison affichée', 'EN: error shown'));
  // tests de non-régression
  w.location.hash = '#lab/tests';
  ok(await until(() => $$('#lab-suites .card').length === 1), L('jeu de tests listé', 'EN: suite listed'));
  const card = T('#lab-suites');
  ok(card.includes('Contrôle RH') && card.includes(L('1 / 2 réussis', '1 / 2 passed')) && card.includes(L('1 cas dégradé(s)', '1 case(s) degraded')) && card.includes(L('automatique', 'automatic')), L('carte : dernier résultat, cas dégradé, mode automatique', 'EN: suite card'));
  if (process.env.DBG) console.log(JSON.stringify(T('#lab-runs')));
  ok($$('#lab-runs tbody tr').length === 2 && T('#lab-runs').includes(L('automatique après le profil « Latence minimale »', 'automatic after the profile “Minimum latency”')) && T('#lab-runs').includes(L('manuel (adm)', 'manual (adm)')), L('historique : déclencheurs (profil, manuel)', 'EN: run history'));
  $$('#lab-runs button').find((b) => b.textContent === L('Détails', 'Details')).click();
  ok(await until(() => $$('#modal-extra .lab-case').length === 2) && T('#modal-extra').includes(L('« Lyon » absent', '“Lyon” missing')) && T('#modal-extra').includes(L('ce n\'est pas du JSON valide', 'it is not valid JSON')) && T('#modal-extra').includes(L('échec', 'failed')), L('détails : cas en échec avec ses raisons', 'EN: run details'));
  if (lang === 'en') { const r = leftovers(w, '#modal'); ok(r.length === 0, 'EN: fenêtre de détails sans français' + (r.length ? ' ' + JSON.stringify(r) : '')); }
  $('#modal-ok').click(); await sleep(100);
  // lancer le jeu
  $$('#lab-suites button').find((b) => b.textContent === L('Lancer', 'Run')).click();
  ok(await until(() => calls.some((c) => c[1] === '/api/lab/run' && c[2].id === 's1' && c[2].model === 'gemma4:12b')), L('jeu lancé avec son modèle', 'EN: suite run'));
  st.evalst = { running: true, step: 1, total: 2, error: '', model: 'gemma4:12b' }; $('#lab-refresh').click();
  ok(await until(() => T('#lab-eval-state').includes(L('Tests en cours : cas 1 sur 2', 'Tests in progress: case 1 of 2'))), L('exécution en cours affichée', 'EN: eval progress'));
  st.evalst = { running: false, step: 0, total: 0, error: '', model: '' }; $('#lab-refresh').click(); await sleep(100);
  // nouveau jeu : exemple prêt à l'emploi, enregistrement
  $('#lab-suite-new').click();
  ok(await until(() => $$('#modal-extra .lab-case').length === 3), L('éditeur : 3 cas d\'exemple', 'EN: editor with 3 sample cases'));
  if (lang === 'en') { const r = leftovers(w, '#modal'); ok(r.length === 0, 'EN: éditeur sans français' + (r.length ? ' ' + JSON.stringify(r) : '')); }
  const auto = $$('#modal-extra input[type=checkbox]')[0]; auto.checked = true;
  $('#modal-ok').click();
  ok(await until(() => T('#modal-text').includes(L('Choisissez le modèle à tester', 'Choose the model to test'))), L('rejeu automatique sans modèle : refusé côté interface', 'EN: auto without model refused'));
  $('#modal-ok').click();
  ok(await until(() => $$('#modal-extra .lab-case').length === 3 && $$('#modal-extra input[type=checkbox]')[0].checked), L('l\'éditeur se rouvre avec la saisie conservée', 'EN: editor reopens with input kept'));
  $('#modal-extra select').value = 'llama3.2:3b';
  $$('#modal-extra .lab-case')[2].querySelector('button').click();
  $('#modal-extra input[type=text]').value = 'Mon contrôle';
  $('#modal-ok').click();
  ok(await until(() => st.saved && st.saved.name === 'Mon contrôle'), L('jeu enregistré', 'EN: saved'));
  ok(st.saved.model === 'llama3.2:3b' && st.saved.auto === true && st.saved.cases.length === 2 && JSON.stringify(st.saved.cases[0].expect) === JSON.stringify({ contains: ['Paris'], language: 'fr', max_chars: 400 }) && st.saved.cases[1].expect.json === true, L('contenu envoyé : modèle, automatique, 2 cas, critères', 'EN: payload'));
  ok(await until(() => $$('#lab-suites .card').length === 2), L('liste rafraîchie', 'EN: refreshed'));
  // modification d'un jeu existant
  $$('#lab-suites button').find((b) => b.textContent === L('Modifier', 'Edit')).click();
  ok(await until(() => $$('#modal-extra .lab-case').length === 2 && $('#modal-extra input[type=text]').value === 'Contrôle RH'), L('modification : valeurs actuelles reprises', 'EN: edit prefilled'));
  $('#modal-ok').click();
  ok(await until(() => st.saved && st.saved.id === 's1'), L('modification : identifiant conservé', 'EN: id kept'));
  // suppression
  $$('#lab-suites button').find((b) => b.textContent === L('Supprimer', 'Delete')).click();
  await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/lab/suite/delete' && c[2].id === 's1')), L('suppression confirmée', 'EN: deleted'));
  if (lang === 'en') {
    await sleep(300);
    const r = [...new Set([...leftovers(w, '#view-lab')])];
    ok(r.length === 0, 'EN: aucun texte français dans le Laboratoire' + (r.length ? ' ' + JSON.stringify(r.slice(0, 10)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
