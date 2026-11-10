process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom');
const BASE = 'https://127.0.0.1:18443'; let n = 0;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 20000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(150); } return false; }
(async () => {
  const html = await (await fetch(BASE + '/')).text(), js = await (await fetch(BASE + '/app.js')).text();
  const w = new JSDOM(html, { url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true }).window, jar = {};
  w.fetch = async (p, o = {}) => { const h = Object.assign({}, o.headers || {}); const c = Object.entries(jar).map(([k, v]) => k + '=' + v).join('; '); if (c) h.Cookie = c;
    const r = await fetch(new URL(p, BASE), Object.assign({}, o, { headers: h })); for (const sc of r.headers.getSetCookie()) { const [kv] = sc.split(';'); const [k, v] = kv.split('='); if (v) jar[k] = v; else delete jar[k]; } return r; };
  w.TextDecoder = TextDecoder;  w.Element.prototype.scrollIntoView = () => {}; w.eval(js); w.alerts = []; w.modalLog = []; w.confirm = w.alert = w.prompt = () => { throw new Error('fenêtre système utilisée'); }; w.setInterval(() => { const m = w.document.getElementById('modal'); if (m && !m.classList.contains('hidden') && !w.manualModal) { const t = w.document.getElementById('modal-text').textContent; w.modalLog.push(t); if (m.classList.contains('error')) w.alerts.push(t); w.document.getElementById('modal-ok').click(); } }, 40);
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  await until(() => !$('#login').classList.contains('hidden'));
  const f = $('#login-form'); f.elements.user.value = 'vti'; f.elements.password.value = 'Ollama-2026!'; f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$('#app').classList.contains('hidden')), 'connexion');
  w.location.hash = '#about';
  ok(await until(() => $$('#credits tr').length === 35), 'À propos : 35 logiciels libres en ' + $$('#credits h3').length + ' catégories');
  const links = $$('#credits a');
  ok(links.every((a) => a.href.startsWith('https://') && a.target === '_blank') && links.filter((a) => a.href.includes('github.com')).length === 26, 'liens : tous en https, 26 vers GitHub, ouverture dans un nouvel onglet');
  ok(links.some((a) => a.textContent === 'Ollama' && a.href.replace(/\/$/, '') === 'https://github.com/ollama/ollama'), 'exemple : Ollama -> github.com/ollama/ollama');
  w.location.hash = '#system';
  ok(await until(() => /2026\.11\.03 -> 2026\.11\.06-0800|2026\.11\.05-1000 -> 2026\.11\.06-0800/.test($('#update-history').textContent)), 'historique des mises à jour affiché : « ' + $('#update-history').textContent.slice(0, 90) + '... »');
  $('#appliance-update').click();
  ok(await until(() => /La mise à jour a échoué/.test($('#ov-title').textContent) && /aucune ISO OllamaBuntu trouvée/.test($('#ov-text').textContent), 40000), 'mise à jour en place sans CD connecté : échec propre -> « ' + $('#ov-text').textContent.trim().slice(0, 80) + ' »');
  process.exit(0);
})().catch((e) => { console.log('ERREUR', e); process.exit(1); });
