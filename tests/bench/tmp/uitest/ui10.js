process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom'); const { spawn } = require('child_process'); const fs = require('fs');
let n = 0, member;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) { if (member) member.kill(); process.exit(1); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 40000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(150); } return false; }
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
  const M = '/tmp/target/tmp/member';
  fs.rmSync(M, { recursive: true, force: true }); fs.mkdirSync(M + '/etc', { recursive: true }); fs.mkdirSync(M + '/state');
  fs.copyFileSync('/tmp/target/etc/ollamabuntu/users.json', M + '/etc/users.json'); fs.writeFileSync(M + '/etc/ollama.env', 'OLLAMA_NO_CLOUD=1\n');
  member = spawn('chroot', ['/tmp/target', '/usr/bin/env', '-i', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG=C.UTF-8', 'OB_ETC=/tmp/member/etc', 'OB_STATE=/tmp/member/state',
    'OB_HTTPS_PORT=18444', 'OB_HTTP_PORT=0', 'OB_OLLAMA_MAIN=127.0.0.1:11434', 'OB_NFT=/usr/local/bin/nft-stub', 'OB_PCI_ROOT=/tmp/gpufake/pci', 'OB_OLLAMA_LOG=/tmp/gpufake/ollama.log', 'python3', '/usr/local/lib/ollamabuntu/admin/server.py'], { stdio: 'ignore' });
  await sleep(2500);
  const S = await browser('https://127.0.0.1:18444'), P = await browser('https://127.0.0.1:18443');
  const $P = (s) => P.document.querySelector(s), $$P = (s) => [...P.document.querySelectorAll(s)], $S = (s) => S.document.querySelector(s);
  const open = () => !$P('#modal').classList.contains('hidden');
  // préparation : serveur ajouté, clé locale sur le serveur géré, données à synchroniser sur la console principale
  const fp = (await S.api('GET', '/api/fleet/member')).fingerprint, tok = (await S.api('POST', '/api/fleet/member/create', { name: 'Console principale' })).token;
  await S.api('POST', '/api/publication/keys/create', { name: 'Clé locale du serveur', perms: ['read'] });
  await P.api('POST', '/api/fleet/servers/add', { name: 'GPU-Lyon-02', url: 'https://127.0.0.1:18444', token: tok, fingerprint: fp });
  const k = await P.api('POST', '/api/publication/keys/create', { name: 'Appli RH', perms: ['inference', 'read'], deny: ['tools'] });
  await P.api('POST', '/api/models/custom/create', { name: 'assistant-parc', base: 'ob-tiny', system: 'Tu es l\'assistant du parc.', params: { temperature: 0.3 } });
  await P.api('POST', '/api/security/policy', { cloud: false, webui: { web_search: true }, webui_locked: true });
  ok(true, 'préparation : serveur ajouté, clé « Appli RH », modèle « assistant-parc » et politique sur la console principale ; clé locale sur le serveur géré');
  P.location.hash = '#fleet';
  const card = () => $$P('#fleet-grid .fleet').find((c) => /GPU-Lyon-02/.test(c.textContent));
  ok(await until(() => card() && /en ligne/.test(card().textContent)), 'onglet Serveurs : GPU-Lyon-02 en ligne');
  [...card().querySelectorAll('button')].find((b) => b.textContent === 'Activer la répartition de charge').click();
  ok(await until(() => open() && /limité à l'utilisation des modèles/.test($P('#modal-text').textContent)), 'activation : explication (jeton limité, politique du serveur conservée)');
  $P('#modal-ok').click();
  ok(await until(() => card() && /répartition/.test(card().querySelector('.head').textContent) && /répartition de charge sur 1 serveur/.test($P('#fleet-summary').textContent)), 'répartition active : pastille « répartition », synthèse « répartition de charge sur 1 serveur(s) »');
  ok(fs.readFileSync('/tmp/target/etc/ollamabuntu/fleet-routes.json', 'utf8').includes('obr_'), 'routes du routeur alimentées (jeton de routage)');
  [...card().querySelectorAll('button')].find((b) => b.textContent === 'Synchroniser...').click();
  ok(await until(() => open() && P.document.querySelectorAll('#modal-extra input[name=sync]').length === 4), 'synchroniser : choix Modèles, Modèles personnalisés, Politique, Clés d\'API');
  ok(!P.document.querySelector('#modal-extra input[value=models]').checked, 'téléchargement des modèles non coché par défaut (volumes importants)');
  $P('#modal-ok').click();
  ok(await until(() => open() && $P('#modal-title').textContent === 'Synchronisation terminée', 60000), 'synchronisation terminée');
  const rep = $P('#modal-text').textContent;
  ok(/GPU-Lyon-02 : politique appliquée, 1 clé\(s\) d'API, .*1 modèle\(s\) personnalisé\(s\) créé\(s\)/.test(rep), 'compte rendu : « ' + rep.replace(/\n/g, ' ') + ' »');
  $P('#modal-ok').click();
  const mpub = JSON.parse(fs.readFileSync(M + '/etc/publication.json', 'utf8')), mpol = JSON.parse(fs.readFileSync(M + '/etc/ai-policy.json', 'utf8'));
  const rh = mpub.keys.find((x) => x.name === 'Appli RH');
  ok(rh && rh.synced_from && rh.deny.includes('tools') && !JSON.stringify(mpub).includes(k.token), 'serveur géré : clé « Appli RH » reçue (empreinte et restrictions), jamais la clé elle-même');
  ok(mpub.keys.some((x) => x.name === 'Clé locale du serveur' && !x.synced_from), 'clé créée localement sur le serveur géré : conservée');
  ok(mpol.webui.web_search === true && mpol.webui_locked === true && mpol.cloud === false, 'serveur géré : politique d\'usage de l\'IA identique à celle de la console principale');
  ok(JSON.parse(fs.readFileSync(M + '/etc/custom-models.json', 'utf8')).models['assistant-parc:latest'].system === 'Tu es l\'assistant du parc.', 'serveur géré : modèle personnalisé « assistant-parc » recréé (prompt et paramètres)');
  ok(await until(() => /Dernièresynchronisation\d/.test(card().textContent.replace(/\s/g, ''))), 'carte du serveur : date de dernière synchronisation');
  S.location.hash = '#system';
  ok(await until(() => /Dernière synchronisation reçue de « Console principale »/.test($S('#fm-fp').textContent) && /répartition de charge autorisée/.test($S('#fm-list').textContent)), 'serveur géré : dernière synchronisation reçue et « répartition de charge autorisée » affichées');
  // téléchargement refusé par la politique du serveur géré
  fs.writeFileSync(M + '/etc/ai-policy.json', JSON.stringify(Object.assign(mpol, { ollama_internet: false })));
  const r = await S.api('POST', '/api/fleet/action', null).catch(() => null);
  const direct = await fetch('https://127.0.0.1:18444/api/fleet/action', { method: 'POST', headers: { 'X-OB': '1', 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }, body: JSON.stringify({ action: 'sync', data: { models: ['modele-absent:1b'] } }) }).then((x) => x.json());
  ok(direct.report && direct.report.pull.models[0] === 'modele-absent:1b' && /fleet-pull$/.test(direct.report.pull.job), 'modèle absent du serveur géré : téléchargement mis dans sa file de tâches (' + direct.report.pull.job + ')');
  [...card().querySelectorAll('button')].find((b) => b.textContent === 'Désactiver la répartition').click();
  await until(open); $P('#modal-ok').click();
  ok(await until(() => !/répartition<\/span>|répartitionen/.test(card().querySelector('.head').innerHTML) && !/répartition/.test(card().querySelector('.head').textContent)), 'répartition désactivée');
  ok(P.native === 0 && S.native === 0, 'aucune fenêtre système utilisée');
  member.kill(); process.exit(0);
})().catch((e) => { console.log('ERREUR', e); if (member) member.kill(); process.exit(1); });
