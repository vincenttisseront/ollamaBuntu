process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom'); const { spawn } = require('child_process'); const fs = require('fs');
let n = 0, member;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) { if (member) member.kill(); process.exit(1); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 30000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(150); } return false; }
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
  const $S = (s) => S.document.querySelector(s), $P = (s) => P.document.querySelector(s), $$P = (s) => [...P.document.querySelectorAll(s)];
  const open = (w) => !w.document.querySelector('#modal').classList.contains('hidden');
  ok(true, 'deux consoles ouvertes : principale (18443) et serveur géré (18444)');
  S.location.hash = '#system';
  ok(await until(() => /([0-9A-F]{2}:){31}[0-9A-F]{2}/.test($S('#fm-fp').textContent)), 'serveur géré : empreinte de son certificat affichée');
  const fp = $S('#fm-fp code').textContent;
  $S('#fm-name').value = 'Console principale Paris'; $S('#fm-add').click();
  ok(await until(() => open(S) && /autorisée/.test($S('#modal-title').textContent)), 'autorisation : fenêtre « ' + $S('#modal-title').textContent + ' »');
  const token = $S('#modal-extra code.token').textContent;
  ok(/^obf_/.test(token) && $S('#modal-extra code.fp').textContent === fp && $S('#modal-cancel').classList.contains('hidden'), 'jeton affiché une seule fois, avec l\'empreinte à vérifier (' + token.slice(0, 10) + '…)');
  $S('#modal-ok').click();
  P.location.hash = '#fleet';
  ok(await until(() => /Aucun serveur enregistré/.test($P('#fleet-summary').textContent)), 'console principale > Serveurs : « ' + $P('#fleet-summary').textContent + ' »');
  const f = $P('#fleet-form'); f.elements.name.value = 'GPU-Paris-01'; f.elements.url.value = 'https://127.0.0.1:18444'; f.elements.token.value = token;
  f.dispatchEvent(new P.Event('submit', { cancelable: true }));
  ok(await until(() => open(P) && $P('#modal-title').textContent === 'Vérifier le certificat'), 'ajout : fenêtre « Vérifier le certificat »');
  ok($P('#modal-extra code').textContent === fp && $P('#modal-ok').textContent === 'Les empreintes sont identiques', 'empreinte présentée identique à celle du serveur géré ; bouton « Les empreintes sont identiques »');
  $P('#modal-ok').click();
  ok(await until(() => /Serveur ajouté/.test($P('#fleet-msg').textContent)), 'serveur ajouté');
  const card = () => $$P('#fleet-grid .fleet').find((c) => /GPU-Paris-01/.test(c.textContent));
  ok(await until(() => card() && /en ligne/.test(card().querySelector('.head').textContent)), 'carte du serveur : « en ligne »');
  ok(/OllamaBuntu 2026/.test(card().textContent) && card().querySelectorAll('.gpus .g').length >= 1 && /Processeur .* - mémoire \d+ % - disque \d+ %/.test(card().textContent),
    'version, charge par GPU (' + card().querySelectorAll('.gpus .g').length + '), processeur, mémoire et disque affichés');
  ok(/1 serveur\(s\) - 1 en ligne/.test($P('#fleet-summary').textContent), 'synthèse du parc : « ' + $P('#fleet-summary').textContent + ' »');
  [...card().querySelectorAll('button')].find((b) => b.textContent === 'Redémarrage d\'Ollama').click();
  ok(await until(() => open(P) && /Redémarrage d'Ollama sur « GPU-Paris-01 »/.test($P('#modal-text').textContent)), 'action à distance : confirmation demandée');
  $P('#modal-ok').click();
  ok(await until(() => open(P) && /Action envoyée à « GPU-Paris-01 »/.test($P('#modal-text').textContent)), 'action envoyée : « ' + $P('#modal-text').textContent + ' »');
  $P('#modal-ok').click();
  S.location.hash = '#dashboard'; await sleep(300); S.location.hash = '#system';
  ok(await until(() => $S('#fm-list') && /dernier contact : \d/.test($S('#fm-list').textContent)), 'serveur géré : la console principale apparaît, avec son dernier contact');
  [...card().querySelectorAll('button')].find((b) => b.textContent === 'Retirer').click();
  await until(() => open(P)); ok($P('#modal-ok').classList.contains('danger'), 'retrait : confirmation (bouton rouge)'); $P('#modal-ok').click();
  ok(await until(() => !card()), 'serveur retiré de la console principale');
  ok(P.native === 0 && S.native === 0, 'aucune fenêtre système utilisée');
  member.kill(); process.exit(0);
})().catch((e) => { console.log('ERREUR', e); if (member) member.kill(); process.exit(1); });
