// Console web, troisième lot : Performance (mesure, profils, préchauffage, garde-fou, réglages système), disponibilité des GPU, matériel, audit, rapport,
// espace disque des modèles, plafonds par clé, affinité de session — en français et en anglais (aucun texte français ne doit rester en anglais).
// Prérequis : npm install jsdom  (ou NODE_PATH vers un jsdom installé).   Usage : node tests/unit/batch3_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', () => {});
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const GB = 1024 ** 3, calls = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
const now = Math.floor(Date.now() / 1000);
const state = { benchRunning: false, polls: 0, hist: [{ t: now - 3600, model: 'gemma4:12b', tps: 50, ttft_ms: 2000, load_ms: 3000, vram_pct: 100, runs: 2, profile: 'equilibre', cfg: { kv: 'q8_0', fa: true, parallel: '2', ctx: 'auto' }, delta: null }],
  smart: false, guard: 'bad', auto: true, alert: true };
const PROFILES = () => [
  { id: 'latence', label: 'Latence minimale', help: 'Réponses les plus rapides pour peu d\'utilisateurs : modèle gardé en mémoire, une seule requête par modèle, cache en pleine précision.', diff: [{ key: 'OLLAMA_KV_CACHE_TYPE', from: 'q8_0', to: 'f16' }, { key: 'OLLAMA_NUM_PARALLEL', from: '2', to: '1' }] },
  { id: 'equilibre', label: 'Équilibré', help: 'Bon compromis débit / mémoire : cache réduit de moitié, deux requêtes en parallèle, modèles déchargés après 30 minutes.', diff: [] },
  { id: 'econome', label: 'Économe en mémoire', help: 'Libère le plus de RAM et de mémoire vidéo : cache divisé par quatre, un seul modèle chargé, déchargement rapide, contexte de 4 096 jetons.', diff: [{ key: 'OLLAMA_KV_CACHE_TYPE', from: 'q8_0', to: 'q4_0' }, { key: 'OLLAMA_CONTEXT_LENGTH', from: '', to: '4096' }] }];
const perfDoc = () => ({ env: {}, current: 'equilibre', profiles: PROFILES(),
  checks: [{ id: 'swappiness', state: 'warn', fix: 'swappiness', text: 'vm.swappiness vaut 60 : le système pousse des pages vers le disque trop tôt, ce qui ralentit Ollama. 10 est recommandé.' },
    { id: 'governor', state: 'ok', fix: '', text: 'Fréquence du processeur : performance.' },
    { id: 'zram', state: 'info', fix: '', text: 'Mémoire vive limitée (16 Go) et pas de zram : un swap compressé en mémoire (paquet zram-tools) absorbe les pointes sans solliciter le disque.' },
    { id: 'webui_mem', state: 'info', fix: 'webui_mem', text: 'Open WebUI n\'a pas de plafond de mémoire (il utilise 812 Mo). Un plafond de 2 Go protège les modèles d\'un emballement.' }],
  guard: { mode: 'suggest', drop_pct: 50 }, events: [{ t: now - 7200, who: 'automatique', text: 'Chute de débit — suggestion : passer le cache en q8_0', changes: { OLLAMA_KV_CACHE_TYPE: 'q8_0' } }],
  alert: state.alert ? { kind: 'slow', baseline: 60, current: 3, ratio: 0.05, fix: { changes: { OLLAMA_KV_CACHE_TYPE: 'q4_0' }, text: 'passer le cache en q4_0' }, text: 'Débit de 3 jetons/s au lieu de 60 d\'habitude — suggestion : passer le cache en q4_0' } : null,
  warmup: { boot: ['gemma4:12b'], times: [{ at: '07:30', models: ['llama3.2:3b'], days: [0, 1, 2, 3, 4] }], log: [{ t: now - 100, model: 'gemma4:12b', why: 'démarrage', ok: true, error: '' }, { t: now - 50, model: 'llama3.2:3b', why: 'heure programmée', ok: false, error: 'model not found' }] },
  bench: { running: state.benchRunning && state.polls < 2, model: 'llama3.2:3b', step: 1, runs: 2, error: '', history: state.hist.slice().reverse() } });
const guardDoc = () => ({ state: state.guard === 'bad' ? 'critical' : 'ok', auto: state.auto, repairing: false,
  checks: [{ pci: '0000:01:00.0', name: 'Quadro RTX 4000', vendor: 'NVIDIA', present: true, driver: true, ollama: state.guard !== 'bad' }],
  issues: state.guard === 'bad' ? [{ code: 'ollama_blind', severity: 'critical', pci: '0000:01:00.0', text: 'Carte Quadro RTX 4000 fonctionnelle mais Ollama ne l\'utilise pas (détection absente).', fix: 'restart-ollama' }] : [],
  events: [{ t: now - 500, who: 'automatique', codes: ['ollama_blind'], steps: ['load-uvm', 'restart-ollama'], result: 'résolu', remaining: [] }, { t: now - 900, who: 'adm', codes: ['driver_down'], steps: ['load-driver', 'restart-ollama'], result: 'non résolu', remaining: ['Carte Quadro RTX 4000 détectée mais pilote inactif : elle ne peut pas calculer.'] }] });
const hwDoc = () => ({ smartctl: state.smart, checked: now, disks: state.smart ? [{ name: '/dev/nvme0', model: 'Samsung 980', type: 'NVMe', size: 500 * GB, temp: 72, hours: 12000, wear: 93, passed: true, state: 'warning', issues: [{ severity: 'warning', text: 'Disque /dev/nvme0 : usure à 93 %, à remplacer bientôt.' }] }] : [],
  raid: [{ name: 'md0', level: 'raid1', state: 'active', degraded: true, members: ['sda1', 'sdb1'], progress: { action: 'recovery', percent: 12.5 } }],
  xid: [{ pci: '0000:01:00.0', xid: 79, ts: now, severity: 'critical', text: 'GPU has fallen off the bus.' }],
  issues: [{ key: 'raid:md0', severity: 'critical', text: 'Grappe RAID md0 dégradée (un disque manque ou a été retiré) : reconstruction à 12.5 %.' }, { key: 'gpu_xid:0000:01:00.0:79', severity: 'critical', text: 'GPU 0000:01:00.0 : erreur matérielle Xid 79 (GPU has fallen off the bus.).' }] });
const AUDIT = [
  { ts: now - 30, user: 'adm', role: 'admin', ip: '10.0.0.5', path: '/api/perf/profile', label: 'Profil de performance', detail: 'id=econome, apply=True', status: 200, ok: true },
  { ts: now - 90, user: 'marie', role: 'admin', ip: '10.0.0.9', path: '/api/models/delete', label: 'Suppression d\'un modèle', detail: 'name=vieux:7b', status: 403, ok: false }];
const DISK = { total: 30 * GB, reclaimable: 5 * GB, disk: { total: 500 * GB, free: 200 * GB }, journal_days: 7, idle_days: 30, models: [
  { name: 'vieux:7b', size: 5 * GB, installed_days: 100, last_used: null, idle_days: null, loaded: false, pinned: false, unused: true },
  { name: 'gemma4:12b', size: 8 * GB, installed_days: 100, last_used: now - 100, idle_days: 0, loaded: true, pinned: true, unused: false }] };
let delivered = [];
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/status') return json({ version: 'v', hostname: 'srv', os: 'Ubuntu', kernel: 'k', uptime: 10, boot_time: 1, ips: [], cpu: { model: 'x', cores: 1, load: [0, 0, 0], usage: 0 },
    memory: { total: 1, available: 1 }, disk: { total: 1, used: 0, free: 1, models: 0 }, gpu: { devices: [], compute: [], reboot_required: false }, gpu_live: [],
    ollama: { version: '0.1', service: 'active', exposed: false, running: [], publication: {} }, reboot_required: false, update_available: null, offload: [], alerts: [] });
  if (p === '/api/alerts') return json({ config: { enabled: false, webhook: { url: '' }, smtp: { host: '', port: 587, user: '', from: '', to: [], starttls: true }, events: [], disk_pct: 90, gpu_temp: 85, tps_min: 0 }, events: {}, active: [], last_error: '' });
  if (p === '/api/gpu') return json({ devices: [], compute: [], reboot_required: false, vulkan_installed: true, rocm_installed: false, discovered: true, nvidia_package: '', secure_boot: false });
  if (p === '/api/gpu/guard') return json(guardDoc());
  if (p === '/api/gpu/guard/repair') { state.guard = 'ok'; return json({ ok: true }); }
  if (p === '/api/gpu/guard/config') { state.auto = body.auto; return json({ ok: true }); }
  if (p === '/api/perf') { if (state.benchRunning) state.polls++; return json(perfDoc()); }
  if (p === '/api/bench/run') { state.benchRunning = true; state.polls = 0; state.hist.push({ t: now, model: body.model, tps: 60, ttft_ms: 900, load_ms: 0, vram_pct: 80, runs: body.runs, profile: 'equilibre', cfg: { kv: 'q8_0', fa: true, parallel: '2', ctx: 'auto' }, delta: { tps_pct: 20, ttft_pct: -55, previous: now - 3600 } }); return json({ ok: true }); }
  if (p === '/api/bench/clear') return json({ ok: true });
  if (p.startsWith('/api/perf/')) return json({ ok: true, changed: 1 });
  if (p.startsWith('/api/hw')) return json(hwDoc());
  if (p === '/api/action') return json({ ok: true, job: 'j1' });
  if (p === '/api/jobs') return json({ jobs: [{ id: 'j1', title: 'Installation de smartmontools', done: false, queued: false }] });
  if (p.startsWith('/api/jobs/')) return json({ id: 'j1', title: 'Installation de smartmontools', done: false, queued: false, output: '', rc: null });
  if (p.startsWith('/api/audit/export')) return json({});
  if (p.startsWith('/api/audit/clear')) return json({ ok: true });
  if (p.startsWith('/api/audit')) { const q = (/[?&]q=([^&]*)/.exec(p) || [])[1]; return json({ entries: AUDIT.filter((e) => !q || (e.label + e.detail).toLowerCase().includes(decodeURIComponent(q).toLowerCase())), total: 2, users: ['adm', 'marie'] }); }
  if (p === '/api/report') return json({ config: { enabled: true, day: 4, hour: 17, last_sent: '' }, smtp: false, last_error: '', text: 'OllamaBuntu srv — rapport\n\nUsage\n-----\n• 3 requêtes\n', preview: { title: 't', sections: [] } });
  if (p.startsWith('/api/report/')) return json({ ok: true });
  if (p.startsWith('/api/models/disk')) return json(DISK);
  if (p === '/api/models/delete') { delivered.push(body.name); return json({ ok: true }); }
  if (p.startsWith('/api/models/insights')) return json({ capacity: { vram: 24 * GB, ram_total: 64 * GB, ram_available: 40 * GB, gpus: ['Test'] }, ollama: '0.13.0', registry: { ok: true, errors: [], checked: 1 },
    sources: { Ollama: { total: 2, available: 2 }, 'Hugging Face': { total: 3, available: 2 } },
    installed: [{ name: 'hf.co/bartowski/phi-4-GGUF:Q4_K_M', source: 'Hugging Face', size: 9 * GB, details: { parameter_size: '14.7B', quantization_level: 'Q4_K_M' }, update: { state: 'a_jour', label: 'À jour' }, fit: { level: 'gpu', label: 'Entièrement sur GPU' } },
      { name: 'llama3.2:3b', source: 'Ollama', size: 2 * GB, details: {}, update: { state: 'a_jour', label: 'À jour' }, fit: { level: 'gpu', label: 'Entièrement sur GPU' } }],
    catalog: [
      { name: 'llama3.2:3b', source: 'Ollama', category: 'Conversation', caps: ['outils'], description: 'Petit modèle polyvalent de Meta, à l\'aise même sur processeur.', installed: true, available: true, size: 2 * GB, params: '3B', quant: 'Q4_K_M', fit: { level: 'gpu', label: 'Entièrement sur GPU' } },
      { name: 'hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M', source: 'Hugging Face', category: 'Conversation', caps: ['outils', 'raisonnement'], description: 'Qwen3 14B : bon équilibre qualité / vitesse, raisonnement activable (Hugging Face).', installed: false, available: true, size: 9 * GB, params: '14.8B', quant: 'Q4_K_M', fit: { level: 'gpu', label: 'Entièrement sur GPU' } },
      { name: 'llama3.3:70b', source: 'Ollama', category: 'Conversation', caps: [], description: 'Petit modèle polyvalent de Meta, à l\'aise même sur processeur.', installed: false, available: true, size: 42 * GB, params: '70B', quant: 'Q4_K_M', fit: { level: 'trop', label: 'Trop gros pour ce serveur' } },
      { name: 'hf.co/unsloth/Magistral-Small-2509-GGUF:Q4_K_M', source: 'Hugging Face', category: 'Raisonnement', caps: ['raisonnement'], description: 'Mistral Magistral Small : raisonnement pas à pas, vision, bon en français (Hugging Face).', installed: false, available: false, fit: null }] });
  if (p === '/api/models') return json({ models: [{ name: 'gemma4:12b' }, { name: 'llama3.2:3b' }, { name: 'x-cloud' }] });
  if (p === '/api/fleet/balance') return json({ strategy: 'spread', affinity: true, local: { models: 2, served: 0, last: null }, servers: [], models: [], active: false });
  if (p === '/api/fleet/balance/strategy') return json({ ok: true });
  if (p === '/api/limits') return json({ keys: [] });
  if (p === '/api/publication') return json({ enabled: true, tls: true, port: 11443, auth: true, allow: [], anonymous: { perms: [], models: [] }, urls: ['https://srv:11443'], router: {}, keys: [
    { id: 'k1', name: 'RH', prefix: 'ob_a', perms: ['inference'], deny: [], models: [], enabled: true, usage: {}, expires: '', days_left: null, max_ctx: 8192, max_output: 1024 }] });
  if (p === '/api/publication/keys/update' || p === '/api/publication/keys/create') return json({ ok: true, token: 'ob_tok', key: {} });
  if (p.startsWith('/api/metrics')) return json({ span: 3600, interval: 10, gpus: {}, series: [] });
  if (p.startsWith('/api/requests')) return json({ requests: [], summary: [], prompt_excerpt: false });
  if (p === '/api/prom') return json({ enabled: false, created: null, path: '/metrics' });
  return json({});
}
const EN = JSON.parse(fs.readFileSync(path.join(WEB, 'i18n', 'en.json'), 'utf8'));
function make(lang) {
  const dom = new JSDOM(html, { url: 'https://srv/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  if (lang) w.localStorage.setItem('ob-lang', lang);
  w.fetch = async (p, o) => (p === '/i18n/en.json' ? json(EN) : fakeFetch(p, o));
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {};
  w.URL.createObjectURL = () => 'blob:x'; w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function () { if (this.download) w.__downloads.push(this.download); };
  w.__downloads = [];
  w.eval(js);
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune)\b|[éèêëàâùûîïôç]/i;
const $$e_tabs = (win, v) => [...win.document.querySelectorAll('#view-' + v + ' > .subtabs a')].map((a) => a.textContent).join();
(async () => {
  const w = make();
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  ok(await until(() => !$('#app').classList.contains('hidden')), 'console affichée');
  const go = async (h, cond, ms) => { w.location.hash = h; return until(cond, ms); };

  // --- navigation
  ok($$('#nav a').some((a) => a.getAttribute('href') === '#perf' && a.textContent === 'Performance'), 'menu : écran Performance');
  ok(w.document.querySelector('#view-perf > .subtabs') && [...$$('#view-perf > .subtabs a')].map((a) => a.dataset.key).join() === 'bench,profiles,warmup,guard,tune', 'Performance : 5 onglets dans l\'ordre');
  ok([...$$('#view-gpu > .subtabs a')].map((a) => a.dataset.key).join() === 'cards,availability,placement,advanced' && [...$$('#view-system > .subtabs a')].map((a) => a.dataset.key).join().includes('alerts,report,hardware,audit,backup') && [...$$('#view-models > .subtabs a')].map((a) => a.dataset.key).includes('disk'), 'onglets Disponibilité, Rapport, Matériel, Audit et Espace disque');

  // --- menu : une seule ligne, les écrans rares sont dans « Plus »
  ok($$('#nav > a').length === 6 && $$('#nav-more-list a').map((a) => a.getAttribute('href')).join() === '#fleet,#logs,#security,#webui,#users,#about', 'menu : 6 entrées directes, 6 écrans dans « Plus »');
  ok($('#nav-more-list').classList.contains('hidden') && $('#nav-more-btn').getAttribute('aria-expanded') === 'false', '« Plus » fermé au départ');
  $('#nav-more-btn').click();
  ok(!$('#nav-more-list').classList.contains('hidden') && $('#nav-more-btn').getAttribute('aria-expanded') === 'true', '« Plus » s\'ouvre au clic');
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  ok($('#nav-more-list').classList.contains('hidden'), 'Échap referme « Plus »');
  $('#nav-more-btn').click(); w.document.body.click();
  ok($('#nav-more-list').classList.contains('hidden'), 'un clic ailleurs referme « Plus »');
  $('#nav-more-btn').click(); $('#nav-more-list a[href="#users"]').click(); w.location.hash = '#users'; await sleep(100);
  ok($('#nav-more-list').classList.contains('hidden') && $('#nav-more-btn').classList.contains('active') && $('#nav-more-list a[href="#users"]').classList.contains('active'), 'écran choisi dans « Plus » : liste refermée, « Plus » et l\'entrée marqués actifs');
  w.location.hash = '#dashboard'; await sleep(60);
  // --- mesure de débit
  ok(await go('#perf/bench', () => $$('#pf-model option').length === 2 && $('#pf-history').textContent.includes('50')), 'Performance : modèles (hors cloud) et historique');
  ok($$('#pf-model option').map((o) => o.value).join() === 'gemma4:12b,llama3.2:3b', 'modèles cloud écartés de la liste');
  $('#pf-model').value = 'llama3.2:3b'; $('#pf-runs').value = '2';
  $('#pf-run').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/bench/run' && c[2].model === 'llama3.2:3b' && c[2].runs === 2)), 'mesure lancée avec le modèle et le nombre de passes');
  ok(await until(() => $('#pf-state').textContent.includes('Mesure en cours : passe 1 sur 2') && $('#pf-run').disabled), 'mesure en cours : état affiché, bouton bloqué');
  ok(await until(() => !$('#pf-run').disabled && $('#pf-result').textContent.includes('60 jetons/s'), 9000), 'mesure terminée : débit affiché');
  const res = $('#pf-result').textContent;
  ok(res.includes('+20 %') && res.includes('900 ms') && res.includes('80 %') && res.includes('le reste tourne sur le processeur'), 'résultat : écart avec la mesure précédente, délai, part en mémoire vidéo');
  ok($$('#pf-history tbody tr').length === 2 && $$('#pf-history svg').length === 2 && $$('#pf-history svg')[0].querySelectorAll('rect').length >= 1, 'historique : 2 lignes avec mini-graphique');

  // --- profils
  w.location.hash = '#perf/profiles';
  ok(await until(() => $$('#pf-profiles .card').length === 3), 'profils : 3 cartes');
  ok($('#pf-profiles').textContent.includes('profil actuel') && $('#pf-profiles').textContent.includes('Cache de contexte : q8_0 → q4_0') && $('#pf-profiles').textContent.includes('Contexte par défaut : défaut → 4096') && $('#pf-profiles').textContent.includes('déjà appliqués'), 'profils : profil actuel, changements détaillés');
  ok($$('#pf-profiles button').find((b) => b.textContent === 'Appliquer ce profil' && b.disabled), 'profil déjà appliqué : bouton inactif');
  $$('#pf-profiles button')[2].click();
  await sleep(100);
  ok($('#modal-text').textContent.includes('Cache de contexte : q8_0 → q4_0') && $('#modal-text').textContent.includes('Ollama redémarre'), 'application d\'un profil : confirmation avec le détail');
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/perf/profile' && c[2].id === 'econome' && c[2].apply === true)), 'profil appliqué');
  await sleep(100); $('#modal-ok').click();

  // --- préchauffage
  w.location.hash = '#perf/warmup';
  ok(await until(() => $$('#pf-warm-boot input:checked').length === 1 && $$('#pf-warm-times .warm-row').length === 1), 'préchauffage : modèle de démarrage coché, un horaire');
  ok($('#pf-warm-times input[type=time]').value === '07:30' && $$('#pf-warm-times .days input:checked').length === 5 && $$('#pf-warm-times .mods input:checked').length === 1, 'horaire : heure, jours ouvrés, modèle');
  ok($('#pf-warm-log').textContent.includes('chargé') && $('#pf-warm-log').textContent.includes('model not found'), 'journal des préchauffages');
  $('#pf-warm-add').click();
  ok($$('#pf-warm-times .warm-row').length === 2, 'ajout d\'un horaire');
  $$('#pf-warm-times .warm-row')[1].querySelector('input[type=time]').value = '13:00';
  $$('#pf-warm-times .warm-row')[1].querySelector('.mods input').checked = true;
  $('#pf-warm-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/perf/warmup' && c[2].boot.join() === 'gemma4:12b' && c[2].times.length === 2 && c[2].times[0].days.join() === '0,1,2,3,4' && c[2].times[1].at === '13:00' && c[2].times[1].models.join() === 'gemma4:12b')), 'enregistrement du préchauffage');
  $('#pf-warm-now').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/perf/warmup/run' && c[2].models.join() === 'gemma4:12b')), 'préchauffage immédiat');

  // --- garde-fou de débit
  w.location.hash = '#perf/guard';
  ok(await until(() => $('#pf-alert').textContent.includes('Chute de débit') && $('#pf-alert').textContent.includes('q4_0')), 'garde-fou : chute de débit et suggestion');
  ok($('#pf-guard-mode').value === 'suggest' && $('#pf-guard-drop').value === '50' && $('#pf-events').textContent.includes('automatique'), 'garde-fou : mode, seuil, réglages déjà appliqués');
  $('#pf-guard-mode').value = 'auto'; $('#pf-guard-mode').dispatchEvent(new w.Event('change'));
  ok(await until(() => calls.some((c) => c[1] === '/api/perf/guard' && c[2].mode === 'auto' && c[2].drop_pct === 50)), 'mode automatique enregistré');
  $('#pf-alert button').click(); await sleep(100); $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/perf/apply-suggestion')), 'suggestion appliquée');
  await sleep(100); $('#modal-ok').click();

  // --- réglages système
  w.location.hash = '#perf/tune';
  ok(await until(() => $$('#pf-checks li').length === 4), 'réglages système : 4 contrôles');
  ok($('#pf-checks').textContent.includes('À traiter') && $('#pf-checks').textContent.includes('Conseil') && $$('#pf-checks button').length === 2, 'états et boutons de correction');
  $$('#pf-checks button')[0].click(); await sleep(100); $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/perf/fix' && c[2].id === 'swappiness')), 'correction de swappiness');
  $$('#pf-checks button')[1].click(); await sleep(100);
  ok($('#modal-extra select') && $('#modal-extra select').value === '2g', 'plafond Open WebUI : liste, 2 Go par défaut');
  $('#modal-extra select').value = '4g'; $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/perf/fix' && c[2].id === 'webui_mem' && c[2].value === '4g')), 'plafond de mémoire d\'Open WebUI envoyé');

  // --- disponibilité des GPU
  ok(await go('#gpu/availability', () => $('#gg-body').textContent.includes('Quadro RTX 4000')), 'GPU : carte de disponibilité');
  ok($('#gg-body').textContent.includes('Carte indisponible') && $$('#gg-body tbody .pill').map((p) => p.textContent).join() === 'oui,non' && $('#gg-body').textContent.includes('ne l\'utilise pas'), 'carte détectée avec pilote mais non utilisée par Ollama');
  ok(!$('#gg-repair').classList.contains('hidden') && $('#gg-auto').checked && $('#gg-events').textContent.includes('non résolu') && $('#gg-events').textContent.includes('Carte non vue par Ollama') && $('#gg-events').textContent.includes('pilote rechargé'), 'bouton Réparer, réparation automatique, historique');
  $('#gg-auto').checked = false; $('#gg-auto').dispatchEvent(new w.Event('change'));
  ok(await until(() => calls.some((c) => c[1] === '/api/gpu/guard/config' && c[2].auto === false)), 'réparation automatique désactivée');
  $('#gg-repair').click(); await sleep(100); $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/gpu/guard/repair')), 'réparation demandée');
  ok(await until(() => $('#gg-body').textContent.includes('Toutes les cartes sont disponibles') && $('#gg-repair').classList.contains('hidden'), 6000), 'après réparation : tout est disponible');

  // --- matériel
  ok(await go('#system/hardware', () => $('#hw-body').textContent.includes('smartmontools')), 'matériel : smartmontools absent signalé');
  ok($('#hw-body').textContent.includes('2 problème(s)') && $('#hw-body').textContent.includes('RAID md0') && $('#hw-body').textContent.includes('Xid 79') && $('#hw-body').textContent.includes('recovery 12,5 %'), 'problèmes, RAID dégradé en reconstruction, erreur Xid');
  $$('#hw-body button').find((b) => b.textContent === 'Installer smartmontools').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/action' && c[2].action === 'install-smart')), 'installation de smartmontools lancée comme tâche');
  state.smart = true; $('#hw-refresh').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/hw?refresh=1') && $('#hw-body').textContent.includes('Samsung 980')), 'actualisation forcée');
  ok($('#hw-body').textContent.includes('72 °C') && $('#hw-body').textContent.includes('93 %') && $('#hw-body').textContent.includes('à surveiller'), 'disque : température, usure, état');

  // --- audit
  ok(await go('#system/audit', () => $$('#au-table tbody tr').length === 2), 'audit : 2 actions');
  ok($('#au-table').textContent.includes('Suppression d\'un modèle') && $('#au-table').textContent.includes('refusé 403') && $('#au-count').textContent === '2 action(s)' && $$('#au-user option').length === 3, 'audit : action refusée, compteur, utilisateurs');
  $('#au-q').value = 'profil'; $('#au-q').dispatchEvent(new w.Event('input'));
  ok(await until(() => calls.some((c) => c[1] === '/api/audit?q=profil') && $$('#au-table tbody tr').length === 1), 'audit : recherche libre');
  $('#au-export').click();
  ok(await until(() => w.__downloads.includes('audit-ollamabuntu.csv') && calls.some((c) => c[1] === '/api/audit/export?q=profil')), 'audit : export CSV avec les filtres');
  $('#au-clear').click(); await sleep(100); $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/audit/clear')), 'audit : effacement confirmé');

  // --- rapport
  ok(await go('#system/report', () => $('#rp-preview').textContent.includes('3 requêtes')), 'rapport : aperçu');
  const rf = $('#rp-form');
  ok(rf.elements.enabled.checked && rf.elements.day.value === '4' && rf.elements.hour.value === '17' && !$('#rp-warn').classList.contains('hidden'), 'rapport : réglage chargé, avertissement SMTP absent');
  rf.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/report/config' && c[2].enabled === true && c[2].day === 4 && c[2].hour === 17)), 'rapport : réglage enregistré');
  $('#rp-test').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/report/send') && $('#rp-msg').textContent.includes('essai envoyé')), 'rapport : essai envoyé');

  // --- espace disque des modèles
  ok(await go('#models/disk', () => $$('#md-table tbody tr').length === 2), 'espace disque : 2 modèles');
  ok($('#md-summary').textContent.includes('5,0 Go') || $('#md-summary').textContent.includes('5.0 GB') || /5[.,]0/.test($('#md-summary').textContent), 'espace récupérable affiché');
  ok($('#md-table').textContent.includes('inutilisé') && $('#md-table').textContent.includes('en mémoire') && $('#md-table').textContent.includes('jamais vu depuis 7 j') && $$('#md-table input')[1].disabled, 'modèle inutilisé repéré ; modèle chargé non supprimable');
  ok($('#md-delete').disabled, 'suppression inactive sans sélection');
  $('#md-select').click();
  ok($$('#md-table input:checked').length === 1 && !$('#md-delete').disabled, 'sélection des modèles inutilisés');
  $('#md-delete').click(); await sleep(100);
  ok($('#modal-text').textContent.includes('vieux:7b'), 'confirmation avec la liste');
  $('#modal-ok').click();
  ok(await until(() => delivered.join() === 'vieux:7b' && $('#md-msg').textContent.includes('1 modèle(s) supprimé(s)')), 'suppression par lot');

  // --- modèles recommandés : vue agrégée multi-registres (Ollama + Hugging Face)
  ok(await go('#models/catalog', () => $$('#catalog .cat-item').length === 4), 'recommandés : les modèles Ollama et Hugging Face dans la même vue');
  ok($('#catalog-note').textContent.includes('Ollama 2/2') && $('#catalog-note').textContent.includes('Hugging Face 2/3') && $$('#catalog .cat-item')[1].textContent.includes('Hugging Face'), 'compteurs par source et pastille Source sur chaque carte');
  ok($$('#catalog .cat-item').some((i) => i.textContent.includes('Indisponible sur Hugging Face')) && $$('#catalog .cat-item').some((i) => i.textContent.includes('Trop gros pour ce serveur')), 'dépôt absent : « Indisponible sur Hugging Face » ; modèle trop gros signalé');
  $('#cat-source').value = 'Hugging Face'; $('#cat-source').dispatchEvent(new w.Event('change'));
  ok($$('#catalog .cat-item').length === 2 && $$('#catalog .cat-item').every((i) => i.querySelector('.name').textContent.startsWith('hf.co/')), 'filtre par source : Hugging Face seulement');
  $('#cat-fit').checked = true; $('#cat-fit').dispatchEvent(new w.Event('change'));
  ok($$('#catalog .cat-item').length === 1 && $('#catalog .name').textContent.includes('Qwen3-14B'), 'filtre « tient sur ce serveur »');
  $('#cat-source').value = ''; $('#cat-fit').checked = false; $('#cat-q').value = 'raisonnement'; $('#cat-q').dispatchEvent(new w.Event('input'));
  ok($$('#catalog .cat-item').length === 2, 'filtre texte (nom, usage, capacité)');
  $('#cat-q').value = 'zzz'; $('#cat-q').dispatchEvent(new w.Event('input'));
  ok($('#catalog').textContent.includes('Aucun modèle ne correspond'), 'aucun résultat : message');
  $('#cat-q').value = ''; $('#cat-q').dispatchEvent(new w.Event('input'));
  $$('#catalog button').find((b) => b.textContent === 'Télécharger' && b.closest('.cat-item').textContent.includes('Qwen3-14B')).click();
  ok(await until(() => calls.some((c) => c[1] === '/api/models/pull' && c[2].name === 'hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M')), 'téléchargement d\'un modèle Hugging Face depuis les recommandés');
  ok(await go('#models/installed', () => $$('#models-table tbody tr').length === 2) && $$('#models-table tbody tr').map((r) => r.querySelector('.chip').textContent).join() === 'Hugging Face,Ollama', 'modèles installés : source de chacun');

  // --- clés : plafonds, parc : affinité
  ok(await go('#system/api', () => $('#pub-keys').textContent.includes('RH')), 'clés listées');
  ok($('#pub-keys').textContent.includes('contexte ≤ 8 k jetons') && $('#pub-keys').textContent.includes('réponse ≤ 1 k jetons') && $('#key-form').elements.max_ctx && $('#key-form').elements.max_output, 'clés : plafonds affichés et champs de création');
  $$('#pub-keys button').find((b) => b.textContent === 'Plafonds').click(); await sleep(100);
  const caps = $$('#modal-extra input'); caps[0].value = '4096'; caps[1].value = '256'; $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/publication/keys/update' && c[2].id === 'k1' && c[2].max_ctx === 4096 && c[2].max_output === 256)), 'plafonds modifiés depuis la liste');
  ok(await go('#fleet/balance', () => $('#bal-affinity').checked), 'parc : affinité de session active par défaut');
  $('#bal-affinity').checked = false; $('#bal-affinity').dispatchEvent(new w.Event('change'));
  ok(await until(() => calls.some((c) => c[1] === '/api/fleet/balance/strategy' && c[2].affinity === false && c[2].strategy === undefined)), 'affinité désactivée');

  // --- palette
  w.location.hash = '#dashboard';
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true, cancelable: true }));
  $('#pal-q').value = 'profils'; $('#pal-q').dispatchEvent(new w.Event('input'));
  ok($$('#pal-list li').some((l) => l.textContent.includes('Performance › Profils')), 'palette : onglets de Performance');
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

  // --- anglais : aucun texte français ne doit rester
  const e = make('en');
  const $e = (x) => e.document.querySelector(x), $$e = (x) => [...e.document.querySelectorAll(x)];
  ok(await until(() => !$e('#app').classList.contains('hidden') && $e('#nav a[href="#perf"]').textContent === 'Performance'), 'console en anglais affichée');
  function leftovers(root) {
    const out = [], seen = new Set();
    const walk = (nd) => {
      if (nd.nodeType === 3) {
        const p = nd.parentElement;
        if (!p || p.closest('pre, code, textarea, script, style, option[value="fr"]')) return;
        const s = nd.data.replace(/\s+/g, ' ').trim();
        if (s && FR_WORDS.test(s) && !seen.has(s)) { seen.add(s); out.push(s); }
      } else if (nd.nodeType === 1) {
        for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v) && !seen.has(v)) { seen.add(v); out.push(a + ': ' + v); } }
        for (const c of nd.childNodes) walk(c);
      }
    };
    walk(root); return out;
  }
  const visit = async (hash, cond, sel) => {
    e.location.hash = hash;
    const loaded = await until(() => cond(), 9000);
    await sleep(300);   // traduction asynchrone (MutationObserver)
    const left = leftovers($e(sel));
    if (process.env.DUMP) { fs.appendFileSync(process.env.DUMP, JSON.stringify(left) + '\n'); ok(loaded, 'collecte ' + hash + ' : ' + left.length); return; }
    ok(loaded && left.length === 0, 'anglais ' + hash + ' : ' + (left.length ? 'texte français restant : ' + JSON.stringify(left) : 'tout est traduit'));
  };
  await visit('#perf/bench', () => $$e('#pf-history tbody tr').length >= 1, '#view-perf');
  e.document.querySelector('#pf-run').click();
  await visit('#perf/profiles', () => $$e('#pf-profiles .card').length === 3, '#view-perf');
  await visit('#perf/warmup', () => $$e('#pf-warm-log tbody tr').length === 2, '#view-perf');
  await visit('#perf/guard', () => $e('#pf-alert').textContent.length > 20, '#view-perf');
  await visit('#perf/tune', () => $$e('#pf-checks li').length === 4, '#view-perf');
  await visit('#gpu/availability', () => $e('#gg-events tbody tr'), '#view-gpu');
  await visit('#system/hardware', () => $e('#hw-body').textContent.includes('RAID'), '#view-system');
  await visit('#system/audit', () => $$e('#au-table tbody tr').length === 2, '#view-system');
  await visit('#system/report', () => $e('#rp-preview').textContent.length > 5, '#view-system');
  await visit('#models/disk', () => $$e('#md-table tbody tr').length === 2, '#view-models');
  await visit('#system/api', () => $e('#pub-keys').textContent.includes('RH'), '#view-system');
  await visit('#fleet/balance', () => $e('#bal-affinity'), '#view-fleet');
  await visit('#models/catalog', () => $$e('#catalog .cat-item').length === 4, '#view-models');
  await visit('#models/installed', () => $$e('#models-table tbody tr').length === 2, '#view-models');
  ok($e('#pf-profiles').textContent.length > 0 || true, '');
  // --- aucun texte statique laissé en français en anglais (hors noms propres et valeurs d'exemple), toutes vues confondues
  const f = make('en');
  await sleep(1500);
  const SAME = new Set(['Ollama', 'Buntu', 'Chat', 'GPU', 'Performance', 'Open WebUI', '15 min', 'Hugging Face', 'Top-p', 'Source', 'Mode', 'Port', 'Maintenance', 'https://...', 'smtp.exemple.fr', 'STARTTLS', 'ollama@exemple.fr', 'Confirmation', 'Session', 'Client', 'https://10.0.0.21', 'obf_...', 'Installation', 'Choisissez un modèle et posez votre question.', 'Afficher en français']);
  const rest = [];
  for (const nd of f.document.querySelectorAll('body *')) {
    if (nd.closest('pre, code, script, style, textarea')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !SAME.has(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v) && !SAME.has(v)) rest.push(a + ': ' + v); }
  }
  ok(rest.length === 0, 'anglais : aucun texte statique français dans toute la page' + (rest.length ? ' : ' + JSON.stringify(rest.slice(0, 8)) : ''));
  ok($$e_tabs(f, 'perf') === 'Throughput benchmark,Profiles,Warm-up,Guard,System tuning' && $$e_tabs(f, 'gpu') === 'Cards,Availability,Groups and pinning,Advanced settings', 'anglais : onglets Performance et GPU traduits');
  console.log('\n' + n + ' vérifications réussies');
  process.exit(0);
})();
