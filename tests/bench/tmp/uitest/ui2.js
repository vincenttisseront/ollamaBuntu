process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom');
const BASE = 'https://127.0.0.1:18443';
let n = 0;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 15000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(150); } return false; }
async function browser() {
  const html = await (await fetch(BASE + '/')).text(), js = await (await fetch(BASE + '/app.js')).text();
  const dom = new JSDOM(html, { url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window, jar = {};
  w.fetch = async (path, opts = {}) => {
    const headers = Object.assign({}, opts.headers || {}); const c = Object.entries(jar).map(([k, v]) => k + '=' + v).join('; ');
    if (c) headers.Cookie = c;
    const r = await fetch(new URL(path, BASE), Object.assign({}, opts, { headers }));
    for (const sc of r.headers.getSetCookie()) { const [kv] = sc.split(';'); const [k, v] = kv.split('='); if (v) jar[k] = v; else delete jar[k]; }
    return r;
  };
  w.TextDecoder = TextDecoder;  w.Element.prototype.scrollIntoView = () => {};
  w.eval(js); w.alerts = []; w.modalLog = []; w.confirm = w.alert = w.prompt = () => { throw new Error('fenêtre système utilisée'); }; w.setInterval(() => { const m = w.document.getElementById('modal'); if (m && !m.classList.contains('hidden') && !w.manualModal) { const t = w.document.getElementById('modal-text').textContent; w.modalLog.push(t); if (m.classList.contains('error')) w.alerts.push(t); w.document.getElementById('modal-ok').click(); } }, 40); return w;
}
const $ = (w, s) => w.document.querySelector(s), $$ = (w, s) => [...w.document.querySelectorAll(s)];
const txt = (w, s) => ($(w, s) || { textContent: '' }).textContent;
(async () => {
  const w = await browser();
  await until(() => !$(w, '#login').classList.contains('hidden'));
  const f = $(w, '#login-form'); f.elements.user.value = 'vti'; f.elements.password.value = 'Ollama-2026!';
  f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$(w, '#app').classList.contains('hidden')), 'connexion administrateur');
  ok([...$$(w, '#nav a')].some((a) => a.textContent === 'Open WebUI' && !a.classList.contains('hidden')), 'onglet « Open WebUI » dans le menu');
  // --- Modèles
  w.location.hash = '#models';
  ok(await until(() => /GPU : 60,4 Go de mémoire vidéo/.test(txt(w, '#capacity'))), 'Modèles > Ce serveur : « ' + txt(w, '#capacity .big') + ' »');
  ok(await until(() => $$(w, '#models-table th').map((t) => t.textContent).includes('Mise à jour')), 'tableau des modèles installés : colonnes Compatibilité + Mise à jour');
  const row = $$(w, '#models-table tr').find((r) => /llama3\.2:3b/.test(r.textContent));
  ok(row && /Mise à jour disponible/.test(row.textContent) && [...row.querySelectorAll('button')].some((b) => b.textContent === 'Mettre à jour'), 'llama3.2:3b : « Mise à jour disponible » + bouton « Mettre à jour »');
  ok(/À jour/.test($$(w, '#models-table tr').find((r) => /qwen3\.5:2b/.test(r.textContent)).textContent), 'qwen3.5:2b : « À jour »');
  ok(await until(() => $$(w, '#catalog .cat-item').length === 24), 'recommandations : 24 modèles, ' + $$(w, '#catalog h3').length + ' catégories (' + $$(w, '#catalog h3').map((h) => h.textContent).join(', ') + ')');
  const first = $(w, '#catalog .cat-item');
  ok(/Entièrement sur GPU/.test(first.textContent), 'premier recommandé (le plus adapté) : ' + first.querySelector('.name').textContent + ' -> ' + first.querySelector('.pill').textContent);
  ok(/Indisponible sur le registre/.test(txt(w, '#catalog')) && /Trop gros pour ce serveur/.test(txt(w, '#catalog')) && /Nécessite Ollama/.test(txt(w, '#catalog')), 'verdicts affichés : indisponible, trop gros, version d\'Ollama insuffisante');
  ok($$(w, '#catalog .cat-item').filter((c) => /Installé/.test(c.textContent)).length === 2, 'modèles déjà installés marqués « Installé »');
  $(w, '#check-name').value = 'gpt-oss:20b'; $(w, '#check-btn').click();
  ok(await until(() => /Entièrement sur GPU/.test(txt(w, '#check-result')) && /Télécharger gpt-oss:20b/.test(txt(w, '#check-result'))), 'vérification : « ' + txt(w, '#check-result').replace(/\s+/g, ' ').slice(0, 95) + ' »');
  $(w, '#check-name').value = 'kimi-k3:cloud'; $(w, '#check-btn').click();
  ok(await until(() => /Modèle cloud/.test(txt(w, '#check-result'))), 'vérification d\'un tag :cloud : « Modèle cloud »');
  // --- Système : mises à jour
  w.location.hash = '#system';
  const EXPECTED = require('child_process').execSync('chroot /tmp/target apt-get -s -o Debug::NoLocking=1 dist-upgrade').toString().split('\n').filter((l) => l.startsWith('Inst ')).length;
  ok(await until(() => new RegExp('^' + EXPECTED + ' paquet\\(s\\) en attente').test(txt(w, '#updates .sum-row')), 20000), 'Système > Mises à jour : « ' + txt(w, '#updates .sum-row').replace(/\s+/g, ' ') + ' »');
  ok(/2 haute/.test(txt(w, '#updates')) && /2 moyenne/.test(txt(w, '#updates')), 'ligne de criticité : ' + $$(w, '#updates .sum-row')[1].textContent.replace(/\s+/g, ' '));
  const link = $$(w, '#updates a.adv').find((a) => a.textContent === 'USN-9001-1');
  ok(link && link.href === 'https://ubuntu.com/security/notices/USN-9001-1' && link.target === '_blank', 'lien vers l\'avis Ubuntu : ' + (link && link.href));
  const firstRow = $$(w, '#updates tbody tr')[0];
  ok(/libssl3t64/.test(firstRow.textContent) && /haute/.test(firstRow.textContent), 'première ligne : ' + firstRow.textContent.replace(/\s+/g, ' ').slice(0, 90));
  ok(['Rechercher maintenant', 'Installer les mises à jour de sécurité', 'Tout mettre à jour'].every((t) => $$(w, '[data-job]').some((b) => b.textContent === t)), 'boutons : rechercher / sécurité seulement / tout');
  // --- Open WebUI
  w.location.hash = '#webui';
  ok(await until(() => /non déployé/.test(txt(w, '#webui-status')) && !$(w, '#webui-deploy').classList.contains('hidden')), 'Open WebUI : « non déployé », formulaire de déploiement affiché');
  const wf = $(w, '#webui-form');
  wf.elements.email.value = 'vti@ibanfirst.com'; wf.elements.name.value = 'VTI'; wf.elements.password.value = 'Owui-Secret-2026'; wf.elements.confirm.value = 'Owui-Secret-2026';
  wf.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => /Déploiement lancé/.test(txt(w, '#webui-msg'))), 'déploiement lancé depuis le formulaire');
  ok(await until(() => /terminé/.test(txt(w, '#job-title')), 60000), 'suivi de la tâche : « ' + txt(w, '#job-title') + ' »');
  ok(await until(() => /en service/.test(txt(w, '#webui-status')) && $(w, '#webui-deploy').classList.contains('hidden'), 20000), 'état : « en service », formulaire masqué');
  const open = $$(w, '#webui-status a').find((a) => a.textContent === 'Ouvrir Open WebUI');
  ok(open && open.href === 'https://127.0.0.1:18843/' && /0\.13\.0/.test(txt(w, '#webui-status')) && /vti@ibanfirst\.com/.test(txt(w, '#webui-status')), 'bouton « Ouvrir Open WebUI » -> ' + (open && open.href) + ', version 0.13.0, administrateur affiché');
  $$(w, '#webui-status button').find((b) => b.textContent === 'Arrêter').click();
  ok(await until(() => /arrêté/.test(txt(w, '#webui-status'))), 'bouton « Arrêter » : état « arrêté »');
  console.log('alertes inattendues :', w.alerts.length ? w.alerts : 'aucune');
  process.exit(0);
})().catch((e) => { console.log('ERREUR', e); process.exit(1); });
