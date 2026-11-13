// Accélération (Performance > Caches, Préchauffage prédictif, Mesure continue, Cache de contexte, Parallélisme, Journal) : jsdom, FR et EN.
// Usage : NODE_PATH=... node tests/unit/accel_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', (e) => { if (process.env.DBG) console.log('REJ', e && e.stack); });
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const GIB = 1073741824;
const now = Math.floor(Date.now() / 1000);
const calls = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
const st = {};
function reset() {
  Object.assign(st, { suites: 1, job: { running: false, model: '', kv: '', step: '', log: [], error: '', result: '' }, bench: false, saveError: '', checks: null });
}
const zeroStat = { entries: 0, bytes: 0, hits: 0, misses: 0, stores: 0, evicted: 0 };
const accel = () => ({
  config: { predict: { enabled: true, lead: 10, max_models: 2, min_days: 3 }, bench_auto: { enabled: true, at: '03:30', models: ['gemma4:12b'], tolerance: 15, recalibrate: true },
    parallel: { mode: 'suggest' }, kv: { mode: 'suggest' }, events: [], last: {},
    regress: { 'gemma4:12b': { t: now - 600, text: 'gemma4:12b : 38 jetons/s au lieu de 50 d\'habitude (−24 %)', pct: -24, hints: ['La carte graphique est à 86 °C : bridage thermique probable (poussière, ventilation, boîtier).', 'Le noyau a changé depuis la mesure précédente (6.8.0-1 -> 6.8.0-2).'] } } },
  cache: { config: { responses: true, embeddings: false, ttl: 3600, max_mb: 64, max_entry_kb: 512, purged: 0 },
    stats: { t: now, responses: { entries: 12, bytes: 3 * 1048576, hits: 30, misses: 10, stores: 12, evicted: 1 }, embeddings: zeroStat, saved_ms: 125000, saved_tokens: 4200,
      prefixes: { distinct: 2, requests: 14, reused: 12, models: [{ model: 'gemma4:12b', distinct: 2, requests: 14, frequent: 2 }] } } },
  parallel: { parallel: 1, profile: { requests: 80, peak: 3, overlap_pct: 40, solo_ttft: 300, busy_ttft: 900 }, model: 'gemma4:12b', headroom: 4 * GIB, slot: GIB,
    advice: { to: 2, why: 'overlap', text: '40 % des demandes se chevauchent (jusqu\'à 3 à la fois) ; le délai avant le premier jeton est de 900 ms quand elles se chevauchent contre 300 ms seules : passer de 1 à 2 requêtes en parallèle.' },
    notes: ['gemma4:12b : 2 débuts d\'invite distincts reviennent souvent pour 1 emplacement(s) : chaque emplacement garde le cache d\'un seul début, les autres se chassent mutuellement et sont recalculés.'] },
  kv: { current: 'f16', suites: st.suites, job: st.job, items: [{ model: 'qwen3:30b-a3b', kv: 'q8_0', ctx: 8192, now_mode: 'cpu', tps_now: 6.2, tps_after: 52.7,
    text: 'qwen3:30b-a3b déborde sur le processeur avec le cache en f16 ; en q8_0 il tient en mémoire vidéo (contexte 8192) : vitesse estimée de 6.2 à 52.7 jetons/s.' }] },
  predict: { candidates: [{ model: 'llama3.2:3b', hits: 5, days: 6, hour: 9 }], models_seen: 3, days: 12 },
  bench_auto: { models: ['gemma4:12b'], running: st.bench }, env: { OLLAMA_KV_CACHE_TYPE: '', OLLAMA_FLASH_ATTENTION: '1', OLLAMA_NUM_PARALLEL: '1' },
  events: [{ t: now - 100, who: 'prédiction', text: 'Modèle « llama3.2:3b » préchargé : habituellement demandé vers 9 h (5 jours sur 6)' },
    { t: now - 900, who: 'automatique', text: 'Requêtes en parallèle : 1 -> 2 (Ollama redémarré)' }] });
const perfDoc = () => ({ env: {}, current: 'equilibre', profiles: [], guard: { mode: 'suggest', drop_pct: 50 }, events: [], alert: null, warmup: { boot: [], times: [], log: [] },
  bench: { running: false, model: '', step: 0, runs: 2, error: '', history: [] },
  checks: st.checks || [
    { id: 'gpu_power:0000:03:00.0', state: 'info', fix: 'amd_power', text: 'AMD Radeon RX 7800 XT gère ses fréquences automatiquement : elle met un instant à monter en puissance au premier jeton après une pause. « high » les fixe au maximum (plus de bruit et de consommation au repos).' },
    { id: 'rebar', state: 'info', fix: '', text: 'Resizable BAR semble désactivé (fenêtre de 0.25 Go pour 16 Go de mémoire vidéo). À activer dans le BIOS (« Above 4G Decoding » puis « Resizable BAR ») : chargement des modèles et échanges avec la mémoire système plus rapides.' },
    { id: 'mem_channels', state: 'warn', fix: '', text: 'Une seule barrette de mémoire : canal simple, soit environ la moitié du débit d\'un double canal. C\'est ce débit qui limite un modèle débordé ou ses experts en mémoire système.' },
    { id: 'mem_speed', state: 'warn', fix: '', text: 'La mémoire tourne à 2133 MT/s alors que ses barrettes sont prévues pour 3200 MT/s : profil XMP / EXPO désactivé dans le BIOS. Le débit de la mémoire système en dépend directement.' },
    { id: 'pcie:0000:03:00.0', state: 'warn', fix: '', text: 'AMD Radeon RX 7800 XT est en PCIe x8 alors que x16 est possible : fente partagée, riser ou câble limitant. Le chargement des modèles et le débordement en pâtissent.' }] });
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/accel') return json(accel());
  if (p === '/api/perf') return json(perfDoc());
  if (p === '/api/models') return json({ models: [{ name: 'gemma4:12b' }, { name: 'llama3.2:3b' }, { name: 'qwen3:30b-a3b' }, { name: 'x-cloud' }] });
  if (p.startsWith('/api/accel/')) {
    if (st.saveError) return json({ error: st.saveError }, 400);
    if (p === '/api/accel/kv/apply') { st.job = { running: true, model: body.model, kv: body.kv, step: 'Référence avant changement : jeu « Base »', log: ['Référence avant changement : jeu « Base »'], error: '', result: '' }; return json({ ok: true }); }
    return json({ ok: true });
  }
  if (p === '/api/perf/fix') return json({ ok: true });
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
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|requête|requêtes|modèle|modèles|mémoire|moteur|carte)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  reset(); calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  const submit = (s) => $(s).dispatchEvent(new w.Event('submit', { cancelable: true }));
  const btn = (root, label) => [...root.querySelectorAll('button')].find((b) => b.textContent.trim() === label);
  const go = async (hash, cond) => { w.location.hash = hash; return until(cond); };
  const sent = (p, f = () => true) => calls.filter((c) => c[1] === p && c[0] === 'POST' && f(c[2]));
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  // --- onglets
  ok(await go('#perf/cache', () => $$('#ac-cache-stats table').length === 1), L('onglet « Caches » chargé', 'EN: caches tab loaded'));
  const keys = $$('#view-perf > .subtabs a').map((a) => a.dataset.key);
  ok(keys.join() === 'bench,profiles,warmup,predict,guard,autobench,kv,parallel,cache,tune,aclog', L('onglets d\'accélération à leur place', 'EN: tab order'));
  ok($('#view-perf > .subtabs a[data-key=autobench]').textContent.trim() === L('Mesure continue', 'Continuous measurement') && $('#view-perf > .subtabs a[data-key=kv]').textContent.trim() === L('Cache de contexte', 'Context cache') && $('#view-perf > .subtabs a[data-key=aclog]').textContent.trim() === L('Journal d\'accélération', 'Acceleration log'), L('libellés des onglets', 'EN: tab labels'));
  // --- caches
  const cf = $('#ac-cache-form').elements;
  ok(cf.responses.checked && !cf.embeddings.checked && cf.ttl.value === '3600' && cf.max_mb.value === '64' && cf.max_entry_kb.value === '512', L('réglages du cache préremplis', 'EN: cache fields prefilled'));
  const crow = $$('#ac-cache-stats tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(crow[0][0] === L('Réponses exactes', 'Exact responses') && crow[0][1] === '12' && crow[0][2] === '3 MB' || crow[0][2].includes('3') , L('ligne « réponses exactes »', 'EN: responses row'));
  ok(crow[0][3] === '30' && crow[0][4] === '10' && crow[0][5] === '75 %' && crow[0][6] === '1', L('servies, non trouvées, taux (30 sur 40 = 75 %), évincées', 'EN: hits, misses, rate'));
  ok(T('#ac-cache-stats').includes(L('2 min de génération et 4', '2 min of generation and 4')) && T('#ac-cache-stats').includes(L('jetons', 'tokens')), L('temps et jetons économisés', 'EN: saved time and tokens'));
  ok(T('#ac-cache-stats').includes(L('2 début(s) distinct(s) pour 14 demande(s) ; 12 demande(s) repartent', '2 distinct beginning(s) for 14 request(s); 12 request(s) start')) && T('#ac-cache-stats').includes(L('gemma4:12b : 2 début(s) distinct(s), 14 demande(s), 2 revenant souvent', 'gemma4:12b: 2 distinct beginning(s), 14 request(s), 2 frequently coming back')), L('débuts d\'invite : comptes et par modèle', 'EN: prefixes'));
  cf.ttl.value = '7200'; cf.embeddings.checked = true; calls.length = 0; submit('#ac-cache-form');
  ok(await until(() => sent('/api/accel/cache').length === 1), L('enregistrement envoyé', 'EN: save sent'));
  const cb = sent('/api/accel/cache')[0][2];
  ok(cb.responses === true && cb.embeddings === true && cb.ttl === 7200 && cb.max_mb === 64 && cb.max_entry_kb === 512, L('contenu du cache envoyé', 'EN: cache payload'));
  ok(await until(() => T('#ac-cache-msg') === L('Enregistré.', 'Saved.')), L('message de confirmation conservé après rechargement', 'EN: message kept after reload'));
  calls.length = 0; $('#ac-cache-purge').click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && sent('/api/accel/cache').length === 0, L('vider : confirmation d\'abord', 'EN: purge asks first'));
  $('#modal-ok').click();
  ok(await until(() => sent('/api/accel/cache', (b) => b.purge === true).length === 1), L('vidage envoyé', 'EN: purge sent'));
  st.saveError = 'valeur invalide : durée de conservation (secondes)'; calls.length = 0; submit('#ac-cache-form');
  ok(await until(() => T('#ac-cache-msg') === L('valeur invalide : durée de conservation (secondes)', 'invalid value: retention time (seconds)')) && $('#ac-cache-msg').classList.contains('error'), L('erreur du serveur affichée', 'EN: server error shown'));
  st.saveError = '';
  // --- préchauffage prédictif
  ok(await go('#perf/predict', () => $$('#ac-predict-now li').length === 1), L('onglet « Préchauffage prédictif » chargé', 'EN: predictive tab loaded'));
  const pf = $('#ac-predict-form').elements;
  ok(pf.enabled.checked && pf.lead.value === '10' && pf.max_models.value === '2' && pf.min_days.value === '3', L('réglages prédictifs préremplis', 'EN: predictive fields'));
  ok(T('#ac-predict-info').includes(L('3 modèle(s) sur 12 jour(s)', '3 model(s) over 12 day(s)')) && T('#ac-predict-now').includes('llama3.2:3b') && T('#ac-predict-now').includes(L('habituellement demandé vers 09 h (5 jour(s) sur 6)', 'usually requested around 09:00 (5 day(s) out of 6)')), L('historique et modèle attendu dans l\'heure', 'EN: history and predicted model'));
  pf.enabled.checked = false; pf.lead.value = '15'; calls.length = 0; submit('#ac-predict-form');
  ok(await until(() => sent('/api/accel/predict', (b) => b.enabled === false && b.lead === 15 && b.max_models === 2 && b.min_days === 3).length === 1), L('réglages prédictifs envoyés', 'EN: predictive payload'));
  // --- mesure continue
  ok(await go('#perf/autobench', () => $$('#ac-bench-models input').length === 3), L('onglet « Mesure continue » : modèles installés (hors cloud)', 'EN: continuous tab: installed models'));
  const bf = $('#ac-bench-form').elements;
  ok(bf.enabled.checked && bf.at.value === '03:30' && bf.tolerance.value === '15' && bf.recalibrate.checked && $$('#ac-bench-models input:checked').map((c) => c.value).join() === 'gemma4:12b', L('réglages de mesure préremplis, modèle coché', 'EN: measurement fields'));
  const rg = $('#ac-bench-state');
  ok(rg.textContent.includes(L('gemma4:12b : 38 jetons/s au lieu de 50 d\'habitude (−24 %)', 'gemma4:12b: 38 tokens/s instead of the usual 50 (−24 %)')) && rg.textContent.includes(L('bridage thermique probable', 'thermal throttling likely')) && rg.textContent.includes(L('Le noyau a changé', 'The kernel changed')), L('baisse de débit et causes probables', 'EN: drop and likely causes'));
  ok(rg.textContent.includes(L('Sera mesuré : gemma4:12b', 'Will be measured: gemma4:12b')), L('modèle qui sera mesuré', 'EN: model to be measured'));
  $$('#ac-bench-models input').find((c) => c.value === 'llama3.2:3b').checked = true; bf.at.value = '04:15'; calls.length = 0; submit('#ac-bench-form');
  ok(await until(() => sent('/api/accel/bench-auto', (b) => b.at === '04:15' && b.tolerance === 15 && b.recalibrate === true && b.enabled === true && b.models.join() === 'gemma4:12b,llama3.2:3b').length === 1), L('mesure : réglages et modèles envoyés', 'EN: measurement payload'));
  await until(() => T('#ac-bench-msg') === L('Enregistré.', 'Saved.'));
  calls.length = 0; $('#ac-bench-now').click();
  ok(await until(() => sent('/api/accel/bench-auto/run').length === 1) && await until(() => T('#ac-bench-msg').includes(L('Mesure lancée', 'Measurement started'))), L('mesure immédiate lancée', 'EN: immediate measurement'));
  // --- cache de contexte
  ok(await go('#perf/kv', () => $$('#ac-kv-body ul.items li').length === 1), L('onglet « Cache de contexte » chargé', 'EN: context cache tab'));
  ok(T('#ac-kv-body').includes(L('qwen3:30b-a3b déborde sur le processeur avec le cache en f16 ; en q8_0 il tient en mémoire vidéo (contexte 8192) : vitesse estimée de 6.2 à 52.7 jetons/s.', 'qwen3:30b-a3b spills over to the processor with an f16 cache; in q8_0 it fits in video memory (context 8192): estimated speed from 6.2 to 52.7 tokens/s.')) && T('#ac-kv-body').includes(L('1 jeu(x) de tests du Laboratoire serviront de contrôle', '1 Lab test suite(s) will serve as a check')), L('conseil de cache quantifié', 'EN: kv advice'));
  calls.length = 0; btn($('#ac-kv-body'), L('Appliquer et vérifier', 'Apply and verify')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes(L('rejoués avant et après', 'replayed before and after')) && sent('/api/accel/kv/apply').length === 0, L('confirmation : jeux de tests rejoués avant et après', 'EN: confirmation mentions the verification'));
  $('#modal-ok').click();
  ok(await until(() => sent('/api/accel/kv/apply').length === 1), L('application demandée', 'EN: apply requested'));
  const kb = sent('/api/accel/kv/apply')[0][2];
  ok(kb.model === 'qwen3:30b-a3b' && kb.kv === 'q8_0' && kb.force === false, L('contenu : modèle, type de cache, pas de contournement', 'EN: apply payload'));
  ok(await until(() => $('#ac-kv-body .pill.info') && T('#ac-kv-body').includes(L('Référence avant changement : jeu « Base »', 'Reference before the change: suite "Base"'))), L('tâche en cours : étape affichée', 'EN: running job shown'));
  ok(btn($('#ac-kv-body'), L('Appliquer et vérifier', 'Apply and verify')).disabled, L('bouton désactivé pendant la tâche', 'EN: button disabled while running'));
  st.job = { running: false, model: 'qwen3:30b-a3b', kv: 'q8_0', step: '', log: ['Passage du cache de contexte en q8_0 (Ollama redémarre)', 'Dégradation constatée : retour aux réglages précédents'], error: '', result: 'annule' };
  w.location.hash = '#perf/bench'; await sleep(50); w.location.hash = '#perf/kv';
  ok(await until(() => T('#ac-kv-body').includes(L('annulé : dégradation constatée', 'cancelled: degradation found')) && T('#ac-kv-body').includes(L('Dégradation constatée : retour aux réglages précédents', 'Degradation found: going back to the previous settings')) && T('#ac-kv-body').includes(L('Passage du cache de contexte en q8_0 (Ollama redémarre)', 'Switching the context cache to q8_0 (Ollama restarts)'))), L('résultat : annulé, journal traduit', 'EN: cancelled result and translated log'));
  st.suites = 0; st.job = { running: false, model: '', kv: '', step: '', log: [], error: '', result: '' };
  $('#ac-kv-mode').value = 'auto'; $('#ac-kv-mode').dispatchEvent(new w.Event('change'));
  ok(await until(() => sent('/api/accel/kv', (b) => b.mode === 'auto').length === 1), L('mode « automatique » enregistré', 'EN: auto mode saved'));
  // --- parallélisme
  ok(await go('#perf/parallel', () => !!$('#ac-par-body .card.inner')), L('onglet « Parallélisme » chargé', 'EN: parallelism tab'));
  ok(T('#ac-par-body').includes(L('1 requête(s) en parallèle', '1 request(s) in parallel')) && T('#ac-par-body').includes(L('Sur 24 h : 80 demande(s), jusqu\'à 3 à la fois, 40 % se chevauchent ; premier jeton après 300 ms seule, 900 ms en chevauchement.', 'Over 24 h: 80 request(s), up to 3 at a time, 40 % overlap; first token after 300 ms alone, 900 ms when overlapping.')), L('profil de charge', 'EN: load profile'));
  ok(T('#ac-par-body').includes(L('passer de 1 à 2 requêtes en parallèle', 'go from 1 to 2 parallel requests')) && T('#ac-par-body').includes(L('2 débuts d\'invite distincts reviennent souvent pour 1 emplacement(s)', '2 distinct prompt beginnings come back often for 1 slot(s)')), L('conseil et note sur les débuts d\'invite', 'EN: advice and prefix note'));
  calls.length = 0; btn($('#ac-par-body'), L('Passer à 2', 'Switch to 2')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes(L('Ollama redémarre', 'Ollama restarts')) && sent('/api/accel/parallel/apply').length === 0, L('confirmation avant de changer le parallélisme', 'EN: confirmation first'));
  $('#modal-ok').click();
  ok(await until(() => sent('/api/accel/parallel/apply', (b) => b.to === 2).length === 1), L('passage à 2 envoyé', 'EN: switch to 2 sent'));
  $('#ac-par-mode').value = 'auto'; $('#ac-par-mode').dispatchEvent(new w.Event('change'));
  ok(await until(() => sent('/api/accel/parallel', (b) => b.mode === 'auto').length === 1), L('mode « automatique » enregistré', 'EN: parallel auto mode saved'));
  // --- journal
  ok(await go('#perf/aclog', () => $$('#ac-events tbody tr').length === 2), L('onglet « Journal d\'accélération » : deux événements', 'EN: log tab: two events'));
  const ev = $$('#ac-events tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(ev[0][1] === L('prédiction', 'prediction') && ev[0][2] === L('Modèle « llama3.2:3b » préchargé : habituellement demandé vers 9 h (5 jours sur 6)', 'Model "llama3.2:3b" preloaded: usually requested around 9:00 (5 days out of 6)') && ev[1][1] === L('automatique', 'automatic') && ev[1][2] === L('Requêtes en parallèle : 1 -> 2 (Ollama redémarré)', 'Parallel requests: 1 -> 2 (Ollama restarted)'), L('événements : origine et texte', 'EN: events'));
  // --- contrôles de la machine
  ok(await go('#perf/tune', () => $$('#pf-checks li').length === 5), L('contrôles de la machine : cinq lignes', 'EN: five machine checks'));
  const ck = $('#pf-checks');
  ok(ck.textContent.includes(L('Resizable BAR semble désactivé (fenêtre de 0.25 Go pour 16 Go de mémoire vidéo)', 'Resizable BAR seems disabled (0.25 GB window for 16 GB of video memory)')) && ck.textContent.includes(L('profil XMP / EXPO désactivé dans le BIOS', 'XMP / EXPO profile disabled in the BIOS')) && ck.textContent.includes(L('est en PCIe x8 alors que x16 est possible', 'runs at PCIe x8 while x16 is possible')) && ck.textContent.includes(L('Une seule barrette de mémoire', 'A single memory stick')), L('Resizable BAR, mémoire, PCIe traduits', 'EN: BAR, memory, PCIe checks'));
  calls.length = 0; btn(ck, L('Corriger', 'Fix')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes(L('fréquences de la carte AMD', 'AMD card')), L('carte AMD : confirmation d\'abord', 'EN: AMD fix asks first'));
  $('#modal-ok').click();
  ok(await until(() => sent('/api/perf/fix', (b) => b.id === 'amd_power').length === 1), L('correction « fréquences maximales » envoyée', 'EN: AMD fix sent'));
  st.checks = [{ id: 'gpu_power:0000:03:00.0', state: 'ok', fix: 'amd_power_auto', text: 'AMD Radeon RX 7800 XT : fréquences maximales fixées.' }];
  $('#pf-refresh').click();
  ok(await until(() => $$('#pf-checks li').length === 1) && !!btn($('#pf-checks'), L('Rétablir', 'Restore')) && T('#pf-checks').includes(L('AMD Radeon RX 7800 XT : fréquences maximales fixées.', 'AMD Radeon RX 7800 XT: maximum clocks pinned.')), L('une fois fixée : bouton « Rétablir »', 'EN: restore button once pinned'));
  calls.length = 0; btn($('#pf-checks'), L('Rétablir', 'Restore')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes(L('gestion automatique', 'automatic management')), L('rétablir : confirmation d\'abord', 'EN: restore asks first'));
  $('#modal-ok').click();
  ok(await until(() => sent('/api/perf/fix', (b) => b.id === 'amd_power_auto').length === 1), L('retour à la gestion automatique envoyé', 'EN: restore sent'));
  if (lang === 'en') {
    for (const k of ['cache', 'predict', 'autobench', 'kv', 'parallel', 'aclog']) {
      w.location.hash = '#perf/' + k; await sleep(120);
      const rest = leftovers(w, '#panel-perf-' + k);
      ok(rest.length === 0, 'EN: ' + k + ' : aucun reste de français' + (rest.length ? ' → ' + JSON.stringify(rest.slice(0, 4)) : ''));
    }
  }
  w.close();
}
(async () => { await scenario(''); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
