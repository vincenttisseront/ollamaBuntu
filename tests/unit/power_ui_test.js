// Réveil et veille du parc (Serveurs > Veille) et autorisation côté serveur géré (Système > Gestion centralisée) : jsdom, FR et EN.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/power_ui_test.js
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
const st = {};
function reset() {
  Object.assign(st, {
    settings: { enabled: true, wake_waiting: 1, wake_after_s: 20, wake_busy_pct: 85, wake_busy_s: 60, cooldown_s: 300, wake_timeout_s: 240, keep_awake: 0, settle_s: 600 },
    servers: [
      { id: '1', name: 'Alpha', state: 'awake', fleet_state: 'en ligne', power: { mac: '3c:ec:ef:00:00:01', broadcast: '', wake: false, sleep: 'suspend', idle_min: 30 }, idle_min: 12, wake_sent: null, failed: false,
        nics: [{ iface: 'enp3s0', mac: '3c:ec:ef:00:00:01', link: 'up', wol: 'off', supported: true }], allow: '', tools: { ethtool: true } },
      { id: '2', name: 'Beta', state: 'asleep', fleet_state: 'hors ligne', power: { mac: '3c:ec:ef:00:00:02', broadcast: '', wake: true, sleep: '', idle_min: 30 }, idle_min: null, wake_sent: null, failed: true, nics: [], allow: '', tools: null },
      { id: '3', name: 'Gamma', state: 'waking', fleet_state: 'hors ligne', power: { mac: '', broadcast: '', wake: false, sleep: '', idle_min: 30 }, idle_min: null, wake_sent: 1, failed: false, nics: [], allow: '', tools: null },
    ],
    log: [{ ts: 1790000300, kind: 'wake-failed', server: 'Beta', why: 'aucune réponse 240 s après le paquet', ok: false, detail: '' },
          { ts: 1790000200, kind: 'sleep', server: 'Alpha', why: 'inactif depuis 45 min', ok: true, detail: 'suspend' },
          { ts: 1790000100, kind: 'wake', server: 'Beta', why: '1 demande(s) en attente, la plus ancienne depuis 40 s', ok: true, detail: '' },
          { ts: 1790000050, kind: 'sleep', server: 'Gamma', why: 'demandé par admin', ok: false, detail: "ce serveur n'autorise pas sa mise en veille à distance" }],
    error: '', allow: 'suspend', wol: 'off',
  });
}
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/power') return json({ settings: st.settings, servers: st.servers, log: st.log, active: true, limits: {} });
  if (p === '/api/power/config') { if (st.error) return json({ error: st.error }, 400); Object.assign(st.settings, { enabled: body.enabled }, Object.fromEntries(Object.entries(body).filter(([k]) => k !== 'enabled').map(([k, v]) => [k, Number(v)]))); return json({ ok: true, settings: st.settings }); }
  if (p === '/api/power/server') { if (st.error) return json({ error: st.error }, 400); const s = st.servers.find((x) => x.id === body.id); Object.assign(s.power, { mac: body.mac, broadcast: body.broadcast, wake: body.wake, sleep: body.sleep, idle_min: Number(body.idle_min) }); return json({ ok: true, power: s.power }); }
  if (p === '/api/power/wake' || p === '/api/power/sleep') return json({ ok: true });
  if (p === '/api/power/member') { st.allow = body.allow; return json({ ok: true, member: { allow: body.allow } }); }
  if (p === '/api/power/wol') { st.wol = body.enable ? 'magic' : 'off'; return json({ ok: true }); }
  if (p === '/api/fleet/member') return json({ fingerprint: 'AA', last_sync: null, consoles: [], power_allow: st.allow, ethtool: true,
    nics: [{ iface: 'enp3s0', mac: '3c:ec:ef:12:34:56', link: 'up', wol: st.wol, supported: true }, { iface: 'enp4s0', mac: '3c:ec:ef:12:34:57', link: 'down', wol: 'off', supported: false }] });
  if (p === '/api/fleet/servers') return json({ servers: [], actions: {}, sync_kinds: {}, local_models: [], local_details: [] });
  if (p === '/api/fleet/balance') return json({ strategy: 'spread', affinity: true, servers: [], local: { models: 0, served: 0, last: null, failures: 0 }, rescued: { count: 0, lost: 0 } });
  if (p === '/api/queue') return json({ settings: { max_active: 0, max_queue: 0 }, active: 0, waiting: [], waits: {}, parallel: 1, live: true, keys: [] });
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
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|requête|requêtes)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(Alpha|Beta|Gamma)/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v)) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  reset(); calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  const submit = (s) => $(s).dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  w.location.hash = '#fleet/power';
  ok(await until(() => $$('#pwr-servers tbody tr').length === 3), L('onglet « Veille » chargé', 'EN: tab loaded'));
  ok([...$$('#view-fleet > .subtabs a')].map((a) => a.dataset.key).join() === 'fleet,balance,queue,power,rules,add', L('onglet placé après « File d\'attente »', 'EN: tab order'));
  const f = $('#pwr-form').elements;
  ok(f.enabled.checked && f.wake_waiting.value === '1' && f.wake_after_s.value === '20' && f.wake_busy_pct.value === '85' && f.keep_awake.value === '0' && f.cooldown_s.value === '300' && f.wake_timeout_s.value === '240', L('réglages préremplis', 'EN: settings prefilled'));
  const rows = $$('#pwr-servers tbody tr');
  const pills = rows.map((r) => r.children[1].querySelector('.pill').textContent);
  ok(pills.join() === [L('Éveillé', 'Awake'), L('En veille', 'Asleep'), L('Réveil en cours', 'Waking up')].join(), L('états des serveurs', 'EN: server states'));
  ok(rows[0].children[1].textContent.includes(L('Au repos depuis 12 min', 'Idle for 12 min')), L('durée de repos d\'un serveur éveillé', 'EN: idle time'));
  ok(rows[0].children[2].textContent === '3c:ec:ef:00:00:01' && rows[2].children[2].textContent === '-', L('adresses MAC (« - » quand elle manque)', 'EN: MAC addresses'));
  ok(rows[0].children[3].textContent.includes(L('veille (suspend)', 'sleep (suspend)')) && rows[0].children[3].textContent.includes(L('30 min d\'inactivité', '30 min of inactivity')) && rows[1].children[3].textContent.includes(L('Réveil automatique', 'Automatic wake-up')) && rows[2].children[3].textContent.includes(L('Manuel seulement', 'Manual only')), L('résumé de l\'automatisme', 'EN: automation summary'));
  ok(rows[1].children[0].textContent.includes(L('Réveil sans effet', 'Wake-up had no effect')) && rows[0].children[0].textContent.includes(L('n\'autorise pas sa mise en veille à distance', 'does not allow being put to sleep remotely')) && rows[0].children[0].textContent.includes(L('Le réveil réseau est désactivé', 'Network wake-up is disabled')), L('alertes : réveil sans effet, veille non autorisée, réveil réseau désactivé', 'EN: warnings'));
  const btn = (r, label) => [...r.querySelectorAll('button')].find((b) => b.textContent === label);
  ok(btn(rows[0], L('Réveiller', 'Wake up')).disabled && !btn(rows[1], L('Réveiller', 'Wake up')).disabled && btn(rows[2], L('Réveiller', 'Wake up')).disabled, L('« Réveiller » : inactif pour un serveur éveillé ou sans adresse MAC', 'EN: wake button state'));
  ok(!btn(rows[0], L('Mettre en veille', 'Put to sleep')).disabled && btn(rows[1], L('Mettre en veille', 'Put to sleep')).disabled, L('« Mettre en veille » : seulement pour un serveur éveillé', 'EN: sleep button state'));
  // journal
  const log = $$('#pwr-log tbody tr');
  ok(log.length === 4 && log[0].classList.contains('error') && log[0].children[2].textContent === L('Réveil sans effet', 'Wake-up had no effect') && log[0].children[3].textContent.includes(L('aucune réponse 240 s après le paquet', 'no answer 240 s after the packet')), L('journal : le plus récent d\'abord, échec en évidence', 'EN: log'));
  ok(log[1].children[3].textContent.includes(L('inactif depuis 45 min', 'idle for 45 min')) && log[1].children[3].textContent.includes(L('veille (suspend)', 'sleep (suspend)')), L('journal : motif et mode de la mise en veille', 'EN: sleep reason and mode'));
  ok(log[2].children[3].textContent.includes(L('1 demande(s) en attente, la plus ancienne depuis 40 s', '1 request(s) waiting, the oldest for 40 s')), L('journal : motif d\'un réveil', 'EN: wake reason'));
  ok(log[3].children[3].textContent.includes(L('demandé par admin', 'requested by admin')) && log[3].children[3].textContent.includes(L('n\'autorise pas sa mise en veille à distance', 'does not allow being put to sleep remotely')), L('journal : refus du serveur expliqué', 'EN: refusal explained'));
  // enregistrement des réglages
  calls.length = 0;
  f.enabled.checked = false; f.wake_waiting.value = '3'; f.keep_awake.value = '1'; f.wake_busy_pct.value = '0';
  submit('#pwr-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/power/config')), L('réglages envoyés', 'EN: settings sent'));
  const sent = calls.find((c) => c[1] === '/api/power/config')[2];
  ok(sent.enabled === false && sent.wake_waiting === '3' && sent.keep_awake === '1' && sent.wake_busy_pct === '0' && sent.cooldown_s === '300' && Object.keys(sent).length === 9, L('contenu : tous les réglages', 'EN: payload'));
  ok(await until(() => T('#pwr-msg') === L('Enregistré.', 'Saved.')), L('confirmation', 'EN: saved'));
  st.error = 'attente avant réveil : 5 à 3600 secondes'; submit('#pwr-form');
  ok(await until(() => $('#pwr-msg').classList.contains('error') && T('#pwr-msg') === L(st.error, 'wait before wake-up: 5 to 3600 seconds')), L('erreur de validation traduite', 'EN: validation error'));
  st.error = '';
  // réveil / veille manuels
  calls.length = 0; btn(rows[1], L('Réveiller', 'Wake up')).click();
  ok(await until(() => calls.some((c) => c[1] === '/api/power/wake' && c[2].id === '2')), L('réveil manuel demandé', 'EN: manual wake'));
  calls.length = 0; btn($$('#pwr-servers tbody tr')[0], L('Mettre en veille', 'Put to sleep')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes('Alpha') && !calls.some((c) => c[1] === '/api/power/sleep'), L('mise en veille : confirmation d\'abord', 'EN: sleep asks first'));
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/power/sleep' && c[2].id === '1')), L('mise en veille demandée après confirmation', 'EN: sleep after confirmation'));
  // réglage d'un serveur
  calls.length = 0; btn($$('#pwr-servers tbody tr')[2], L('Régler', 'Configure')).click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal-title').includes('Gamma'), L('fenêtre de réglage du serveur', 'EN: server settings window'));
  const mi = (label) => $$('#modal input, #modal select').find((i) => (i.getAttribute('aria-label') || '').startsWith(label));
  const mac = mi(L('Adresse MAC', 'MAC address')), wake = mi(L('Réveil automatique', 'Automatic wake-up')), slp = mi(L('Mise en veille automatique', 'Automatic sleep')), idle = mi(L('Inactivité', 'Inactivity'));
  ok(mac && wake && slp && idle && mac.value === '' && !wake.checked && slp.value === '' && idle.value === '30', L('valeurs actuelles préremplies', 'EN: current values'));
  mac.value = '3C-EC-EF-00-00-03'; wake.checked = true; slp.value = 'poweroff'; idle.value = '45';
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/power/server')), L('réglages du serveur envoyés', 'EN: server settings sent'));
  const ss = calls.find((c) => c[1] === '/api/power/server')[2];
  ok(ss.id === '3' && ss.mac === '3C-EC-EF-00-00-03' && ss.wake === true && ss.sleep === 'poweroff' && ss.idle_min === '45' && ss.broadcast === '', L('contenu : MAC, réveil, mode, inactivité', 'EN: payload'));
  ok(await until(() => $$('#pwr-servers tbody tr')[2].children[2].textContent === '3C-EC-EF-00-00-03'), L('liste actualisée', 'EN: list refreshed'));
  // erreur d'enregistrement d'un serveur
  st.error = 'adresse MAC invalide (ex. 3c:ec:ef:12:34:56)'; btn($$('#pwr-servers tbody tr')[2], L('Régler', 'Configure')).click();
  await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(await until(() => !$('#modal').classList.contains('hidden') && T('#modal').includes(L('adresse MAC invalide', 'invalid MAC address'))), L('erreur de validation affichée dans une fenêtre', 'EN: validation error window'));
  $('#modal-ok').click();
  st.error = '';
  // côté serveur géré
  w.location.hash = '#system/central';
  ok(await until(() => $$('#pm-nics tbody tr').length === 2), L('cartes réseau listées', 'EN: network cards listed'));
  ok($('#pm-allow').value === 'suspend', L('autorisation actuelle sélectionnée', 'EN: current permission'));
  const nr = $$('#pm-nics tbody tr');
  ok(nr[0].children[1].textContent === '3c:ec:ef:12:34:56' && nr[0].children[2].textContent === L('Connectée', 'Connected') && nr[1].children[2].textContent === L('Débranchée', 'Unplugged'), L('MAC et liaison de chaque carte', 'EN: MAC and link'));
  ok(nr[0].children[3].textContent === L('Désactivé', 'Disabled') && nr[1].children[3].textContent === L('Non pris en charge', 'Not supported') && nr[1].querySelector('button').disabled && !nr[0].querySelector('button').disabled, L('réveil réseau : état, bouton inactif quand non pris en charge', 'EN: card wake state'));
  calls.length = 0; nr[0].querySelector('button').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/power/wol' && c[2].iface === 'enp3s0' && c[2].enable === true)), L('activation du réveil réseau demandée', 'EN: enable requested'));
  ok(await until(() => $$('#pm-nics tbody tr')[0].children[3].textContent === L('Activé', 'Enabled') && $$('#pm-nics tbody tr')[0].querySelector('button').textContent === L('Désactiver', 'Disable')), L('état actualisé : « Activé », bouton « Désactiver »', 'EN: refreshed'));
  calls.length = 0; $('#pm-allow').value = 'poweroff'; $('#pm-allow').dispatchEvent(new w.Event('change'));
  ok(await until(() => calls.some((c) => c[1] === '/api/power/member' && c[2].allow === 'poweroff')) && await until(() => T('#pm-msg') === L('Enregistré.', 'Saved.')), L('autorisation modifiée et enregistrée', 'EN: permission saved'));
  if (lang === 'en') {
    const r = [...new Set(leftovers(w, '#view-fleet [data-panel=power]').concat(leftovers(w, '#view-system [data-panel=central]')))];
    ok(r.length === 0, 'EN: aucun texte français dans Veille ni dans Gestion centralisée' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
