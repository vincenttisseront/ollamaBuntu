process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom'); const { spawn } = require('child_process'); const fs = require('fs'); const http = require('http');
let n = 0, member, router;
const kill = () => { if (member) member.kill(); if (router) router.kill(); };
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) { kill(); process.exit(1); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 40000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(150); } return false; }
const SECRET = 'Résume le contrat de Mme Martin, IBAN FR7630006000011234567890189, mail martin@exemple.fr';
const gen = (prompt) => new Promise((res) => { const body = JSON.stringify({ model: 'ob-tiny', prompt, stream: false, options: { num_predict: 6 } });
  const r = http.request({ host: '127.0.0.1', port: 18434, path: '/api/generate', method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, (resp) => { resp.resume(); resp.on('end', () => res(resp.statusCode)); }); r.end(body); });
async function browser(BASE) {
  const html = await (await fetch(BASE + '/')).text(), js = await (await fetch(BASE + '/app.js')).text();
  const w = new JSDOM(html, { url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true }).window, jar = {};
  w.fetch = async (p, o = {}) => { const h = Object.assign({}, o.headers || {}); const c = Object.entries(jar).map(([k, v]) => k + '=' + v).join('; '); if (c) h.Cookie = c;
    const r = await fetch(new URL(p, BASE), Object.assign({}, o, { headers: h })); for (const sc of r.headers.getSetCookie()) { const [kv] = sc.split(';'); const [k, v] = kv.split('='); if (v) jar[k] = v; else delete jar[k]; } return r; };
  w.native = 0; w.confirm = w.alert = w.prompt = () => { w.native++; return true; };
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {}; w.eval(js);
  const $ = (s) => w.document.querySelector(s);
  await until(() => !$('#login').classList.contains('hidden'));
  const f = $('#login-form'); f.elements.user.value = 'vti'; f.elements.password.value = 'Ollama-2026!'; f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  await until(() => !$('#app').classList.contains('hidden'));
  w.api = async (method, path, body) => { const r = await w.fetch(path, { method, headers: { 'X-OB': '1', 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }); return r.json(); };
  return w;
}
(async () => {
  const M = '/tmp/target/tmp/member', E = '/tmp/target/etc/ollamabuntu/';
  fs.rmSync(M, { recursive: true, force: true }); fs.mkdirSync(M + '/etc', { recursive: true }); fs.mkdirSync(M + '/state');
  fs.copyFileSync(E + 'users.json', M + '/etc/users.json'); fs.writeFileSync(M + '/etc/ollama.env', 'OLLAMA_NO_CLOUD=1\n');
  for (const f of ['fleet.json', 'fleet-routes.json', 'balance.json', 'request-log.json']) fs.rmSync(E + f, { force: true });
  for (const f of ['requests.jsonl', 'requests.jsonl.1']) fs.rmSync('/tmp/target/tmp/reqs/' + f, { force: true });
  member = spawn('chroot', ['/tmp/target', '/usr/bin/env', '-i', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG=C.UTF-8', 'OB_ETC=/tmp/member/etc', 'OB_STATE=/tmp/member/state',
    'OB_HTTPS_PORT=18444', 'OB_HTTP_PORT=0', 'OB_OLLAMA_MAIN=127.0.0.1:11434', 'OB_NFT=/usr/local/bin/nft-stub', 'OB_PCI_ROOT=/tmp/gpufake/pci', 'OB_OLLAMA_LOG=/tmp/gpufake/ollama.log', 'python3', '/usr/local/lib/ollamabuntu/admin/server.py'], { stdio: 'ignore' });
  router = spawn('chroot', ['--userspec=ollama:ollama', '/tmp/target', '/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'OB_ETC=/etc/ollamabuntu', 'OB_MAIN=127.0.0.1:11434', 'OB_ROUTER_LISTEN=127.0.0.1:18434',
    'OB_ROUTER_REQLOG=/tmp/reqs/requests.jsonl', 'OB_ROUTER_USAGE=/tmp/reqs/usage.json', 'python3', '/usr/local/lib/ollamabuntu/router.py'], { stdio: 'ignore' });
  await sleep(3000);
  const S = await browser('https://127.0.0.1:18444'), P = await browser('https://127.0.0.1:18443');
  const $ = (s) => P.document.querySelector(s), $$ = (s) => [...P.document.querySelectorAll(s)], open = () => !$('#modal').classList.contains('hidden');
  const fp = (await S.api('GET', '/api/fleet/member')).fingerprint, tok = (await S.api('POST', '/api/fleet/member/create', { name: 'Console principale' })).token;
  // --- ajout d'un serveur : la case « répartition » est cochée par défaut
  P.location.hash = '#fleet/add';
  const f = $('#fleet-form');
  ok(f.elements.route.checked === true && /Activer aussi la répartition de charge/.test(f.textContent), 'formulaire d\'ajout : « Activer aussi la répartition de charge » cochée par défaut');
  f.elements.name.value = 'GPU-Lyon-02'; f.elements.url.value = 'https://127.0.0.1:18444'; f.elements.token.value = tok; f.dispatchEvent(new P.Event('submit', { cancelable: true }));
  ok(await until(() => open() && $('#modal-title').textContent === 'Vérifier le certificat'), 'vérification du certificat demandée'); $('#modal-ok').click();
  ok(await until(() => /répartition de charge activée/.test($('#fleet-msg').textContent)), 'ajout : « ' + $('#fleet-msg').textContent + ' »');
  // --- onglet Répartition
  P.location.hash = '#fleet/balance';
  ok(await until(() => $('#bal-issues li.okmsg')), 'onglet Répartition : « ' + ($('#bal-issues li.okmsg') || { textContent: '' }).textContent + ' »');
  const srows = () => $$('#bal-servers tbody tr').map((r) => r.textContent.replace(/\s+/g, ' '));
  ok(await until(() => srows().length === 2), 'tableau par serveur : ' + srows().join(' | ').slice(0, 150));
  ok(/GPU-Lyon-02.*en ligne.*activée/.test(srows()[1]) && /^Ce serveur/.test(srows()[0]), 'GPU-Lyon-02 : en ligne, répartition activée ; ligne « Ce serveur » en tête');
  ok($$('#bal-models tbody tr').some((r) => /ob-tiny/.test(r.textContent) && /Ce serveur, GPU-Lyon-02/.test(r.children[1].textContent) && r.lastChild.textContent === 'oui'), 'tableau des modèles : ob-tiny présent sur les deux serveurs, répartissable');
  const sel = $('#bal-strategy');
  ok(sel.value === 'spread' && /se relaient/.test($('#bal-strategy-help').textContent), 'stratégie par défaut : « Répartir » avec son explication');
  sel.value = 'warm'; sel.dispatchEvent(new P.Event('change'));
  ok(await until(() => /Enregistré/.test($('#bal-msg').textContent)) && JSON.parse(fs.readFileSync(E + 'balance.json', 'utf8')).strategy === 'warm' && /déjà le modèle en mémoire/.test($('#bal-strategy-help').textContent), 'stratégie « modèle déjà chargé » enregistrée, explication mise à jour');
  sel.value = 'spread'; sel.dispatchEvent(new P.Event('change')); await sleep(600);
  ok(!$('#bal-test').disabled, 'bouton « Tester la répartition » actif');
  $('#bal-test').click();
  ok(await until(() => open() && $('#modal-title').textContent === 'Tester la répartition' && $('#modal-extra select') && [...$('#modal-extra select').options].some((o) => o.value === 'ob-tiny:latest')), 'test : fenêtre avec le choix du modèle (ob-tiny présent sur les deux serveurs)');
  $('#modal-ok').click();
  ok(await until(() => open() && $('#modal-title').textContent === 'Résultat du test', 60000), 'test terminé');
  const txt = $('#modal-text').textContent, items = [...$('#modal-extra').querySelectorAll('li')].map((l) => l.textContent.replace(/\s+/g, ' ').trim());
  ok(/4 requêtes envoyées en même temps, 4 réussie\(s\)/.test(txt) && items.length === 2 && items.some((x) => /^Ce serveur 2 requête/.test(x)) && items.some((x) => /^GPU-Lyon-02 2 requête/.test(x)), 'résultat : ' + txt + ' -> ' + items.join(' ; '));
  $('#modal-ok').click();
  // --- tableau de bord : serveur et demande
  for (let i = 0; i < 4; i++) await gen(SECRET);
  P.location.hash = '#dashboard';
  ok(await until(() => $$('#dash-requests tbody tr').length >= 4), 'tableau de bord : ' + $$('#dash-requests tbody tr').length + ' requêtes récentes');
  const heads = $$('#dash-requests thead th').map((t) => t.textContent);
  ok(['Serveur', 'Demande'].every((h) => heads.includes(h)), 'colonnes : ' + heads.join(' | '));
  const col = (name) => heads.indexOf(name), rows = () => $$('#dash-requests tbody tr');
  ok(rows().every((r) => r.children[col('Demande')].textContent === '-') && !$('#dash-req-note').classList.contains('hidden') && $('#dash-req-note a[href="#logs/requests"]'), 'extrait désactivé : colonne « Demande » vide et lien « ' + $('#dash-req-note a').textContent + ' »');
  const wh = new Set(rows().map((r) => r.children[col('Serveur')].textContent));
  ok(wh.has('Ce serveur') && wh.has('GPU-Lyon-02'), 'colonne « Serveur » : ' + [...wh].join(', ') + ' (la répartition se voit d\'un coup d\'œil)');
  // --- journaux : activer l'extrait
  P.location.hash = '#logs/requests';
  ok(await until(() => $('#req-excerpt') && $('#req-excerpt').checked === false && $$('#req-list tbody tr').length >= 4), 'Journaux > Requêtes : extrait décoché par défaut');
  $('#req-excerpt').checked = true; $('#req-excerpt').dispatchEvent(new P.Event('change'));
  ok(await until(() => open() && /visible des administrateurs/.test($('#modal-text').textContent)), 'activation : confirmation expliquant la portée et le masquage'); $('#modal-ok').click();
  ok(await until(() => /Enregistré/.test($('#req-settings-msg').textContent)) && JSON.parse(fs.readFileSync(E + 'request-log.json', 'utf8')).prompt_excerpt === true, 'extrait activé (fichier de réglage à jour)');
  await sleep(500); for (let i = 0; i < 2; i++) await gen(SECRET);
  P.location.hash = '#dashboard';
  ok(await until(() => rows().some((r) => /\[IBAN\]/.test(r.children[col('Demande')].textContent)), 30000), 'tableau de bord : l\'extrait s\'affiche -> « ' + (rows().map((r) => r.children[col('Demande')].textContent).find((t) => t !== '-') || '') + ' »');
  const shown = $('#dash-requests').textContent;
  ok(!/FR7630|martin@/.test(shown) && /\[e-mail\]/.test(shown) && $('#dash-req-note').classList.contains('hidden'), 'IBAN et e-mail masqués à l\'écran ; l\'invitation à activer l\'extrait a disparu');
  // --- effacer
  P.location.hash = '#logs/requests';
  ok(await until(() => $('#req-clear') && $$('#req-list tbody tr').some((r) => /\[IBAN\]/.test(r.textContent))), 'journal complet : colonne « Demande » renseignée');
  $('#req-clear').click();
  ok(await until(() => open() && $('#modal-ok').classList.contains('danger') && /définitive/.test($('#modal-text').textContent)), 'effacement : confirmation rouge « action définitive »'); $('#modal-ok').click();
  ok(await until(() => /Historique effacé/.test($('#req-settings-msg').textContent) && /Aucune requête enregistrée/.test($('#req-list').textContent)), 'historique effacé');
  await P.api('POST', '/api/requests/settings', { prompt_excerpt: false });
  ok(P.native === 0 && S.native === 0, 'aucune fenêtre système utilisée');
  for (const x of ['fleet.json', 'fleet-routes.json', 'balance.json', 'request-log.json']) fs.rmSync(E + x, { force: true });
  kill(); process.exit(0);
})().catch((e) => { console.log('ERREUR', e); kill(); process.exit(1); });
