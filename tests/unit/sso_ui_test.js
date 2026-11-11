// Connexion unique (SSO) : bouton de la page de connexion, codes d'erreur, panneau de configuration, comptes SSO : jsdom, FR et EN.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/sso_ui_test.js
const { JSDOM, VirtualConsole } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', (e) => { if (process.env.DBG) console.log('REJ', e && e.stack); });
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({ size: 1 }) });
const calls = [];
const st = { logged: true, providers: { oidc: 'Entreprise', ldap: true }, saveError: '', testError: '' };
const cfg = () => ({ oidc: { enabled: true, name: 'Entreprise', issuer: 'https://login.exemple.fr/realms/corp', client_id: 'ollama', client_secret_set: true, scopes: 'openid profile email', groups_claim: 'groups',
  redirect_base: 'https://ollama.exemple.fr', redirect_uri: 'https://ollama.exemple.fr/sso/oidc/callback', ca_pem: '', ca_set: false },
  ldap: { enabled: true, host: 'ad.exemple.fr', port: 636, tls: 'ldaps', bind_dn: 'CN=svc,DC=exemple,DC=fr', bind_password_set: true, base_dn: 'DC=exemple,DC=fr', user_filter: '(sAMAccountName={user})',
    group_attr: 'memberOf', group_base: '', group_filter: '', ca_pem: '', ca_set: false },
  roles: [{ group: 'OllamaAdmins', role: 'admin' }, { group: 'Staff', role: 'utilisateur' }], default_role: '', users: 2 });
const users = [{ user: 'admin', role: 'admin', linux: true, sso: '', display: '', created: 1700000000 },
  { user: 'sso:alice', role: 'admin', linux: false, sso: 'oidc', display: 'Alice Martin', created: 1700000100 },
  { user: 'ldap:bob', role: 'utilisateur', linux: false, sso: 'ldap', display: '', created: 1700000200 }];
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/sso/providers') return json(st.providers);
  if (p === '/api/session') return st.logged ? json({ user: 'adm', role: 'admin', version: 'v' }) : json({ error: 'non connecté' }, 401);
  if (p === '/api/users') return json({ users });
  if (p === '/api/sso/config' && m === 'GET') return json(cfg());
  if (p === '/api/sso/config') return st.saveError ? json({ error: st.saveError }, 400) : json({ ok: true, config: cfg() });
  if (p === '/api/sso/test') {
    if (st.testError) return json({ error: st.testError }, 400);
    if (body.kind === 'oidc') return json({ ok: true, issuer: 'https://login.exemple.fr/realms/corp', keys: 2 });
    return json(body.user ? { ok: true, bound: 'CN=svc,DC=exemple,DC=fr', dn: 'CN=Alice,DC=exemple,DC=fr', groups: ['OllamaAdmins'], role: 'admin' } : { ok: true, bound: 'CN=svc,DC=exemple,DC=fr' });
  }
  if (p === '/api/status') return json({ version: 'v', hostname: 'srv', os: 'Ubuntu', kernel: 'k', uptime: 10, boot_time: 1, ips: [], cpu: { model: 'x', cores: 1, load: [0, 0, 0], usage: 0 },
    memory: { total: 1, available: 1 }, disk: { total: 1, used: 0, free: 1, models: 0 }, gpu: { devices: [], compute: [], reboot_required: false }, gpu_live: [],
    ollama: { version: '0.1', service: 'active', exposed: false, running: [], publication: {} }, reboot_required: false, update_available: null, offload: [], alerts: [] });
  return json({});
}
const EN = JSON.parse(fs.readFileSync(path.join(WEB, 'i18n', 'en.json'), 'utf8'));
function make(lang, search) {
  const navs = [], vc = new VirtualConsole();
  vc.on('jsdomError', (e) => { if (/navigation/i.test(e.message)) navs.push(e.message); });
  const dom = new JSDOM(html, { url: 'https://srv/' + (search || ''), runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  if (lang) w.localStorage.setItem('ob-lang', lang);
  w.fetch = async (p, o) => (p === '/i18n/en.json' ? json(EN) : fakeFetch(p, o));
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {};
  w.eval(js);
  w.__navs = navs;
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|compte|groupe|rôle|mot de passe|annuaire|fournisseur)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style, textarea')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(Alice Martin|Ressources|Entreprise|OllamaAdmins|CN=)/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v) && !/^(CN|DC)=/.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function loginScenario(lang) {
  st.logged = false; st.providers = { oidc: 'Entreprise', ldap: true }; calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), L = (fr, en) => (lang === 'en' ? en : fr);
  ok(await until(() => !$('#login').classList.contains('hidden') && !$('#login-sso').classList.contains('hidden')), L('page de connexion : bouton de connexion unique affiché', 'EN: SSO button shown'));
  ok($('#login-oidc').textContent === L('Se connecter avec Entreprise', 'Sign in with Entreprise'), L('le bouton porte le nom choisi par l\'administrateur', 'EN: button label'));
  ok(!$('#login-form').elements.user.disabled, L('le formulaire identifiant / mot de passe reste disponible (compte local d\'urgence, annuaire)', 'EN: form still there'));
  $('#login-oidc').click(); await sleep(50);
  ok(w.__navs.length === 1, L('clic : navigation vers le point d\'entrée /sso/oidc/start', 'EN: click navigates'));
  ok(leftovers(w, '#login').length === 0 || lang !== 'en', L('page de connexion en français', 'EN: login page fully English') + (lang === 'en' ? ' ' + JSON.stringify(leftovers(w, '#login')) : ''));
  st.providers = { oidc: null, ldap: true };
  const w2 = make(lang);
  ok(await until(() => !w2.document.querySelector('#login').classList.contains('hidden') && calls.filter((c) => c[1] === '/api/sso/providers').length >= 2) && w2.document.querySelector('#login-sso').classList.contains('hidden'), L('connexion unique non configurée : aucun bouton', 'EN: no button when SSO is off'));
  for (const code of ['state', 'idp', 'denied', 'config', 'user']) {
    const w3 = make(lang, '?sso=' + code + '#x');
    ok(await until(() => w3.document.querySelector('#login-error').textContent.length > 10), L('code « ' + code + ' » : message explicite', 'EN: error code ' + code));
    ok(w3.location.search === '' && w3.location.hash === '#x', L('adresse nettoyée après lecture du code (pas de rejeu au rechargement)', 'EN: URL cleaned'));
    if (lang === 'en') ok(!FR_WORDS.test(w3.document.querySelector('#login-error').textContent), 'EN: message translated (' + code + ')');
  }
  const w4 = make(lang, '?sso=<img src=x onerror=alert(1)>');
  await sleep(300);
  ok(w4.document.querySelector('#login-error').textContent === '' && !w4.document.querySelector('#login-error img'), L('code inconnu ignoré, rien n\'est injecté dans la page', 'EN: unknown code ignored'));
}
async function adminScenario(lang) {
  st.logged = true; st.saveError = ''; st.testError = ''; calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr);
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#users';
  ok(await until(() => $$('#users-table tbody tr').length === 3), L('comptes listés', 'EN: accounts listed'));
  const rows = $$('#users-table tbody tr'), cell = (i, j) => rows[i].children[j];
  ok(cell(1, 0).textContent.includes('Alice Martin') && cell(1, 0).textContent.includes('sso:alice') && cell(1, 0).querySelector('.sso-tag').textContent === 'SSO', L('compte SSO : nom affiché, identifiant interne et étiquette « SSO »', 'EN: SSO account tag'));
  ok(cell(2, 0).querySelector('.sso-tag').textContent === L('Annuaire', 'Directory') && !cell(0, 0).querySelector('.sso-tag'), L('compte d\'annuaire étiqueté, compte local sans étiquette', 'EN: directory tag'));
  ok(!cell(1, 1).querySelector('select') && cell(1, 1).textContent.includes(L('selon ses groupes', 'from their groups')) && !!cell(0, 1).querySelector('select') && !cell(2, 1).querySelector('select'), L('rôle d\'un compte SSO non modifiable à la main (il suit les groupes) ; celui d\'un compte local l\'est', 'EN: SSO role read-only, local role editable'));
  const btns = (i) => [...rows[i].querySelectorAll('button')].map((b) => b.textContent);
  ok(!btns(1).includes(L('Mot de passe', 'Password')) && !btns(2).includes(L('Mot de passe', 'Password')) && btns(0).includes(L('Mot de passe', 'Password')), L('pas de bouton « Mot de passe » pour les comptes SSO', 'EN: no password button for SSO accounts'));
  ok(btns(1).includes(L('Supprimer', 'Delete')), L('suppression possible (le compte sera recréé à la prochaine connexion)', 'EN: deletable'));
  ok($$('#view-users > .subtabs a').some((a) => a.dataset.key === 'sso'), L('onglet « Connexion unique (SSO) » dans Utilisateurs', 'EN: SSO tab'));
  w.location.hash = '#users/sso';
  const f = $('#sso-form');
  ok(await until(() => f.elements.oidc_issuer.value === 'https://login.exemple.fr/realms/corp'), L('configuration chargée', 'EN: config loaded'));
  ok(f.elements.oidc_enabled.checked && f.elements.ldap_enabled.checked && f.elements.ldap_host.value === 'ad.exemple.fr' && f.elements.ldap_port.value === '636' && f.elements.ldap_tls.value === 'ldaps' && f.elements.oidc_name.value === 'Entreprise', L('champs OpenID Connect et LDAP remplis', 'EN: fields filled'));
  ok(f.elements.oidc_client_secret.value === '' && f.elements.ldap_bind_password.value === '' && /^(déjà|already)/.test(f.elements.oidc_client_secret.placeholder) && /^(déjà|already)/.test(f.elements.ldap_bind_password.placeholder), L('les secrets ne sont jamais renvoyés au navigateur : seul « déjà enregistré » est indiqué', 'EN: secrets never shown'));
  ok($('#sso-redirect').textContent === 'https://ollama.exemple.fr/sso/oidc/callback', L('adresse de retour à déclarer affichée', 'EN: return address'));
  ok($$('#sso-roles .sso-role').length === 2 && $$('#sso-roles .sso-group')[0].value === 'OllamaAdmins' && $$('#sso-roles .sso-rolesel')[0].value === 'admin' && $$('#sso-roles .sso-rolesel')[1].value === 'utilisateur', L('correspondances groupe → rôle affichées', 'EN: role rows'));
  $('#sso-role-add').click();
  const rowsR = $$('#sso-roles .sso-role');
  ok(rowsR.length === 3, L('ajout d\'une ligne', 'EN: row added'));
  rowsR[2].querySelector('.sso-group').value = 'CN=llm-users,OU=Groupes,DC=exemple,DC=fr';
  $('#sso-role-add').click();   // ligne vide : ignorée à l'enregistrement
  rowsR[1].querySelector('button').click();
  ok($$('#sso-roles .sso-role').length === 3, L('retrait d\'une ligne', 'EN: row removed'));
  f.elements.default_role.value = 'utilisateur';
  f.elements.oidc_scopes.value = 'openid profile email groups';
  f.requestSubmit(); 
  ok(await until(() => calls.some((c) => c[1] === '/api/sso/config' && c[0] === 'POST')), L('enregistrement envoyé', 'EN: save sent'));
  const sent = calls.filter((c) => c[1] === '/api/sso/config' && c[0] === 'POST')[0][2];
  ok(sent.oidc.enabled === true && sent.oidc.scopes === 'openid profile email groups' && sent.ldap.host === 'ad.exemple.fr' && sent.ldap.port === '636' && sent.default_role === 'utilisateur', L('contenu : OpenID Connect, LDAP, rôle par défaut', 'EN: payload'));
  ok(!('client_secret' in sent.oidc) && !('bind_password' in sent.ldap), L('secrets laissés vides : non envoyés (les valeurs enregistrées sont conservées)', 'EN: empty secrets not sent'));
  ok(sent.roles.length === 2 && sent.roles[0].group === 'OllamaAdmins' && sent.roles[1].group.startsWith('CN=llm-users') && sent.roles[1].role === 'utilisateur', L('lignes vides ignorées, ligne retirée absente', 'EN: roles payload'));
  ok(await until(() => $('#sso-msg').textContent === L('Enregistré.', 'Saved.')), L('confirmation affichée', 'EN: confirmation'));
  calls.length = 0;
  f.elements.oidc_client_secret.value = 'nouveau-secret'; f.elements.ldap_bind_password.value = 'nouveau-mdp';
  f.requestSubmit();
  ok(await until(() => calls.some((c) => c[1] === '/api/sso/config' && c[0] === 'POST')), L('second enregistrement', 'EN: second save'));
  const s2 = calls.filter((c) => c[1] === '/api/sso/config' && c[0] === 'POST')[0][2];
  ok(s2.oidc.client_secret === 'nouveau-secret' && s2.ldap.bind_password === 'nouveau-mdp', L('secrets saisis : envoyés', 'EN: typed secrets sent'));
  ok(await until(() => f.elements.oidc_client_secret.value === '' && f.elements.ldap_bind_password.value === ''), L('champs de secret vidés après enregistrement', 'EN: secret fields cleared'));
  st.saveError = 'OIDC : identifiant et secret du client obligatoires';
  f.requestSubmit();
  ok(await until(() => $('#sso-msg').classList.contains('error') && $('#sso-msg').textContent === L(st.saveError, 'OIDC: client ID and secret are required')), L('erreur de validation affichée', 'EN: validation error'));
  // essais
  calls.length = 0; const tf = $('#sso-test-form');
  $('#sso-test-oidc').click();
  ok(await until(() => $('#sso-test-out').textContent.includes('login.exemple.fr')), L('essai OpenID Connect : fournisseur et clés affichés', 'EN: OIDC test') + ' ' + $('#sso-test-out').textContent);
  ok(calls.some((c) => c[1] === '/api/sso/test' && c[2].kind === 'oidc' && !('user' in c[2])), L('essai OIDC : aucun identifiant envoyé', 'EN: OIDC test payload'));
  calls.length = 0;
  $('#sso-test-ldap').click();
  ok(await until(() => $('#sso-test-out').textContent.includes('CN=svc')), L('essai LDAP sans compte : compte de service', 'EN: LDAP test'));
  ok(calls.some((c) => c[1] === '/api/sso/test' && c[2].kind === 'ldap' && !('user' in c[2])), L('sans identifiant : rien d\'autre envoyé', 'EN: no user sent'));
  tf.elements.user.value = 'alice'; tf.elements.password.value = 'alice-pw'; calls.length = 0;
  $('#sso-test-ldap').click();
  ok(await until(() => $('#sso-test-out').textContent.includes('OllamaAdmins')), L('essai LDAP avec un compte : groupes et rôle', 'EN: LDAP test with account'));
  ok($('#sso-test-out').textContent.includes(L('administrateur', 'administrator')) && !$('#sso-test-out').textContent.includes('alice-pw'), L('rôle obtenu affiché, mot de passe jamais affiché', 'EN: role shown, no password'));
  ok(calls.some((c) => c[1] === '/api/sso/test' && c[2].user === 'alice' && c[2].password === 'alice-pw') && tf.elements.password.value === '', L('mot de passe d\'essai effacé du formulaire après l\'essai', 'EN: test password cleared'));
  st.testError = 'annuaire injoignable : timed out';
  $('#sso-test-ldap').click();
  ok(await until(() => $('#sso-test-out').classList.contains('error') && $('#sso-test-out').textContent.includes(L('annuaire injoignable', 'directory unreachable'))), L('échec de l\'essai : message de l\'appliance affiché', 'EN: test failure'));
  const left = leftovers(w, '#view-users');
  ok(lang !== 'en' || left.length === 0, L('panneau en français', 'EN: users view fully English') + (left.length && lang === 'en' ? ' ' + JSON.stringify(left.slice(0, 8)) : ''));
}
(async () => {
  for (const lang of [undefined, 'en']) { await loginScenario(lang); await adminScenario(lang); }
  console.log(`\n${n} vérifications réussies.`); process.exit(0);
})().catch((e) => { console.log('ERREUR', e && e.stack); process.exit(1); });
