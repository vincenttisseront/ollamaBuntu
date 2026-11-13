// Redirection de modèles (Modèles > Redirections) : jsdom, FR et EN.   Usage : NODE_PATH=... node tests/unit/redirect_ui_test.js
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
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({}) });
let saved = [{ from: 'gemma4:12b', to: 'qwen3:14b', percent: 100, enabled: true, to_installed: false }];
let fail = null;
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/redirects') return json({ rules: saved, models: ['gemma4:12b', 'qwen3:14b'] });
  if (p === '/api/redirects/config') {
    if (fail) return json({ error: fail }, 400);
    saved = body.rules.map((r) => Object.assign({ to_installed: true }, r)); return json({ ok: true, rules: saved });
  }
  if (p === '/api/models/context') return json({ default: null, parallel: 1, models: [] });
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
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|demande|demandes|modèle|règle)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style, textarea')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(gemma4|qwen3)/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  saved = [{ from: 'gemma4:12b', to: 'qwen3:14b', percent: 100, enabled: true, to_installed: false }]; fail = null; calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#models/redirect';
  ok(await until(() => $$('#rd-body tbody tr').length === 1), L('onglet « Redirections » chargé', 'EN: redirects tab loaded'));
  const keys = [...$$('#view-models > .subtabs a')].map((a) => a.dataset.key);
  ok(keys.indexOf('redirect') === keys.indexOf('engine') + 1, L('onglet placé après « Moteur MoE »', 'EN: tab order'));
  ok($('#view-models > .subtabs a[data-key=redirect]').textContent.trim() === L('Redirections', 'Redirects'), L('libellé de l\'onglet', 'EN: tab label'));
  let ins = $$('#rd-body tbody tr:first-child input');
  ok(ins[0].value === 'gemma4:12b' && ins[1].value === 'qwen3:14b' && ins[2].value === '100' && ins[7].checked, L('règle existante affichée', 'EN: existing rule shown'));
  ok($$('#rd-models option').map((o) => o.value).join() === 'gemma4:12b,qwen3:14b' && ins[0].getAttribute('list') === 'rd-models', L('liste des modèles installés proposée pour la saisie', 'EN: model suggestions'));
  ok(T('#rd-body').includes(L('Non installé sur ce serveur', 'Not installed on this server')), L('cible non installée signalée', 'EN: not installed hint'));
  ok(!/null|undefined/.test(T('#rd-body')), L('aucun « null » affiché', 'EN: no null'));
  ok(ins.length === 8 && ins[3].value === '' && !ins[4].checked && !ins[5].checked && !ins[6].checked, L('conditions de la règle existante : aucune', 'EN: no conditions on the existing rule'));
  ok(T('#rd-body').includes(L('Seulement si (facultatif)', 'Only if (optional)')) && T('#rd-body').includes(L('Sans outils', 'Without tools')) && T('#rd-body').includes(L('Si ce modèle échoue, reprendre avec le modèle demandé', 'If this model fails, retry with the requested model')) && T('#rd-body').includes(L('Moins de', 'Fewer than')), L('colonne des conditions affichée', 'EN: conditions column'));
  $('#rd-add').click();
  ok(await until(() => $$('#rd-body tbody tr').length === 2), L('« Ajouter une règle » ajoute une ligne', 'EN: add row'));
  ins = $$('#rd-body tbody tr:nth-child(2) input');
  ins[0].value = 'llama3.2:3b'; ins[0].dispatchEvent(new w.Event('input'));
  ins[1].value = 'qwen3:14b'; ins[1].dispatchEvent(new w.Event('input'));
  ins[2].value = '30'; ins[2].dispatchEvent(new w.Event('input'));
  ins[3].value = '2000'; ins[3].dispatchEvent(new w.Event('input'));
  for (const k of [4, 6]) { ins[k].checked = true; ins[k].dispatchEvent(new w.Event('change')); }
  const first = $$('#rd-body tbody tr:first-child input')[7]; first.checked = false; first.dispatchEvent(new w.Event('change'));
  $('#rd-save').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/redirects/config')), L('enregistrement envoyé', 'EN: save sent'));
  const sent = calls.find((c) => c[1] === '/api/redirects/config')[2].rules;
  ok(sent.length === 2 && sent[0].enabled === false && sent[1].from === 'llama3.2:3b' && sent[1].to === 'qwen3:14b' && sent[1].percent === 30 && sent[1].enabled === true && !('to_installed' in sent[0]) && sent[1].short_chars === 2000 && sent[1].no_tools === true && sent[1].no_images === false && sent[1].fallback === true && sent[0].short_chars === 0 && sent[0].fallback === false,
    L('règles envoyées : désactivation, nouvelle règle à 30 % avec ses conditions et son repli', 'EN: rules sent'));
  ok(await until(() => T('#rd-msg') === L('Enregistré : appliqué aux prochaines demandes.', 'Saved: applies to the next requests.')), L('confirmation affichée', 'EN: saved message'));
  ok(await until(() => { const i2 = $$('#rd-body tbody tr:nth-child(2) input'); return i2.length === 8 && i2[3].value === '2000' && i2[4].checked && !i2[5].checked && i2[6].checked; }), L('après rechargement : conditions et repli de la règle toujours affichés', 'EN: conditions kept after reload'));
  fail = L('« a » : le modèle servi est le même que le modèle demandé', '"a": the serving model is the same as the requested model');
  $('#rd-save').click();
  ok(await until(() => T('#rd-msg').includes('a') && $('#rd-msg').classList.contains('error')), L('erreur du serveur affichée', 'EN: server error shown'));
  fail = null;
  $$('#rd-body tbody tr:first-child button')[0].click();
  ok(await until(() => $$('#rd-body tbody tr').length === 1), L('« Retirer » supprime la ligne', 'EN: remove row'));
  $$('#rd-body tbody tr:first-child button')[0].click();
  ok(await until(() => T('#rd-body').includes(L('Aucune redirection', 'No redirect'))), L('liste vide : message dédié', 'EN: empty message'));
  if (lang === 'en') {
    const r = [...new Set(leftovers(w, '#view-models [data-panel=redirect], #view-models .panel[data-key=redirect]'))];
    ok(r.length === 0, 'EN: aucun texte français dans l\'onglet Redirections' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
