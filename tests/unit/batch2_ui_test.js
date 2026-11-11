// Console web, second lot : thème, cloche, parc, statistiques, filtres et export CSV, palette Ctrl+K, graphes GPU, échéance des clés, Prometheus.
// Prérequis : npm install jsdom  (ou NODE_PATH vers un jsdom installé).   Usage : node tests/unit/batch2_ui_test.js
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
let prom = { enabled: false, created: null, path: '/metrics' };
const REQS = [
  { ts: now - 10, client: 'RH', model: 'gemma4:12b', status: 200, ms: 900, in_tok: 10, out_tok: 50, tps: 40, path: '/api/chat', instance: 'local' },
  { ts: now - 20, client: 'local', model: 'llama3.2:3b', status: 500, ms: 50, path: '/api/chat', instance: 'local' },
  { ts: now - 30, client: 'RH', model: 'llama3.2:3b', status: 200, aborted: true, ms: 70, path: '/api/generate', instance: 'local' }];
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/status') return json({ version: 'v', hostname: 'srv', os: 'Ubuntu', kernel: 'k', uptime: 10, boot_time: 1, ips: [], cpu: { model: 'x', cores: 1, load: [0, 0, 0], usage: 0 },
    memory: { total: 1, available: 1 }, disk: { total: 1, used: 0, free: 1, models: 0 }, gpu: { devices: [], compute: [], reboot_required: false }, gpu_live: [],
    ollama: { version: '0.1', service: 'active', exposed: false, running: [], publication: {} }, reboot_required: false, update_available: null, offload: [], alerts: [] });
  if (p === '/api/alerts') return json({ config: { enabled: false, webhook: { url: '' }, smtp: { host: '', port: 587, user: '', from: '', to: [], starttls: true }, events: [], disk_pct: 90, gpu_temp: 85, tps_min: 0 },
    events: { key_expiry: "Clé d'API expirée ou bientôt expirée" }, active: [{ key: 'disk', severity: 'warning', text: 'Disque occupé à 95 %' }, { key: "key_expiry:RH", severity: 'info', text: "Clé d'API « RH » expire dans 3 jour(s)" }], last_error: '' });
  if (p === '/api/fleet/servers') return json({ servers: [{ id: 's1', name: 'Srv1', state: 'en ligne', route: true, data: { gpu_live: [{ util: 45, mem_used: 3 * GB, mem_total: 8 * GB }], ollama: { running: [{ name: 'gemma4:12b' }] } } },
    { id: 's2', name: 'Srv2', state: 'hors ligne', error: 'délai dépassé', route: false, data: null }], actions: {}, sync_kinds: {}, local_models: [] });
  if (p.startsWith('/api/metrics')) return json({ span: 3600, interval: 10, gpus: { '0000:01:00.0': 'Quadro RTX 4000' }, series: [{ t: now - 60, cpu: 5, mem: 20, gpus: { '0000:01:00.0': { u: 50, m: 40, t: 66, p: 90 } }, rpm: 1, tok_s: 2, tps: 30, ttft: 200 }] });
  if (p.startsWith('/api/requests/export')) return json({});
  if (p.startsWith('/api/requests/settings')) return json({ prompt_excerpt: false, chars: 120, days: 7 });
  if (p.startsWith('/api/requests')) return json({ requests: REQS, summary: [], prompt_excerpt: false });
  if (p.startsWith('/api/usage')) return json({ span: p.includes('604800') ? 604800 : 86400, total: { count: 3, errors: 1, in_tok: 10, out_tok: 50, ms: 1020 },
    models: [{ name: 'gemma4:12b', count: 2, errors: 0, in_tok: 10, out_tok: 50, ms: 900 }, { name: 'llama3.2:3b', count: 1, errors: 1, in_tok: 0, out_tok: 0, ms: 50 }],
    clients: [{ name: 'RH', count: 2, errors: 0, in_tok: 10, out_tok: 50, ms: 900 }, { name: 'local', count: 1, errors: 1, in_tok: 0, out_tok: 0, ms: 50 }],
    buckets: Array.from({ length: 24 }, (_, i) => ({ t: now - (24 - i) * 3600, count: i === 23 ? 3 : 0, errors: i === 23 ? 1 : 0, in_tok: 0, out_tok: 0, ms: 0 })) });
  if (p === '/api/prom') return json(prom);
  if (p === '/api/prom/token') { prom = body.action === 'create' ? { enabled: true, created: now, path: '/metrics' } : { enabled: false, created: null, path: '/metrics' }; return json({ ok: true, token: body.action === 'create' ? 'obm_secret_token' : null }); }
  if (p === '/api/limits') return json({ keys: [] });
  if (p === '/api/publication') return json({ enabled: true, tls: true, port: 11443, auth: true, allow: [], anonymous: { perms: [], models: [] }, urls: ['https://srv:11443'], router: {}, keys: [
    { id: 'k1', name: 'RH', prefix: 'ob_a', perms: ['inference'], deny: [], models: [], enabled: true, usage: {}, expires: '2026-11-14', days_left: 3 },
    { id: 'k2', name: 'Vieille', prefix: 'ob_b', perms: ['inference'], deny: [], models: [], enabled: true, usage: {}, expires: '2026-01-01', days_left: -300 },
    { id: 'k3', name: 'Lointaine', prefix: 'ob_c', perms: ['inference'], deny: [], models: [], enabled: true, usage: {}, expires: '2030-01-01', days_left: 1000 },
    { id: 'k4', name: 'Sans', prefix: 'ob_d', perms: ['inference'], deny: [], models: [], enabled: true, usage: {}, expires: '', days_left: null }] });
  if (p === '/api/publication/keys/create') return json({ ok: true, key: { name: body.name }, token: 'ob_tok' });
  if (p === '/api/models') return json({ models: [] });
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
(async () => {
  const w = make();
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  const key = (k, o = {}) => w.document.dispatchEvent(new w.KeyboardEvent('keydown', Object.assign({ key: k, bubbles: true, cancelable: true }, o)));
  ok(await until(() => !$('#app').classList.contains('hidden')), 'console affichée');

  // 1. thème
  const root = w.document.documentElement;
  ok(!root.hasAttribute('data-theme') && $('#theme-btn').getAttribute('aria-label') === 'Thème : automatique', 'thème : automatique au départ');
  $('#theme-btn').click();
  ok(root.getAttribute('data-theme') === 'light' && w.localStorage.getItem('ob-theme') === 'light' && $('#theme-btn').getAttribute('aria-label') === 'Thème : clair', 'thème : clair, mémorisé');
  $('#theme-btn').click();
  ok(root.getAttribute('data-theme') === 'dark', 'thème : sombre');
  $('#theme-btn').click();
  ok(!root.hasAttribute('data-theme') && w.localStorage.getItem('ob-theme') === 'auto', 'thème : retour à automatique');
  const css = fs.readFileSync(path.join(WEB, 'app.css'), 'utf8');
  ok(css.includes(':root[data-theme=dark]') && css.includes(':root:not([data-theme=light])'), 'feuille de style : thème forcé et thème du système respectant le choix « clair »');

  // 2. cloche
  ok(await until(() => $('#bell-n').textContent === '2' && !$('#bell-n').classList.contains('hidden')), 'cloche : 2 alertes comptées');
  ok($('#bell').getAttribute('aria-label') === '2 alerte(s) active(s)', 'cloche : libellé accessible');
  $('#bell').click();
  ok(!$('#bell-pop').classList.contains('hidden') && $('#bell-pop').textContent.includes('Disque occupé à 95 %') && $('#bell-pop').textContent.includes('expire dans 3 jour(s)') && $('#bell').getAttribute('aria-expanded') === 'true', 'cloche : liste des alertes ouverte');
  ok($('#bell-pop a').getAttribute('href') === '#system/alerts', 'cloche : lien vers la configuration');
  key('Escape');
  ok($('#bell-pop').classList.contains('hidden'), 'cloche : fermée par Échap');

  // 3. parc sur le tableau de bord
  ok(await until(() => $('#dash-fleet').textContent.includes('Srv1')), 'tableau de bord : carte du parc');
  const ft = $('#dash-fleet').textContent;
  ok(ft.includes('GPU 45 %') && ft.includes('gemma4:12b') && ft.includes('Srv2') && ft.includes('hors ligne') && ft.includes('délai dépassé') && ft.includes('répartition'), 'parc : charge GPU, modèle chargé, serveur hors ligne et répartition');

  // 4. graphes GPU
  ok(await until(() => $('#perf-charts').textContent.includes('Température GPU') && $('#perf-charts').textContent.includes('Puissance GPU')), 'graphiques : température et puissance des GPU');

  // 5. requêtes : filtres et export
  w.location.hash = '#logs/requests';
  ok(await until(() => $$('#req-list tbody tr').length === 3), 'requêtes : 3 lignes');
  $('#rf-q').value = 'llama'; $('#rf-q').dispatchEvent(new w.Event('input'));
  ok($$('#req-list tbody tr').length === 2 && $('#rf-count').textContent === '2 résultat(s) sur 3', 'filtre texte : modèle');
  $('#rf-status').value = 'error'; $('#rf-status').dispatchEvent(new w.Event('change'));
  ok($$('#req-list tbody tr').length === 2, 'filtre statut : erreurs et interruptions');
  $('#rf-status').value = 'ok'; $('#rf-status').dispatchEvent(new w.Event('change'));
  ok($$('#req-list tbody tr').length === 0, 'filtres combinés : aucune requête réussie pour « llama »');
  $('#rf-q').value = 'RH'; $('#rf-q').dispatchEvent(new w.Event('input'));
  ok($$('#req-list tbody tr').length === 1 && $('#req-list').textContent.includes('gemma4:12b'), 'filtre par client + réussies');
  $('#rf-export').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/requests/export?q=RH&status=ok') && w.__downloads.some((d) => /^requetes-\d{4}-\d{2}-\d{2}\.csv$/.test(d))), 'export CSV : filtres transmis, fichier téléchargé');

  // 6. statistiques
  w.location.hash = '#logs/stats';
  ok(await until(() => $('#st-body').textContent.includes('Par client')), 'statistiques : écran');
  const st = $('#st-body').textContent;
  ok(st.includes('33 %') && st.includes('gemma4:12b') && st.includes('RH') && st.includes('2 - 60 jetons'), 'statistiques : taux d\'erreur, modèles, clients et jetons');
  ok($$('#st-body svg rect').length >= 25 && $$('#st-body svg title')[0].textContent.includes('requête(s)'), 'statistiques : histogramme (24 tranches + erreurs, infobulles)');
  $$('#st-range button')[1].click();
  ok(await until(() => calls.some((c) => c[1] === '/api/usage?span=604800')), 'statistiques : période de 7 jours');

  // 7. clés : échéance
  w.location.hash = '#system/api';
  ok(await until(() => $('#pub-keys').textContent.includes('Lointaine')), 'clés listées');
  const kt = $('#pub-keys').textContent;
  ok(kt.includes('expire dans 3 j') && kt.includes('expirée') && kt.includes('expire le 2030-01-01'), 'clés : échéance proche, clé expirée, échéance lointaine');
  ok(!$$('#pub-keys tbody tr')[3].textContent.includes('expire'), 'clé sans échéance : aucune mention');
  ok($('#key-form').elements.expires.type === 'date', 'formulaire de clé : champ d\'échéance');
  const kf = $('#key-form'); kf.elements.name.value = 'Stage'; kf.elements.expires.value = '2027-01-31'; kf.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/publication/keys/create' && c[2].expires === '2027-01-31' && c[2].name === 'Stage')), 'création de clé : échéance envoyée');
  await sleep(150); $('#modal-ok').click(); await sleep(50);
  $$('#pub-keys button').find((b) => b.textContent === 'Échéance').click();
  await sleep(100);
  const inp = $('#modal-extra input'); inp.value = '2028-02-02'; $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/publication/keys/update' && c[2].id === 'k1' && c[2].expires === '2028-02-02')), 'échéance modifiée depuis la liste');

  // 8. Prometheus
  ok(await until(() => $('#prom-state').textContent.includes('Export désactivé') && $('#prom-create').textContent === 'Générer un jeton' && $('#prom-revoke').classList.contains('hidden')), 'Prometheus : désactivé au départ');
  $('#prom-create').click();
  ok(await until(() => $('#modal-extra').textContent.includes('obm_secret_token') && calls.some((c) => c[1] === '/api/prom/token' && c[2].action === 'create')), 'Prometheus : jeton affiché une fois');
  $('#modal-ok').click();
  ok(await until(() => $('#prom-state').textContent.includes('metrics_path: /metrics') && $('#prom-state').textContent.includes('srv') && !$('#prom-revoke').classList.contains('hidden') && $('#prom-create').textContent === 'Remplacer le jeton'), 'Prometheus : configuration d\'exemple et boutons');
  ok(!$('#prom-state').textContent.includes('obm_secret_token'), 'Prometheus : le jeton n\'est plus affiché');
  $('#prom-revoke').click(); await sleep(100); $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/prom/token' && c[2].action === 'revoke') && $('#prom-state').textContent.includes('Export désactivé')), 'Prometheus : jeton révoqué');

  // 9. palette de commandes
  w.location.hash = '#dashboard';
  key('k', { ctrlKey: true });
  ok(!$('#palette').classList.contains('hidden') && w.document.activeElement === $('#pal-q') && $$('#pal-list li').length > 10, 'palette : ouverte par Ctrl+K, focus dans la recherche');
  $('#pal-q').value = 'journ'; $('#pal-q').dispatchEvent(new w.Event('input'));
  ok($$('#pal-list li')[0].textContent.includes('Journaux') && $$('#pal-list li').every((l) => l.textContent.toLowerCase().includes('journ')), 'palette : filtre');
  $('#pal-q').value = 'stat'; $('#pal-q').dispatchEvent(new w.Event('input'));
  ok($$('#pal-list li').some((l) => l.textContent.includes('Journaux › Statistiques')), 'palette : onglets proposés');
  $('#pal-q').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  ok($('#palette').classList.contains('hidden') && w.location.hash === '#logs/stats', 'palette : Entrée ouvre l\'onglet');
  key('k', { ctrlKey: true });
  $('#pal-q').value = 'theme'; $('#pal-q').dispatchEvent(new w.Event('input'));
  ok($$('#pal-list li')[0].textContent.includes('Changer de thème'), 'palette : recherche sans accent');
  $('#pal-q').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  ok(root.getAttribute('data-theme') === 'light', 'palette : action « changer de thème »');
  key('k', { ctrlKey: true });
  $('#pal-q').value = 'zzzz'; $('#pal-q').dispatchEvent(new w.Event('input'));
  ok($('#pal-list').textContent.includes('Aucun résultat.'), 'palette : aucun résultat');
  $('#pal-q').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  ok($('#palette').classList.contains('hidden'), 'palette : fermée par Échap');

  // 10. anglais
  const e = make('en');
  const $e = (x) => e.document.querySelector(x);
  ok(await until(() => !$e('#app').classList.contains('hidden') && $e('#bell-n').textContent === '2'), 'console en anglais affichée');
  ok($e('#theme-btn').getAttribute('aria-label') === 'Theme: automatic' && $e('#bell').getAttribute('aria-label') === '2 active alert(s)', 'anglais : thème et cloche');
  e.document.getElementById('bell').click();
  ok(await until(() => $e('#bell-pop').textContent.includes('API key “RH” expires in 3 day(s)') && $e('#bell-pop').textContent.includes('Disk 95% full')), 'anglais : alertes de la cloche');
  ok(await until(() => $e('#dash-fleet').textContent.includes('GPU 45% - ') && $e('#dash-fleet').textContent.includes('In memory: gemma4:12b') && $e('#dash-fleet').textContent.includes('Server fleet')), 'anglais : parc sur le tableau de bord');
  e.location.hash = '#logs/stats';
  ok(await until(() => $e('#st-body').textContent.includes('By client') && $e('#st-body').textContent.includes('2 - 60 tokens') && $e('#st-body').textContent.includes('Error rate')), 'anglais : statistiques');
  e.location.hash = '#system/api';
  ok(await until(() => $e('#pub-keys').textContent.includes('expires in 3 d') && $e('#pub-keys').textContent.includes('expired') && $e('#pub-keys').textContent.includes('expires on 2030-01-01')), 'anglais : échéances des clés');
  ok($e('#prom-card').textContent.includes('Prometheus export') && $e('#prom-create').textContent === 'Generate a token', 'anglais : export Prometheus');
  e.location.hash = '#logs/requests';
  ok(await until(() => $e('#rf-export').textContent === 'Export as CSV'), 'anglais : export CSV');
  console.log('\n' + n + ' vérifications réussies');
  process.exit(0);
})();
