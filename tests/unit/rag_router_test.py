#!/usr/bin/env python3
"""Base de documents par l'API du routeur : /rag/search et /rag/ask, de bout en bout (faux Ollama : embeddings par sacs de mots, conversation qui renvoie ce qu'elle a reçu)."""
import base64, hashlib, http.client, http.server, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp()
os.environ.update(OB_ETC=tmp, OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"), OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"), OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_RAG=os.path.join(tmp, "rag"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import rag, router
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def vec(text):
    v = [0.0] * 64
    for w in text.lower().replace(":", " ").replace(".", " ").replace(",", " ").replace("?", " ").split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
    return v
CHAT = []; MISSING = [False]
class Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if self.path == "/api/embed":
            if MISSING[0]: code, out = 404, {"error": "model not found"}
            else: code, out = 200, {"embeddings": [vec(t) for t in b["input"]]}
        else:
            CHAT.append((self.path, b)); code = 200
            out = {"message": {"role": "assistant", "content": "ok"}, "done": True, "prompt_eval_count": 5, "eval_count": 6, "eval_duration": 1000000000}
        raw = json.dumps(out).encode(); self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=up.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % up.server_address[1]
store = rag.Store(os.environ["OB_RAG"])
def add(name, coll, text, model="nomic-embed-text"):
    chunks = rag.chunk([(2, text)], 400, 0); vs = rag.embed(router.MAIN, model, [rag.prefixes(model)[0] + c["t"] for c in chunks])
    store.save({"id": store.new_id(), "name": name, "collection": coll, "model": model, "dim": 64, "chunks": len(chunks), "added": int(time.time()), "size": len(text)}, chunks, vs)
add("conges.txt", "RH", "# Congés\n\nLes congés payés sont de vingt cinq jours par an.")
add("achats.txt", "Finance", "# Achats\n\nTout achat supérieur à mille euros exige deux signatures.")
KEY = {"id": "k1", "name": "RH", "collections": []}
WHO = ["key"]; PERMS = [{"inference", "read"}]
def fake_rights(self):
    if WHO[0] == "local": self._key = None; return None
    self._key = KEY; return ("RH", PERMS[0], set(), "k1", set())
next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates")).rights = fake_rights
srv = router.make_server("127.0.0.1", 0, False, False); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
def call(path, body, method="POST"):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    c.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read(); h = {k.lower(): v for k, v in r.getheaders()}; c.close()
    try: return r.status, json.loads(raw or b"{}"), h
    except ValueError: return r.status, {}, h

# --- /rag/search
st, d, _ = call("/rag/search", {"question": "combien de jours de congés payés par an", "collection": "RH"})
ok(st == 200 and d["sources"][0]["name"] == "conges.txt" and d["sources"][0]["page"] == 2 and d["sources"][0]["heading"] == "Congés" and "vingt cinq" in d["passages"][0]["text"] and d["model"] == "nomic-embed-text", "recherche : extrait le plus proche avec nom, page, titre et score")
ok(all(set(s) == {"n", "doc", "name", "collection", "page", "heading", "score", "excerpt"} for s in d["sources"]) and "text" not in d["sources"][0], "sources : champs documentés, texte complet seulement dans « passages »")
st, d, _ = call("/rag/search", {"query": "achat supérieur à mille euros deux signatures", "k": 1})
ok(st == 200 and len(d["sources"]) == 1 and d["sources"][0]["collection"] == "Finance", "champ « query » accepté ; sans base indiquée, toutes les bases sont cherchées")
st, d, _ = call("/rag/search", {"question": "   "}); ok(st == 400 and "question vide" in d["error"], "question vide : 400")
st, d, _ = call("/rag/search", {"question": "x", "collection": "a/b"}); ok(st == 400 and "base de documents" in d["error"], "nom de base invalide : 400")
c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10); c.request("POST", "/rag/search", b"pas du json"); r = c.getresponse(); r.read(); c.close(); ok(r.status == 400, "corps invalide : 400")
st, d, _ = call("/rag/search", None, "GET"); ok(st == 405, "GET : 405")
PERMS[0] = {"read"}; st, d, _ = call("/rag/search", {"question": "congés"}); ok(st == 403 and "utilisation des modèles" in d["error"], "clé sans le droit d'utiliser les modèles : refusée")
PERMS[0] = {"inference", "read"}

# --- bases autorisées d'une clé
KEY["collections"] = ["Finance"]
st, d, _ = call("/rag/search", {"question": "achat supérieur à mille euros deux signatures"}); ok(st == 200 and d["sources"] and all(s["collection"] == "Finance" for s in d["sources"]), "clé limitée à « Finance » : les documents RH sont invisibles")
st, d, _ = call("/rag/search", {"question": "congés", "collection": "RH"}); ok(st == 403 and "non autorisée" in d["error"], "…et demander la base RH explicitement est refusé")
WHO[0] = "local"; st, d, _ = call("/rag/search", {"question": "congés payés vingt cinq jours", "collection": "RH"}); ok(st == 200 and d["sources"][0]["collection"] == "RH", "l'accès local n'est pas limité")
WHO[0] = "key"; KEY["collections"] = []

# --- /rag/ask
CHAT.clear()
st, d, h = call("/rag/ask", {"model": "llama3.2:3b", "question": "combien de jours de congés payés par an", "collection": "RH"})
path, sent = CHAT[-1]
ok(st == 200 and d["message"]["content"] == "ok" and path == "/api/chat" and sent["model"] == "llama3.2:3b" and sent["stream"] is False, "ask : devient une conversation /api/chat, sans flux par défaut")
ok(sent["messages"][0]["role"] == "system" and "[1] conges.txt › Congés, p. 2" in sent["messages"][0]["content"] and "vingt cinq" in sent["messages"][0]["content"] and sent["messages"][-1] == {"role": "user", "content": "combien de jours de congés payés par an"}, "le modèle reçoit les extraits numérotés en consigne système puis la question")
src = json.loads(base64.b64decode(h["x-ollamabuntu-sources"]))
ok(src[0]["n"] == 1 and src[0]["name"] == "conges.txt" and src[0]["page"] == 2 and "x-ollamabuntu-instance" in h, "sources renvoyées dans l'en-tête X-OllamaBuntu-Sources")
log = [json.loads(l) for l in open(os.environ["OB_ROUTER_REQLOG"])]
ok(log[-1]["path"] == "/api/chat" and log[-1]["client"] == "RH" and log[-1]["model"] == "llama3.2:3b" and log[-1]["status"] == 200 and log[-1]["out_tok"] == 6, "la conversation est mesurée comme les autres (journal, jetons, client)")
CHAT.clear()
st, d, h = call("/rag/ask", {"model": "m", "stream": True, "messages": [{"role": "user", "content": "bonjour"}, {"role": "assistant", "content": "salut"}, {"role": "user", "content": "achat supérieur à mille euros deux signatures"}], "options": {"temperature": 0}, "evil": 1})
sent = CHAT[-1][1]
ok(sent["stream"] is True and [m["role"] for m in sent["messages"]] == ["system", "user", "assistant", "user"] and sent["options"] == {"temperature": 0} and "evil" not in sent and "achats.txt" in sent["messages"][0]["content"], "historique conservé, question prise dans le dernier message, options transmises, champs inconnus ignorés")
CHAT.clear(); st, d, h = call("/rag/ask", {"model": "m", "question": "zzz yyy xxx qqq", "collection": "RH"})
ok(st == 200 and "Aucun extrait pertinent" in CHAT[-1][1]["messages"][0]["content"] and h["x-ollamabuntu-sources"], "rien de pertinent : le modèle est prévenu de le dire plutôt que d'inventer")
st, d, _ = call("/rag/ask", {"question": "congés"}); ok(st == 400 and "model" in d["error"], "modèle de conversation absent : 400")
CHAT.clear(); KEY["collections"] = ["Finance"]
st, d, _ = call("/rag/ask", {"model": "m", "question": "congés payés vingt cinq", "collection": "RH"}); ok(st == 403 and not CHAT, "base interdite : refusée avant tout appel au modèle")
KEY["collections"] = []
MISSING[0] = True; CHAT.clear(); st, d, _ = call("/rag/ask", {"model": "m", "question": "congés exceptionnels"})
ok(st == 503 and "nomic-embed-text" in d["error"] and "absent" in d["error"] and not CHAT, "modèle d'embeddings absent : 503 qui dit quoi installer, aucun appel au modèle de conversation")
MISSING[0] = False

# --- confidentialité et garde-fous appliqués aussi aux demandes documentaires
open(os.path.join(tmp, "privacy.json"), "w").write(json.dumps({"words": ["achat"], "words_action": "block"}))
CHAT.clear(); st, d, _ = call("/rag/ask", {"model": "m", "question": "congés payés vingt cinq", "collection": "RH"}); ok(st == 200, "demande sans terme interdit : passe")
st, d, _ = call("/rag/ask", {"model": "m", "question": "un achat ?", "collection": "Finance"})
ok(st == 403 and "terme interdit" in d["error"] and len(CHAT) == 1, "termes interdits : examinés aussi (la question ET les extraits retrouvés), le modèle n'est pas appelé")
st, d, _ = call("/rag/ask", {"model": "m", "question": "exige deux signatures euros mille supérieur", "collection": "Finance"})
ok(st == 403 and "« achat »" in d["error"] and len(CHAT) == 1, "terme interdit présent seulement dans l'extrait retrouvé (pas dans la question) : refusé aussi")
# --- modèle d'embeddings différent : documents à réindexer
open(os.path.join(tmp, "rag.json"), "w").write(json.dumps({"embed_model": "autre-embed"})); os.utime(os.path.join(tmp, "rag.json"), (time.time() + 50, time.time() + 50))
open(os.path.join(tmp, "privacy.json"), "w").write("{}"); os.utime(os.path.join(tmp, "privacy.json"), (time.time() + 60, time.time() + 60))
st, d, _ = call("/rag/search", {"question": "congés payés vingt cinq jours"}); ok(st == 200 and d["sources"] == [] and d["stale_documents"] == 2 and d["model"] == "autre-embed", "modèle d'embeddings changé : documents ignorés et signalés (« stale_documents »), pas d'erreur")
print("\n%d vérifications réussies." % n)
