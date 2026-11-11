#!/usr/bin/env python3
"""Routeur : reprise automatique entre serveurs (vrais échanges HTTP/HTTPS avec des serveurs simulés) et disjoncteur."""
import hashlib, http.client, http.server, json, os, shutil, ssl, subprocess, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import limits, router
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
# --- disjoncteur (module pur)
h = limits.Health(limit=3, window=60, cool=30)
h.fail("a", 100); h.fail("a", 101)
ok(not h.tripped("a", 102), "2 échecs : le serveur reste utilisé")
h.fail("a", 103)
ok(h.tripped("a", 104) and not h.tripped("b", 104), "3 échecs en moins d'une minute : serveur écarté")
ok(not h.tripped("a", 140), "30 s après le dernier échec : de nouveau essayé")
h.fail("a", 141); h.fail("a", 142)
ok(h.tripped("a", 143), "les échecs repartent de zéro après la pause puis s'accumulent de nouveau")
h.ok("a")
ok(not h.tripped("a", 143), "une réponse réussie remet le compteur à zéro")
h2 = limits.Health(limit=3, window=60, cool=30); h2.fail("x", 0); h2.fail("x", 10); h2.fail("x", 100)
ok(not h2.tripped("x", 101), "échecs trop espacés (fenêtre de 60 s) : pas de disjoncteur")
ok(router.retry_status(503, "remote", True) and router.retry_status(401, "remote", True) and not router.retry_status(500, "remote", True) and router.retry_status(500, "remote", False)
   and router.retry_status(500, "local", False) and not router.retry_status(500, "local", True) and not router.retry_status(404, "remote", False) and not router.retry_status(200, "remote", False) and not router.retry_status(401, "local", False),
   "statuts rejouables : pannes du distant toujours, erreur 500 seulement s'il reste un autre serveur, jamais une erreur du client (404, 400)")

# --- serveurs simulés
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", tmp + "/k.pem", "-out", tmp + "/c.pem", "-days", "2", "-subj", "/CN=127.0.0.1"], check=True, capture_output=True)
der = ssl.PEM_cert_to_DER_cert(open(tmp + "/c.pem").read())
FP = ":".join(hashlib.sha256(der).hexdigest().upper()[i:i + 2] for i in range(0, 64, 2))
def backend(name, tls):
    st = {"mode": "ok", "hits": 0, "name": name}
    class Hd(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)); st["hits"] += 1
            st["last_model"] = (json.loads(body or b"{}") or {}).get("model")
            mode = st["mode"]
            if mode == "close":
                self.close_connection = True; self.connection.close(); return
            if mode in ("500", "503", "404"):
                out = json.dumps({"error": "erreur simulée %s" % mode}).encode(); self.send_response(int(mode)); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out); return
            if mode == "empty":
                self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers(); return
            if mode == "cut":   # promet 100 octets, n'en envoie aucun puis coupe
                self.send_response(200); self.send_header("Content-Length", "100"); self.end_headers(); self.wfile.flush(); self.close_connection = True; self.connection.close(); return
            out = (json.dumps({"response": "ok de " + name, "done": True, "eval_count": 5, "eval_duration": 1000000000}) + "\n").encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
        do_GET = do_POST
    class S(http.server.ThreadingHTTPServer):
        daemon_threads = True
        def handle_error(self, request, client_address): pass   # connexions coupées volontairement par les essais
    srv = S(("127.0.0.1", 0), Hd)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(tmp + "/c.pem", tmp + "/k.pem"); srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st
mainsrv, main = backend("local", False)
r1, s1 = backend("s1", True); r2, s2 = backend("s2", True)
router.MAIN = "127.0.0.1:%d" % mainsrv.server_address[1]
router.QUEUE_WAIT = 1
def remote(i, srv):
    return {"id": "s%d" % i, "name": "Srv%d" % i, "online": True, "models": [{"name": "m:1b"}], "loaded": [], "load": 0, "url": "https://127.0.0.1:%d" % srv.server_address[1], "fingerprint": FP, "token": "obr_x"}
FL = {"local": {"load": 0, "loaded": []}, "servers": [remote(1, r1), remote(2, r2)]}
router.fleet = lambda: FL
router.local_models = lambda: {"names": set(), "tags": []}
Handler = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
Handler.rights = lambda self: None
httpd = router.make_server("127.0.0.1", 0, False, False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
PORT = httpd.server_address[1]
def ask(model="m:1b"):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request("POST", "/api/generate", body=json.dumps({"model": model, "prompt": "salut", "stream": False}), headers={"Content-Type": "application/json"})
    r = c.getresponse(); body = r.read(); c.close()
    return r.status, body.decode(), r.getheader("X-OllamaBuntu-Instance")
def reset(first=1):
    router._inflight.clear(); router._rr.clear(); router._health._fails.clear()
    for s in (s1, s2, main): s["mode"] = "ok"; s["hits"] = 0
def log():
    time.sleep(0.2)
    try: return [json.loads(l) for l in open(router.REQ_LOG)]
    except OSError: return []
def clear_log():
    try: os.remove(router.REQ_LOG)
    except OSError: pass

# --- 1. tout va bien : aucune reprise
reset(); clear_log()
st, body, inst = ask()
ok(st == 200 and inst == "serveur:Srv1" and "ok de s1" in body and s1["hits"] == 1 and s2["hits"] == 0, "aucune panne : le premier serveur répond")
ok("retried" not in log()[-1], "aucune reprise dans le journal")
# --- 2. erreur 500 du premier : la même requête est rejouée sur le second
for mode, why in (("500", "erreur interne 500"), ("503", "serveur saturé 503"), ("close", "connexion coupée sans réponse"), ("empty", "réponse vide"), ("cut", "réponse promise mais coupée")):
    reset(); clear_log(); s1["mode"] = mode
    st, body, inst = ask()
    ok(st == 200 and inst == "serveur:Srv2" and "ok de s2" in body and s1["hits"] == 1 and s2["hits"] == 1, "%s : le client reçoit quand même une réponse du second serveur" % why)
    e = log()[-1]
    ok(e["status"] == 200 and len(e.get("retried", [])) == 1 and e["retried"][0].startswith("Srv1 : ") and e["instance"] == "serveur:Srv2", "%s : reprise tracée dans le journal (%s)" % (why, e.get("retried")))
# --- 3. le modèle de remplacement est bien repris pour le serveur suivant
reset(); s1["mode"] = "500"; FL["servers"][1]["model_map"] = {"m:1b": "r:2b"}; FL["servers"][1]["models"] = [{"name": "r:2b"}]; FL["servers"][0]["models"] = [{"name": "m:1b"}]
st, body, inst = ask()
ok(st == 200 and s2["last_model"] == "r:2b", "la reprise utilise le modèle de remplacement du second serveur")
FL["servers"][1].pop("model_map"); FL["servers"][1]["models"] = [{"name": "m:1b"}]
# --- 4. les deux en erreur 500 : le dernier laisse passer la vraie erreur
reset(); clear_log(); s1["mode"] = "500"; s2["mode"] = "500"
st, body, inst = ask()
ok(st == 500 and "erreur simulée 500" in json.loads(body)["error"] and s1["hits"] == 1 and s2["hits"] == 1, "tous en erreur 500 : le client voit l'erreur d'Ollama (pas un message générique)")
# --- 5. erreur du client (404) : pas de reprise
reset(); s1["mode"] = "404"
st, body, inst = ask()
ok(st == 404 and s2["hits"] == 0, "erreur 404 (modèle inconnu) : rejouer ailleurs n'aurait pas de sens, pas de reprise")
# --- 6. panne totale : 503 explicite et journalisée
reset(); clear_log(); s1["mode"] = "503"; s2["mode"] = "503"
st, body, inst = ask()
ok(st == 503 and "aucun serveur disponible" in body, "tous les serveurs saturés : message clair")
e = log()[-1]
ok(e["status"] == 503 and len(e["retried"]) == 2, "échec total journalisé avec les deux tentatives")
# --- 7. serveur local d'abord puis distant
reset(); clear_log(); router.local_models = lambda: {"names": {router.norm("m:1b")}, "tags": []}; FL["local"] = {"load": 0, "loaded": ["m:1b"]}
FL["servers"] = [remote(1, r1)]
main["mode"] = "500"
orders = []
for _ in range(2):
    reset(); main["mode"] = "500"; st, body, inst = ask(); orders.append((st, inst))
ok(all(st == 200 for st, _ in orders) and any(i == "serveur:Srv1" for _, i in orders), "ce serveur en erreur 500 : repris sur le distant")
# --- 8. disjoncteur : après 3 échecs, le serveur fautif est écarté
router.local_models = lambda: {"names": set(), "tags": []}
FL["servers"] = [remote(1, r1), remote(2, r2)]
reset(); s1["mode"] = "500"
for _ in range(3):
    router._rr.clear(); ask()
ok(router._health.tripped("s1"), "3 échecs consécutifs de Srv1 : disjoncteur ouvert")
s1["hits"] = 0; s2["hits"] = 0
for _ in range(4): ask()
ok(s1["hits"] == 0 and s2["hits"] == 4, "Srv1 n'est plus sollicité (4 requêtes, toutes sur Srv2) : plus de latence perdue")
FL["servers"] = [remote(1, r1)]
s1["mode"] = "ok"; s1["hits"] = 0
st, body, inst = ask()
ok(st == 200 and s1["hits"] == 1, "seul candidat : utilisé même disjoncteur ouvert (mieux vaut essayer que refuser)")

# --- côté console : requêtes sauvées et échecs par serveur (24 h)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import server
now = time.time()
server.read_request_log = lambda since: [
    {"ts": now - 10, "status": 200, "instance": "serveur:Srv2", "retried": ["Srv1 : 500"]},
    {"ts": now - 20, "status": 200, "instance": "serveur:Srv2", "retried": ["Srv1 : injoignable", "local : 503"]},
    {"ts": now - 30, "status": 503, "instance": "-", "retried": ["Srv1 : 503", "Srv2 : 503"]},
    {"ts": now - 40, "status": 200, "instance": "serveur:Srv1"}]
server.ollama_json = lambda *a, **k: (200, {"models": [{"name": "m:1b"}]})
server.load_fleet = lambda: [{"id": "s1", "name": "Srv1", "route_token": "t"}, {"id": "s2", "name": "Srv2", "route_token": "t"}]
server._fleet_state.update({"s1": {"state": "en ligne", "data": {"model_tags": [{"name": "m:1b"}]}}, "s2": {"state": "en ligne", "data": {"model_tags": [{"name": "m:1b"}]}}})
bv = server.balance_view()
ok(bv["rescued"] == {"count": 2, "lost": 1}, "console : 2 requêtes sauvées, 1 perdue sur 24 h")
by = {s["name"]: s for s in bv["servers"]}
ok(by["Srv1"]["failures"] == 3 and by["Srv2"]["failures"] == 1 and bv["local"]["failures"] == 1, "console : échecs par serveur (Srv1 3, Srv2 1, ce serveur 1)")
ok(by["Srv2"]["served"] == 2 and by["Srv1"]["served"] == 1, "les requêtes servies ne comptent que les réponses réussies")
print("\n%d vérifications réussies" % n)
