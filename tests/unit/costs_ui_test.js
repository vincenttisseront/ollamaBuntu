// Imputation des coûts (Journaux > Coûts, équipe d'une clé, export CSV) : jsdom, FR et EN.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/costs_ui_test.js
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', '..', 'src', 'rootfs', 'usr', 'local', 'lib', 'ollamabuntu', 'admin', 'web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
let n = 0;
process.on('unhandledRejection', (e) => { if (process.env.DBG) console.log('REJ', e && e.stack); });
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { /* attente */ } await sleep(40); } return false; }
const calls = [], downloads = [];
const json = (o, status = 200) => ({ ok: status < 400, status, json: async () => o, blob: async () => ({ size: 1 }) });
const st = { cfg: { watts: 300, kwh_price: 0.2, gpu_hour: 1, currency: '€' } };
const row = (name, n, o, h, kwh, cost, share, team) => Object.assign({ name, n, e: n > 10 ? 2 : 0, i: o / 2, o, gpu_h: h, kwh, cost, share }, team ? { team } : {});
const doc = (month) => ({ month: month || '2026-11', months: ['2026-11', '2026-10'], first_day: '2026-10-02', lag_min: 30, teams: ['Ressources humaines'], keys: [],
  summary: { config: st.cfg, total: { name: 'total', n: 1234, e: 2, i: 50000, o: 100000, gpu_h: 12.5, kwh: 3.75, cost: 13.25, share: 0 },
    teams: [row('Ressources humaines', 1000, 80000, 10, 3, 10.8, 82), row('(sans équipe)', 234, 20000, 2.5, 0.75, 2.45, 18)],
    clients: [row('Appli RH', 1000, 80000, 10, 3, 10.8, 82, 'Ressources humaines'), row('Appli test', 5, 20000, 2.5, 0.75, 2.45, 18, '(sans équipe)')],
    models: [row('llama3.2:3b', 1234, 100000, 12.5, 3.75, 13.25, 100)] } });
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p.startsWith('/api/costs/export')) return { ok: true, status: 200, blob: async () => ({ size: 10 }), json: async () => ({}) };
  if (p.startsWith('/api/costs?') || p === '/api/costs') return json(doc((p.split('month=')[1] || '').split('&')[0] || undefined));
  if (p === '/api/costs/config') { st.cfg = Object.assign({}, st.cfg, { watts: Number(body.watts), kwh_price: Number(body.kwh_price), gpu_hour: Number(body.gpu_hour), currency: body.currency }); return json({ ok: true, config: st.cfg }); }
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
  w.URL.createObjectURL = () => 'blob:x'; w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function () { if (this.download) downloads.push(this.download); };
  w.eval(js + '\nwindow.__t = { keyLimits, keyCaps };');
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|requête|requêtes|équipe|clé|coût)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style, textarea')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(Ressources humaines|Appli |llama)/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  st.cfg = { watts: 300, kwh_price: 0.2, gpu_hour: 1, currency: '€' }; calls.length = 0; downloads.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#logs/costs';
  ok(await until(() => $$('#costs-clients tbody tr').length === 2), L('onglet « Coûts » chargé', 'EN: costs tab loaded'));
  ok([...$$('#view-logs > .subtabs a')].map((a) => a.dataset.key).join() === 'requests,stats,costs,system', L('onglet placé après « Statistiques »', 'EN: tab order'));
  ok([...$('#costs-month').options].map((o) => o.value).join() === '2026-11,2026-10' && $('#costs-month').value === '2026-11', L('sélecteur de mois : mois en cours sélectionné', 'EN: month selector'));
  const k = $$('#costs-total .card').map((c) => c.textContent);
  ok(k.length === 5 && k[1].includes('100') && k[2].includes('12') && k[3].includes('3') && k[4].includes('13') && k[4].includes('€'), L('indicateurs : requêtes, jetons, temps de calcul, énergie, coût', 'EN: KPIs'));
  const th = (s) => $$(s + ' thead th').map((x) => x.textContent);
  ok(th('#costs-clients')[0] === L('Clé', 'Key') && th('#costs-clients')[1] === L('Équipe', 'Team') && th('#costs-teams')[0] === L('Équipe', 'Team') && th('#costs-models')[0] === L('Modèle', 'Model'), L('en-têtes : clé + équipe, équipe, modèle', 'EN: headers'));
  const tr = $$('#costs-teams tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(tr[0][0] === 'Ressources humaines' && tr[0][8] === '82 %' && tr[0][7].includes('€') && tr[1][0] === L('(sans équipe)', '(no team)'), L('équipes : coût, part, regroupement « sans équipe »', 'EN: teams'));
  const cl = $$('#costs-clients tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(cl[0][0] === 'Appli RH' && cl[0][1] === 'Ressources humaines' && cl[1][1] === L('(sans équipe)', '(no team)'), L('clés : équipe de chaque clé', 'EN: keys'));
  ok(T('#costs-lag').includes(L('30 dernières minutes', 'last 30 minutes')) && T('#costs-lag').includes('2026-10-02'), L('mention du délai de versement et de la date de début du registre', 'EN: lag note'));
  const f = $('#costs-form').elements;
  ok(f.watts.value === '300' && f.kwh_price.value === '0.2' && f.gpu_hour.value === '1' && f.currency.value === '€', L('paramètres préremplis', 'EN: settings prefilled'));
  f.watts.value = '450'; f.kwh_price.value = '0.18'; f.gpu_hour.value = '0.5'; f.currency.value = 'EUR';
  $('#costs-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/costs/config' && c[2].watts === '450' && c[2].kwh_price === '0.18' && c[2].gpu_hour === '0.5' && c[2].currency === 'EUR')), L('paramètres envoyés', 'EN: settings sent'));
  ok(await until(() => T('#costs-cfg-msg') === L('Enregistré.', 'Saved.')) && await until(() => T('#costs-total').includes('EUR')), L('confirmation, tableaux recalculés avec la nouvelle devise', 'EN: saved and refreshed'));
  $('#costs-month').value = '2026-10'; $('#costs-month').dispatchEvent(new w.Event('change'));
  ok(await until(() => calls.some((c) => c[1].startsWith('/api/costs?month=2026-10'))), L('changement de mois : nouvelle requête', 'EN: month change'));
  $('#costs-export').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/costs/export?month=2026-10')) && await until(() => downloads.includes('couts-2026-10.csv')), L('export CSV du mois choisi', 'EN: CSV export'));
  // équipe d'une clé
  const kf = $('#key-form').elements;
  ok(kf.team && kf.team.getAttribute('list') === 'team-list', L('création de clé : champ « Équipe » avec suggestions', 'EN: team field'));
  kf.name.value = 'Appli RH'; kf.team.value = '  Ressources humaines ';
  $('#key-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => calls.some((c) => c[1] === '/api/publication/keys/create' && c[2].team === 'Ressources humaines')), L('équipe envoyée à la création de la clé', 'EN: team on create'));
  await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(w.__t.keyLimits({ team: 'Finance' }).includes('équipe : Finance') && !w.__t.keyLimits({}).join().includes('équipe'), L('colonne des limites : équipe affichée si renseignée', 'EN: limits column'));
  const pr = w.__t.keyCaps({ id: 'k1', name: 'RH', team: 'Finance', priority: 2, max_ctx: 0, max_output: 0 });
  ok(await until(() => !$('#modal').classList.contains('hidden') && $('#modal input[list=team-list]')), L('fenêtre « Plafonds » avec l\'équipe', 'EN: caps modal'));
  ok($('#modal input[list=team-list]').value === 'Finance', L('équipe actuelle préremplie', 'EN: current team'));
  $('#modal input[list=team-list]').value = ' Compta '; $('#modal-ok').click(); await pr;
  ok(calls.some((c) => c[1] === '/api/publication/keys/update' && c[2].id === 'k1' && c[2].team === 'Compta'), L('équipe modifiée enregistrée', 'EN: team saved'));
  if (lang === 'en') {
    const r = [...new Set(leftovers(w, '#view-logs .panel[data-key=costs]'))];
    ok(r.length === 0, 'EN: aucun texte français dans l\'onglet Coûts' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
