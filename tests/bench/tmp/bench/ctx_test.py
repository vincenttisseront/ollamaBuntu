import json, ssl, http.client, os, subprocess, time, sys
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE; n = 0; T = "/tmp/target"
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: router.terminate(); sys.exit(1)
def api(method, path, body=None, ck=None):
    c = http.client.HTTPSConnection("127.0.0.1", 18443, context=ctx, timeout=120); h = {"X-OB": "1", "Content-Type": "application/json"}
    if ck: h["Cookie"] = ck
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
    return r, raw
def login(u, p):
    r, _ = api("POST", "/api/login", {"user": u, "password": p}); return "; ".join(v.split(";")[0] for k, v in r.getheaders() if k.lower() == "set-cookie")
def plain(method, port, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=120); c.request(method, path, body=json.dumps(body) if body is not None else None); r = c.getresponse(); return json.loads(r.read() or b"{}")
def loaded_ctx(model):
    for m in plain("GET", 11434, "/api/ps").get("models", []):
        if m["name"].startswith(model): return m.get("context_length")
def unload_all():
    for m in plain("GET", 11434, "/api/ps").get("models", []): plain("POST", 11434, "/api/generate", {"model": m["name"], "keep_alive": 0})
    time.sleep(0.5)
router = subprocess.Popen(["chroot", "--userspec=ollama:ollama", T, "/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "OB_ETC=/etc/ollamabuntu", "OB_MAIN=127.0.0.1:11434",
    "OB_ROUTER_LISTEN=127.0.0.1:18434", "OB_ROUTER_REQLOG=/tmp/reqs/requests.jsonl", "OB_ROUTER_USAGE=/tmp/reqs/usage.json", "python3", "/usr/local/lib/ollamabuntu/router.py"],
    stdout=open("/tmp/router-ctx.log", "w"), stderr=subprocess.STDOUT); time.sleep(2)
adm = login("vti", "Ollama-2026!")
r, raw = api("GET", "/api/models/context", ck=adm); d = json.loads(raw); tiny = next(m for m in d["models"] if m["name"] == "ob-tiny:latest")
ok(r.status == 200 and tiny["max"] and tiny["bytes_per_token"], "Modèles > Contexte : ob-tiny, maximum %s jetons, %s octets de cache par jeton (d'après son architecture)" % (tiny["max"], tiny["bytes_per_token"]))
r, raw = api("POST", "/api/models/context", {"model": "ob-tiny:latest", "num_ctx": 4096}, ck=adm)
ok(r.status == 400 and "maximum du modèle (%d jetons)" % tiny["max"] in json.loads(raw)["error"], "4 096 jetons pour un modèle limité à %d : refusé « %s »" % (tiny["max"], json.loads(raw)["error"]))
r, _ = api("POST", "/api/models/context", {"model": "ob-tiny:latest", "num_ctx": tiny["max"]}, ck=adm)
st = os.stat(T + "/etc/ollamabuntu/model-context.json")
ok(r.status == 200 and json.load(open(T + "/etc/ollamabuntu/model-context.json"))["models"]["ob-tiny:latest"] == tiny["max"] and oct(st.st_mode & 0o777) == "0o644", "contexte d'ob-tiny fixé à son maximum (%d), fichier lisible par le routeur" % tiny["max"])
# le routeur, vu depuis un faux Ollama qui enregistre ce qu'il reçoit
import threading, http.server
got = []
class Cap(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        got.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")))
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{"done":true}')
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18999), Cap); threading.Thread(target=srv.serve_forever, daemon=True).start()
r2 = subprocess.Popen(["chroot", "--userspec=ollama:ollama", T, "/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "OB_ETC=/etc/ollamabuntu", "OB_MAIN=127.0.0.1:18999",
    "OB_ROUTER_LISTEN=127.0.0.1:18435", "OB_ROUTER_REQLOG=/tmp/reqs/r2.jsonl", "OB_ROUTER_USAGE=/tmp/reqs/u2.json", "python3", "/usr/local/lib/ollamabuntu/router.py"], stdout=open("/tmp/router-cap.log", "w"), stderr=subprocess.STDOUT); time.sleep(2)
plain("POST", 18435, "/api/generate", {"model": "ob-tiny", "prompt": "x", "options": {"temperature": 0.2}})
ok(got[-1][1]["options"] == {"temperature": 0.2, "num_ctx": tiny["max"]}, "routeur : taille du modèle ajoutée, autres options conservées %s" % got[-1][1]["options"])
plain("POST", 18435, "/api/chat", {"model": "ob-tiny:latest", "messages": [], "options": {"num_ctx": 128}})
ok(got[-1][1]["options"] == {"num_ctx": 128}, "routeur : taille précisée par la requête conservée (128)")
plain("POST", 18435, "/api/generate", {"model": "qwen3.5:2b", "prompt": "x"})
ok("options" not in got[-1][1], "routeur : modèle sans réglage, requête transmise telle quelle")
plain("POST", 18435, "/v1/chat/completions", {"model": "ob-tiny", "messages": []})
ok("options" not in got[-1][1], "routeur : API compatible OpenAI non modifiée (elle suit la valeur par défaut du serveur)")
r2.terminate(); srv.shutdown()
unload_all(); plain("POST", 18434, "/api/generate", {"model": "ob-tiny", "prompt": "Bonjour", "stream": False, "options": {"num_predict": 4}})
ok(loaded_ctx("ob-tiny") == tiny["max"], "vrai Ollama via le routeur : ob-tiny chargé avec %s jetons de contexte" % loaded_ctx("ob-tiny"))
unload_all(); r, raw = api("POST", "/api/chat", {"model": "ob-tiny:latest", "messages": [{"role": "user", "content": "Bonjour"}], "num_ctx": 8192}, ck=adm)
ok(r.status == 200 and loaded_ctx("ob-tiny") == min(8192, tiny["max"]), "Chat de la console avec 8 K jetons : Ollama charge %s jetons" % loaded_ctx("ob-tiny"))
unload_all(); r, raw = api("POST", "/api/chat", {"model": "ob-tiny:latest", "messages": [{"role": "user", "content": "Bonjour"}], "num_ctx": 1048576}, ck=adm)
ok(r.status == 200 and loaded_ctx("ob-tiny") == tiny["max"], "Chat avec 1 M jetons demandés : plafonné au maximum du modèle (%s), pas de saturation de la mémoire" % loaded_ctx("ob-tiny"))
r, raw = api("POST", "/api/models/context", {"model": "ob-tiny:latest", "num_ctx": 100}, ck=adm); ok(r.status == 400 and "hors limites" in json.loads(raw)["error"], "valeur trop petite (100) : refusée « %s »" % json.loads(raw)["error"])
open(T + "/tmp/systemctl-calls.log", "w").close()
r, _ = api("POST", "/api/models/context/default", {"num_ctx": 16384}, ck=adm); env = open(T + "/etc/ollamabuntu/ollama.env").read()
ok(r.status == 200 and "OLLAMA_CONTEXT_LENGTH=16384" in env and "restart ollama" in open(T + "/tmp/systemctl-calls.log").read(), "valeur par défaut du serveur : OLLAMA_CONTEXT_LENGTH=16384, Ollama redémarré")
api("POST", "/api/models/context/default", {"num_ctx": None}, ck=adm)
ok("OLLAMA_CONTEXT_LENGTH" not in open(T + "/etc/ollamabuntu/ollama.env").read(), "retour à la valeur par défaut d'Ollama : variable retirée")
api("POST", "/api/users/create", {"user": "lucie", "password": "Lucie-2026!", "role": "utilisateur", "linux": False}, ck=adm); usr = login("lucie", "Lucie-2026!")
r, _ = api("POST", "/api/models/context", {"model": "ob-tiny:latest", "num_ctx": 8192}, ck=usr); ok(r.status == 403, "simple utilisateur : réglage du contexte refusé (403)")
api("POST", "/api/models/context", {"model": "ob-tiny:latest", "num_ctx": None}, ck=adm)
ok("ob-tiny:latest" not in json.load(open(T + "/etc/ollamabuntu/model-context.json"))["models"], "retour au défaut du serveur pour ob-tiny : réglage retiré")
router.terminate()
