process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom'); const fs = require('fs');
const BASE = 'https://127.0.0.1:18443'; let n = 0;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 20000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(100); } return false; }
(async () => {
  const html = await (await fetch(BASE + '/')).text(), js = await (await fetch(BASE + '/app.js')).text();
  const w = new JSDOM(html, { url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true }).window, jar = {};
  w.fetch = async (p, o = {}) => { const h = Object.assign({}, o.headers || {}); const c = Object.entries(jar).map(([k, v]) => k + '=' + v).join('; '); if (c) h.Cookie = c;
    const r = await fetch(new URL(p, BASE), Object.assign({}, o, { headers: h })); for (const sc of r.headers.getSetCookie()) { const [kv] = sc.split(';'); const [k, v] = kv.split('='); if (v) jar[k] = v; else delete jar[k]; } return r; };
  let nativeUsed = 0; w.confirm = w.alert = w.prompt = () => { nativeUsed++; return true; };
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {}; w.eval(js);
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], txt = (s) => ($(s) || { textContent: '' }).textContent;
  const modalOpen = () => !$('#modal').classList.contains('hidden');
  const key = (k, opts = {}) => w.document.activeElement.dispatchEvent(new w.KeyboardEvent('keydown', Object.assign({ key: k, bubbles: true, cancelable: true }, opts)));
  await until(() => !$('#login').classList.contains('hidden'));
  const f = $('#login-form'); f.elements.user.value = 'vti'; f.elements.password.value = 'Ollama-2026!'; f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$('#app').classList.contains('hidden')), 'connexion');
  // ---------------- boîtes de dialogue
  w.location.hash = '#models';
  ok(await until(() => $$('#models-table tr').some((r) => /qwen3\.5:2b/.test(r.textContent))), 'onglet Modèles chargé');
  const delBtn = () => [...$$('#models-table tr').find((r) => /qwen3\.5:2b/.test(r.textContent)).querySelectorAll('button')].find((b) => b.textContent === 'Supprimer');
  delBtn().click();
  ok(await until(modalOpen), 'clic sur « Supprimer » : fenêtre de la console ouverte');
  ok(txt('#modal-title') === 'Confirmation' && txt('#modal-text') === 'Supprimer le modèle « qwen3.5:2b » ?' && $('#modal-ok').textContent === 'Supprimer' && $('#modal-ok').classList.contains('danger'),
    'titre « Confirmation », bouton rouge « Supprimer » (action destructrice)');
  ok(w.document.activeElement === $('#modal-ok'), 'focus placé sur le bouton principal');
  key('Tab'); ok(w.document.activeElement === $('#modal-cancel'), 'Tab : focus sur « Annuler »');
  key('Tab'); ok(w.document.activeElement === $('#modal-ok'), 'Tab : le focus reste dans la fenêtre (retour au bouton principal)');
  key('Escape'); await sleep(300);
  ok(!modalOpen() && $$('#models-table tr').some((r) => /qwen3\.5:2b/.test(r.textContent)), 'Échap : fenêtre fermée, modèle conservé');
  delBtn().click(); await until(modalOpen); $('#modal').dispatchEvent(new w.MouseEvent('click', { bubbles: true })); await sleep(300);
  ok(!modalOpen() && $$('#models-table tr').some((r) => /qwen3\.5:2b/.test(r.textContent)), 'clic en dehors de la fenêtre : annulé, modèle conservé');
  delBtn().click(); await until(modalOpen); key('Enter');
  ok(await until(() => !$$('#models-table tr').some((r) => /qwen3\.5:2b/.test(r.textContent)), 15000), 'Entrée : suppression confirmée, modèle retiré de la liste');
  const delOf = (name) => [...$$('#models-table tr').find((r) => r.textContent.includes(name)).querySelectorAll('button')].find((b) => b.textContent === 'Supprimer');
  delOf('llama3.2:3b').click(); await until(modalOpen);
  await fetch('http://127.0.0.1:11434/api/delete', { method: 'DELETE', body: JSON.stringify({ model: 'llama3.2:3b' }) });   // supprimé entre-temps par un autre client
  key('Enter');
  ok(await until(() => modalOpen() && $('#modal').classList.contains('error')) && txt('#modal-title') === 'Erreur' && $('#modal-cancel').classList.contains('hidden'),
    'erreur du serveur : fenêtre « Erreur » de la console (« ' + txt('#modal-text').slice(0, 60) + ' »), un seul bouton');
  key('Enter'); await sleep(200);
  // ---------------- file des tâches système
  w.location.hash = '#system';
  ok(await until(() => $$('[data-job]').length >= 2), 'onglet Système chargé');
  w.manualModal = false;
  const auto = w.setInterval(() => { if (modalOpen() && !w.manualModal) $('#modal-ok').click(); }, 40);
  const jobBtn = (t) => $$('[data-job]').find((b) => b.textContent === t);
  jobBtn('Rechercher maintenant').click(); await sleep(400); jobBtn('Installer les mises à jour de sécurité').click(); await sleep(400); jobBtn('Rechercher maintenant').click();
  ok(await until(() => $$('#job-queue .q').length === 3), 'carte des tâches : file de 3 tâches affichée');
  ok(/en cours/.test($$('#job-queue .q')[0].textContent) && /en attente n°1/.test($$('#job-queue .q')[1].textContent) && /en attente n°2/.test($$('#job-queue .q')[2].textContent),
    'ordre affiché : ' + $$('#job-queue .q').map((q) => q.textContent.replace('Annuler', '').trim()).join(' | '));
  w.manualModal = true;
  const cancelled = $$('#job-queue .q')[2].textContent; const before = $$('#job-queue .q').length;
  $$('#job-queue .q')[2].querySelector('button').click(); await until(modalOpen);
  ok(txt('#modal-title') === 'Annuler une tâche' && $('#modal-ok').textContent === 'Retirer de la file' && $('#modal-cancel').textContent === 'Garder', 'annulation : fenêtre « Retirer de la file » / « Garder »');
  $('#modal-ok').click(); w.manualModal = false;
  ok(await until(() => $$('#job-queue .q').length < before && $$('#job-queue .q').filter((q) => /en attente/.test(q.textContent)).length <= 1), 'tâche retirée de la file (« ' + cancelled.replace('Annuler', '').trim() + ' »)');
  ok(await until(() => !$$('#job-queue .q').length && /terminé/.test(txt('#job-title')), 60000), 'file vidée, la carte a enchaîné jusqu\'à la dernière tâche : « ' + txt('#job-title') + ' »');
  // ---------------- publication de l'API
  ok(await until(() => $('#pub-form').elements.port.value === '11443'), 'carte Publication : HTTPS 11443 proposé par défaut, accès désactivé');
  ok(!$('#expose-api'), 'ancien interrupteur « sans authentification » supprimé');
  const pf = $('#pub-form'); pf.elements.enabled.checked = true; pf.elements.tls.value = '1'; pf.elements.auth.checked = true;
  pf.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => /Enregistré/.test(txt('#pub-msg'))), 'publication HTTPS avec clés enregistrée');
  ok(/https:\/\/192\.0\.2\.2:11443/.test(txt('#pub-urls')) && /Authorization: Bearer <clé>/.test(txt('#pub-urls .example')), 'adresse et exemple affichés : « ' + txt('#pub-urls .example').slice(0, 70) + '... »');
  const kf = $('#key-form'); kf.elements.name.value = 'Appli Test'; $$('#key-models input').find((i) => i.value === 'ob-tiny:latest').checked = true;
  w.manualModal = true; kf.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => modalOpen() && /Clé « Appli Test » créée/.test(txt('#modal-title'))), 'clé créée : fenêtre « ' + txt('#modal-title') + ' »');
  const token = txt('#modal-extra .token');
  ok(/^ob_[A-Za-z0-9_-]{40,}$/.test(token) && $('#modal-cancel').classList.contains('hidden') && $('#modal-ok').textContent === 'J\'ai copié la clé', 'clé affichée une seule fois (' + token.slice(0, 9) + '…) avec « Copier » et « J\'ai copié la clé »');
  ok(!fs.readFileSync('/tmp/target/etc/ollamabuntu/publication.json', 'utf8').includes(token), 'la clé affichée n\'est pas stockée en clair sur le serveur');
  $('#modal-ok').click(); w.manualModal = false;
  ok(await until(() => $$('#pub-keys tbody tr').some((r) => /Appli Test/.test(r.textContent) && /ob-tiny:latest/.test(r.textContent) && /jamais/.test(r.textContent))), 'tableau des clés : « Appli Test », modèle ob-tiny:latest, jamais utilisée');
  $$('#pub-keys button').find((b) => b.textContent === 'Désactiver').click();
  ok(await until(() => /désactivée/.test(txt('#pub-keys'))), 'clé désactivée (après confirmation)');
  pf.elements.auth.checked = true; pf.elements.auth.click();   // décocher : clé non exigée
  ok(!$('#pub-anon').classList.contains('hidden'), 'clé non exigée : réglage des droits anonymes affiché');
  w.manualModal = true; pf.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => modalOpen() && txt('#modal-title') === 'Publier sans clé ?' && $('#modal-ok').classList.contains('danger')), 'publier sans clé : avertissement « ' + txt('#modal-text').slice(0, 70) + ' »');
  $('#modal-ok').click(); w.manualModal = false;
  ok(await until(() => /API publiée sans clé/.test(txt('#pub-warn'))), 'avertissement permanent sur la carte : « ' + txt('#pub-warn .notice').slice(0, 70) + ' »');
  $$('#pub-keys button').find((b) => b.textContent === 'Supprimer').click();
  ok(await until(() => !$$('#pub-keys tbody tr').length), 'clé supprimée');
  w.clearInterval(auto);
  ok(nativeUsed === 0, 'aucune fenêtre système (confirm/alert/prompt) utilisée pendant tout le parcours');
  process.exit(0);
})().catch((e) => { console.log('ERREUR', e); process.exit(1); });
