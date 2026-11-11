// Confidentialité (Journaux > Confidentialité, termes interdits d'une clé) : jsdom, FR et EN.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/privacy_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', (e) => { if (process.env.DBG) console.log('REJ', e && e.stack); });
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const calls = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({ size: 1 }) });
const st = { cfg: { categories: { secret: true, iban: true, nir: true, number: true, phone: true, email: true, ip: false }, anonymize: false, detect: true, words: ['salaire', 'projet orion'], words_action: 'block' }, saveError: '', action: 'block' };
const stats = (k) => k === 'day' ? { n: 120, with_pii: 9, masked: 4, blocked: 2, by_cat: { email: 6, phone: 3, iban: 1 }, clients: [{ client: 'Appli RH', n: 80, pii: 7, masked: 4, blocked: 2 }, { client: 'local', n: 40, pii: 2, masked: 0, blocked: 0 }] }
  : { n: 800, with_pii: 51, masked: 20, blocked: 5, by_cat: { email: 30, phone: 12, iban: 6, secret: 3 }, clients: [] };
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/privacy') return json({ config: st.cfg, day: stats('day'), week: stats('week'), keys: [], limits: { words: 200, key_words: 50 }, categories: ['secret', 'iban', 'nir', 'number', 'phone', 'email', 'ip'] });
  if (p === '/api/privacy/config') {
    if (st.saveError) return json({ error: st.saveError }, 400);
    st.cfg = Object.assign({}, st.cfg, { detect: body.detect, anonymize: body.anonymize, categories: body.categories, words: body.words.split('\n').filter(Boolean), words_action: body.words_action }); return json({ ok: true, config: st.cfg });
  }
  if (p === '/api/privacy/test') return json({ masked: body.text.replace(/\S+@\S+/g, '[e-mail]'), categories: /@/.test(body.text) ? ['email'] : [], hits: /salaire/i.test(body.text) ? ['SALAIRE'] : [], action: st.action, anonymize: st.cfg.anonymize });
  if (p === '/api/costs' || p.startsWith('/api/costs?')) return json({ month: '2026-11', months: ['2026-11'], first_day: null, lag_min: 30, teams: [], keys: [], summary: { config: { watts: 300, kwh_price: 0.2, gpu_hour: 0, currency: '€' }, total: { name: 'total', n: 0, e: 0, i: 0, o: 0, gpu_h: 0, kwh: 0, cost: 0, share: 0 }, teams: [], clients: [], models: [] } });
  if (p === '/api/requests?limit=500') return json({ requests: [], summary: [] });
  if (p === '/api/publication/keys/create') return json({ ok: true, token: 'ob_secret', key: { name: body.name } });
  if (p === '/api/publication/keys/update') return json({ ok: true });
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
  w.eval(js + '\nwindow.__t = { keyLimits, keyCaps };');
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|requête|requêtes)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(Appli RH|salaire|projet orion|SALAIRE)/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v) && !/^ex\. (salaire|projet)/.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  st.cfg = { categories: { secret: true, iban: true, nir: true, number: true, phone: true, email: true, ip: false }, anonymize: false, detect: true, words: ['salaire', 'projet orion'], words_action: 'block' };
  st.saveError = ''; st.action = 'block'; calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  const submit = (s) => $(s).dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#logs/privacy';
  ok(await until(() => $$('#privacy-cats input').length === 7), L('onglet « Confidentialité » chargé', 'EN: privacy tab loaded'));
  ok([...$$('#view-logs > .subtabs a')].map((a) => a.dataset.key).join() === 'requests,stats,costs,privacy,system', L('onglet placé après « Coûts »', 'EN: tab order'));
  const kp = $$('#privacy-stats .kpis')[0].textContent, kw = $$('#privacy-stats .kpis')[1].textContent;
  ok(kp.includes('120') && kp.includes('9') && kp.includes('4') && kp.includes('2') && kw.includes('800') && kw.includes('51'), L('indicateurs des 24 h et des 7 jours', 'EN: 24 h and 7 day KPIs'));
  const tags = $$('#privacy-stats .sso-tag').map((x) => x.textContent);
  ok(tags.slice(0, 3).join('|') === ['E-mails 6', L('Téléphones 3', 'Phone numbers 3'), 'IBAN 1'].join('|') && tags.includes('Secrets 3'), L('catégories détectées, la plus fréquente d\'abord (24 h puis 7 jours)', 'EN: categories'));
  const rows = $$('#privacy-stats tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(rows.length === 2 && rows[0].join('|') === 'Appli RH|80|7|4|2' && rows[1][0] === 'local', L('par client : les plus concernés d\'abord', 'EN: per client'));
  const f = $('#privacy-form').elements;
  ok(f.detect.checked && !f.anonymize.checked && f.words.value === 'salaire\nprojet orion' && f.words_action.value === 'block', L('réglages préremplis', 'EN: settings prefilled'));
  const cb = (k) => $('#privacy-cats input[data-cat=' + k + ']');
  ok(cb('secret').checked && cb('secret').disabled && cb('email').checked && !cb('email').disabled && !cb('ip').checked, L('secrets toujours masqués (case grisée), adresse IP désactivée par défaut', 'EN: secret locked, IP off by default'));
  cb('email').checked = false; cb('ip').checked = true; f.anonymize.checked = true; f.words.value = 'salaire\nbudget 2027\n'; f.words_action.value = 'mask';
  submit('#privacy-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/privacy/config')), L('réglages envoyés', 'EN: settings sent'));
  const sent = calls.find((c) => c[1] === '/api/privacy/config')[2];
  ok(sent.anonymize === true && sent.detect === true && sent.categories.email === false && sent.categories.ip === true && sent.categories.secret === true && sent.words === 'salaire\nbudget 2027\n' && sent.words_action === 'mask', L('contenu : catégories, anonymisation, termes, action', 'EN: payload'));
  ok(await until(() => T('#privacy-cfg-msg') === L('Enregistré.', 'Saved.')) && await until(() => f.words.value === 'salaire\nbudget 2027'), L('confirmation et rechargement', 'EN: saved and reloaded'));
  st.saveError = 'termes interdits : une liste est attendue'; submit('#privacy-form');
  ok(await until(() => $('#privacy-cfg-msg').classList.contains('error') && T('#privacy-cfg-msg') === L('termes interdits : une liste est attendue', 'forbidden terms: a list is expected')), L('erreur de validation affichée', 'EN: validation error'));
  // essai
  calls.length = 0; const tf = $('#privacy-test-form').elements;
  tf.text.value = 'écrire à marie@exemple.fr';
  submit('#privacy-test-form');
  ok(await until(() => T('#privacy-test-out').includes('[e-mail]')), L('essai : texte masqué', 'EN: test masked'));
  ok(T('#privacy-test-out').includes(L('reçu par le modèle', 'received by the model')) && T('#privacy-test-out').includes(L('Adresses', 'E-mails').slice(0, 3) === 'Adr' ? 'E-mails' : 'E-mails'), L('anonymisation active : le texte affiché est celui que recevrait le modèle', 'EN: shows what the model receives'));
  tf.text.value = 'le salaire de Paul'; submit('#privacy-test-form');
  ok(await until(() => T('#privacy-test-out').includes('SALAIRE')) && T('#privacy-test-out').includes(L('Demande refusée', 'Request refused')) && $('#privacy-test-out .error'), L('terme interdit : refus annoncé', 'EN: forbidden term refused'));
  st.action = 'mask'; submit('#privacy-test-form');
  ok(await until(() => T('#privacy-test-out').includes(L('Terme interdit masqué', 'Forbidden term masked'))), L('action « masquer » : annoncé', 'EN: mask action'));
  tf.text.value = 'bonjour'; submit('#privacy-test-form');
  ok(await until(() => T('#privacy-test-out').includes(L('Aucune donnée sensible détectée.', 'No sensitive data detected.'))), L('texte sans donnée sensible', 'EN: nothing found'));
  ok(calls.filter((c) => c[1] === '/api/privacy/test').every((c) => Object.keys(c[2]).join() === 'text'), L('seul le texte est envoyé', 'EN: only the text is sent'));
  // termes interdits d'une clé
  const kf = $('#key-form').elements;
  ok(!!kf.words, L('création de clé : champ « Termes interdits »', 'EN: key form field'));
  kf.name.value = 'Appli RH'; kf.words.value = 'salaire, projet orion';
  submit('#key-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/publication/keys/create' && c[2].words === 'salaire, projet orion')), L('termes envoyés à la création de la clé', 'EN: words on create'));
  await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(w.__t.keyLimits({ words: ['a1', 'b2'] }).includes('2 terme(s) interdit(s)') && !w.__t.keyLimits({}).join().includes('interdit'), L('colonne des limites : nombre de termes', 'EN: limits column'));
  const pr = w.__t.keyCaps({ id: 'k1', name: 'RH', words: ['salaire'], priority: 2, max_ctx: 0, max_output: 0 });
  ok(await until(() => !$('#modal').classList.contains('hidden') && $('#modal input[aria-label]')), L('fenêtre « Plafonds »', 'EN: caps modal'));
  const wi = $$('#modal input').find((i) => /Termes interdits|Forbidden terms/.test(i.getAttribute('aria-label')));
  ok(wi && wi.value === 'salaire', L('termes actuels préremplis', 'EN: current words'));
  wi.value = 'salaire, budget'; $('#modal-ok').click(); await pr;
  ok(calls.some((c) => c[1] === '/api/publication/keys/update' && c[2].id === 'k1' && c[2].words === 'salaire, budget'), L('termes modifiés enregistrés', 'EN: words saved'));
  if (lang === 'en') {
    const r = [...new Set(leftovers(w, '#view-logs .panel[data-key=privacy]'))];
    ok(r.length === 0, 'EN: aucun texte français dans l\'onglet Confidentialité' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
