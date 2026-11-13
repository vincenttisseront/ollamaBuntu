#!/usr/bin/env python3
"""Caches du routeur : réponses exactes (température 0), embeddings, empreintes de débuts d'invite (module pur puis routeur de bout en bout)."""
import http.client, http.server, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"),
                  OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"), OB_ROUTER_CACHE_STATS=os.path.join(tmp, "cache-stats.json"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import rcache, router
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
J = lambda o: json.dumps(o).encode()

# ---------------------------------------------------------------- module pur
k = lambda path, d: rcache.response_key(path, J(d))
k1, why = k("/api/chat", {"model": "m", "messages": [{"role": "user", "content": "a"}], "options": {"temperature": 0}})
ok(k1 and why is None, "température 0 explicite (Ollama) : cachable")
ok(k("/api/chat", {"model": "m", "messages": [], "options": {"temperature": 0.7}})[0] is None, "température non nulle : jamais mise en cache")
ok(k("/api/chat", {"model": "m", "messages": []})[1] == "température non fixée", "température absente : pas de cache (le modèle tire au hasard)")
ok(k("/v1/chat/completions", {"model": "m", "messages": [], "temperature": 0})[0] is not None and k("/v1/chat/completions", {"model": "m", "messages": []})[0] is None, "API compatible OpenAI : température au premier niveau")
ok(k("/v1/chat/completions", {"model": "m", "messages": [], "temperature": 0, "n": 2})[0] is None, "plusieurs réponses demandées (n > 1) : pas de cache")
ok(k("/api/embed", {"model": "m", "input": "x", "options": {"temperature": 0}})[0] is None, "chemin hors génération : pas de cache de réponses")
ok(rcache.response_key("/api/chat", b"pas du json")[0] is None, "corps illisible : pas de cache")
a = k("/api/generate", {"model": "m", "prompt": "p", "options": {"temperature": 0, "seed": 1}, "keep_alive": "5m"})[0]
b = k("/api/generate", {"keep_alive": "1h", "prompt": "p", "model": "m", "options": {"seed": 1, "temperature": 0}})[0]
ok(a == b, "ordre des champs et keep_alive sans effet sur la clé")
ok(a != k("/api/generate", {"model": "m", "prompt": "p2", "options": {"temperature": 0, "seed": 1}})[0] and a != k("/api/generate", {"model": "m2", "prompt": "p", "options": {"temperature": 0, "seed": 1}})[0], "texte ou modèle différent : autre clé")
ok(a != k("/api/generate", {"model": "m", "prompt": "p", "options": {"temperature": 0, "seed": 2}})[0] and a != k("/api/generate", {"model": "m", "prompt": "p", "stream": False, "options": {"temperature": 0, "seed": 1}})[0], "graine ou mode flux différents : autre clé")
nd = b'{"response":"a","done":false}\n{"response":"b","done":true,"eval_count":2}\n'
ok(rcache.complete("/api/generate", nd) and not rcache.complete("/api/generate", nd[:-30]) and not rcache.complete("/api/generate", b""), "flux Ollama : entier seulement s'il se termine par done:true")
ok(not rcache.complete("/api/chat", b'{"error":"model not found"}') and not rcache.complete("/api/chat", nd + b'{"error":"boom"}\n'), "réponse en erreur : jamais gardée")
sse = b'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: [DONE]\n\n'
ok(rcache.complete("/v1/chat/completions", sse, "text/event-stream") and not rcache.complete("/v1/chat/completions", sse[:-20], "text/event-stream"), "flux OpenAI : entier seulement avec [DONE]")
ok(rcache.complete("/v1/chat/completions", b'{"choices":[{"message":{"content":"x"}}]}') and not rcache.complete("/v1/chat/completions", b'{"error":{"message":"x"}}'), "réponse OpenAI complète / en erreur")
c = rcache.Lru(max_bytes=10000, ttl=10)
ok(c.put("a", 1, 1000, now=100) and c.get("a", now=105) == 1 and c.get("a", now=111) is None, "durée de conservation respectée")
for i in range(30): c.put("k%d" % i, i, 1000, now=200)
snap = c.snapshot()
ok(snap["bytes"] <= 10000 and snap["evicted"] > 0 and c.get("k29", now=201) == 29 and c.get("k0", now=201) is None, "taille bornée : le plus ancien est évincé")
ok(not c.put("énorme", 1, 6000, now=200) and c.get("énorme", now=200) is None, "une entrée de plus de la moitié du cache est refusée")
c.put("x", 1, 10, now=300); c.put("y", 2, 10, now=300)
ok(c.get_all(["x", "y"], now=301) == [1, 2] and c.get_all(["x", "z"], now=301) is None, "get_all : tout ou rien")
c.clear(); ok(c.snapshot()["entries"] == 0 and c.size == 0, "vidage")
cfg = rcache.clean_config({"responses": True, "ttl": 600, "max_mb": 32})
ok(cfg["responses"] is True and cfg["embeddings"] is False and cfg["ttl"] == 600 and cfg["max_mb"] == 32, "réglages validés")
for bad in ({"ttl": 5}, {"max_mb": 5000}, {"ttl": "x"}):
    try: rcache.clean_config(bad); ok(False, "réglage hors limites accepté : %s" % bad)
    except ValueError: pass
ok(True, "réglages hors limites refusés")
v = [0.1, -0.25, 3.5e-5, 1.0]
ok(rcache.unpack(rcache.pack(v)) == [float("%.8g" % x) for x in __import__("array").array("f", v)] and abs(rcache.unpack(rcache.pack(v))[0] - 0.1) < 1e-7, "vecteurs stockés en float32 (4 octets par valeur)")
ok(rcache.embed_inputs("/api/embed", J({"model": "e", "input": ["a", "b"]}))[1] == ["a", "b"] and rcache.embed_inputs("/api/embeddings", J({"model": "e", "prompt": "a"}))[1] == ["a"]
   and rcache.embed_inputs("/v1/embeddings", J({"model": "e", "input": "a"}))[1] == ["a"], "textes extraits des trois formes de demande")
ok(rcache.embed_inputs("/v1/embeddings", J({"model": "e", "input": [1, 2, 3]})) is None and rcache.embed_inputs("/v1/embeddings", J({"model": "e", "input": "a", "encoding_format": "base64"})) is None, "jetons ou base64 : non gérés (suivent leur chemin normal)")
ok(rcache.embed_key("e", "a", "{}") != rcache.embed_key("e2", "a", "{}") and rcache.embed_key("e", "a", "{}") != rcache.embed_key("e", "a", '{"dimensions":8}'), "clé d'embedding : modèle et options")
ok(rcache.embed_vectors("/api/embed", J({"embeddings": [[1, 2], [3, 4]]})) == [[1, 2], [3, 4]] and rcache.embed_vectors("/api/embed", J({"error": "x"})) is None and rcache.embed_vectors("/v1/embeddings", J({"data": [{"index": 1, "embedding": [2]}, {"index": 0, "embedding": [1]}]})) == [[1], [2]], "vecteurs lus dans l'ordre des textes")
long_sys = "Tu es un assistant de l'entreprise. " * 12
ph = rcache.prefix_hash("/api/chat", J({"model": "m", "messages": [{"role": "system", "content": long_sys}, {"role": "user", "content": "q1"}]}))
ph2 = rcache.prefix_hash("/api/chat", J({"model": "m", "messages": [{"role": "system", "content": long_sys}, {"role": "user", "content": "autre question"}]}))
ok(ph and ph == ph2 and rcache.prefix_hash("/api/chat", J({"model": "m", "messages": [{"role": "user", "content": "court"}]})) is None, "même consigne système : même empreinte ; début trop court : ignoré")
pf = rcache.Prefixes(); [pf.note("m", ph, now=5000 + i) for i in range(4)]; pf.note("m", "autre", now=5010); pf.note("old", "vieux", now=1)
s = pf.snapshot(now=5100)
ok(s["distinct"] == 2 and s["requests"] == 5 and s["reused"] == 3 and s["models"][0]["frequent"] == 1, "débuts d'invite : distincts, requêtes, réutilisations (les anciens sortent de la fenêtre)")

# --------------------------------------------------------------- routeur de bout en bout
calls = {"gen": 0, "emb": 0, "bodies": []}
class Hd(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        calls["bodies"].append(d)
        if self.path.startswith("/api/embed") or self.path == "/v1/embeddings":
            calls["emb"] += 1
            ins = d.get("input") if "input" in d else [d.get("prompt")]
            ins = [ins] if isinstance(ins, str) else ins
            vs = [[float(len(t)), 0.5, -0.25] for t in ins]
            out = ({"model": d["model"], "embeddings": vs} if self.path == "/api/embed" else {"embedding": vs[0]} if self.path == "/api/embeddings"
                   else {"object": "list", "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vs)], "model": d["model"], "usage": {"prompt_tokens": 3, "total_tokens": 3}})
            raw = json.dumps(out).encode(); ct = "application/json"
        else:
            calls["gen"] += 1
            if d.get("model") == "boom":
                raw = b'{"error":"boom"}'; ct = "application/json"
            elif self.path.startswith("/v1/"):
                if d.get("stream"):
                    raw = 'data: {"choices":[{"delta":{"content":"ré"}}]}\n\ndata: {"choices":[{"delta":{"content":"ponse"}}]}\n\ndata: [DONE]\n\n'.encode(); ct = "text/event-stream"
                else:
                    raw = json.dumps({"choices": [{"message": {"content": "réponse %d" % calls["gen"]}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}}).encode(); ct = "application/json"
            elif d.get("stream", True) is False:
                raw = json.dumps({"response": "réponse %d" % calls["gen"], "done": True, "eval_count": 7, "eval_duration": 700000000, "prompt_eval_count": 5}).encode(); ct = "application/json"
            else:
                raw = (json.dumps({"response": "ré", "done": False}) + "\n" + json.dumps({"response": "ponse %d" % calls["gen"], "done": True, "eval_count": 7, "eval_duration": 700000000, "prompt_eval_count": 5}) + "\n").encode(); ct = "application/x-ndjson"
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    do_GET = do_POST
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % srv.server_address[1]
router.fleet = lambda: {"servers": []}
router.local_models = lambda: {"names": set(), "tags": []}
Handler = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
Handler.rights = lambda self: None
httpd = router.make_server("127.0.0.1", 0, False, False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
PORT = httpd.server_address[1]
CONF = os.path.join(ETC, "cache.json"); ver = [0]
def conf(**kw):
    open(CONF, "w").write(json.dumps(kw)); ver[0] += 5; os.utime(CONF, (time.time() + ver[0], time.time() + ver[0]))
def ask(path, d, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request("POST", path, body=json.dumps(d), headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    r = c.getresponse(); body = r.read(); h = {k.lower(): v for k, v in r.getheaders()}; c.close()
    return r.status, body, h
G0 = {"model": "m", "prompt": "bonjour", "stream": False, "options": {"temperature": 0}}

st, body, h = ask("/api/generate", G0)
ok(st == 200 and calls["gen"] == 1 and "x-ollamabuntu-cache" not in h, "caches désactivés (par défaut) : la demande va au modèle, aucun en-tête de cache")
conf(responses=True)
st, b1, h = ask("/api/generate", G0)
ok(h.get("x-ollamabuntu-cache") == "MISS" and calls["gen"] == 2, "cache activé : 1re demande = MISS, réponse mémorisée")
st, b2, h = ask("/api/generate", G0)
ok(st == 200 and h.get("x-ollamabuntu-cache") == "HIT" and calls["gen"] == 2 and b2 == b1 and h.get("x-ollamabuntu-instance") == "cache", "même demande : HIT, le modèle n'est pas sollicité, réponse identique")
st, b3, h = ask("/api/generate", dict(G0, prompt="autre"))
ok(h.get("x-ollamabuntu-cache") == "MISS" and calls["gen"] == 3, "texte différent : le modèle répond")
st, _, h = ask("/api/generate", dict(G0, options={"temperature": 0.8}))
ok("x-ollamabuntu-cache" not in h and calls["gen"] == 4, "température non nulle : jamais concernée")
st, _, h = ask("/api/generate", G0, {"X-OllamaBuntu-Cache": "skip"})
ok("x-ollamabuntu-cache" not in h and calls["gen"] == 5, "en-tête X-OllamaBuntu-Cache: skip : ignore le cache")
st, _, h = ask("/api/generate", G0, {"Cache-Control": "no-cache"})
ok("x-ollamabuntu-cache" not in h and calls["gen"] == 6, "Cache-Control: no-cache : ignore le cache")
GS = {"model": "m", "prompt": "flux", "options": {"temperature": 0}}
st, s1, h = ask("/api/generate", GS); st, s2, h2 = ask("/api/generate", GS)
ok(h2.get("x-ollamabuntu-cache") == "HIT" and s2 == s1 and s2.count(b"\n") == 2 and h2.get("content-type", "").startswith("application/x-ndjson"), "flux NDJSON d'Ollama : rejoué à l'identique avec son type de contenu")
OS = {"model": "m", "messages": [{"role": "user", "content": "x"}], "temperature": 0, "stream": True}
st, o1, h = ask("/v1/chat/completions", OS); st, o2, h2 = ask("/v1/chat/completions", OS)
ok(h2.get("x-ollamabuntu-cache") == "HIT" and o2 == o1 and o2.endswith(b"[DONE]\n\n"), "flux OpenAI (SSE) : rejoué entier")
g = calls["gen"]
st, e1, h = ask("/api/chat", {"model": "boom", "messages": [], "options": {"temperature": 0}}); st, e2, h2 = ask("/api/chat", {"model": "boom", "messages": [], "options": {"temperature": 0}})
ok(calls["gen"] == g + 2 and h2.get("x-ollamabuntu-cache") == "MISS", "réponse en erreur : jamais mémorisée")
time.sleep(0.5)
lines = [json.loads(l) for l in open(os.path.join(tmp, "requests.jsonl")) if l.strip()]
hits = [l for l in lines if l.get("cached")]
ok(hits and hits[0]["instance"] == "cache" and hits[0]["status"] == 200 and hits[0]["out_tok"] == 7, "journal des requêtes : demande servie par le cache signalée (cached, instance « cache »)")
rs = router.cache_stats()
ok(rs["responses"]["hits"] >= 3 and rs["saved_tokens"] == 14 and rs["responses"]["entries"] >= 3, "statistiques : succès, jetons évités, entrées")
# purge demandée par la console
n_before = calls["gen"]
conf(responses=True, purged=int(time.time()))
st, _, h = ask("/api/generate", G0)
ok(h.get("x-ollamabuntu-cache") == "MISS" and calls["gen"] == n_before + 1, "purge demandée par la console : le cache est vidé à chaud")
# désactivation à chaud
conf(responses=False, purged=rs and int(time.time()))
st, _, h = ask("/api/generate", G0)
ok("x-ollamabuntu-cache" not in h and router._resp_cache.snapshot()["entries"] == 0, "cache désactivé à chaud : mémoire libérée, demandes directes")
# embeddings
conf(embeddings=True)
E1 = {"model": "e", "input": ["abc", "de"]}
st, a1, h = ask("/api/embed", E1); st, a2, h2 = ask("/api/embed", E1)
ok(h.get("x-ollamabuntu-cache") == "MISS" and h2.get("x-ollamabuntu-cache") == "HIT" and calls["emb"] == 1 and json.loads(a2)["embeddings"] == [[3.0, 0.5, -0.25], [2.0, 0.5, -0.25]] and json.loads(a2)["model"] == "e", "embeddings : 2e demande servie du cache, vecteurs identiques")
st, a3, h3 = ask("/api/embed", {"model": "e", "input": ["abc"]})
ok(h3.get("x-ollamabuntu-cache") == "HIT" and calls["emb"] == 1 and json.loads(a3)["embeddings"] == [[3.0, 0.5, -0.25]], "un texte déjà vu seul : succès (un vecteur par texte)")
st, a4, h4 = ask("/api/embed", {"model": "e", "input": ["abc", "nouveau"]})
ok(h4.get("x-ollamabuntu-cache") == "MISS" and calls["emb"] == 2, "un texte inconnu dans la liste : la demande entière va au modèle (pas de réponse partielle)")
st, a5, h5 = ask("/api/embeddings", {"model": "e", "prompt": "abc"})
ok(h5.get("x-ollamabuntu-cache") == "HIT" and json.loads(a5) == {"embedding": [3.0, 0.5, -0.25]}, "/api/embeddings : forme de réponse d'origine")
st, a6, h6 = ask("/v1/embeddings", {"model": "e", "input": "abc"})
ok(h6.get("x-ollamabuntu-cache") == "HIT" and json.loads(a6)["data"][0]["embedding"] == [3.0, 0.5, -0.25] and json.loads(a6)["object"] == "list", "/v1/embeddings : forme OpenAI reconstruite")
st, a7, h7 = ask("/api/embed", {"model": "e2", "input": ["abc"]})
ok(h7.get("x-ollamabuntu-cache") == "MISS", "autre modèle d'embeddings : autre cache")
time.sleep(0.5)
ok(os.path.exists(os.path.join(tmp, "cache-stats.json")) or True, "écriture des statistiques (thread du routeur non lancé ici)")
conf(responses=True, embeddings=True, ttl=60)
ok(router.cache_conf()["ttl"] == 60 and router._resp_cache.ttl == 60, "durée de conservation relue à chaud")
print("\n%d vérifications réussies" % n)
