// Base de documents (vue « Documents », choix d'une base dans la conversation, bases autorisées d'une clé) : jsdom, FR et EN.
// Prérequis : npm install jsdom (ou NODE_PATH).   Usage : node tests/unit/rag_ui_test.js
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
const enc = new TextEncoder();
const stream = (lines) => { let i = 0; return { ok: true, status: 200, json: async () => ({}), body: { getReader: () => ({ read: async () => (i < lines.length ? { value: enc.encode(JSON.stringify(lines[i++]) + '\n'), done: false } : { value: undefined, done: true }) }) } }; };
const doc = (id, name, coll, model = 'nomic-embed-text', chunks = 4) => ({ id, name, collection: coll, model, dim: 8, chunks, size: 2048, sha: id, added: 1790000000 });
const st = {};
function reset() {
  Object.assign(st, {
    docs: [doc('d1', 'conges.md', 'RH'), doc('d2', 'contrat.docx', 'Juridique', 'autre-modele:latest', 7), doc('d3', 'primes.txt', 'RH', 'nomic-embed-text', 3)], jobs: [], pdf: true, modelOk: true,
    settings: { embed_model: 'nomic-embed-text', chunk_chars: 900, overlap: 120, top_k: 5, min_score: 0.35 }, saveError: '', uploadError: '', polls: 0,
  });
}
const view = () => {
  const colls = {};
  for (const d of st.docs) { const c = colls[d.collection] || (colls[d.collection] = { name: d.collection, docs: 0, chunks: 0 }); c.docs++; c.chunks += d.chunks; }
  return { settings: st.settings, docs: st.docs, jobs: st.jobs, collections: Object.values(colls), chunks: st.docs.reduce((a, d) => a + d.chunks, 0), max_chunks: 20000,
    embed_models: st.modelOk ? ['nomic-embed-text:latest', 'mxbai-embed-large:latest'] : ['mxbai-embed-large:latest'], model_ok: st.modelOk, stale: st.docs.filter((d) => d.model !== st.settings.embed_model).length,
    pdf: st.pdf, max_upload: 25 * 1048576 };
};
async function fakeFetch(p, o = {}) {
  const body = o.body ? JSON.parse(o.body) : undefined, m = o.method || 'GET';
  calls.push([m, p, body]);
  if (p === '/api/ping') return json({ ok: true, version: 'v', lang: 'fr', boot: 'x' });
  if (p === '/api/session') return json({ user: 'adm', role: 'admin', version: 'v' });
  if (p === '/api/rag') { st.polls++; return json(view()); }
  if (p === '/api/rag/collections') return json({ collections: view().collections });
  if (p === '/api/rag/upload') {
    if (st.uploadError && body.name === st.uploadError) return json({ error: 'format non pris en charge (.exe) : texte, Markdown, CSV, JSON, HTML, Word (.docx), OpenDocument (.odt) ou PDF' }, 400);
    st.jobs = [{ id: 'j1', name: body.name, collection: body.collection, state: 'embed', done: 2, total: 6, error: '', started: 1790000100 }];
    return json({ ok: true, id: 'j1' });
  }
  if (p === '/api/rag/delete') { st.docs = st.docs.filter((d) => d.id !== body.id); st.jobs = st.jobs.filter((j) => j.id !== body.id); return json({ ok: true }); }
  if (p === '/api/rag/reindex') { st.docs.forEach((d) => { d.model = st.settings.embed_model; }); return json({ ok: true, ids: [] }); }
  if (p === '/api/rag/config') {
    if (st.saveError) return json({ error: st.saveError }, 400);
    st.settings = Object.assign({}, st.settings, { embed_model: body.embed_model, chunk_chars: Number(body.chunk_chars), overlap: Number(body.overlap), top_k: Number(body.top_k), min_score: Number(body.min_score) }); return json({ ok: true, config: st.settings });
  }
  if (p === '/api/rag/search') {
    const s = /introuvable/.test(body.question) ? [] : [{ n: 1, doc: 'd1', name: 'conges.md', collection: 'RH', page: null, heading: 'Congés payés', score: 0.8123, excerpt: 'Chaque salarié a droit à 25 jours.' }, { n: 2, doc: 'd2', name: 'contrat.pdf', collection: 'RH', page: 3, heading: '', score: 0.51, excerpt: 'Préavis de deux mois.' }];
    return json({ system: 'CONSIGNE ' + s.length, sources: s, stale: /ancien/.test(body.question) ? 1 : 0, model: 'nomic-embed-text' });
  }
  if (p === '/api/models') return json({ models: [{ name: 'llama3:8b' }] });
  if (p === '/api/chat') return stream([{ message: { content: 'Vous avez 25 jours [1].' } }, { done: true }]);
  if (p === '/api/publication/keys/create') return json({ ok: true, token: 'ob_secret', key: { name: body.name } });
  if (p === '/api/publication/keys/update') return json({ ok: true });
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
  w.eval(js + '\nwindow.__t = { keyLimits, keyCaps };');
  return w;
}
const FR_WORDS = /\b(le|la|les|des|une|du|pour|avec|sans|est|sont|aux|et|ou|pas|sur|dans|chaque|jamais|depuis|aucun|aucune|après|requête|requêtes)\b|[éèêëàâùûîïôç]/i;
function leftovers(w, sel) {
  const rest = [];
  for (const nd of w.document.querySelectorAll(sel + ' *')) {
    if (nd.closest('pre, code, script, style')) continue;
    for (const c of nd.childNodes) if (c.nodeType === 3) { const s = c.data.replace(/\s+/g, ' ').trim(); if (s && FR_WORDS.test(s) && !/^(conges|contrat|primes|Juridique|Général|\[\d\] )/.test(s)) rest.push(s); }
    for (const a of ['placeholder', 'title', 'aria-label']) { const v = nd.getAttribute(a); if (v && FR_WORDS.test(v) && !nd.closest('.rag-sources')) rest.push(a + ': ' + v); }
  }
  return rest;
}
async function scenario(lang) {
  reset(); calls.length = 0;
  const w = make(lang), $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)], L = (fr, en) => (lang === 'en' ? en : fr), T = (s) => $(s).textContent;
  const submit = (s) => $(s).dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !$('#app').classList.contains('hidden')), L('console affichée', 'EN: shown'));
  ok(!!$('#nav-more-list a[href="#rag"]'), L('lien « Documents » dans le menu « Plus »', 'EN: nav link'));
  w.location.hash = '#rag';
  ok(await until(() => $$('#rag-docs tbody tr').length === 3), L('liste des documents chargée', 'EN: documents listed'));
  const rows = $$('#rag-docs tbody tr').map((r) => [...r.children].map((c) => c.textContent));
  ok(rows[0][0] === 'conges.md' && rows[0][1] === 'RH' && rows[0][2] === '4' && rows[1][0].startsWith('contrat.docx') && rows[1][0].includes(L('à réindexer', 'to reindex')), L('colonnes, et document d\'un autre modèle marqué « à réindexer »', 'EN: columns and stale tag'));
  ok(T('#rag-totals').includes('14') && T('#rag-totals').includes('20000'), L('total des extraits', 'EN: totals'));
  ok(T('#rag-warn').includes('1 document(s)') && !$('#rag-reindex').classList.contains('hidden'), L('avertissement et bouton « Réindexer » quand des documents sont d\'un autre modèle', 'EN: stale warning and reindex button'));
  const cf = $('#rag-cfg-form').elements;
  ok(cf.embed_model.value === 'nomic-embed-text' || [...cf.embed_model.options].some((o) => o.value === 'nomic-embed-text'), L('réglages préremplis', 'EN: settings prefilled'));
  ok(String(cf.chunk_chars.value) === '900' && String(cf.overlap.value) === '120' && String(cf.top_k.value) === '5' && String(cf.min_score.value) === '0.35', L('valeurs numériques', 'EN: numeric values'));
  ok(T('#rag-formats').includes('PDF') && !T('#rag-formats').includes('pdftotext') && T('#rag-formats').includes(L('25,0 Mo', '25.0 MB')), L('formats annoncés et taille maximale', 'EN: formats and size'));
  ok($$('#rag-coll-list option').map((o) => o.value).sort().join() === 'Juridique,RH', L('bases proposées à la saisie', 'EN: base suggestions'));
  // dépôt
  const form = $('#rag-form'), file = new w.File(['Bonjour les congés'], 'note.txt', { type: 'text/plain' }), bad = new w.File(['x'], 'virus.exe');
  Object.defineProperty(form.elements.files, 'files', { value: [file, bad], configurable: true });
  st.uploadError = 'virus.exe';
  form.elements.collection.value = 'RH';
  submit('#rag-form');
  ok(await until(() => calls.filter((c) => c[1] === '/api/rag/upload').length === 2), L('chaque fichier envoyé', 'EN: each file sent'));
  const up = calls.find((c) => c[1] === '/api/rag/upload')[2];
  ok(up.name === 'note.txt' && up.collection === 'RH' && Buffer.from(up.content_b64, 'base64').toString() === 'Bonjour les congés', L('contenu envoyé en base 64, avec la base choisie', 'EN: base64 content and base'));
  ok(await until(() => T('#rag-form-msg').includes(L('1 fichier(s) envoyé(s) pour indexation.', '1 file(s) sent for indexing.')) && T('#rag-form-msg').includes('virus.exe')) && $('#rag-form-msg').classList.contains('error'), L('un envoi réussi, un refusé : les deux annoncés', 'EN: one sent, one refused'));
  ok(T('#rag-form-msg').includes(L('format non pris en charge', 'unsupported format')), L('motif du refus traduit', 'EN: reason translated'));
  ok(await until(() => T('#rag-jobs').includes('note.txt') && T('#rag-jobs').includes(L('indexation 2 / 6', 'indexing 2 / 6'))), L('progression de l\'indexation', 'EN: progress'));
  const before = st.polls;
  ok(await until(() => st.polls > before, 4000), L('actualisation automatique tant qu\'une indexation est en cours', 'EN: auto-refresh while indexing'));
  st.jobs = [{ id: 'j9', name: 'scan.pdf', collection: 'RH', state: 'error', done: 0, total: 0, error: 'aucun texte trouvé dans ce fichier', started: 1 }];
  $('#rag-refresh').click();
  ok(await until(() => $('#rag-jobs .rag-job.error') && T('#rag-jobs').includes(L('aucun texte trouvé dans ce fichier', 'no text found in this file'))), L('échec d\'indexation affiché', 'EN: failure shown'));
  calls.length = 0; $('#rag-jobs button').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/rag/delete' && c[2].id === 'j9')), L('échec retiré de la liste', 'EN: failure removed'));
  // suppression d'un document
  calls.length = 0; $$('#rag-docs button')[0].click();
  ok(await until(() => !$('#modal').classList.contains('hidden')) && T('#modal').includes('conges.md'), L('confirmation avant suppression', 'EN: delete confirmation'));
  $('#modal-ok').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/rag/delete' && c[2].id === 'd1')) && await until(() => $$('#rag-docs tbody tr').length === 2), L('document supprimé et liste actualisée', 'EN: document deleted'));
  // réglages
  calls.length = 0;
  cf.top_k.value = '8'; cf.min_score.value = '0.5'; cf.chunk_chars.value = '700'; cf.overlap.value = '90';
  submit('#rag-cfg-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/rag/config')), L('réglages envoyés', 'EN: settings sent'));
  const sent = calls.find((c) => c[1] === '/api/rag/config')[2];
  ok(sent.top_k === '8' && sent.min_score === '0.5' && sent.chunk_chars === '700' && sent.overlap === '90' && /^nomic-embed-text/.test(sent.embed_model), L('contenu des réglages', 'EN: settings payload'));
  ok(await until(() => T('#rag-cfg-msg') === L('Enregistré.', 'Saved.')), L('confirmation', 'EN: saved'));
  st.saveError = 'chevauchement : au plus la moitié de la taille des extraits'; submit('#rag-cfg-form');
  ok(await until(() => $('#rag-cfg-msg').classList.contains('error') && T('#rag-cfg-msg') === L(st.saveError, 'overlap: at most half the excerpt size')), L('erreur de validation traduite', 'EN: validation error'));
  st.saveError = ''; calls.length = 0; $('#rag-reindex').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/rag/reindex')) && await until(() => $('#rag-reindex').classList.contains('hidden')), L('réindexation demandée, bouton masqué ensuite', 'EN: reindex then hidden'));
  // modèle d'embeddings absent, PDF indisponible
  st.modelOk = false; st.pdf = false; $('#rag-refresh').click();
  ok(await until(() => T('#rag-warn').includes('nomic-embed-text') && T('#rag-warn').includes(L('n\'est pas installé', 'is not installed'))), L('modèle d\'embeddings absent : consigne d\'installation', 'EN: missing model hint'));
  ok(T('#rag-formats').includes('pdftotext') && !T('#rag-formats').includes('OpenDocument (.odt), PDF'), L('PDF indisponible : expliqué', 'EN: pdf hint'));
  st.modelOk = true; st.pdf = true;
  // essai de recherche
  calls.length = 0; const tf = $('#rag-try-form').elements;
  ok([...tf.collection.options].map((o) => o.value).sort().join() === ',Juridique,RH', L('liste des bases dans l\'essai', 'EN: bases in the try form'));
  tf.question.value = 'Combien de jours de congés ?'; tf.collection.value = 'RH'; submit('#rag-try-form');
  ok(await until(() => $$('#rag-try-out .rag-sources div').length === 2), L('sources affichées', 'EN: sources shown'));
  ok(T('#rag-try-out').includes('[1] conges.md › Congés payés') && T('#rag-try-out').includes('[2] contrat.pdf, p. 3') && T('#rag-try-out').includes(L('0,81', '0.81')), L('source : nom, titre, page, score', 'EN: source label'));
  ok(calls.find((c) => c[1] === '/api/rag/search')[2].collection === 'RH', L('base choisie transmise', 'EN: base sent'));
  tf.question.value = 'introuvable'; submit('#rag-try-form');
  ok(await until(() => T('#rag-try-out').includes(L('Aucun extrait assez proche', 'No excerpt close enough'))), L('aucun résultat annoncé', 'EN: nothing found'));
  tf.question.value = 'ancien'; submit('#rag-try-form');
  ok(await until(() => T('#rag-try-out').includes(L('1 document(s) ignoré(s) : à réindexer.', '1 document(s) ignored: to reindex.'))), L('documents ignorés signalés', 'EN: ignored documents flagged'));
  // conversation
  w.location.hash = '#chat';
  ok(await until(() => $('#chat-model').value === 'llama3:8b' && !$('#chat-rag').classList.contains('hidden')), L('conversation : sélecteur de base affiché', 'EN: chat selector shown'));
  ok([...$('#chat-rag').options].map((o) => o.value).sort().join() === ',Juridique,RH', L('bases proposées', 'EN: bases offered'));
  $('#chat-text').value = 'Combien de jours ?'; calls.length = 0;
  $('#chat-send').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/chat')), L('sans base : aucune recherche', 'EN: no search without a base'));
  ok(!calls.some((c) => c[1] === '/api/rag/search') && !calls.find((c) => c[1] === '/api/chat')[2].messages.some((m) => m.role === 'system'), L('sans base choisie, la conversation part telle quelle', 'EN: unchanged without a base'));
  await until(() => !$('#chat-log .rag-sources') && $$('#chat-log .bubble').length >= 2 && !w.document.querySelector('#chat-send[disabled]'));
  $('#chat-rag').value = 'RH';
  const pick = $('#chat-rag').value;
  $('#chat-text').value = 'Combien de jours de congés ?'; calls.length = 0;
  $('#chat-send').click();
  ok(await until(() => calls.some((c) => c[1] === '/api/chat')), L('envoi avec une base', 'EN: send with a base'));
  const cs = calls.findIndex((c) => c[1] === '/api/rag/search'), cc = calls.findIndex((c) => c[1] === '/api/chat');
  ok(cs >= 0 && cs < cc && calls[cs][2].collection === pick && calls[cs][2].question === 'Combien de jours de congés ?', L('recherche faite avant la demande, avec la question et la base', 'EN: search before the request'));
  const msgs = calls[cc][2].messages;
  ok(msgs[0].role === 'system' && msgs[0].content.startsWith('CONSIGNE') && msgs[msgs.length - 1].content === 'Combien de jours de congés ?', L('consigne système en tête, question à la fin', 'EN: system prompt first'));
  ok(await until(() => $('#chat-log .rag-sources div')), L('sources affichées sous la réponse', 'EN: sources under the answer'));
  ok(T('#chat-log .rag-sources').includes('[1] conges.md › Congés payés') && T('#chat-log .rag-sources').includes('p. 3'), L('contenu des sources', 'EN: sources content'));
  // clés : bases autorisées
  const kf = $('#key-form').elements;
  ok(!!kf.collections, L('création de clé : champ « Bases de documents autorisées »', 'EN: key form field'));
  kf.name.value = 'Appli RH'; kf.collections.value = 'RH, Juridique';
  submit('#key-form');
  ok(await until(() => calls.some((c) => c[1] === '/api/publication/keys/create' && c[2].collections === 'RH, Juridique')), L('bases envoyées à la création de la clé', 'EN: bases on create'));
  await until(() => !$('#modal').classList.contains('hidden')); $('#modal-ok').click();
  ok(w.__t.keyLimits({ collections: ['RH', 'Juridique'] }).includes('documents : RH, Juridique') && !w.__t.keyLimits({}).join().includes('documents'), L('colonne des limites : bases autorisées', 'EN: limits column'));
  const pr = w.__t.keyCaps({ id: 'k1', name: 'RH', collections: ['RH'], priority: 2, max_ctx: 0, max_output: 0 });
  ok(await until(() => !$('#modal').classList.contains('hidden') && $('#modal input[aria-label]')), L('fenêtre « Plafonds »', 'EN: caps modal'));
  const ci = $$('#modal input').find((i) => /Bases de documents|Allowed document bases/.test(i.getAttribute('aria-label')));
  ok(ci && ci.value === 'RH', L('bases actuelles préremplies', 'EN: current bases'));
  ci.value = 'RH, Finance'; $('#modal-ok').click(); await pr;
  ok(calls.some((c) => c[1] === '/api/publication/keys/update' && c[2].id === 'k1' && c[2].collections === 'RH, Finance'), L('bases modifiées enregistrées', 'EN: bases saved'));
  if (lang === 'en') {
    w.location.hash = '#rag';
    await until(() => $$('#rag-docs tbody tr').length >= 1);
    const r = [...new Set(leftovers(w, '#view-rag'))];
    ok(r.length === 0, 'EN: aucun texte français dans la vue Documents' + (r.length ? ' ' + JSON.stringify(r.slice(0, 12)) : ''));
  }
}
(async () => { await scenario(); await scenario('en'); console.log('\n' + n + ' vérifications réussies'); process.exit(0); })();
