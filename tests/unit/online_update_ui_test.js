// Console web : écran « Appliance » (mise à jour depuis Internet). Navigateur simulé jsdom, API simulée.
// Prérequis : npm install jsdom  (ou NODE_PATH vers un jsdom installé).   Usage : node tests/unit/online_update_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', () => {});   // autres écrans de la console : API simulée incomplète, sans rapport avec ce test
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }

const calls = [];
let online = { installed: '2026.01.01-0000', config: { repo: 'o/r', channel: 'stable', auto_check: false }, token_set: false, checked_at: null, error: null, latest: null, available: false, signed: true };
const NEW = { version: '2026.05.01-0800', tag: 'v2026.05.01-0800', prerelease: false, notes: 'Notes <b>de</b> version', url: 'https://github.com/o/r/releases/tag/v2026.05.01-0800' };
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o });
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: online.installed, lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: online.installed });
  if (p === '/api/status') return json({ version: online.installed, hostname: 'srv', os: 'Ubuntu', kernel: 'k', uptime: 10, boot_time: 1, ips: [], cpu: { model: 'x', cores: 1, load: [0, 0, 0], usage: 0 },
    memory: { total: 1, available: 1 }, disk: { total: 1, used: 0, free: 1, models: 0 }, gpu: { devices: [], compute: [], reboot_required: false }, gpu_live: [],
    ollama: { version: '0.1', service: 'active', exposed: false, running: [], publication: {} }, reboot_required: false, update_available: online.available ? online.latest.version : null });
  if (p === '/api/about') return json({ version: online.installed, build: { build_date: 'x', ubuntu: 'U', ollama: 'v0.50.0', models: '' }, os: 'U', kernel: 'k', updates: [], ollama: '0.50.0', hostname: 'srv', boot_time: 1 });
  if (p === '/api/update/online') return json(online);
  if (p === '/api/update/online/check') { online = Object.assign({}, online, { checked_at: 1760000000, latest: NEW, available: true, error: null }); return json(Object.assign({ ok: true }, online)); }
  if (p === '/api/update/online/config') {
    online = Object.assign({}, online, { config: { repo: body.repo, channel: body.channel, auto_check: body.auto_check }, token_set: body.clear_token ? false : (body.token ? true : online.token_set) });
    return json(Object.assign({ ok: true }, online));
  }
  if (p === '/api/action') return json({ job: '20261110-100000-appliance-update-online' });
  if (p.startsWith('/api/jobs/')) return json({ id: 'x', title: 'Mise à jour', done: true, rc: 0, output: 'ok' });
  return json({});
}

const EN = JSON.parse(fs.readFileSync(path.join(WEB, 'i18n', 'en.json'), 'utf8'));
function make(lang) {
  const dom = new JSDOM(html, { url: 'https://srv/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  if (lang) w.localStorage.setItem('ob-lang', lang);
  w.fetch = async (p, o) => (p === '/i18n/en.json' ? json(EN) : fakeFetch(p, o));
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {};
  w.nativeDialogs = 0; w.confirm = w.alert = w.prompt = () => { w.nativeDialogs++; return true; };
  w.eval(js);
  return w;
}
(async () => {
  const w = make();
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  ok(await until(() => !$('#app').classList.contains('hidden')), 'console affichée (session administrateur)');
  w.location.hash = '#system/appliance';
  ok(await until(() => !$('#panel-system-appliance').classList.contains('hidden')), 'onglet « Appliance » de l\'écran Système accessible par #system/appliance');
  ok($$('#panel-system-appliance > .card').length === 2, 'onglet Appliance : deux cartes au plus (Internet, À propos + ISO)');
  ok($$('#view-system > .subtabs a').map((a) => a.dataset.key).join() === 'overview,appliance,updates,api,central', 'ordre des onglets : ' + $$('#view-system > .subtabs a').map((a) => a.textContent).join(' | '));
  ok($('#appliance-update') && $('#panel-system-appliance').contains($('#appliance-update')), 'la mise à jour par ISO/clé USB est dans le même onglet');
  ok(await until(() => /v2026\.01\.01-0000/.test($('#ou-state').textContent)), 'version installée affichée : ' + $('#ou-state').textContent.replace(/\s+/g, ' ').slice(0, 120));
  ok(/jamais vérifié/.test($('#ou-state').textContent) && $('#ou-apply').classList.contains('hidden'), 'état initial « jamais vérifié », bouton de mise à jour masqué');
  ok($('#ou-form').elements.repo.value === 'o/r' && !$('#ou-form').elements.auto_check.checked, 'réglages : dépôt livré, vérification automatique décochée par défaut');

  $('#ou-check').click();
  ok(await until(() => !$('#ou-apply').classList.contains('hidden')), 'après « Rechercher » : bouton « ' + $('#ou-apply').textContent + ' »');
  ok(/nouvelle version disponible/.test($('#ou-state').textContent) && /v2026\.05\.01-0800/.test($('#ou-state').textContent), 'état : nouvelle version disponible');
  ok($('#ou-notes pre') && $('#ou-notes pre').textContent === 'Notes <b>de</b> version' && !$('#ou-notes pre b'), 'notes de version affichées comme du texte (aucun HTML interprété)');
  const link = $('#ou-notes a');
  ok(link && link.getAttribute('href').startsWith('https://github.com/') && /noopener/.test(link.rel) && link.target === '_blank', 'lien vers la release GitHub (noopener)');
  w.location.hash = '#about'; await sleep(100); w.location.hash = '#system/overview';   // le retour sur l'écran Système recharge l'état
  ok(await until(() => /v2026\.05\.01-0800 est publié/.test($('#sys-update-note').textContent)), 'vue d\'ensemble : « ' + $('#sys-update-note').textContent.trim() + ' »');
  ok($('#sys-update-note a').getAttribute('href') === '#system/appliance', 'le bandeau renvoie vers l\'onglet Appliance');

  // réglages
  const f = $('#ou-form');
  f.elements.repo.value = 'https://github.com/o/autre'; f.elements.channel.value = 'preview'; f.elements.auto_check.checked = true; f.elements.token.value = 'ghp_' + 'Z9y8X7w6'.repeat(4);
  f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => /Enregistré/.test($('#ou-cfg-msg').textContent)), 'réglages enregistrés');
  const saved = calls.filter((c) => c[1] === '/api/update/online/config').pop()[2];
  ok(saved.repo === 'https://github.com/o/autre' && saved.channel === 'preview' && saved.auto_check === true && saved.token.startsWith('ghp_'), 'corps envoyé : dépôt, canal, vérification automatique, jeton');
  ok($('#ou-form').elements.token.value === '' && /Jeton enregistré/.test($('#ou-form').elements.token.placeholder), 'le champ du jeton est vidé après enregistrement');
  ok(!$('#ou-token-clear').disabled, 'bouton « Retirer le jeton » actif');

  // application : confirmation puis tâche, avec la version affichée
  $('#ou-apply').click();
  ok(await until(() => !$('#modal').classList.contains('hidden')), 'confirmation demandée avant de lancer la mise à jour');
  const msg = $('#modal').textContent;
  ok(/v2026\.01\.01-0000/.test(msg) && /v2026\.05\.01-0800/.test(msg) && /signature/.test(msg), 'la confirmation indique les deux versions et la vérification de la signature');
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/action')), 'tâche lancée');
  const act = calls.filter((c) => c[1] === '/api/action').pop()[2];
  ok(act.action === 'appliance-update-online' && act.tag === 'v2026.05.01-0800', 'action « appliance-update-online » avec la version affichée (' + act.tag + ')');

  // l'ISO garde son action d'origine (régression : le gestionnaire reçoit un événement de clic)
  calls.length = 0;
  $('#appliance-update').click();
  ok(await until(() => !$('#modal').classList.contains('hidden')), 'ISO : confirmation demandée');
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/action')) && calls.filter((c) => c[1] === '/api/action')[0][2].action === 'appliance-update', 'ISO / clé USB : action « appliance-update » inchangée');
  ok(w.nativeDialogs === 0, 'aucune fenêtre système (alert / confirm / prompt)');

  // --- même parcours en anglais : aucun texte français ne doit rester dans l'onglet ni dans les messages
  online = Object.assign({}, online, { checked_at: null, latest: null, available: false, error: null });
  const e = make('en'), E$ = (q) => e.document.querySelector(q), frText = (el) => (el.textContent.match(/[À-ÿ]/g) || []).length;
  ok(await until(() => !E$('#app').classList.contains('hidden')), 'anglais : console affichée');
  e.location.hash = '#system/appliance';
  ok(await until(() => /never checked/.test(E$('#ou-state').textContent)), 'anglais : état initial traduit (' + E$('#ou-state').textContent.replace(/\s+/g, ' ').slice(0, 90) + ')');
  E$('#ou-check').click();
  ok(await until(() => !E$('#ou-apply').classList.contains('hidden')), 'anglais : bouton « ' + E$('#ou-apply').textContent + ' »');
  ok(E$('#ou-apply').textContent === 'Update to v2026.05.01-0800', 'anglais : libellé du bouton traduit');
  ok(frText(E$('#panel-system-appliance .card')) === 0, 'anglais : aucun caractère accentué (français) dans la carte « Mise à jour depuis Internet » → ' + (E$('#panel-system-appliance .card').textContent.match(/\S*[À-ÿ]\S*/g) || []).join(' '));
  ok(E$('#ou-form').elements.repo.placeholder === 'owner/repository' || E$('#ou-form').elements.repo.value === 'o/r', 'anglais : réglages traduits');
  E$('#ou-apply').click();
  ok(await until(() => !E$('#modal').classList.contains('hidden') && /Update the appliance from v2026\.01\.01-0000 to v2026\.05\.01-0800/.test(E$('#modal').textContent)), 'anglais : confirmation traduite');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
