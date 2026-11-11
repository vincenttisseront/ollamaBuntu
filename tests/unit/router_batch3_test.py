#!/usr/bin/env python3
"""Troisième lot, routeur : affinité de session (cache de prompt chaud) et plafonds de contexte / sortie par clé (faux Ollama de bout en bout)."""
import http.client, http.server, json, os, shutil, sys, threading, time
sys.dont_write_bytecode = True
ETC = "/tmp/rb3-etc"; shutil.rmtree(ETC, ignore_errors=True); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_ROUTER_USAGE=ETC + "/usage.json", OB_ROUTER_LIMITS=ETC + "/limits.json", OB_ROUTER_REQLOG=ETC + "/req.jsonl")
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB)
import limits, router
H = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
chat = lambda msgs, **kw: json.dumps(dict(model="m", messages=msgs, **kw)).encode()
S = [{"role": "system", "content": "Tu es un assistant RH."}, {"role": "user", "content": "Bonjour, combien de jours de congés ?"}]

# --- identifiant de conversation
k1 = limits.session_key({}, chat(S), "k1", "m")
k2 = limits.session_key({}, chat(S + [{"role": "assistant", "content": "25 jours."}, {"role": "user", "content": "Et en cas de maladie ?"}]), "k1", "m")
ok(k1 and k1 == k2, "la conversation garde le même identifiant à chaque tour (système + 1re question)")
ok(k1 != limits.session_key({}, chat(S), "k2", "m") and k1 != limits.session_key({}, chat([S[0], {"role": "user", "content": "Autre sujet"}]), "k1", "m"), "autre clé ou autre conversation : autre identifiant")
ok(limits.session_key({"X-OllamaBuntu-Session": "abc"}, chat(S), "k1", "m").endswith("|abc") and limits.session_key({}, chat(S, user="u-42"), "k1", "m").endswith("|u-42"), "en-tête X-OllamaBuntu-Session et champ « user » prioritaires")
ok(limits.session_key({}, b"pas du json", "k", "m") is None and limits.session_key({}, json.dumps({"model": "m", "prompt": "x"}).encode(), "k", "m") is None, "requête isolée ou illisible : pas d'affinité")
ok(limits.session_key({}, chat([{"role": "user", "content": [{"type": "text", "text": "Salut"}, {"type": "image_url", "image_url": {"url": "x"}}]}]), "k", "m"), "contenu en parties (texte + image) géré")

# --- affinité : mémoire et priorité à la charge
a = limits.Affinity(ttl=100, slack=2)
ids = ["local", "s1"]
ok(a.order("c1", ids, {}, now=0) == (["local", "s1"], False), "1re requête : choix normal de la répartition, mémorisé")
ok(a.order("c1", ["s1", "local"], {"local": 1, "s1": 0}, now=10) == (["local", "s1"], True), "tour suivant : retour au serveur de la conversation")
ok(a.order("c1", ["s1", "local"], {"local": 5, "s1": 0}, now=20)[0] == ["s1", "local"] and a.order("c1", ["local", "s1"], {"local": 0, "s1": 5}, now=30)[1] is False, "serveur trop occupé (écart > 2) : la charge reprend la priorité, la conversation migre")
ok(a.order("c2", ids, {}, now=0)[1] is False and a.order("c2", ["s1", "local"], {}, now=500) == (["s1", "local"], False), "mémoire expirée après le délai : choix normal")
ok(a.order("c1", ["s1"], {}, now=40)[1] is False and a.order(None, ids, {})[0] == ids, "serveur absent des candidats / pas d'identifiant : ordre inchangé")
small = limits.Affinity(size=8)
for i in range(30): small.order("k%d" % i, ids, {}, now=i)
ok(len(small._map) <= 8, "mémoire bornée")

# --- affinité dans la répartition (candidates)
router.local_models = lambda: {"names": {router.norm("m")}, "tags": []}
srv = lambda i: {"id": "s%d" % i, "name": "S%d" % i, "online": True, "models": [{"name": "m:latest"}], "loaded": [], "load": 1.0, "url": "", "fingerprint": "", "token": ""}
fl = {"local": {"load": 0.0, "loaded": []}, "servers": [srv(1), srv(2)]}
def pick(session):
    c = H.candidates(router.norm("m"), fl, "k1", session)[0]; key = "local" if c[0] == "local" else c[3]["id"]
    router.inflight_add(key, -1); return key
router._inflight.clear(); router._rr.clear()
free = [pick(None) for _ in range(9)]
ok(sorted(set(free)) == ["local", "s1", "s2"], "sans identifiant : répartition en tour de rôle (%s)" % free)
router._inflight.clear(); router._rr.clear()
first = pick("k1|m|conv-A")
seq = [pick("k1|m|conv-A") for _ in range(8)]
ok(set(seq) == {first}, "même conversation : toujours le même serveur (%s) malgré le tour de rôle" % first)
others = {pick("k1|m|conv-%d" % i) for i in range(12)}
ok(len(others) >= 2, "conversations différentes : toujours réparties entre plusieurs serveurs (%s)" % sorted(others))
open(ETC + "/balance.json", "w").write(json.dumps({"strategy": "spread", "affinity": False})); os.utime(ETC + "/balance.json", (time.time() + 5, time.time() + 5))
router._inflight.clear(); router._rr.clear()
seq = [pick("k1|m|conv-A") for _ in range(6)]
ok(len(set(seq)) > 1 and router.affinity_enabled() is False, "affinité désactivée dans la console : le tour de rôle reprend")

# --- plafonds : fonction pure
body = lambda **kw: json.dumps(kw).encode()
def caps(path, b, c=0, o=0):
    nb, cl = limits.apply_caps(path, b, c, o); return (json.loads(nb) if nb else None), cl
d, cl = caps("/api/chat", body(model="m", options={"num_ctx": 32768, "num_predict": 9000}), 8192, 1024)
ok(d["options"] == {"num_ctx": 8192, "num_predict": 1024} and cl == ["num_ctx", "num_predict"], "API native : contexte et sortie ramenés au plafond")
d, cl = caps("/api/chat", body(model="m", options={"num_ctx": 4096, "num_predict": 200, "temperature": 0.2}), 8192, 1024)
ok(d["options"]["num_ctx"] == 4096 and d["options"]["num_predict"] == 200 and d["options"]["temperature"] == 0.2 and cl == [], "valeurs sous le plafond : intactes, corps inchangé")
d, cl = caps("/api/generate", body(model="m", prompt="x"), 8192, 512)
ok(d["options"] == {"num_predict": 512} and cl == ["num_predict"], "sortie absente : plafond appliqué ; contexte absent : jamais ajouté (éviterait un rechargement)")
d, cl = caps("/api/generate", body(model="m", prompt="x", options={"num_predict": -1}), 0, 512)
ok(d["options"]["num_predict"] == 512, "sortie illimitée (-1) plafonnée")
d, cl = caps("/v1/chat/completions", body(model="m", messages=[], max_tokens=5000, max_completion_tokens=100), 0, 1000)
ok(d["max_tokens"] == 1000 and d["max_completion_tokens"] == 100 and cl == ["max_tokens"], "compatible OpenAI : max_tokens plafonné, max_completion_tokens respecté")
d, cl = caps("/v1/chat/completions", body(model="m", messages=[]), 0, 1000)
ok(d["max_tokens"] == 1000, "compatible OpenAI sans max_tokens : plafond ajouté")
nb, cl = limits.apply_caps("/api/embed", body(model="m", input="x"), 100, 100)
ok(cl == [] and json.loads(nb) == {"model": "m", "input": "x"}, "autres routes (embeddings) : intactes")
ok(limits.apply_caps("/api/chat", b"x", 1, 1) == (b"x", []) and limits.apply_caps("/api/chat", body(model="m"), 0, 0)[1] == [], "corps illisible ou sans plafond : intact")

# --- plafonds : de bout en bout
seen = []
class Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_POST(self):
        seen.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
        raw = json.dumps({"response": "ok", "done": True, "eval_count": 5, "eval_duration": 10 ** 9}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=up.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % up.server_address[1]
KEY = {"id": "k1", "name": "RH", "max_ctx": 4096, "max_output": 256}
def fake_rights(self):
    self._key = KEY
    return ("RH", {"inference", "read"}, set(), "k1", set())
H.rights = fake_rights
srv_ = router.make_server("127.0.0.1", 0, False, False); threading.Thread(target=srv_.serve_forever, daemon=True).start()
def call(b, path="/api/generate"):
    c = http.client.HTTPConnection("127.0.0.1", srv_.server_address[1], timeout=20)
    c.request("POST", path, json.dumps(b), {"Content-Type": "application/json"}); r = c.getresponse(); r.read(); h = r.getheader("X-OllamaBuntu-Clamped"); c.close(); return r.status, h
st, h = call({"model": "m", "prompt": "x", "options": {"num_ctx": 65536}})
ok(st == 200 and seen[-1]["options"] == {"num_ctx": 4096, "num_predict": 256} and h == "num_ctx,num_predict", "Ollama reçoit les valeurs plafonnées ; le client en est averti (X-OllamaBuntu-Clamped: %s)" % h)
st, h = call({"model": "m", "prompt": "x", "options": {"num_ctx": 2048, "num_predict": 64}})
ok(seen[-1]["options"] == {"num_ctx": 2048, "num_predict": 64} and h is None, "requête dans les limites : transmise telle quelle, sans en-tête")
KEY.update(max_ctx=0, max_output=0)
call({"model": "m", "prompt": "x", "options": {"num_ctx": 65536}})
ok(seen[-1]["options"] == {"num_ctx": 65536}, "clé sans plafond : comportement inchangé")
print("\n%d vérifications réussies" % n)
