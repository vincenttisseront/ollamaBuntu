process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { JSDOM } = require('jsdom');
const BASE = 'https://127.0.0.1:18443'; let n = 0;
const ok = (c, m) => { n++; console.log((c ? `[${String(n).padStart(2, '0')}] OK   - ` : `[${String(n).padStart(2, '0')}] ÉCHEC - `) + m); if (!c) process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 20000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(50); } return false; }
(async () => {
  const html = await (await fetch(BASE + '/')).text(), js = await (await fetch(BASE + '/app.js')).text();
  const w = new JSDOM(html, { url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true }).window, jar = {};
  w.fetch = async (p, o = {}) => { const h = Object.assign({}, o.headers || {}); const c = Object.entries(jar).map(([k, v]) => k + '=' + v).join('; '); if (c) h.Cookie = c;
    const r = await fetch(new URL(p, BASE), Object.assign({}, o, { headers: h })); for (const sc of r.headers.getSetCookie()) { const [kv] = sc.split(';'); const [k, v] = kv.split('='); if (v) jar[k] = v; else delete jar[k]; } return r; };
  w.TextDecoder = TextDecoder; w.Element.prototype.scrollIntoView = () => {}; w.eval(js);
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  await until(() => !$('#login').classList.contains('hidden'));
  const f = $('#login-form'); f.elements.user.value = 'vti'; f.elements.password.value = 'Ollama-2026!'; f.dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$('#app').classList.contains('hidden')), 'connexion');
  w.location.hash = '#chat'; await until(() => $('#chat-model').options.length > 0);
  for (const m of ['think-sep', 'think-tags', 'plain']) $('#chat-model').append(w.document.createElement('option')), $('#chat-model').lastChild.value = m, $('#chat-model').lastChild.textContent = m;
  const send = (model, text) => { $('#chat-model').value = model; $('#chat-text').value = text; $('#chat-send').click(); };
  const last = () => $$('#chat-log .msg.assistant').pop();
  // ---- raisonnement dans un champ séparé
  send('think-sep', 'Quelle est la capitale de la France ?');
  ok(await until(() => last() && last().querySelector('.think.running')), 'pendant la réflexion : indicateur affiché');
  const d = last().querySelector('.think');
  ok(d.querySelector('.t-label').textContent === 'Réflexion en cours…' && !d.open && last().querySelector('.content .typing'), '« Réflexion en cours… », raisonnement replié, animation dans la bulle (rien d\'autre)');
  ok(await until(() => !$('#chat-send').classList.contains('hidden'), 15000), 'réponse terminée');
  const content = last().querySelector('.content').textContent;
  ok(content === 'La capitale de la France est Paris.' && last().querySelector('.content strong').textContent === 'Paris', 'la bulle n\'affiche que le résultat : « ' + content + ' »');
  ok(!d.open && !d.classList.contains('running') && d.querySelector('.t-label').textContent === 'Raisonnement' && /^\(\d+ s, 7 mots\)$/.test(d.querySelector('.t-meta').textContent),
    'raisonnement replié : « Raisonnement ' + d.querySelector('.t-meta').textContent + ' »');
  d.querySelector('summary').click();
  ok(d.open && d.querySelector('.think-body').textContent === "L'utilisateur demande la capitale. Je réponds brièvement.", 'un clic déplie le raisonnement complet');
  // ---- raisonnement entre balises <think>
  send('think-tags', 'Combien font 2 + 2 ?');
  ok(await until(() => last() !== null && last().querySelector('.think.running') && last().querySelector('.think-body').textContent.includes('Calcul')), 'balises <think> : reconnues pendant le flux, avant la balise de fin');
  ok(!last().querySelector('.content').textContent.includes('Calcul') && !last().querySelector('.content').textContent.includes('<think>'), 'le raisonnement n\'apparaît jamais dans la bulle pendant le flux');
  ok(await until(() => !$('#chat-send').classList.contains('hidden'), 15000), 'réponse terminée');
  const t2 = last();
  ok(t2.querySelector('.content').textContent === 'Le résultat est 4.' && t2.querySelector('.think-body').textContent === 'Calcul : 2 + 2 = 4.' && !t2.querySelector('.think').open,
    'bulle : « ' + t2.querySelector('.content').textContent + ' » ; raisonnement replié : « ' + t2.querySelector('.think-body').textContent + ' »');
  // ---- réponse simple
  send('plain', 'Bonjour');
  ok(await until(() => !$('#chat-send').classList.contains('hidden') && last().querySelector('.content').textContent === 'Bonjour !'), 'modèle sans raisonnement : réponse affichée');
  ok(last().querySelector('.think').classList.contains('hidden'), 'aucune ligne « Raisonnement » pour un modèle qui ne raisonne pas');
  const mock = await (await fetch('http://127.0.0.1:11999/last')).json();
  const hist = mock.last.messages.filter((m) => m.role === 'assistant').map((m) => m.content);
  ok(JSON.stringify(hist) === JSON.stringify(['La capitale de la France est **Paris**.', 'Le résultat est **4**.']), 'historique envoyé au modèle : réponses seules, sans le raisonnement');
  // ---- interruption pendant la réflexion
  send('think-sep', 'Encore ?'); await until(() => last().querySelector('.think.running'));
  await sleep(700); $('#chat-stop').click();
  ok(await until(() => !$('#chat-send').classList.contains('hidden')) && !last().querySelector('.think').classList.contains('running') && /\[interrompu\]/.test(last().querySelector('.content').textContent),
    'arrêt pendant la réflexion : « [interrompu] », raisonnement partiel conservé et replié (' + last().querySelector('.t-meta').textContent + ')');
  process.exit(0);
})().catch((e) => { console.log('ERREUR', e); process.exit(1); });
