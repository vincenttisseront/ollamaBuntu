// Exécute la vraie page + le vrai app.js dans jsdom, contre le vrai serveur (HTTPS, cookies).
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom');
const BASE = 'https://127.0.0.1:18443';
let n = 0;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 8000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(100); } return false; }

async function browser() {
  const html = await (await fetch(BASE + '/')).text();
  const js = await (await fetch(BASE + '/app.js')).text();
  const dom = new JSDOM(html, { url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window, jar = {};
  w.fetch = async (path, opts = {}) => {
    const headers = Object.assign({}, opts.headers || {});
    const c = Object.entries(jar).map(([k, v]) => k + '=' + v).join('; ');
    if (c) headers.Cookie = c;
    const r = await fetch(new URL(path, BASE), Object.assign({}, opts, { headers }));
    for (const sc of r.headers.getSetCookie()) { const [kv] = sc.split(';'); const [k, v] = kv.split('='); if (v) jar[k] = v; else delete jar[k]; }
    return r;
  };
  w.TextDecoder = TextDecoder; 
  w.eval(js); w.alerts = []; w.modalLog = []; w.confirm = w.alert = w.prompt = () => { throw new Error('fenêtre système utilisée'); }; w.setInterval(() => { const m = w.document.getElementById('modal'); if (m && !m.classList.contains('hidden') && !w.manualModal) { const t = w.document.getElementById('modal-text').textContent; w.modalLog.push(t); if (m.classList.contains('error')) w.alerts.push(t); w.document.getElementById('modal-ok').click(); } }, 40);
  return w;
}
const $ = (w, s) => w.document.querySelector(s);
const vis = (w, s) => { const e = $(w, s); return e && !e.classList.contains('hidden') && !e.closest('.hidden'); };
async function login(w, u, p) {
  await until(() => vis(w, '#login'));
  $(w, '#login-form [name=user]').value = u; $(w, '#login-form [name=password]').value = p;
  $(w, '#login-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  return until(() => vis(w, '#app'));
}
const go = async (w, view) => { w.location.hash = '#' + view; await sleep(50); };

(async () => {
  let w = await browser();
  ok(await until(() => vis(w, '#login') && /OllamaBuntu \d{4}\.\d{2}\.\d{2}/.test($(w, '#login-version').textContent)), 'page de connexion affichée avec la version : « ' + $(w, '#login-version').textContent + ' »');
  const lg = await login(w, 'vti', 'Ollama-2026!'); ok(lg, 'connexion administrateur ' + (lg ? '' : '-> erreur affichée : ' + $(w, '#login-error').textContent));
  ok(/^v\d{4}\.\d{2}\.\d{2}/.test($(w, '#ver').textContent), 'version dans l\'en-tête : ' + $(w, '#ver').textContent);
  const navAdmin = [...w.document.querySelectorAll('#nav a')].filter((a) => !a.classList.contains('hidden')).map((a) => a.textContent);
  ok(navAdmin.length === 11 && navAdmin.includes('Serveurs') && navAdmin.includes('Open WebUI') && navAdmin.includes('Sécurité') && navAdmin.includes('À propos'), 'menu administrateur : ' + navAdmin.join(' | '));
  ok(await until(() => w.document.querySelectorAll('#dash-grid .card:not(.gpu-live)').length === 6), 'tableau de bord : 6 cartes');
  ok(/L40S/.test($(w, '#dash-grid').textContent) && /CUDA/.test($(w, '#dash-grid').textContent), 'carte « Calcul » : NVIDIA L40S (CUDA) affichée');
  await go(w, 'gpu');
  ok(await until(() => w.document.querySelectorAll('#gpu-devices .gpu-dev').length === 8), 'onglet GPU : 8 cartes affichées');
  const btns = [...w.document.querySelectorAll('#gpu-devices button')].map((b) => b.textContent);
  ok(btns.includes('Installer le pilote NVIDIA') && btns.includes('Activer Vulkan (pilote Mesa)') && btns.includes('Installer ROCm pour Ollama (~1 Go)') && btns.includes('Autoriser le GPU intégré'),
    'boutons proposés : ' + [...new Set(btns)].join(' | '));
  ok(w.document.querySelectorAll('#gpu-devices .gpu-dev.ok').length === 2 && w.document.querySelectorAll('#gpu-devices .gpu-dev.info').length === 2, '2 cartes « OK » (utilisées), 2 « Information » (BMC + VMware)');
  ok(await until(() => w.document.querySelectorAll('#env-fields input').length === 11), 'paramètres avancés : 11 champs (dont OLLAMA_SCHED_SPREAD)');
  await go(w, 'users');
  ok(await until(() => /vti/.test($(w, '#users-table').textContent) && /\(vous\)/.test($(w, '#users-table').textContent)), 'onglet Utilisateurs : comptes listés (vti, marqué « vous »)');
  const f = $(w, '#user-form');
  f.elements.user.value = 'carol'; f.elements.password.value = 'Carol-2026'; f.elements.confirm.value = 'Carol-2026'; f.elements.role.value = 'utilisateur';
  f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => /carol/.test($(w, '#users-table').textContent)), 'création de « carol » depuis le formulaire : ' + $(w, '#user-msg').textContent);
  f.elements.user.value = 'dan'; f.elements.password.value = 'Dan-20266'; f.elements.confirm.value = 'Dan-20267';
  f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => /pas identiques/.test($(w, '#user-msg').textContent)), 'confirmation différente refusée côté interface');
  await go(w, 'system');
  ok(await until(() => /v\d{4}\.\d{2}\.\d{2}/.test($(w, '#about').textContent) && /v0\.\d+\.\d+/.test($(w, "#about").textContent)), 'Système > À propos : ' + $(w, '#about').textContent.replace(/\s+/g, ' ').slice(0, 110));
  w.document.querySelector('[data-power=reboot]').click();
  ok(await until(() => /Commande refusée/.test($(w, '#ov-title').textContent)), 'redémarrage refusé (pas de systemd ici) : affiché clairement -> ' + $(w, '#ov-text').textContent.slice(0, 60));
  $(w, '#ov-close').click();
  $(w, '#logout').click();
  ok(await until(() => vis(w, '#login')), 'déconnexion');
  w = await browser();
  ok(await login(w, 'carol', 'Carol-2026'), 'connexion de « carol » (rôle utilisateur)');
  const navUser = [...w.document.querySelectorAll('#nav a')].filter((a) => !a.classList.contains('hidden')).map((a) => a.textContent);
  ok(navUser.join('|') === 'Modèles|Chat|À propos', 'menu utilisateur limité à : ' + navUser.join(' | '));
  ok(vis(w, '#view-chat') && /carol \(utilisateur\)/.test($(w, '#who').textContent), 'arrivée directe sur le Chat, en-tête « ' + $(w, '#who').textContent + ' »');
  await go(w, 'gpu');
  ok(vis(w, '#view-chat') && !vis(w, '#view-gpu'), 'accès à #gpu par l\'URL : renvoyé vers le Chat');
  await go(w, 'models');
  ok(await until(() => vis(w, '#view-models')) && !vis(w, '#pull-btn'), 'Modèles : liste visible, téléchargement masqué');
  await go(w, 'account');
  const pf = $(w, '#pw-form'); pf.elements.current.value = 'Carol-2026'; pf.elements.new.value = 'Carol-2027'; pf.elements.confirm.value = 'Carol-2027';
  pf.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => /modifié/.test($(w, '#pw-msg').textContent)), 'Mon compte : changement de mot de passe -> ' + $(w, '#pw-msg').textContent);
  console.log('alertes inattendues :', w.alerts.length ? w.alerts : 'aucune');
  process.exit(0);
})().catch((e) => { console.log('ERREUR', e); process.exit(1); });
