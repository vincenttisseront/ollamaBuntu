#!/usr/bin/env python3
"""Démon du moteur llama.cpp, de bout en bout avec un faux llama-server réel : démarrage à la demande, traduction Ollama (flux et JSON), relais vers Ollama,
arrêt après inactivité, échecs (binaire, modèle, plantage, délai), reprise après plantage, requêtes simultanées, client qui part, déchargement des modèles d'Ollama."""
import http.client, http.server, importlib.util, json, os, socket, subprocess, sys, tempfile, threading, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); MODELS = os.path.join(tmp, "models"); os.makedirs(ETC)
def free_port(lo, hi):
    for p in range(lo, hi):
        s = socket.socket()
        try: s.bind(("127.0.0.1", p)); s.close(); return p
        except OSError: s.close()
    raise SystemExit("aucun port libre")
PORT, BPORT = free_port(11600, 11699), free_port(11700, 11799)
OLL_PORT = free_port(21400, 21499)
LOG = os.path.join(tmp, "fake.log")
os.environ.update(OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"), OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"), OB_ETC=ETC, OB_MODELS=MODELS, OB_OLLAMA_MAIN="127.0.0.1:%d" % OLL_PORT, OB_ENGINE_TICK="0.1", OB_ENGINE_IDLE_UNIT="0.5", OB_ENGINE_RETRY="0.6", OB_ENGINE_STOP_WAIT="5", FAKE_LOG=LOG)
spec = importlib.util.spec_from_file_location("llama_engine", os.path.join(LIB, "llama-engine.py")); E = importlib.util.module_from_spec(spec); sys.path.insert(0, LIB); spec.loader.exec_module(E)
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def log_lines():
    try: return [json.loads(l) for l in open(LOG) if l.strip()]
    except OSError: return []
def starts(): return [l for l in log_lines() if l["kind"] == "start"]
def alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False

# --- modèle installé dans Ollama (manifeste + fichier) et binaire simulé
D = "d" * 64; MODEL = "qwen3:30b-a3b"
os.makedirs(os.path.join(MODELS, "manifests", "registry.ollama.ai", "library", "qwen3")); os.makedirs(os.path.join(MODELS, "blobs"))
json.dump({"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:" + D}]}, open(os.path.join(MODELS, "manifests", "registry.ollama.ai", "library", "qwen3", "30b-a3b"), "w"))
BLOB = os.path.join(MODELS, "blobs", "sha256-" + D); open(BLOB, "wb").write(b"G" * 4096)
BIN = os.path.join(tmp, "bin", "llama-server"); os.makedirs(os.path.dirname(BIN))
open(BIN, "w").write("#!/bin/sh\nexec %s %s \"$@\"\n" % (sys.executable, os.path.join(HERE, "fake_llama_server.py"))); os.chmod(BIN, 0o755)
json.dump({"binary": BIN}, open(os.path.join(ETC, "llama.json"), "w"))
OTHER_PORT = 0
def write_cfg(**kw):
    c = {"id": "qwen", "model": MODEL, "port": PORT, "backend_port": BPORT, "ctx": 8192, "n_cpu_moe": 11, "kv": "q8_0", "idle_min": 0, "start_timeout": 60, "parallel": 1}
    c.update(kw)
    json.dump({"engines": [c, {"id": "autre", "model": "x:1b", "port": OTHER_PORT}]}, open(os.path.join(ETC, "engines.json"), "w"))
    os.utime(os.path.join(ETC, "engines.json"), (time.time() + write_cfg.n, time.time() + write_cfg.n)); write_cfg.n += 1
write_cfg.n = 0

# --- faux Ollama (modèles chargés, déchargement, relais) et faux autre moteur
OLL = {"loaded": ["gemma4:12b"], "calls": []}
class FakeOllama(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_GET(self):
        out = {"models": [{"name": x, "model": x} for x in OLL["loaded"]]} if self.path == "/api/ps" else {"models": [{"name": MODEL}]}
        raw = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"); OLL["calls"].append((self.path, b))
        if self.path == "/api/generate" and b.get("keep_alive") == 0 and b.get("model") in OLL["loaded"]: OLL["loaded"].remove(b["model"])
        raw = json.dumps({"relayed": self.path, "model": b.get("model")}).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
oll = http.server.ThreadingHTTPServer(("127.0.0.1", OLL_PORT), FakeOllama); threading.Thread(target=oll.serve_forever, daemon=True).start()
OTHER = {"stops": 0}
class FakeOther(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0)); OTHER["stops"] += 1 if self.path == "/engine/stop" else 0
        raw = b'{"ok": true}'; self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
OTHER_PORT = free_port(21500, 21599); oth = http.server.ThreadingHTTPServer(("127.0.0.1", OTHER_PORT), FakeOther); threading.Thread(target=oth.serve_forever, daemon=True).start()
write_cfg()

E.ENGINE = E.Engine("qwen")
srv = E.Server(("127.0.0.1", PORT), E.Handler); threading.Thread(target=srv.serve_forever, daemon=True).start()
threading.Thread(target=E.ENGINE.watch, daemon=True).start()
def req(method, path, body=None, timeout=60):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read(); c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, raw
def ndjson(raw): return [json.loads(l) for l in raw.decode().splitlines() if l.strip()]
def status(): return json.loads(req("GET", "/engine/status")[2])
def wait(pred, t=10):
    t0 = time.time()
    while time.time() - t0 < t:
        if pred(): return True
        time.sleep(0.05)
    return False

# --- avant toute demande : rien ne tourne
st = status()
ok(st["state"] == "stopped" and st["pid"] is None and not starts(), "au repos : llama-server n'est pas lancé (aucune mémoire prise)")
ok(json.loads(req("GET", "/api/ps")[2]) == {"models": []} and json.loads(req("GET", "/api/version")[2])["version"].startswith("llama.cpp"), "/api/ps vide, /api/version")

# --- première demande : démarrage à la demande, flux traduit
t0 = time.time()
code, h, raw = req("POST", "/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "salut"}], "options": {"temperature": 0.3, "num_predict": 50, "num_ctx": 99999}})
objs = ndjson(raw)
ok(code == 200 and h["content-type"] == "application/x-ndjson" and [o["message"]["content"] for o in objs] == ["Bon", "jour", ""] and objs[-1]["done"] is True and objs[-1]["eval_count"] == 2 and objs[-1]["prompt_eval_count"] == 7, "première demande (flux par défaut) : llama-server démarré, réponse traduite en lignes JSON d'Ollama")
ok(objs[-1]["load_duration"] > 0 and objs[-1]["eval_duration"] == 25_000_000 and objs[-1]["prompt_eval_duration"] == 12_500_000, "durées : le démarrage du moteur est annoncé en load_duration, la génération mesurée par llama-server")
s0 = starts()
ok(len(s0) == 1, "un seul lancement")
a = s0[0]["args"]
ok(a[a.index("-m") + 1] == BLOB and a[a.index("--n-cpu-moe") + 1] == "11" and a[a.index("-c") + 1] == "8192" and a[a.index("--port") + 1] == str(BPORT) and a[a.index("--host") + 1] == "127.0.0.1" and a[a.index("--cache-type-k") + 1] == "q8_0" and "--jinja" in a,
   "ligne de commande : fichier GGUF d'Ollama, experts de 11 couches en mémoire système, contexte, port interne, cache q8_0")
ok(s0[0]["ld"].startswith(os.path.dirname(BIN)), "bibliothèques du binaire ajoutées à LD_LIBRARY_PATH")
ok(OLL["loaded"] == [] and any(c[0] == "/api/generate" and c[1] == {"model": "gemma4:12b", "keep_alive": 0} for c in OLL["calls"]), "avant le démarrage, les modèles chargés dans Ollama sont déchargés (la mémoire vidéo est libérée)")
ok(OTHER["stops"] == 1, "un autre moteur qui tournait est arrêté (un seul à la fois)")
req_body = [l for l in log_lines() if l["kind"] == "request"][0]["body"]
ok(req_body["stream"] is True and req_body["stream_options"] == {"include_usage": True} and req_body["temperature"] == 0.3 and req_body["max_tokens"] == 50 and "num_ctx" not in req_body and req_body["messages"] == [{"role": "user", "content": "salut"}], "ce que reçoit llama-server : échantillonnage traduit, num_ctx non transmis")
st = status()
ok(st["state"] == "ready" and st["pid"] and alive(st["pid"]) and st["requests"] == 1 and st["gguf"] == BLOB and st["start_seconds"] >= 0 and st["caps"]["n_cpu_moe"], "état : prêt, processus vivant, options reconnues")
ps = json.loads(req("GET", "/api/ps")[2])["models"][0]
ok(ps["name"] == MODEL and ps["size"] == 4096 and ps["engine"] == "llama.cpp", "/api/ps : le modèle servi par le moteur (taille du fichier)")

# --- demande suivante : pas de redémarrage, réponse complète
code, h, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "encore"}]})
r = json.loads(raw)
ok(code == 200 and h["content-type"].startswith("application/json") and r["message"] == {"role": "assistant", "content": "Bonjour"} and r["done"] and r["load_duration"] < 50_000_000 and len(starts()) == 1, "demande suivante : même processus, réponse JSON complète, pas de temps de chargement")
code, _, raw = req("POST", "/api/generate", {"model": MODEL, "prompt": "bonjour", "system": "bref", "stream": False})
r = json.loads(raw)
gb = [l for l in log_lines() if l["kind"] == "request"][-1]["body"]
ok(code == 200 and r["response"] == "Bonjour" and r["eval_count"] == 2 and gb["messages"] == [{"role": "system", "content": "bref"}, {"role": "user", "content": "bonjour"}], "/api/generate : traduit en conversation, champ « response »")

# --- ce que le moteur refuse ou relaie
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "x", "images": ["AAAA"]}]})
ok(code == 400 and "images" in json.loads(raw)["error"], "image : 400 explicite")
code, _, raw = req("POST", "/api/generate", {"model": MODEL, "prompt": "x", "raw": True})
ok(code == 400 and "raw" in json.loads(raw)["error"], "mode brut : 400 explicite")
code, _, raw = req("POST", "/api/chat", b"" if False else {"model": MODEL})
ok(code == 400 and "messages" in json.loads(raw)["error"], "demande sans messages : 400")
code, _, raw = req("POST", "/api/show", {"model": MODEL}); ok(code == 200 and json.loads(raw) == {"relayed": "/api/show", "model": MODEL}, "/api/show : relayé à Ollama (le modèle y est installé)")
code, _, raw = req("POST", "/api/embed", {"model": MODEL, "input": "x"}); ok(code == 200 and json.loads(raw)["relayed"] == "/api/embed", "/api/embed : relayé à Ollama")
code, _, raw = req("GET", "/api/tags"); ok(code == 200 and json.loads(raw)["models"][0]["name"] == MODEL, "/api/tags : relayé")
code, h, raw = req("POST", "/v1/chat/completions", {"model": MODEL, "stream": True, "messages": [{"role": "user", "content": "x"}]})
ok(code == 200 and h["content-type"] == "text/event-stream" and raw.count(b"data: ") == 5 and raw.rstrip().endswith(b"[DONE]"), "API compatible OpenAI : flux SSE transmis tel quel")
code, _, raw = req("POST", "/v1/chat/completions", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]})
ok(code == 200 and json.loads(raw)["choices"][0]["message"]["content"] == "Bonjour", "API compatible OpenAI : réponse JSON transmise")
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "ERREUR"}]})
ok(code == 400 and "context size" in json.loads(raw)["error"], "erreur de llama-server (contexte dépassé) : renvoyée avec son message")
ok(len(starts()) == 1, "…sans relancer le moteur")

# --- requêtes simultanées (une place) : servies à la suite
res = []
def one(): res.append(req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "ATTENDS"}]})[0])
t0 = time.time(); ths = [threading.Thread(target=one) for _ in range(2)]
[t.start() for t in ths]; [t.join() for t in ths]
ok(res == [200, 200] and time.time() - t0 >= 0.75, "deux demandes simultanées avec une place : toutes deux servies, l'une après l'autre (%.1f s)" % (time.time() - t0))

# --- client qui part en plein flux : la génération est interrompue
before = len([l for l in log_lines() if l["kind"] == "aborted"])
sk = socket.create_connection(("127.0.0.1", PORT)); body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": "LENT"}]}).encode()
sk.sendall(b"POST /api/chat HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(body) + body); sk.recv(300); sk.close()
ok(wait(lambda: len([l for l in log_lines() if l["kind"] == "aborted"]) > before, 8), "client parti en plein flux : la connexion à llama-server est coupée (il arrête de générer)")
ok(wait(lambda: status()["inflight"] == 0), "…et la place est rendue")

# --- plantage pendant la réponse, puis reprise automatique
pid = status()["pid"]
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "MEURS"}]})
ok(wait(lambda: not alive(pid)) and wait(lambda: status()["state"] == "stopped"), "llama-server tombé en pleine réponse : constaté, état « arrêté »")
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "reprise"}]})
ok(code == 200 and len(starts()) == 2 and status()["pid"] != pid, "la demande suivante relance un llama-server tout neuf")

# --- arrêt demandé / arrêt après inactivité
pid = status()["pid"]
code, _, raw = req("POST", "/engine/stop"); ok(code == 200 and json.loads(raw)["stopped"] is True and not alive(pid) and status()["state"] == "stopped", "arrêt demandé : processus terminé")
ok(json.loads(req("POST", "/engine/stop")[2])["stopped"] is False, "arrêt d'un moteur déjà arrêté : sans effet")
write_cfg(idle_min=1)   # 1 « minute » = 0,5 s dans l'essai
code, _, raw = req("POST", "/engine/start"); pid = status()["pid"]
ok(code == 200 and status()["state"] == "ready", "démarrage demandé sans requête")
ok(wait(lambda: status()["state"] == "stopped", 6) and not alive(pid), "inactif plus longtemps que réglé : llama-server arrêté, mémoire rendue")
code, _, _ = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]}); ok(code == 200 and status()["state"] == "ready", "…et relancé à la demande suivante")
write_cfg(idle_min=1)
sk = socket.create_connection(("127.0.0.1", PORT)); body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": "LENT"}]}).encode()
sk.sendall(b"POST /api/chat HTTP/1.0\r\nContent-Length: %d\r\n\r\n" % len(body) + body); sk.recv(100); time.sleep(1.2)
ok(status()["state"] == "ready" and status()["inflight"] == 1, "jamais d'arrêt pour inactivité pendant une requête en cours")
sk.close(); ok(wait(lambda: status()["state"] == "stopped", 6), "…mais dès qu'elle est finie, l'inactivité compte")
write_cfg()

# --- échecs : plantage au démarrage, délai, binaire, modèle
os.environ["FAKE_MODE"] = "crash"
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]})
msg = json.loads(raw)["error"]; ns = len(starts())
ok(code == 503 and "s'est arrêté au démarrage" in msg and "boom" in msg, "llama-server qui plante au démarrage : 503 avec les dernières lignes de sa sortie")
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]})
ok(code == 503 and len(starts()) == ns, "nouvelle demande aussitôt : même erreur sans relancer en boucle")
os.environ["FAKE_MODE"] = ""; time.sleep(0.7)
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]}); ok(code == 200, "après le délai de répit : nouvelle tentative, réussie")
req("POST", "/engine/stop")
os.environ["FAKE_MODE"] = "hang"; E.START_TIMEOUT = "1.5"
t0 = time.time(); code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]})
ok(code == 503 and "pas prêt après" in json.loads(raw)["error"] and time.time() - t0 < 8, "llama-server jamais prêt : abandonné au délai réglé, processus tué")
ok(wait(lambda: all(not alive(l["pid"]) for l in starts()[-1:])), "…aucun processus orphelin")
os.environ["FAKE_MODE"] = ""; E.START_TIMEOUT = None; time.sleep(0.7)
os.environ["FAKE_MODE"] = "slow"
t0 = time.time(); code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]})
ok(code == 200 and json.loads(raw)["load_duration"] > 1_000_000_000 and time.time() - t0 >= 1.1, "chargement lent (1,2 s) : la demande attend, load_duration l'annonce")
os.environ["FAKE_MODE"] = ""; req("POST", "/engine/stop")
old = json.load(open(os.path.join(ETC, "llama.json"))); json.dump({}, open(os.path.join(ETC, "llama.json"), "w")); time.sleep(0.7)
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]})
ok(code == 503 and "n'est pas installé" in json.loads(raw)["error"], "binaire absent : 503 qui dit où l'installer")
json.dump(old, open(os.path.join(ETC, "llama.json"), "w")); write_cfg(model="absent:1b"); time.sleep(0.7)
code, _, raw = req("POST", "/api/chat", {"model": "absent:1b", "stream": False, "messages": [{"role": "user", "content": "x"}]})
ok(code == 503 and "non installé dans Ollama" in json.loads(raw)["error"], "modèle non installé dans Ollama : 503 explicite")
write_cfg(); time.sleep(0.7)
# --- démarrage annulé par un arrêt
os.environ["FAKE_MODE"] = "slow"
th = threading.Thread(target=lambda: req("POST", "/engine/start")); th.start(); wait(lambda: status()["state"] == "starting", 3)
ok(json.loads(req("POST", "/engine/stop")[2])["stopped"] is True and wait(lambda: status()["state"] == "stopped", 6), "arrêt demandé pendant le démarrage : démarrage annulé")
th.join(); os.environ["FAKE_MODE"] = ""
req("POST", "/engine/stop")
ok(wait(lambda: all(not alive(l["pid"]) for l in starts())), "plus aucun llama-server après l'arrêt")

# --- par le routeur : la table des moteurs envoie les demandes du modèle au démon, les autres modèles à Ollama
import router
router.MAIN = "127.0.0.1:%d" % OLL_PORT
router.fleet = lambda: {"servers": []}
router.local_models = lambda: {"names": {router.norm(MODEL), router.norm("gemma4:12b")}, "tags": []}
RH = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates")); RH.rights = lambda self: None
rsrv = router.make_server("127.0.0.1", 0, False, False); threading.Thread(target=rsrv.serve_forever, daemon=True).start()
def rreq(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", rsrv.server_address[1], timeout=60)
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read(); c.close(); return r.status, raw
tbl, inst = router.routes()
ok(tbl[router.norm(MODEL)] == "127.0.0.1:%d" % PORT and any(i.get("engine") and i["port"] == PORT for i in inst), "le routeur lit engines.json : le modèle est confié au démon, qui compte parmi les instances")
code, raw = rreq("POST", "/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "via le routeur"}]})
o = ndjson(raw)
ok(code == 200 and [x["message"]["content"] for x in o] == ["Bon", "jour", ""] and o[-1]["done"], "demande au modèle MoE par le routeur : traduite et relayée en flux")
code, raw = rreq("POST", "/api/chat", {"model": "gemma4:12b", "messages": [{"role": "user", "content": "x"}]}); ok(code == 200 and json.loads(raw)["relayed"] == "/api/chat", "un autre modèle va toujours à Ollama")
time.sleep(0.5)
rl = [json.loads(l) for l in open(os.path.join(tmp, "requests.jsonl")) if l.strip()]
mine = [r for r in rl if r.get("model") == MODEL]
ok(mine and mine[-1]["status"] == 200 and mine[-1]["instance"] == "127.0.0.1:%d" % PORT and mine[-1].get("out_tok") == 2 and mine[-1].get("tps"), "journal des requêtes : instance du moteur, jetons de sortie et débit mesurés comme pour Ollama")
code, raw = rreq("GET", "/api/ps")
ps = json.loads(raw)["models"]
ok(any(m.get("engine") == "llama.cpp" and m["name"] == MODEL for m in ps), "/api/ps du routeur : le modèle servi par le moteur apparaît avec ceux d'Ollama")
code, raw = rreq("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}], "images": []})
ok(code == 200 and json.loads(raw)["message"]["content"] == "Bonjour", "réponse JSON complète par le routeur")
# --- accélération : débuts d'invite réutilisés, mémoire verrouillée, décodage spéculatif avec un modèle brouillon
D2 = "e" * 64
json.dump({"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:" + D2}]}, open(os.path.join(MODELS, "manifests", "registry.ollama.ai", "library", "qwen3", "0.6b"), "w"))
DRAFT = os.path.join(MODELS, "blobs", "sha256-" + D2); open(DRAFT, "wb").write(b"D" * 512)
req("POST", "/engine/stop"); ok(wait(lambda: status()["state"] == "stopped"), "arrêt avant d'essayer les réglages d'accélération")
write_cfg(cache_reuse=256, cache_ram=2048, mlock=True, spec="draft", draft_model="qwen3:0.6b", draft_max=12, draft_ngl=999)
n0 = len(starts()); L0 = len([l for l in log_lines() if l["kind"] == "request"])
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "avec brouillon"}]})
ok(code == 200 and len(starts()) == n0 + 1, "démarrage avec les réglages d'accélération")
a = starts()[n0]["args"]
ok(a[a.index("--cache-reuse") + 1] == "256" and a[a.index("--cache-ram") + 1] == "2048" and "--mlock" in a, "ligne de commande : réutilisation du cache (256 jetons), mémoire du cache d'invites, mémoire verrouillée")
ok(a[a.index("--model-draft") + 1] == DRAFT and a[a.index("--draft-max") + 1] == "12" and a[a.index("--n-gpu-layers-draft") + 1] == "999", "ligne de commande : le fichier du modèle brouillon d'Ollama, 12 jetons proposés, brouillon sur la carte")
rb = [l for l in log_lines() if l["kind"] == "request"][L0]["body"]
ok(rb.get("cache_prompt") is True, "chaque demande autorise la réutilisation du début de l'invite déjà calculé (cache_prompt)")
st = status()
ok(st["spec"] == {"drafted": 10, "accepted": 7}, "état : jetons proposés et acceptés par le brouillon comptés (flux)")
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "encore"}]})
ok(status()["spec"] == {"drafted": 20, "accepted": 14}, "…et en réponse non diffusée")
req("POST", "/engine/stop"); ok(wait(lambda: status()["state"] == "stopped"), "arrêt")
write_cfg(spec="ngram", draft_max=8)
n0 = len(starts()); code, _, raw = req("POST", "/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "motifs"}]})
a = starts()[n0]["args"]
ok(code == 200 and a[a.index("--spec-type") + 1] == "ngram-simple" and "--model-draft" not in a and "--cache-reuse" not in a and "--mlock" not in a, "motifs répétés : --spec-type ngram-simple sans second modèle ; options non demandées absentes")
ok(status()["spec"] == {"drafted": 0, "accepted": 0}, "compteurs remis à zéro à chaque démarrage de llama-server")
req("POST", "/engine/stop"); ok(wait(lambda: status()["state"] == "stopped"), "arrêt")
write_cfg(spec="draft", draft_model="absent:1b")
code, _, raw = req("POST", "/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "brouillon absent"}]})
ok(code >= 500 and "modèle brouillon" in json.loads(raw)["error"] and "absent:1b" in json.loads(raw)["error"], "modèle brouillon absent d'Ollama : échec clair, llama-server n'est pas lancé")
write_cfg()

json.dump({"engines": []}, open(os.path.join(ETC, "engines.json"), "w")); os.utime(os.path.join(ETC, "engines.json"), (time.time() + 5, time.time() + 5))
code, raw = rreq("POST", "/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "x"}]})
ok(json.loads(raw).get("relayed") == "/api/chat", "moteur retiré de la table : le modèle retourne à Ollama, sans redémarrer le routeur")
req("POST", "/engine/stop")
ok(wait(lambda: all(not alive(l["pid"]) for l in starts())), "en fin d'essai : plus aucun llama-server")
print("\n%d vérifications réussies" % n)
os._exit(0)
