// Console web : alertes, débordement CPU/GPU, réglage automatique, limites des clés, règles de routage, retour arrière, sauvegarde, Hugging Face.
// Prérequis : npm install jsdom  (ou NODE_PATH vers un jsdom installé).   Usage : node tests/unit/ops_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', () => {});
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const GB = 1024 ** 3;
const calls = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: '2026.11.10-1055', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: '2026.11.10-1055' });
  if (p === '/api/status') return json({ version: '2026.11.10-1055', hostname: 'srv', os: 'Ubuntu', kernel: 'k', uptime: 10, boot_time: 1, ips: [], cpu: { model: 'x', cores: 1, load: [0, 0, 0], usage: 0 },
    memory: { total: 1, available: 1 }, disk: { total: 1, used: 0, free: 1, models: 0 }, gpu: { devices: [], compute: [], reboot_required: false }, gpu_live: [],
    ollama: { version: '0.1', service: 'active', exposed: false, running: [], publication: {} }, reboot_required: false, update_available: null,
    offload: [{ name: 'gemma4:12b', cpu_pct: 40, size: 10 * GB, vram: 6 * GB }], alerts: [{ key: 'disk', severity: 'warning', text: 'Disque occupé à 95 %' }] });
  if (p === '/api/alerts') return json({ config: { enabled: true, webhook: { url: 'https://h.example/x' }, smtp: { host: 'smtp.x', port: 587, user: 'u', from: 'a@b.fr', to: ['c@d.fr'], starttls: true, has_password: true },
    events: ['disk'], disk_pct: 90, gpu_temp: 85, tps_min: 0 }, events: { disk: 'Disque presque plein', offload: 'Modèle partiellement sur le processeur' }, active: [{ key: 'disk', text: 'Disque occupé à 95 %' }], last_error: '' });
  if (p === '/api/alerts/config' || p === '/api/alerts/test') return json({ ok: true, results: { webhook: 'ok' } });
  if (p === '/api/update/backups') return json({ installed: '2026.11.10-1055', backups: [{ file: 'appliance-2026.11.06-1509-20261110-105500.tar.gz', version: '2026.11.06-1509', stamp: '20261110-105500', size: 1 }, { file: 'appliance-2026.11.10-1055-20261111-080000.tar.gz', version: '2026.11.10-1055', stamp: '20261111-080000', size: 1 }] });
  if (p === '/api/tuning') return json({ vram: 8 * GB, gpus: ['Quadro RTX 4000'], current: { ctx: 32768, parallel: 4, kv_type: 'f16' }, models: [
    { name: 'gemma4:12b', weights: 7 * GB, max: 131072, known: true, fits: true, tokens: 20000, parallel: 2, ctx: 8192 }, { name: 'gros:70b', weights: 40 * GB, max: 8192, known: true, fits: false, tokens: 0, parallel: 1, ctx: null }] });
  if (p === '/api/tuning/apply') return json({ ok: true });
  if (p === '/api/limits') return json({ keys: [{ id: 'k1', name: 'RH', max_concurrent: 2, quota_day: 1000000, quota_month: 0, running: 2, waiting: 1, day: 250000, month: 900000, total: 900000, requests: 5 }], queue_total: { running: 2, waiting: 1 } });
  if (p === '/api/publication') return json({ enabled: true, tls: true, port: 11443, auth: true, allow: [], anonymous: { perms: [], models: [] }, urls: ['https://srv:11443'], router: {}, keys: [{ id: 'k1', name: 'RH', prefix: 'ob_abcdef', perms: ['inference'], deny: [], models: [], enabled: true, usage: {}, max_concurrent: 2, quota_day: 1000000 }] });
  if (p === '/api/models') return json({ models: [{ name: 'gemma4:12b', size: 7 * GB, details: {} }] });
  if (p === '/api/fleet/servers') return json({ servers: [{ id: 's1', name: 'Srv1', url: 'https://x', state: 'en ligne', route: true, data: null }], actions: {}, sync_kinds: {}, local_models: [] });
  if (p === '/api/fleet/rules') return json({ rules: [{ key: 'k1', model: 'gemma*', server: 's1', mode: 'only' }] });
  if (p.startsWith('/api/hf/files')) return json({ id: 'u/r-GGUF', uncensored: false, vram: 8 * GB, ram: 16 * GB, quants: [{ quant: 'Q2_K', size: 2 * GB, files: 1, fit: 'gpu' }, { quant: 'Q6_K', size: 7 * GB, files: 1, fit: 'partial' }, { quant: 'Q8_0', size: 30 * GB, files: 1, fit: 'no' }] });
  if (p.startsWith('/api/hf/search')) return json({ models: [{ id: 'u/r-GGUF', downloads: 1500, likes: 3, updated: '2026-11-01', uncensored: false }], mode: 'standard' });
  return json({});
}
const EN = JSON.parse(fs.readFileSync(path.join(WEB, 'i18n', 'en.json'), 'utf8'));
function make(lang) {
  const dom = new JSDOM(html, { url: 'https://srv/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  if (lang) w.localStorage.setItem('ob-lang', lang);
  w.fetch = async (p, o) => (p === '/i18n/en.json' ? json(EN) : fakeFetch(p, o));
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {};
  w.confirm = w.alert = w.prompt = () => true;
  w.eval(js);
  return w;
}
(async () => {
  const w = make();
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  ok(await until(() => !$('#app').classList.contains('hidden')), 'console affichée');
  ok(await until(() => $('#dash-alerts').textContent.includes('Disque occupé à 95 %')), 'tableau de bord : alerte active affichée');
  ok($('#dash-alerts').textContent.includes('gemma4:12b tourne à 40 % sur le processeur'), 'tableau de bord : débordement CPU/GPU signalé avec le pourcentage');
  ok($('#dash-alerts a[href="#models"]') !== null, 'lien vers le réglage recommandé');

  w.location.hash = '#models/tuning';
  ok(await until(() => $('#tuning-body').textContent.includes('gemma4:12b')), 'réglage automatique : modèles listés');
  const t = $('#tuning-body').textContent;
  ok(t.includes('2 en parallèle, contexte 8192') && t.includes('ne tient pas en VRAM') && t.includes('dépasse la mémoire disponible'), 'recommandation, modèle trop gros et réglage actuel excessif signalés');
  $$('#tuning-body button').find((b) => b.textContent === 'Appliquer').click();
  await sleep(150);
  const okBtn = $$('button').find((b) => b.textContent === 'Appliquer' && b.closest('.modal, dialog, [role=dialog]'));
  if (okBtn) { okBtn.click(); ok(await until(() => calls.some((c) => c[1] === '/api/tuning/apply' && c[2].parallel === 2 && c[2].ctx === 8192)), 'application : parallélisme 2, contexte 8192 envoyés'); }
  else ok(false, 'confirmation du réglage : boîte de dialogue introuvable');

  w.location.hash = '#models/hf';
  $('#hf-q').value = 'llama'; $('#hf-search').click();
  ok(await until(() => $('#hf-results').textContent.includes('u/r-GGUF')), 'Hugging Face : résultats');
  $$('#hf-results button')[0].click();
  ok(await until(() => $('#hf-quants').textContent.includes('Q6_K')), 'Hugging Face : quantifications');
  const q = $('#hf-quants').textContent;
  ok(q.includes('tient en VRAM') && q.includes('déborde sur le processeur') && q.includes('trop gros') && q.includes('Mémoire vidéo de ce serveur'), 'Hugging Face : adaptation à la VRAM de chaque quantification');

  w.location.hash = '#system/alerts';
  ok(await until(() => $('#al-form').elements.webhook.value === 'https://h.example/x'), 'alertes : configuration chargée');
  ok($('#al-form').elements.smtp_password.value === '' && $('#al-form').elements.smtp_password.placeholder.includes('enregistré'), 'alertes : le mot de passe SMTP n\'est jamais affiché');
  ok($('#al-active').textContent.includes('Disque occupé à 95 %') && $$('#al-events input').length === 2, 'alertes : alertes actives et événements');
  $('#al-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/alerts/config' && c[2].smtp.to[0] === 'c@d.fr' && c[2].webhook.url === 'https://h.example/x' && c[2].events[0] === 'disk')), 'alertes : enregistrement envoyé');

  w.location.hash = '#system/appliance';
  ok(await until(() => $('#rb-list').textContent.includes('v2026.11.06-1509')), 'retour arrière : sauvegardes listées');
  const rb = $$('#rb-list button');
  ok(rb.length === 1 && rb[0].textContent === 'Revenir à cette version' && $('#rb-list').textContent.includes('installée') && $('#rb-list').textContent.includes('10/11/2026 10:55'), 'retour arrière : version installée sans bouton, dates lisibles');

  w.location.hash = '#system/api';
  ok(await until(() => $('#pub-keys').textContent.includes('au plus 2 simultanée(s)')), 'clés : plafond affiché');
  const kt = $('#pub-keys').textContent;
  ok(kt.includes('2 en cours, 1 en attente') && kt.includes('jour : 250 k / 1,0 M jetons'), 'clés : file d\'attente et consommation du jour');
  ok($('#key-form').elements.max_concurrent && $('#key-form').elements.quota_day && $('#key-form').elements.quota_month, 'formulaire de clé : plafond et quotas');

  w.location.hash = '#fleet/rules';
  ok(await until(() => $('#rules-list').textContent.includes('gemma*')), 'règles de routage : liste');
  ok($('#rules-list').textContent.includes('RH') && $('#rules-list').textContent.includes('Uniquement sur') && $('#rules-list').textContent.includes('Srv1'), 'règles : client, règle et serveur nommés');
  const f = $('#rules-form'); f.elements.model.value = 'llama*'; f.elements.mode.value = 'never'; f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/fleet/rules' && c[2] && c[2].rules.length === 2 && c[2].rules[1].model === 'llama*' && c[2].rules[1].mode === 'never')), 'règles : ajout envoyé avec les règles existantes');
  ok($('#bal-check') !== null, 'bouton « Vérifier chaque serveur »');

  w.location.hash = '#system/backup';
  ok(await until(() => $('#bk-export') !== null && !$('#panel-system-backup').classList.contains('hidden')), 'sauvegarde de la configuration : écran');
  ok($('#bk-export').elements.passphrase.minLength === 12, 'phrase secrète : 12 caractères au minimum');
  // anglais : les nouveaux écrans sont traduits (alertes du serveur comprises)
  const e = make('en');
  const $e = (x) => e.document.querySelector(x);
  ok(await until(() => !$e('#app').classList.contains('hidden')), 'console en anglais affichée');
  ok(await until(() => $e('#dash-alerts').textContent.includes('Disk 95% full')), 'anglais : alerte du serveur traduite (« Disk 95% full »)');
  ok($e('#dash-alerts').textContent.includes('gemma4:12b runs 40% on the processor'), 'anglais : débordement CPU/GPU traduit');
  e.location.hash = '#fleet/rules';
  ok(await until(() => $e('#rules-list').textContent.includes('Only on')), 'anglais : règles de routage traduites');
  e.location.hash = '#system/api';
  ok(await until(() => $e('#pub-keys').textContent.includes('2 running, 1 waiting')), 'anglais : file d\'attente des clés traduite');
  ok($e('#pub-keys').textContent.includes('at most 2 simultaneous') && $e('#pub-keys').textContent.includes('day: 250 k / 1.0 M tokens'), 'anglais : plafond et quota traduits');
  process.exit(0);
})();
