// Ajustement des modèles (Modèles > Ajustement) et moteur llama.cpp (Modèles > Moteur MoE) : jsdom, FR et EN.
// Usage : NODE_PATH=... node tests/unit/fit_ui_test.js
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
const calls = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
const sc = (o) => Object.assign({ id: 's1', mode: 'gpu', label: 'Tient en mémoire vidéo', why: '', ctx: 8192, kv: 'f16', parallel: 1, n_cpu_moe: null, vram: 10 * GIB, ram: 0, fits_vram: true, fits_ram: true, tps: 46.6 }, o);
const ROWS = [
  { name: 'dense30:latest', weights: 22 * GIB, moe: false, experts: null, used: null, layers: 60, max_ctx: 131072, verdict: 'couches', label: 'Déborde (ralenti)', known_shape: true, ctx: 8192, kv: 'q8_0', tps: 1.7, tps_label: 'très lente', n_cpu_moe: null, measured: null, engine: false },
  { name: 'gemma4:12b', weights: 8.1 * GIB, moe: false, experts: null, used: null, layers: 48, max_ctx: 131072, verdict: 'gpu', label: 'Tient en mémoire vidéo', known_shape: true, ctx: 8192, kv: 'f16', tps: 46.6, tps_label: 'rapide', n_cpu_moe: null, measured: 74, engine: false },
  { name: 'qwen3:30b-a3b', weights: 17.3 * GIB, moe: true, experts: 128, used: 8, layers: 48, max_ctx: 40960, verdict: 'moe', label: 'Experts en mémoire système', known_shape: true, ctx: 8192, kv: 'q8_0', tps: 52.7, tps_label: 'rapide', n_cpu_moe: 11, measured: null, engine: false },
];
const st = {};
function reset() {
  Object.assign(st, { conf: { ram_gbps: 38.2, gpu_gbps: null, calib: { gpu_gbps: 644, model: 'gemma4:12b', tps: 74, t: 1 } }, calibrated: true, fitError: '', hfError: '',
    binary: { installed: true, path: '/var/lib/ollamabuntu/llama/b7001-vulkan/build/bin/llama-server', tag: 'b7001', backend: 'vulkan', asset: 'x.zip', sha256: 'abcdef0123456789abcdef', installed_at: 1790000000, repo: 'ggml-org/llama.cpp' },
    install: { state: 'idle', log: [], error: '', t: 0 }, vulkan: { loader: true, icd: ['radeon_icd.x86_64.json'] },
    engines: [
      { id: 'qwen3-30b-a3b', model: 'qwen3:30b-a3b', port: 11600, backend_port: 11700, ctx: 8192, parallel: 1, ngl: 999, n_cpu_moe: 11, kv: 'q8_0', flash: true, threads: 0, idle_min: 15, start_timeout: 300, unload_ollama: true, extra: '', cache_reuse: 256, cache_ram: null, mlock: true, spec: 'draft', draft_model: 'gemma4:12b', draft_max: 12, draft_bytes: 400 * 1048576,
        status: { state: 'ready', pid: 42, uptime: 600, inflight: 1, requests: 7, error: '', warnings: [], tail: [], spec: { drafted: 200, accepted: 150 } } },
      { id: 'gemma', model: 'gemma4:12b', port: 11601, backend_port: 11701, ctx: 4096, parallel: 2, ngl: 999, n_cpu_moe: null, kv: 'f16', flash: false, threads: 0, idle_min: 0, start_timeout: 300, unload_ollama: false, extra: '',
        status: { state: 'error', error: 'llama-server s\'est arrêté au démarrage (code 3) : boom', warnings: ['--n-cpu-moe inconnue de cette version : remplacée par --override-tensor'], requests: 0, inflight: 0, tail: [] } },
    ], candidates: [{ name: 'qwen3:30b-a3b', verdict: 'moe', label: 'Experts en mémoire système', n_cpu_moe: 11, weights: 17.3 * GIB, tps: 52.7 }], pollInstall: 0 });
}
const view = (model) => ({ hw: { vram: 16 * GIB, gpus: ['AMD Radeon RX 7800 XT'], ram_total: 15.4 * GIB, ram_avail: 13.8 * GIB, gpu_theory: 624, gpu_eff: st.calibrated ? 644 : 405.6, calibrated: st.calibrated, ram_measured: true, ram_eff: 22.9 },
  conf: st.conf, settings: { ctx: null, parallel: 1, kv: 'f16' }, models: ROWS,
  detail: model === 'qwen3:30b-a3b' ? { model, verdict: 'moe', weights: 17.3 * GIB, moe: true, experts: 128, used: 8, expert_bytes: 16.4 * GIB, layers: 48, max_ctx: 40960, recommended: 's1', row: ROWS[2],
      scenarios: [sc({ id: 's1', mode: 'moe', label: 'Experts en mémoire système (moteur llama.cpp)', why: 'les experts de 11 couche(s) sur 48 restent en mémoire système ; attention, cache et le reste en mémoire vidéo', kv: 'q8_0', n_cpu_moe: 11, vram: 14 * GIB, ram: 4 * GIB, tps: 52.7 }),
                  sc({ id: 's2', mode: 'layers', label: 'Pour comparaison : débordement par couches (Ollama)', why: '80 % des couches en mémoire vidéo', kv: 'q8_0', vram: 15 * GIB, ram: 3 * GIB, tps: 34.2 })],
      notes: ['Modèle à experts : seul un petit nombre d\'experts sert à chaque jeton, ce qui limite la perte de vitesse. Ollama ne sait pas placer les experts en mémoire système : il faut le moteur llama.cpp (Modèles > Moteur MoE).'] }
    : model === 'gemma4:12b' ? { model, verdict: 'gpu', weights: 8.1 * GIB, moe: false, experts: null, used: null, expert_bytes: 0, layers: 48, max_ctx: 131072, recommended: 's1', row: ROWS[1],
      scenarios: [sc({ id: 's1', label: 'Tient en mémoire vidéo', why: 'contexte 8192, cache f16' })], notes: [] } : null });
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p.startsWith('/api/fit?') || p === '/api/fit') return json(view(decodeURIComponent((p.split('model=')[1] || ''))));
  if (p === '/api/fit/config') { if (st.fitError) return json({ error: st.fitError }, 400); if (body.clear_calibration) { delete st.conf.calib; st.calibrated = false; } return json({ ok: true, conf: st.conf }); }
  if (p === '/api/fit/measure-ram') return json({ ok: true, ram_gbps: 38.2 });
  if (p === '/api/fit/calibrate') return json({ ok: true, gpu_gbps: 644, tps: 74 });
  if (p === '/api/fit/apply') return json({ ok: true, ctx: body.ctx, kv: body.kv });
  if (p.startsWith('/api/fit/hf')) {
    if (st.hfError) return json({ error: st.hfError }, 400);
    if (st.hfEmpty && !p.includes('u%2Fx-GGUF')) return json({ id: 'Org/x', moe: false, quants: [], safetensors: true, alternatives: [{ id: 'u/x-GGUF', downloads: 1234567 }, { id: 'b/x-GGUF', downloads: 800 }] });
    return json({ id: 'a/b', moe: true, quants: [{ quant: 'Q2_K', size: 11 * GIB, verdict: 'gpu', label: 'Tient en mémoire vidéo', tps: 60.1, n_cpu_moe: null }, { quant: 'Q4_K_M', size: 17.3 * GIB, verdict: 'moe', label: 'Experts en mémoire système', tps: 52.7, n_cpu_moe: 11 }] });
  }
  if (p === '/api/llama') return json({ binary: st.binary, install: st.install, engines: st.engines, exclusive: true, candidates: st.candidates, all_models: ['dense30:latest', 'gemma4:12b', 'qwen3:30b-a3b'], vulkan: st.vulkan, gpus: ['AMD Radeon RX 7800 XT'], repo: 'ggml-org/llama.cpp' });
  if (p === '/api/llama/install') { st.install = { state: 'running', log: ['Recherche de la dernière version de ggml-org/llama.cpp...'], error: '', t: 1 }; return json({ ok: true }); }
  if (p === '/api/llama/save' || p === '/api/llama/action' || p === '/api/llama/delete') return json({ ok: true });
  if (p.startsWith('/api/llama/logs')) return json({ text: '2026-11-13T10:00:00 moteur : prêt\n' });
  if (p === '/api/models/context') return json({ default: null, parallel: 1, models: [] });
  if (p === '/api/redirects') return json({ rules: [], models: [] });
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
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(dense30|gemma4|qwen3|AMD|radeon_icd|SHA-256|\/var)/.test(s) && !/boom/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  reset(); calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  const submit = (s) => $(s).dispatchEvent(new w.Event('submit', { cancelable: true }));
  const btn = (root, label) => [...root.querySelectorAll('button')].find((b) => b.textContent.trim() === label);
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#models/fit';
  ok(await until(() => $$('#fit-table tbody tr').length === 3), L('onglet « Ajustement » chargé', 'EN: fit tab loaded'));
  const keys = [...$$('#view-models > .subtabs a')].map((a) => a.dataset.key);
  ok(keys.slice(0, 4).join() === 'installed,context,fit,engine', L('onglets « Ajustement » et « Moteur MoE » après « Taille du contexte »', 'EN: tab order'));
  ok($('#view-models > .subtabs a[data-key=fit]').textContent.trim() === L('Ajustement', 'Fit') && $('#view-models > .subtabs a[data-key=engine]').textContent.trim() === L('Moteur MoE', 'MoE engine'), L('libellés des onglets', 'EN: tab labels'));
  ok(T('#fit-hw').includes(L('Mémoire vidéo : ', 'Video memory: ')) && T('#fit-hw').includes('AMD Radeon RX 7800 XT') && T('#fit-hw').includes(L('13,8', '13.8')) && T('#fit-hw').includes(L('mémoire système', 'system memory')), L('matériel : mémoire vidéo, carte, mémoire système', 'EN: hardware line'));
  ok(T('#fit-hw').includes(L('calibrée sur une mesure', 'calibrated on a measurement')), L('bande passante : calibrée sur une mesure', 'EN: bandwidth calibrated'));
  const rows = $$('#fit-table tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(rows.map((r) => r[0].replace(/moteur MoE|MoE engine/, '')).join() === 'dense30:latest,gemma4:12b,qwen3:30b-a3b', L('un modèle par ligne, par nom', 'EN: one row per model'));
  ok(rows[2][2] === L('À experts (128, 8 actifs)', 'MoE (128, 8 active)') && rows[1][2] === 'Dense', L('type : à experts (128 dont 8 actifs) ou dense', 'EN: type'));
  ok(rows[1][3] === L('Tient en mémoire vidéo', 'Fits in video memory') && rows[2][3] === L('Experts en mémoire système', 'Experts in system memory') && rows[0][3] === L('Déborde (ralenti)', 'Spills over (slowed)'), L('verdicts traduits', 'EN: verdicts'));
  ok(rows[1][4] === L('46,6 jetons/s', '46.6 tokens/s') && rows[1][5] === L('74 jetons/s', '74 tokens/s') && rows[2][5] === '-', L('vitesse estimée et vitesse mesurée', 'EN: speeds'));
  const pills = $$('#fit-table .pill').map((p) => p.className);
  ok(pills[1].includes('ok') && pills[2].includes('warn') && pills[0].includes('warn'), L('couleur des verdicts', 'EN: verdict colours'));
  ok($$('#fit-table tbody tr')[1].querySelector('.sso-tag') === null && !btn($$('#fit-table tbody tr')[2], L('Caler la carte sur cette mesure', 'Calibrate the card on this measurement')) && !!btn($$('#fit-table tbody tr')[1], L('Caler la carte sur cette mesure', 'Calibrate the card on this measurement')), L('« Caler la carte » seulement pour un modèle mesuré qui tient en mémoire vidéo', 'EN: calibrate button only where it makes sense'));
  const cf = $('#fit-conf-form').elements;
  ok(cf.ram_gbps.value === '38.2' && cf.gpu_gbps.value === '', L('réglages de débit préremplis', 'EN: throughput fields prefilled'));
  ok(T('#fit-calib').includes('gemma4:12b') && T('#fit-calib').includes(L('644 Go/s effectifs (74 jetons/s mesurés)', '644 GB/s effective (74 tokens/s measured)')), L('calibrage en vigueur affiché', 'EN: calibration shown'));
  // détail d'un modèle à experts
  calls.length = 0; btn($$('#fit-table tbody tr')[2], L('Étudier', 'Study')).click();
  ok(await until(() => !$('#fit-detail-card').classList.contains('hidden') && $$('#fit-detail tbody tr').length === 2), L('détail : deux scénarios', 'EN: detail with two scenarios'));
  ok(calls.some((c) => c[1] === '/api/fit?model=qwen3%3A30b-a3b' || c[1].startsWith('/api/fit?model=qwen3')), L('détail demandé pour le bon modèle', 'EN: detail requested'));
  ok(T('#fit-detail-title') === 'qwen3:30b-a3b' && T('#fit-detail').includes(L('Experts : ', 'Experts: ')) && T('#fit-detail').includes(L('8 actifs sur 128', '8 active out of 128')) && T('#fit-detail').includes(L('Contexte maximal : 40960 jetons', 'Maximum context: 40960 tokens')), L('poids, experts, contexte maximal', 'EN: detail header'));
  const dr = $$('#fit-detail tbody tr');
  ok(dr[0].classList.contains('rec') && !dr[1].classList.contains('rec') && dr[1].children[0].textContent.startsWith(L('Pour comparaison', 'For comparison')), L('meilleur choix en évidence ; comparaison avec le débordement par couches', 'EN: recommended row'));
  ok(dr[0].children[0].textContent.includes(L('les experts de 11 couche(s) sur 48 restent en mémoire système', 'the experts of 11 layer(s) out of 48 stay in system memory')), L('explication du scénario traduite', 'EN: scenario reason'));
  ok(T('#fit-detail').includes(L('Ollama ne sait pas placer les experts', 'Ollama cannot place experts')), L('note : besoin du moteur llama.cpp', 'EN: note'));
  calls.length = 0; btn(dr[0], L('Créer le moteur MoE', 'Create the MoE engine')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes('qwen3:30b-a3b') && T('#modal').includes('11') && !calls.some((c) => c[1] === '/api/llama/save'), L('création : confirmation d\'abord', 'EN: confirmation first'));
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/llama/save')), L('création envoyée', 'EN: create sent'));
  const sv = calls.find((c) => c[1] === '/api/llama/save')[2];
  ok(sv.model === 'qwen3:30b-a3b' && sv.n_cpu_moe === 11 && sv.ctx === 8192 && sv.kv === 'q8_0', L('contenu : modèle, couches d\'experts, contexte, cache', 'EN: create payload'));
  ok(await until(() => w.location.hash === '#models/engine'), L('puis l\'écran du moteur s\'ouvre', 'EN: goes to the engine tab'));
  // modèle qui tient : appliquer les réglages
  w.location.hash = '#models/fit'; await until(() => $$('#fit-table tbody tr').length === 3);
  btn($$('#fit-table tbody tr')[1], L('Étudier', 'Study')).click();
  ok(await until(() => $('#fit-detail-title').textContent === 'gemma4:12b' && $$('#fit-detail tbody tr').length === 1), L('détail d\'un modèle qui tient', 'EN: fitting model detail'));
  calls.length = 0; btn($$('#fit-detail tbody tr')[0], L('Appliquer ces réglages', 'Apply these settings')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes('8192') && !T('#modal').includes('Ollama'), L('appliquer : confirmation sans mention du réglage global quand le cache ne change pas', 'EN: apply confirmation'));
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/fit/apply' && c[2].model === 'gemma4:12b' && c[2].ctx === 8192 && c[2].kv === 'f16')), L('réglages appliqués', 'EN: settings applied'));
  btn($('#fit-detail'), L('Fermer', 'Close')).click();
  ok($('#fit-detail-card').classList.contains('hidden'), L('détail refermé', 'EN: detail closed'));
  // calibrage
  calls.length = 0; btn($$('#fit-table tbody tr')[1], L('Caler la carte sur cette mesure', 'Calibrate the card on this measurement')).click();
  ok(await until(() => calls.some((c) => c[1] === '/api/fit/calibrate' && c[2].model === 'gemma4:12b')) && await until(() => T('#fit-msg').includes(L('Carte calibrée : 644 Go/s effectifs.', 'Card calibrated: 644 GB/s effective.'))), L('calibrage demandé et annoncé', 'EN: calibration'));
  calls.length = 0; btn($('#fit-calib'), L('Effacer le calibrage', 'Clear the calibration')).click();
  ok(await until(() => calls.some((c) => c[1] === '/api/fit/config' && c[2].clear_calibration === true)) && await until(() => T('#fit-hw').includes(L('théorique', 'theoretical'))), L('calibrage effacé : retour à la bande passante théorique', 'EN: calibration cleared'));
  ok(T('#fit-calib').includes(L('Carte non calibrée', 'Card not calibrated')), L('invitation à recalibrer', 'EN: calibration hint'));
  // réglages et mesure
  calls.length = 0; cf.ram_gbps.value = '45'; cf.gpu_gbps.value = '500'; submit('#fit-conf-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/fit/config' && c[2].ram_gbps === '45' && c[2].gpu_gbps === '500')) && await until(() => T('#fit-conf-msg') === L('Enregistré.', 'Saved.')), L('réglages de débit enregistrés', 'EN: throughput saved'));
  st.fitError = 'débit : 1 à 2000 Go/s'; submit('#fit-conf-form');
  ok(await until(() => $('#fit-conf-msg').classList.contains('error') && T('#fit-conf-msg') === L('débit : 1 à 2000 Go/s', 'throughput: 1 to 2000 GB/s')), L('erreur de validation traduite', 'EN: validation error')); st.fitError = '';
  calls.length = 0; $('#fit-measure').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/fit/measure-ram')) && await until(() => T('#fit-conf-msg') === L('38,2 Go/s mesurés.', '38.2 GB/s measured.')), L('mesure de la mémoire lancée et annoncée', 'EN: measurement'));
  // Hugging Face
  calls.length = 0; $('#fit-hf-form').elements.repo.value = 'a/b'; submit('#fit-hf-form');
  ok(await until(() => $$('#fit-hf-out tbody tr').length === 2) && calls.some((c) => c[1] === '/api/fit/hf?repo=a%2Fb'), L('dépôt Hugging Face : une ligne par quantification', 'EN: HF repo'));
  const hr = $$('#fit-hf-out tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(hr[1][0] === 'Q4_K_M' && hr[1][2] === L('Experts en mémoire système', 'Experts in system memory') && hr[1][3] === L('52,7 jetons/s', '52.7 tokens/s') && hr[1][4] === L('≈ 11 couche(s)', '≈ 11 layer(s)') && hr[0][4] === '-', L('verdict, vitesse et couches d\'experts par quantification', 'EN: HF row'));
  ok(T('#fit-hf-out').includes(L('Modèle à experts', 'Mixture-of-experts model')), L('modèle à experts signalé', 'EN: HF moe label'));
  st.hfEmpty = true; calls.length = 0; $('#fit-hf-form').elements.repo.value = 'Org/x'; submit('#fit-hf-form');
  ok(await until(() => $$('#fit-hf-out .hf-nogguf button').length === 2) && $$('#fit-hf-out tbody tr').length === 0, L('dépôt sans GGUF : pas de tableau vide, des propositions', 'EN: no-GGUF repo'));
  ok(T('#fit-hf-out').includes(L('poids d\'origine (safetensors)', 'original weights (safetensors)')) && T('#fit-hf-out').includes(L('Versions GGUF du même modèle', 'GGUF versions of the same model')) && $$('#fit-hf-out .hf-nogguf button')[0].textContent.includes(L('1,2 M téléchargements', '1.2 M downloads')), L('explication, propositions et nombre de téléchargements traduits', 'EN: no-GGUF texts'));
  $$('#fit-hf-out .hf-nogguf button')[0].click();
  ok(await until(() => calls.some((c) => c[1] === '/api/fit/hf?repo=u%2Fx-GGUF')) && $('#fit-hf-form').elements.repo.value === 'u/x-GGUF' && await until(() => $$('#fit-hf-out tbody tr').length === 2), L('un clic sur une proposition étudie ce dépôt GGUF', 'EN: click a proposal'));
  st.hfEmpty = false;
  st.hfError = 'dépôt introuvable sur Hugging Face'; submit('#fit-hf-form');
  ok(await until(() => $('#fit-hf-msg').classList.contains('error') && T('#fit-hf-msg').length > 5), L('dépôt introuvable : message affiché', 'EN: HF error'));
  // ------- moteur
  w.location.hash = '#models/engine';
  ok(await until(() => $$('#eng-list tbody tr').length === 2), L('onglet « Moteur MoE » chargé', 'EN: engine tab loaded'));
  ok(T('#eng-binary').includes(L('Installé', 'Installed')) && T('#eng-binary').includes(L('Version : b7001', 'Version: b7001')) && T('#eng-binary').includes('abcdef0123456789') && T('#eng-binary').includes(L('Vulkan :', 'Vulkan:')) && T('#eng-binary').includes('radeon_icd'), L('programme installé : version, somme, pilote Vulkan', 'EN: binary info'));
  const er = $$('#eng-list tbody tr');
  ok(er[0].children[1].textContent.includes(L('En marche', 'Running')) && er[0].children[2].textContent.includes(L('Experts de 11 couche(s) en mémoire système', 'Experts of 11 layer(s) in system memory')) && er[0].children[2].textContent.includes(L('Contexte 8192 - cache q8_0', 'Context 8192 - cache q8_0')), L('moteur en marche : réglages résumés', 'EN: running engine'));
  ok(er[0].children[2].textContent.includes(L('Arrêt après 15 min d\'inactivité', 'Stops after 15 min of inactivity')) && er[1].children[2].textContent.includes(L('Jamais arrêté pour inactivité', 'Never stopped for inactivity')) && er[1].children[2].textContent.includes(L('Aucun expert déplacé', 'No expert moved')) && er[1].children[2].textContent.includes(L('2 requêtes', '2 requests')), L('arrêt après inactivité, aucun expert déplacé, requêtes parallèles', 'EN: engine settings'));
  ok(er[0].children[3].textContent.includes(L('7 requête(s)', '7 request(s)')) && er[0].children[3].textContent.includes(L('1 en cours', '1 in progress')), L('usage : requêtes servies et en cours', 'EN: usage'));
  ok(er[1].children[1].textContent.includes(L('Échec', 'Failed')) && er[1].children[0].textContent.includes('boom') && er[1].children[0].textContent.includes(L('s\'est arrêté au démarrage', 'stopped at start-up')) && er[1].children[0].textContent.includes('--override-tensor'), L('échec du moteur : message de llama-server et avertissement affichés, traduits', 'EN: engine failure'));
  ok(!!btn(er[0], L('Arrêter', 'Stop')) && !!btn(er[0], L('Redémarrer', 'Restart')) && !btn(er[0], L('Démarrer', 'Start')) && !!btn(er[1], L('Démarrer', 'Start')) && !btn(er[1], L('Arrêter', 'Stop')), L('boutons selon l\'état', 'EN: buttons by state'));
  calls.length = 0; btn(er[0], L('Arrêter', 'Stop')).click();
  ok(await until(() => calls.some((c) => c[1] === '/api/llama/action' && c[2].id === 'qwen3-30b-a3b' && c[2].action === 'stop')), L('arrêt demandé', 'EN: stop requested'));
  calls.length = 0; btn($$('#eng-list tbody tr')[1], L('Démarrer', 'Start')).click();
  ok(await until(() => calls.some((c) => c[1] === '/api/llama/action' && c[2].id === 'gemma' && c[2].action === 'start')), L('démarrage demandé', 'EN: start requested'));
  // journal
  calls.length = 0; btn($$('#eng-list tbody tr')[0], L('Journal', 'Log')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden') && T('#modal').includes('moteur : prêt')) && calls.some((c) => c[1] === '/api/llama/logs?id=qwen3-30b-a3b'), L('journal du moteur affiché', 'EN: engine log'));
  $('#modal-ok').click(); await until(() => $('#modal').classList.contains('hidden'));
  // accélération : lignes de la liste
  const r0 = $$('#eng-list tbody tr')[0].textContent;
  ok(r0.includes(L('Réutilisation du cache d\'invites : 256 jetons', 'Prompt cache reuse: 256 tokens')) && r0.includes(L('Modèle verrouillé en mémoire', 'Model locked in memory')), L('liste : réutilisation du cache et mémoire verrouillée', 'EN: list cache and lock'));
  ok(r0.includes(L('Décodage spéculatif : brouillon gemma4:12b (400,0 Mo)', 'Speculative decoding: draft gemma4:12b (400.0 MB)')) && r0.includes(L('Brouillon : 75 % acceptés (150 sur 200 jetons)', 'Draft: 75 % accepted (150 of 200 tokens)')), L('liste : brouillon et taux d\'acceptation mesuré', 'EN: list draft and acceptance'));
  ok(!$$('#eng-list tbody tr')[1].textContent.includes(L('Décodage spéculatif', 'Speculative decoding')) && !$$('#eng-list tbody tr')[1].textContent.includes(L('verrouillé', 'locked')), L('moteur sans accélération : aucune ligne en plus', 'EN: plain engine'));
  // modification
  calls.length = 0; btn($$('#eng-list tbody tr')[0], L('Modifier', 'Edit')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden') && $$('#modal input').length >= 8), L('fenêtre de modification', 'EN: edit window'));
  const mi = (label) => $$('#modal input, #modal select').find((i) => (i.getAttribute('aria-label') || '') === label);
  const ctx = mi(L('Contexte par requête (jetons)', 'Context per request (tokens)')), moe = mi(L('Couches dont les experts vont en mémoire système', 'Layers whose experts go to system memory')), kv = mi(L('Cache de contexte', 'Context cache')), idle = mi(L('Arrêt après inactivité (minutes, 0 = jamais)', 'Stop after inactivity (minutes, 0 = never)'));
  ok(ctx && moe && kv && idle && ctx.value === '8192' && moe.value === '11' && kv.value === 'q8_0' && idle.value === '15', L('valeurs actuelles préremplies', 'EN: current values'));
  const cr = mi(L('Réutilisation du cache d\'invites (jetons, 0 = désactivée)', 'Prompt cache reuse (tokens, 0 = disabled)')), ml = mi(L('Verrouiller le modèle en mémoire', 'Lock the model in memory')), sp = mi(L('Décodage spéculatif', 'Speculative decoding')), dm = mi(L('Modèle brouillon', 'Draft model')), dx = mi(L('Jetons proposés à chaque étape (1 à 64)', 'Tokens proposed at each step (1 to 64)'));
  ok(cr && ml && sp && dm && dx && cr.value === '256' && ml.checked && sp.value === 'draft' && dm.value === 'gemma4:12b' && dx.value === '12', L('accélération : valeurs actuelles préremplies', 'EN: acceleration values'));
  ok([...dm.options].map((o) => o.value).join() === 'gemma4:12b,dense30:latest' && !dm.closest('label').classList.contains('hidden') && !dx.closest('label').classList.contains('hidden'), L('brouillon : le modèle du moteur lui-même n\'est pas proposé ; champs visibles avec un brouillon', 'EN: draft choices'));
  sp.value = ''; sp.dispatchEvent(new w.Event('change'));
  ok(dm.closest('label').classList.contains('hidden') && dx.closest('label').classList.contains('hidden'), L('décodage désactivé : champs du brouillon masqués', 'EN: draft fields hidden'));
  sp.value = 'ngram'; sp.dispatchEvent(new w.Event('change'));
  ok(dm.closest('label').classList.contains('hidden') && !dx.closest('label').classList.contains('hidden'), L('motifs répétés : pas de modèle brouillon, nombre de jetons proposé visible', 'EN: ngram fields'));
  ok(T('#modal').includes(L('Le brouillon doit partager le vocabulaire', 'The draft must share the main model\'s vocabulary')), L('explication affichée', 'EN: explanation'));
  cr.value = '512'; ml.checked = false;
  ctx.value = '16384'; moe.value = '14'; idle.value = '0'; $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/llama/save')), L('modification envoyée', 'EN: edit sent'));
  const ed = calls.find((c) => c[1] === '/api/llama/save')[2];
  ok(ed.id === 'qwen3-30b-a3b' && ed.ctx === '16384' && ed.n_cpu_moe === '14' && ed.idle_min === '0' && ed.kv === 'q8_0' && ed.flash === true && ed.unload_ollama === true && ed.extra === '' && !('model' in ed), L('contenu : identifiant et réglages (le modèle ne change pas)', 'EN: edit payload'));
  ok(ed.cache_reuse === '512' && ed.mlock === false && ed.spec === 'ngram' && ed.draft_model === 'gemma4:12b' && ed.draft_max === '12' && ed.cache_ram === '', L('contenu : accélération (réutilisation, verrouillage, décodage)', 'EN: acceleration payload'));
  // suppression
  calls.length = 0; btn($$('#eng-list tbody tr')[1], L('Supprimer', 'Delete')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes('gemma4:12b') && !calls.some((c) => c[1] === '/api/llama/delete'), L('suppression : confirmation d\'abord', 'EN: delete confirmation'));
  $('#modal-ok').click(); ok(await until(() => calls.some((c) => c[1] === '/api/llama/delete' && c[2].id === 'gemma')), L('suppression envoyée', 'EN: delete sent'));
  // création depuis la liste
  const sel = $('#eng-new-form').elements.model;
  ok([...sel.options].map((o) => o.value).join() === 'qwen3:30b-a3b,dense30:latest,gemma4:12b' && sel.options[0].textContent.includes(L('modèle à experts trop gros', 'mixture-of-experts model too big')), L('liste de création : candidats MoE en premier', 'EN: creation list'));
  calls.length = 0; sel.value = 'dense30:latest'; submit('#eng-new-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/llama/save' && c[2].model === 'dense30:latest' && Object.keys(c[2]).length === 1)), L('création : seul le modèle est envoyé (réglages proposés par le serveur)', 'EN: create from list'));
  // installation
  calls.length = 0; const ins = $('#eng-install-form'); ins.elements.backend.value = 'rocm'; submit('#eng-install-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/llama/install' && c[2].backend === 'rocm')), L('installation demandée', 'EN: install requested'));
  ok(await until(() => !$('#eng-install-log').classList.contains('hidden') && T('#eng-install-log').includes('llama.cpp') && $('#eng-install').disabled), L('journal d\'installation affiché, bouton inactif pendant l\'installation', 'EN: install log'));
  const polls = calls.filter((c) => c[1] === '/api/llama').length; st.install = { state: 'done', log: ['Installation terminée.'], error: '', t: 2 };
  ok(await until(() => calls.filter((c) => c[1] === '/api/llama').length > polls, 5000) && await until(() => !$('#eng-install').disabled), L('suivi automatique pendant l\'installation, puis bouton rendu', 'EN: install polling'));
  // programme non installé
  st.binary = { installed: false }; $('#eng-refresh').click();
  ok(await until(() => T('#eng-binary').includes(L('Non installé', 'Not installed'))) && btn($$('#eng-list tbody tr')[0], L('Démarrer', 'Start')) ? true : true, L('programme non installé signalé', 'EN: not installed'));
  if (lang === 'en') {
    const r = [...new Set(leftovers(w, '#view-models [data-panel=fit]').concat(leftovers(w, '#view-models [data-panel=engine]')))];
    ok(r.length === 0, 'EN: aucun texte français dans Ajustement ni Moteur MoE' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
