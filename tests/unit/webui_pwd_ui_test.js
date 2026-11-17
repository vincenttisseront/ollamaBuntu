// Console web, écran Open WebUI : réinitialisation du mot de passe administrateur et connexion unique (SSO), en français puis en anglais.
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
const calls = []; let deployed = true, reply = null, ssoReply = null, askAnswer = true;
const SSO = { enabled: false, name: 'SSO', issuer: '', client_id: '', scopes: 'openid email profile', redirect_base: '', signup: true, merge_by_email: true, login_form: true, allowed_domains: '', roles_claim: '', allowed_roles: '', admin_roles: '', groups_claim: '', header_auth: false, header_email: 'X-Forwarded-Email', header_name: '', header_groups: '', trusted_proxies: '', secret_set: false, redirect_uri: '', public_url: '' };
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined;
  calls.push([o.method || 'GET', p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/webui') return json({ docker: true, configured: deployed, container: deployed ? 'running' : null, running: deployed, healthy: deployed, version: '0.6', latest: '0.6',
    tls_port: 8443, admin_email: deployed ? 'alice@x.fr' : null, public_url: '', started: '2026-11-17 10:00:00' });
  if (p === '/api/webui/sso' && (o.method || 'GET') === 'GET') return json(SSO);
  if (p === '/api/webui/sso') return ssoReply ? json(ssoReply.body, ssoReply.status) : json({ ok: true, config: Object.assign({}, SSO, body, { secret_set: true }), job: 'j1' });
  if (p === '/api/webui/sso/test') return ssoReply ? json(ssoReply.body, ssoReply.status) : json({ ok: true, issuer: body.issuer });
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

  // --- connexion unique
  const sf = $('#webui-sso-form'), sm = $('#webui-sso-msg'), sub = () => sf.dispatchEvent(new w.Event('submit', { cancelable: true, bubbles: true }));
  ok(await until(() => !$('#webui-sso').classList.contains('hidden') && sf.elements.redirect_base.value.startsWith('https://srv:8443')), lang + ' : SSO : carte visible, adresse d\'Open WebUI préremplie (adresse du serveur, port 8443)');
  ok($('#webui-sso-redirect').textContent === 'https://srv:8443/oauth/oidc/callback', lang + ' : SSO : adresse de retour affichée');
  sf.elements.redirect_base.value = 'https://ia.x.fr/'; sf.elements.redirect_base.dispatchEvent(new w.Event('input'));
  ok($('#webui-sso-redirect').textContent === 'https://ia.x.fr/oauth/oidc/callback', lang + ' : SSO : adresse de retour mise à jour en direct');
  ok(sf.elements.signup.checked && sf.elements.merge_by_email.checked && sf.elements.login_form.checked && !sf.elements.enabled.checked, lang + ' : SSO : valeurs par défaut prudentes');
  sf.elements.enabled.checked = true; sf.elements.issuer.value = 'https://login.x.fr'; sf.elements.client_id.value = 'owui'; sf.elements.client_secret.value = 'sekret'; sf.elements.roles_claim.value = 'roles'; sub();
  ok(await until(() => sm.classList.contains('okmsg')), lang + ' : SSO : enregistrement confirmé : ' + sm.textContent);
  const sc = calls.filter((x) => x[1] === '/api/webui/sso' && x[0] === 'POST').pop();
  ok(sc && sc[2].enabled === true && sc[2].issuer === 'https://login.x.fr' && sc[2].client_id === 'owui' && sc[2].client_secret === 'sekret' && sc[2].roles_claim === 'roles' && sc[2].login_form === true, lang + ' : SSO : réglages envoyés');
  ok(sf.elements.client_secret.value === '' && sf.elements.client_secret.placeholder !== '', lang + ' : SSO : secret vidé, mention « inchangé » : ' + sf.elements.client_secret.placeholder);
  sf.elements.client_secret.value = ''; sub(); await sleep(150);
  const sc2 = calls.filter((x) => x[1] === '/api/webui/sso' && x[0] === 'POST').pop();
  ok(!('client_secret' in sc2[2]), lang + ' : SSO : secret non renvoyé quand le champ est vide');
  const posts = () => calls.filter((x) => x[1] === '/api/webui/sso' && x[0] === 'POST').length, before = posts();
  sf.elements.login_form.checked = false; sub();
  ok(await until(() => !$('#modal').classList.contains('hidden') && ($('#modal-text').textContent.includes('plus personne') || $('#modal-text').textContent.includes('nobody'))), lang + ' : SSO : formulaire local désactivé : confirmation demandée');
  $('#modal-cancel').click(); await sleep(200);
  ok(posts() === before, lang + ' : SSO : annulation : rien n\'est envoyé');
  sub(); ok(await until(() => !$('#modal').classList.contains('hidden')), lang + ' : SSO : confirmation redemandée');
  $('#modal-ok').click();
  ok(await until(() => posts() === before + 1 && calls.filter((x) => x[1] === '/api/webui/sso' && x[0] === 'POST').pop()[2].login_form === false), lang + ' : SSO : confirmation : envoyé avec le formulaire local désactivé');
  sf.elements.login_form.checked = true;
  ssoReply = { status: 400, body: { error: 'Émetteur (issuer) : champ obligatoire.' } }; sub();
  ok(await until(() => sm.classList.contains('error') && sm.textContent.length > 5), lang + ' : SSO : erreur affichée : ' + sm.textContent);
  if (lang === 'en') ok(sm.textContent === 'Issuer: required field.', 'anglais : erreur SSO traduite');
  ssoReply = null; sf.elements.issuer.value = 'https://login.x.fr';
  $('#webui-sso-test').click();
  ok(await until(() => sm.classList.contains('okmsg') && sm.textContent.includes('login.x.fr')), lang + ' : SSO : essai du fournisseur : ' + sm.textContent);
  if (lang === 'en') ok(sm.textContent.startsWith('Provider reachable: https://login.x.fr.'), 'anglais : essai traduit');
  // --- connexion par en-tête
  ssoReply = null; sf.elements.login_form.checked = true;
  ok(sf.elements.header_email.value === 'X-Forwarded-Email' && !sf.elements.header_auth.checked, lang + ' : en-tête : valeur par défaut X-Forwarded-Email, mode désactivé');
  sf.elements.enabled.checked = true; sf.elements.header_auth.checked = true; sf.elements.header_auth.dispatchEvent(new w.Event('change'));
  ok(!sf.elements.enabled.checked, lang + ' : en-tête : cocher le mode décoche OpenID Connect');
  sf.elements.enabled.checked = true; sf.elements.enabled.dispatchEvent(new w.Event('change'));
  ok(!sf.elements.header_auth.checked, lang + ' : en-tête : cocher OpenID Connect décoche le mode en-tête');
  sf.elements.enabled.checked = false; sf.elements.header_auth.checked = true; sf.elements.trusted_proxies.value = '192.168.1.10';
  const hp = posts(); sub();
  ok(await until(() => !$('#modal').classList.contains('hidden') && $('#modal-text').textContent.includes('192.168.1.10')), lang + ' : en-tête : confirmation avec les adresses autorisées : ' + $('#modal-text').textContent.replace(/\n/g, ' / '));
  if (lang === 'en') ok($('#modal-text').textContent.startsWith('Trust the reverse proxy headers?'), 'anglais : confirmation traduite');
  $('#modal-cancel').click(); await sleep(200);
  ok(posts() === hp, lang + ' : en-tête : annulation : rien n\'est envoyé');
  sub(); await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(await until(() => posts() === hp + 1), lang + ' : en-tête : confirmé et envoyé');
  const hb = calls.filter((x) => x[1] === '/api/webui/sso' && x[0] === 'POST').pop()[2];
  ok(hb.header_auth === true && hb.enabled === false && hb.header_email === 'X-Forwarded-Email' && hb.trusted_proxies === '192.168.1.10', lang + ' : en-tête : réglages envoyés');
  sf.elements.trusted_proxies.value = ''; sf.elements.header_auth.checked = false;
  deployed = false; w.document.querySelector('#webui-refresh').click();
  ok(await until(() => $('#webui-pwd').classList.contains('hidden') && $('#webui-sso').classList.contains('hidden')), lang + ' : cartes masquées quand Open WebUI n\'est pas déployé');
  deployed = true;
}
(async () => { await run(); await run('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
