// Console web : réinitialisation du mot de passe administrateur d'Open WebUI (écran Open WebUI), en français puis en anglais.
// Prérequis : jsdom (NODE_PATH).   Usage : node tests/unit/webui_pwd_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
const EN = JSON.parse(fs.readFileSync(path.join(WEB, 'i18n', 'en.json'), 'utf8'));
let n = 0;
process.on('unhandledRejection', () => {});
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
const calls = []; let deployed = true, reply = null;
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined;
  calls.push([o.method || 'GET', p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/webui') return json({ docker: true, configured: deployed, container: deployed ? 'running' : null, running: deployed, healthy: deployed, version: '0.6', latest: '0.6',
    tls_port: 8443, admin_email: deployed ? 'alice@x.fr' : null, public_url: '', started: '2026-11-17 10:00:00' });
  if (p === '/api/webui/password') return reply ? json(reply.body, reply.status) : json({ ok: true, email: body.email || 'alice@x.fr' });
  return json({});
}
function make(lang) {
  const dom = new JSDOM(html, { url: 'https://srv/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  if (lang) w.localStorage.setItem('ob-lang', lang);
  w.fetch = async (p, o) => (p === '/i18n/en.json' ? json(EN) : fakeFetch(p, o));
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {};
  w.eval(js);
  return w;
}
async function run(l) {
  const lang = l || 'fr'; calls.length = 0;
  const w = make(l), $ = (s) => w.document.querySelector(s);
  ok(await until(() => !$('#app').classList.contains('hidden')), lang + ' : console affichée');
  w.location.hash = '#webui';
  ok(await until(() => !$('#webui-pwd').classList.contains('hidden')), lang + ' : carte du mot de passe visible quand Open WebUI est déployé');
  const f = $('#webui-pwd-form'), msg = $('#webui-pwd-msg');
  ok(f.elements.email.placeholder.includes('alice@x.fr'), lang + ' : placeholder sur l\'administrateur configuré');
  const submit = () => f.dispatchEvent(new w.Event('submit', { cancelable: true, bubbles: true }));
  f.elements.password.value = 'abcdefgh1'; f.elements.confirm.value = 'different1'; submit(); await sleep(150);
  ok(msg.classList.contains('error') && !calls.some((c) => c[1] === '/api/webui/password'), lang + ' : confirmation différente refusée sans appel');
  f.elements.confirm.value = 'abcdefgh1'; f.elements.email.value = 'bob@x.fr'; submit();
  ok(await until(() => msg.classList.contains('okmsg')), lang + ' : succès affiché');
  const c = calls.filter((x) => x[1] === '/api/webui/password').pop();
  ok(c && c[2].email === 'bob@x.fr' && c[2].password === 'abcdefgh1', lang + ' : e-mail et mot de passe envoyés');
  ok(msg.textContent.includes('bob@x.fr') && (lang === 'en' ? msg.textContent.startsWith('Password reset for') : msg.textContent.startsWith('Mot de passe réinitialisé')), lang + ' : message de succès : ' + msg.textContent);
  ok(f.elements.password.value === '' && f.elements.confirm.value === '', lang + ' : champs vidés après succès');
  reply = { status: 404, body: { error: 'Aucun compte Open WebUI avec cette adresse. Administrateurs : alice@x.fr, zoe@x.fr' } };
  f.elements.password.value = 'abcdefgh1'; f.elements.confirm.value = 'abcdefgh1'; submit();
  ok(await until(() => msg.classList.contains('error') && !msg.classList.contains('okmsg') && msg.textContent.includes('zoe@x.fr')), lang + ' : compte inconnu : erreur avec la liste des administrateurs : ' + msg.textContent);
  if (lang === 'en') ok(msg.textContent.startsWith('No Open WebUI account with this address. Administrators:'), 'anglais : erreur traduite');
  reply = null;
  deployed = false; w.document.querySelector('#webui-refresh').click();
  ok(await until(() => $('#webui-pwd').classList.contains('hidden')), lang + ' : carte masquée quand Open WebUI n\'est pas déployé');
  deployed = true;
}
(async () => { await run(); await run('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
