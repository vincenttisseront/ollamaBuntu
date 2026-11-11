#!/usr/bin/env python3
"""Base de documents, côté console : dépôt et indexation (faux Ollama), progression, erreurs, doublons, suppression, réindexation, recherche, routes HTTP, audit."""
import base64, hashlib, http.client, http.server, io, json, os, shutil, sys, tempfile, threading, time, zipfile
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_STATE=os.path.join(tmp, "state"), OB_RAG=os.path.join(tmp, "rag"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import rag, server, backup
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a, **k):
    try: f(*a, **k)
    except ValueError as e: return str(e)
    return None
def vec(text):
    v = [0.0] * 64
    for w in text.lower().replace(":", " ").replace(".", " ").replace(",", " ").replace("?", " ").split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
    return v
MODE = ["ok"]; DELAY = [0.0]; EMBEDS = []
class Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def send(self, code, out):
        raw = json.dumps(out).encode(); self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        self.send(200, {"models": [{"name": "nomic-embed-text:latest"}, {"name": "llama3.2:3b"}, {"name": "bge-m3:latest"}]})
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))); time.sleep(DELAY[0])
        EMBEDS.append(b)
        if MODE[0] == "missing": return self.send(404, {"error": "model not found"})
        self.send(200, {"embeddings": [vec(t) for t in b["input"]]})
up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=up.serve_forever, daemon=True).start()
server.main_addr = lambda: "127.0.0.1:%d" % up.server_address[1]
server.AUDIT_FILE = os.path.join(tmp, "audit.jsonl"); server.RAG_CONF = os.path.join(ETC, "rag.json")
server.save_users({"admin": dict(server.hash_password("Secret-123"), role="admin", linux=False, rev="r0", created=1, updated=1),
                   "jean": dict(server.hash_password("Secret-456"), role="utilisateur", linux=False, rev="r1", created=1, updated=1)})
b64 = lambda b: base64.b64encode(b).decode()
def wait(pred, t=15):
    t0 = time.time()
    while time.time() - t0 < t:
        if pred(): return True
        time.sleep(0.05)
    return False
def idle(): return wait(lambda: not any(j["state"] in ("queued", "extract", "embed") for j in server.rag_view()["jobs"]))

# --- réglages
ok(server.rag_config() == rag.DEFAULTS, "réglages par défaut")
c = server.rag_save({"top_k": 3, "chunk_chars": 500, "overlap": 50}); ok(c["top_k"] == 3 and server.rag_config()["chunk_chars"] == 500 and oct(os.stat(server.RAG_CONF).st_mode & 0o777) == "0o644", "enregistrés (lisibles par le routeur)")
before = open(server.RAG_CONF).read(); ok(raises(server.rag_save, {"top_k": 99}) and open(server.RAG_CONF).read() == before, "réglage invalide refusé sans toucher au fichier")
open(server.RAG_CONF, "w").write("{cassé"); ok(server.rag_config() == rag.DEFAULTS, "fichier corrompu : valeurs par défaut")
server.rag_save({"top_k": 3, "chunk_chars": 500, "overlap": 50, "min_score": 0.2})

# --- dépôt d'un texte
DOC = "# Congés\n\nLes congés payés sont de vingt cinq jours par an.\n\n# Achats\n\nTout achat supérieur à mille euros exige deux signatures.\n\n" + "\n\n".join("Paragraphe %d du règlement intérieur. " % i + "texte " * 40 for i in range(8))
DELAY[0] = 0.15
jid = server.rag_upload({"name": "règlement.md", "collection": "RH", "content_b64": b64(DOC.encode())})
ok(wait(lambda: any(j["id"] == jid and j["state"] == "embed" and j["total"] > 0 for j in server.rag_view()["jobs"])), "indexation lancée en arrière-plan : la progression est visible (état « embed », total connu)")
j = next(j for j in server.rag_view()["jobs"] if j["id"] == jid)
ok(j["name"] == "règlement.md" and j["collection"] == "RH" and j["error"] == "", "…avec le nom du fichier et la base")
ok(idle(), "indexation terminée"); DELAY[0] = 0
v = server.rag_view()
d = v["docs"][0]
ok(v["jobs"] == [] and len(v["docs"]) == 1 and d["id"] == jid and d["name"] == "règlement.md" and d["collection"] == "RH" and d["model"] == "nomic-embed-text" and d["dim"] == 64 and d["chunks"] >= 5 and d["size"] == len(DOC.encode()), "document prêt : modèle, dimension, nombre d'extraits")
ok(v["collections"] == [{"name": "RH", "docs": 1, "chunks": d["chunks"]}] and v["chunks"] == d["chunks"] and v["max_chunks"] == rag.MAX_CHUNKS and v["stale"] == 0, "bases et totaux")
ok(v["embed_models"] == ["bge-m3", "nomic-embed-text"] and v["model_ok"] is True, "modèles d'embeddings détectés parmi les modèles installés (la conversation n'en fait pas partie)")
ok(any(b["input"][0].startswith("search_document: ") for b in EMBEDS), "préfixe « search_document: » ajouté aux extraits pour nomic")
ok(oct(os.stat(server.RAG_DIR).st_mode & 0o777) == "0o700", "dossier des documents réservé à root")

# --- recherche
r = server.rag_search({"question": "combien de jours de congés payés par an", "collection": "RH"})
ok(r["sources"][0]["name"] == "règlement.md" and "vingt cinq" in r["system"] and r["sources"][0]["heading"] == "Congés" and r["model"] == "nomic-embed-text" and r["stale"] == 0, "recherche : bon extrait, consigne système prête, titre de section")
ok(any(b["input"] == ["search_query: combien de jours de congés payés par an"] for b in EMBEDS), "préfixe « search_query: » ajouté à la question")
ok(len(server.rag_search({"question": "congés payés", "k": 1})["sources"]) == 1 and raises(server.rag_search, {"question": " "}) == "question vide", "k borné ; question vide refusée")
ok(server.rag_search({"question": "zzz yyy", "collection": "Autre"})["sources"] == [], "base inconnue : aucun résultat")

# --- refus à l'indexation
ok("déjà dans la base" in raises(server.rag_upload, {"name": "copie.md", "collection": "RH", "content_b64": b64(DOC.encode())}), "même contenu dans la même base : refusé (doublon)")
jid2 = server.rag_upload({"name": "copie.md", "collection": "Autre", "content_b64": b64(DOC.encode())}); ok(idle() and len(server.rag_view()["docs"]) == 2, "…mais accepté dans une autre base")
ok("non pris en charge" in raises(server.rag_upload, {"name": "x.exe", "collection": "RH", "content_b64": b64(b"MZ")}) and "illisible" in raises(server.rag_upload, {"name": "x.txt", "content_b64": "***"}) and "vide" in raises(server.rag_upload, {"name": "x.txt", "content_b64": ""}), "format inconnu, contenu illisible ou vide : refusés tout de suite")
ok("nom de fichier" in raises(server.rag_upload, {"name": "", "content_b64": b64(b"x")}) and raises(server.rag_upload, {"name": "x.txt", "collection": "a/b", "content_b64": b64(b"x")}) and "trop volumineux" in raises(server.rag_upload, {"name": "x.txt", "content_b64": b64(b"x" * (rag.MAX_UPLOAD + 1))}), "nom invalide, base invalide, fichier de plus de 25 Mo : refusés")
ok(server.rag_upload({"name": "../../etc/passwd.txt", "collection": "RH", "content_b64": b64(b"Contenu du fichier passwd texte")}) and idle() and "passwd.txt" in [d["name"] for d in server.rag_view()["docs"]], "chemin dans le nom : seul le nom de fichier est retenu")
real = shutil.which; shutil.which = lambda n: None
ok("pdftotext" in raises(server.rag_upload, {"name": "x.pdf", "content_b64": b64(b"%PDF")}) and server.rag_view()["pdf"] is False, "PDF sans pdftotext : refusé tout de suite avec la marche à suivre")
shutil.which = real

# --- erreurs pendant l'indexation (visibles, supprimables)
MODE[0] = "missing"
jid3 = server.rag_upload({"name": "nouveau.txt", "collection": "RH", "content_b64": b64(b"Un autre document texte assez long pour exister")}); ok(idle(), "indexation sans modèle d'embeddings : se termine")
j = next(j for j in server.rag_view()["jobs"] if j["id"] == jid3)
ok(j["state"] == "error" and "absent" in j["error"] and "nomic-embed-text" in j["error"] and jid3 not in [d["id"] for d in server.rag_view()["docs"]], "…en erreur claire (quel modèle installer), rien n'est enregistré")
server.rag_delete(jid3); ok(server.rag_view()["jobs"] == [], "une indexation en erreur se retire de la liste")
MODE[0] = "ok"
jid4 = server.rag_upload({"name": "vide.docx", "collection": "RH", "content_b64": b64(b"pas un zip")}); idle()
ok(next(j for j in server.rag_view()["jobs"] if j["id"] == jid4)["error"].startswith("fichier illisible"), "fichier Word illisible : erreur affichée")
server.rag_delete(jid4)
many = "\n\n".join("x" * 300 for _ in range(rag.MAX_DOC_CHUNKS + 5))
jid5 = server.rag_upload({"name": "geant.txt", "collection": "RH", "content_b64": b64(many.encode())}); idle()
ok("trop long" in next(j for j in server.rag_view()["jobs"] if j["id"] == jid5)["error"], "document dépassant le nombre d'extraits par document : refusé avec la marche à suivre")
server.rag_delete(jid5)
saved = rag.MAX_CHUNKS; rag.MAX_CHUNKS = 3
jid6 = server.rag_upload({"name": "plein.txt", "collection": "RH", "content_b64": b64(b"Encore un document")}); idle()
ok("supprimez des documents" in next(j for j in server.rag_view()["jobs"] if j["id"] == jid6)["error"], "base pleine : refusé")
server.rag_delete(jid6); rag.MAX_CHUNKS = saved

# --- suppression
ok(raises(server.rag_delete, "zzzzzzzzzzzz") and raises(server.rag_delete, "../x"), "suppression d'un identifiant inconnu ou piégé : refusée")
docs = {d["name"]: d["id"] for d in server.rag_view()["docs"]}
DELAY[0] = 0.3; MODE[0] = "ok"
jid7 = server.rag_upload({"name": "lent.txt", "collection": "RH", "content_b64": b64(("phrase lente. " * 400).encode())})
ok(wait(lambda: any(j["id"] == jid7 and j["state"] in ("extract", "embed") for j in server.rag_view()["jobs"])) and "en cours" in raises(server.rag_delete, jid7), "indexation en cours : suppression refusée")
idle(); DELAY[0] = 0

# --- réindexation après changement de modèle
server.rag_save({"embed_model": "bge-m3"})
v = server.rag_view(); ok(v["stale"] == len(v["docs"]) and v["model_ok"] is True, "modèle changé : tous les documents sont à réindexer")
ok(server.rag_search({"question": "congés payés vingt cinq"})["sources"] == [] and server.rag_search({"question": "congés payés vingt cinq"})["stale"] == len(v["docs"]), "…et ignorés par la recherche tant qu'ils ne le sont pas")
ids = server.rag_reindex(); ok(len(ids) == len(v["docs"]) and idle(), "réindexation de tous les documents")
v = server.rag_view(); ok(v["stale"] == 0 and all(d["model"] == "bge-m3" for d in v["docs"]) and v["jobs"] == [], "…terminée, sans nouveau dépôt du fichier d'origine (le texte découpé est conservé)")
ok(server.rag_search({"question": "congés payés vingt cinq jours"})["sources"][0]["name"] in ("règlement.md", "copie.md") and not any(b["input"][0].startswith("search_document") and b["model"] == "bge-m3" for b in EMBEDS), "recherche à nouveau possible ; pas de préfixe nomic avec un autre modèle")
ok(raises(server.rag_reindex, "zzzzzzzzzzzz") and server.rag_reindex() == [], "réindexer rien : liste vide ; document inconnu : refusé")

# --- routes HTTP
httpd = server.make_server(0, server.Handler); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
def req(method, path, cookie="", body=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = cookie
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    try:
        c.request(method, path, body=data, headers=h)
        r = c.getresponse(); out = r.read(); cookies = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    except (ConnectionError, OSError) as e:
        return 0, [], {"error": str(e)}
    finally: c.close()
    try: return r.status, cookies, json.loads(out or b"{}")
    except ValueError: return r.status, cookies, {}
def login(u, p):
    st, ck, d = req("POST", "/api/login", body={"user": u, "password": p}); return next(c.split(";")[0] for c in ck if c.startswith("ob_session="))
adm, usr = login("admin", "Secret-123"), login("jean", "Secret-456")
st, _, d = req("GET", "/api/rag", adm); ok(st == 200 and len(d["docs"]) == 4 and d["settings"]["embed_model"] == "bge-m3", "GET /api/rag")
ok(req("GET", "/api/rag", usr)[0] == 403 and req("GET", "/api/rag")[0] == 401, "gestion des documents réservée aux administrateurs")
st, _, d = req("GET", "/api/rag/collections", usr); ok(st == 200 and [c["name"] for c in d["collections"]] == ["Autre", "RH"] and all(set(c) == {"name", "docs", "chunks"} for c in d["collections"]), "un simple utilisateur peut lister les bases (noms et tailles seulement) pour sa conversation")
ok(req("GET", "/api/rag/collections")[0] == 401, "…mais pas sans être connecté")
st, _, d = req("POST", "/api/rag/search", usr, {"question": "congés payés vingt cinq jours", "collection": "RH"}); ok(st == 200 and d["sources"] and "vingt cinq" in d["system"] and "doc" in d["sources"][0] and "text" not in d["sources"][0], "recherche ouverte aux utilisateurs connectés (sources sans le texte complet)")
st, _, d = req("POST", "/api/rag/search", usr, {"question": ""}); ok(st == 400, "question vide : 400")
ok(req("POST", "/api/rag/upload", usr, {"name": "a.txt", "content_b64": b64(b"x")})[0] == 403 and req("POST", "/api/rag/delete", usr, {"id": "x"})[0] == 403 and req("POST", "/api/rag/config", usr, {"top_k": 2})[0] == 403 and req("POST", "/api/rag/reindex", usr, {})[0] == 403, "dépôt, suppression, réglages et réindexation : administrateurs seulement")
big = b'{"name": "a.txt", "content_b64": "' + b"A" * (server.MAX_BODY + 10) + b'"}'
st, _, d = req("POST", "/api/rag/upload", "", raw=big); ok(st in (0, 401), "gros envoi sans session : refusé AVANT d'être lu (401 ou connexion fermée)")
st, _, d = req("POST", "/api/rag/upload", usr, raw=big); ok(st in (0, 403), "gros envoi par un simple utilisateur : refusé avant lecture")
st, _, d = req("POST", "/api/rag/config", adm, {"embed_model": "nomic-embed-text"}); ok(st == 200 and d["config"]["embed_model"] == "nomic-embed-text", "POST /api/rag/config")
st, _, d = req("POST", "/api/rag/config", adm, {"top_k": 0}); ok(st == 400, "réglage invalide : 400")
req("POST", "/api/rag/reindex", adm, {}); idle()
body = ("Procédure d'astreinte du serveur. " * 3000).encode()   # ~100 Ko
st, _, d = req("POST", "/api/rag/upload", adm, {"name": "astreinte.txt", "collection": "IT", "content_b64": b64(body)}); ok(st == 200 and d["id"], "envoi de plus de 2 Mo (limite des autres routes) accepté pour un administrateur")
big_ok = b"Mot de passe du coffre. " * 120000   # ~2,8 Mo
st, _, d = req("POST", "/api/rag/upload", adm, {"name": "gros.txt", "collection": "IT", "content_b64": b64(big_ok)}); ok(st == 200, "fichier de 2,8 Mo : accepté (le corps dépasse 2 Mo)")
idle()
st, _, d = req("POST", "/api/rag/delete", adm, {"id": d["id"]}); ok(st == 200, "POST /api/rag/delete")
st, _, d = req("POST", "/api/rag/delete", adm, {"id": "zzzzzzzzzzzz"}); ok(st == 400 and "introuvable" in d["error"], "document inconnu : 400")
st, _, d = req("POST", "/api/rag/upload", adm, {"name": "x.exe", "content_b64": b64(b"MZ")}); ok(st == 400 and "non pris en charge" in d["error"], "format refusé : 400 avec la liste des formats")
log = open(server.AUDIT_FILE).read()
ok("Dépôt d'un document" in log and "astreinte.txt" in log and "UGVyb2PD" not in log and "QXN0cmVpbnRl" not in log and "congés payés vingt cinq" not in log, "audit : dépôts consignés (nom, base), jamais le contenu ni les questions")
ok("rag.json" in backup.FILES, "réglages inclus dans la sauvegarde")
print("\n%d vérifications réussies." % n)
