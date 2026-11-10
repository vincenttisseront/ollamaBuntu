process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom'); const { spawn } = require('child_process'); const fs = require('fs'); const http = require('http');
const BASE = 'https://127.0.0.1:18443'; let n = 0, router;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) { if (router) router.kill(); process.exit(1); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 30000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(150); } return false; }
const gen = (model) => new Promise((res) => { const body = JSON.stringify({ model, prompt: 'Bonjour', stream: true, options: { num_predict: 16 } });
  const r = http.request({ host: '127.0.0.1', port: 18434, path: '/api/generate', method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, (resp) => { resp.resume(); resp.on('end', () => res(resp.statusCode)); }); r.end(body); });
(async () => {
  router = spawn('chroot', ['--userspec=ollama:ollama', '/tmp/target', '/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'OB_ETC=/tmp/rt-etc2', 'OB_MAIN=127.0.0.1:11434', 'OB_ROUTER_LISTEN=127.0.0.1:18434',
    'OB_ROUTER_REQLOG=/tmp/reqs/requests.jsonl', 'OB_ROUTER_USAGE=/tmp/reqs/usage.json', 'python3', '/usr/local/lib/ollamabuntu/router.py'], { stdio: 'ignore' });
  await sleep(2000);
  const html = await (await fetch(BASE + '/')).text(), js = await (await fetch(BASE + '/app.js')).text();
  const w = new JSDOM(html, { url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true }).window, jar = {};
  w.fetch = async (p, o = {}) => { const h = Object.assign({}, o.headers || {}); const c = Object.entries(jar).map(([k, v]) => k + '=' + v).join('; '); if (c) h.Cookie = c;
    const r = await fetch(new URL(p, BASE), Object.assign({}, o, { headers: h })); for (const sc of r.headers.getSetCookie()) { const [kv] = sc.split(';'); const [k, v] = kv.split('='); if (v) jar[k] = v; else delete jar[k]; } return r; };
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {}; w.eval(js);
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], txt = (s) => ($(s) || { textContent: '' }).textContent;
  await until(() => !$('#login').classList.contains('hidden'));
  const f = $('#login-form'); f.elements.user.value = 'vti'; f.elements.password.value = 'Ollama-2026!'; f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$('#app').classList.contains('hidden')), 'connexion');
  // --- onglets internes
  const tabs = (v) => $$('#view-' + v + ' > .subtabs a').map((a) => a.textContent);
  ok(tabs('system').join(' | ') === "Vue d'ensemble | Mises à jour | Publication de l'API | Gestion centralisée", 'Système : ' + tabs('system').join(' | '));
  ok(tabs('models').length === 5 && tabs('gpu').length === 3 && tabs('security').length === 4 && tabs('logs').length === 2 && tabs('fleet').length === 3 && tabs('users').length === 2,
    'onglets : Modèles 5, GPU 3, Sécurité 4, Journaux 2, Serveurs 3, Utilisateurs 2');
  w.location.hash = '#system';
  ok(await until(() => !$('#panel-system-overview').classList.contains('hidden') && $('#panel-system-api').classList.contains('hidden')), 'Système : un seul onglet visible à la fois (Vue d\'ensemble)');
  $('#tab-system-api').click(); await sleep(300);
  ok(w.location.hash === '#system/api' && !$('#panel-system-api').classList.contains('hidden') && $('#tab-system-api').getAttribute('aria-selected') === 'true', 'clic sur « Publication de l\'API » : lien direct #system/api, onglet accessible (aria-selected)');
  w.location.hash = '#dashboard'; await sleep(300); w.location.hash = '#system'; await sleep(300);
  ok(!$('#panel-system-api').classList.contains('hidden'), 'onglet choisi mémorisé au retour sur l\'écran');
  const maxCards = Math.max(...$$('.panel').map((p) => p.querySelectorAll(':scope > .card').length));
  ok(maxCards <= 2, 'plus d\'empilement : 2 cartes au plus par onglet (contre 7 auparavant dans Système)');
  // --- requêtes réelles et performances
  for (const m of ['ob-tiny', 'ob-tiny', 'qwen3.5:2b']) ok(await gen(m) === 200, 'requête réelle via le routeur : ' + m);
  w.location.hash = '#logs/requests';
  ok(await until(() => $$('#req-list tbody tr').length >= 3, 15000), 'Journaux > Requêtes Ollama : ' + $$('#req-list tbody tr').length + ' requêtes listées');
  const row = $$('#req-list tbody tr')[0].textContent;
  ok(/local/.test(row) && /200/.test(row) && /\d+ \/ \d+/.test(row), 'ligne de requête : client, statut, jetons entrée / sortie (« ' + row.replace(/\s+/g, ' ').slice(0, 90) + ' »)');
  ok($$('#req-list tbody tr').some((r) => /\d+,\d|\d+\.\d/.test(r.lastChild.textContent)), 'vitesse de génération (t/s) mesurée et affichée');
  const sum = $$('#req-summary tbody tr').map((r) => r.textContent);
  const cells = $$('#req-summary tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(cells.some((c) => c[0] === 'ob-tiny:latest' && c[1] === '2') && cells.some((c) => c[0] === 'qwen3.5:2b' && c[1] === '1'), 'synthèse par modèle sur la dernière heure : ob-tiny 2 requêtes, qwen3.5 1 (« ob-tiny » et « ob-tiny:latest » regroupés)');
  const rl = fs.readFileSync('/tmp/target/tmp/reqs/requests.jsonl', 'utf8');
  ok(!/Bonjour/.test(rl) && /"tps"/.test(rl), 'journal du routeur : métadonnées et t/s, jamais le texte des requêtes');
  w.location.hash = '#dashboard';
  ok(await until(() => $$('#perf-charts .chart').length === 6, 15000), 'tableau de bord : 6 graphiques de performances');
  let fed = false;   // un rendu à la fois : attendre sa fin avant de vérifier
  for (let i = 0; i < 20 && !fed; i++) { $('#perf-range button[data-span="3600"]').click(); await sleep(1200); fed = $$('#perf-charts .chart')[3].querySelectorAll('path, circle').length >= 1; if (!fed) await sleep(1000); }
  ok(fed, 'graphique « Requêtes par minute » alimenté par les requêtes réelles');
  ok($$('#perf-charts .chart')[0].querySelectorAll('path').length >= 1 && /AMD Radeon PRO W7800/.test($$('#perf-charts .chart')[0].textContent), 'graphique « Charge GPU » : une courbe par GPU, nommée');
  ok($$('#perf-charts svg').every((s) => /:/.test(s.getAttribute('aria-label'))), 'graphiques accessibles : résumé textuel des valeurs (aria-label)');
  ok(await until(() => $$('#dash-requests tbody tr').length >= 3), 'tableau de bord : dernières requêtes (' + $$('#dash-requests tbody tr').length + ')');
  $$('#perf-range button')[0].click(); await sleep(800);
  ok($$('#perf-range button')[0].classList.contains('on') && /15 min/.test($$('#perf-range button')[0].textContent), 'période des graphiques : 15 min sélectionnable');
  // --- journaux en direct
  fs.writeFileSync('/tmp/target/var/log/ollamabuntu-install.log', 'ligne 1 : installation\nligne 2 : ERREUR de test\n');
  w.location.hash = '#logs/system'; $('#log-source').value = 'install'; $('#log-source').dispatchEvent(new w.Event('change'));
  ok(await until(() => $$('#log-text div').length === 2), 'journal d\'installation affiché ligne par ligne');
  ok($$('#log-text div')[1].classList.contains('l-err'), 'lignes d\'erreur mises en évidence');
  $('#log-live').click(); ok($('#log-live').getAttribute('aria-pressed') === 'true', 'suivi en direct activé');
  fs.appendFileSync('/tmp/target/var/log/ollamabuntu-install.log', 'ligne 3 : ajoutée pendant le suivi\n');
  ok(await until(() => $$('#log-text div').length === 3 && /ajoutée pendant le suivi/.test(txt('#log-text')), 10000), 'nouvelle ligne apparue d\'elle-même en moins de 3 s (curseur : seules les nouvelles lignes)');
  $('#log-filter').value = 'ERREUR'; $('#log-filter').dispatchEvent(new w.Event('input'));
  ok($$('#log-text div:not(.hide)').length === 1, 'filtre : seules les lignes contenant « ERREUR » restent visibles');
  w.location.hash = '#dashboard'; await sleep(300);
  ok($('#log-live').getAttribute('aria-pressed') === 'false', 'suivi en direct arrêté en quittant l\'écran');
  router.kill(); process.exit(0);
})().catch((e) => { console.log('ERREUR', e); if (router) router.kill(); process.exit(1); });
