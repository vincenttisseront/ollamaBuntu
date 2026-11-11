#!/usr/bin/env python3
"""Routeur : plafond de requêtes simultanées (file d'attente) et quotas de jetons, de bout en bout avec un faux Ollama."""
import http.client, http.server, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp()
os.environ.update(OB_ETC=tmp, OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"), OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import router
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)

DELAY = [0.0]
class Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0)); time.sleep(DELAY[0])
        raw = json.dumps({"response": "ok", "done": True, "prompt_eval_count": 50, "eval_count": 60, "eval_duration": 1000000000}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=up.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % up.server_address[1]
KEY = {"id": "k1", "name": "RH", "max_concurrent": 0, "quota_day": 0, "quota_month": 0}
def fake_rights(self):
    self._key = KEY
    return ("RH", {"inference", "read"}, set(), "k1", set())
next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates")).rights = fake_rights
srv = router.make_server("127.0.0.1", 0, False, False); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
def call():
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    c.request("POST", "/api/generate", json.dumps({"model": "m", "prompt": "x", "stream": False}), {"Content-Type": "application/json"})
    r = c.getresponse(); body = r.read(); c.close(); return r.status, body

# sans limite : tout passe
ok(call()[0] == 200 and call()[0] == 200, "sans plafond ni quota : les requêtes passent")
ok(router._tokens.snapshot()["k1"]["day"] == 220, "jetons comptés (entrée + sortie) : 2 x 110")

# quota journalier
KEY["quota_day"] = 300
ok(call()[0] == 200, "sous le quota (220 < 300) : admis")
st, body = call()
ok(st == 429 and "quota journalier" in json.loads(body)["error"] and "RH" in json.loads(body)["error"], "quota atteint (330 >= 300) : 429 avec message clair")
KEY["quota_day"] = 0

# plafond de requêtes simultanées avec file d'attente
KEY["max_concurrent"] = 1; DELAY[0] = 0.5
res = []; t0 = time.time()
ths = [threading.Thread(target=lambda: res.append(call()[0])) for _ in range(3)]
for t in ths: t.start()
time.sleep(0.25)
q = router._limiter.snapshot()["k1"]
ok(q["running"] == 1 and q["waiting"] == 2, "file d'attente visible : 1 en cours, 2 en attente")
for t in ths: t.join()
ok(res == [200, 200, 200] and time.time() - t0 >= 1.4, "les 3 requêtes passent l'une après l'autre (plafond de 1) : %.1f s" % (time.time() - t0))
ok(router._limiter.snapshot() == {}, "tout libéré après les réponses")

# file d'attente pleine : refus après l'attente maximale
router.QUEUE_WAIT = 0.2; DELAY[0] = 0.8
res = []
ths = [threading.Thread(target=lambda: res.append(call()[0])) for _ in range(2)]
ths[0].start(); time.sleep(0.15); ths[1].start()
for t in ths: t.join()
ok(sorted(res) == [200, 429], "attente maximale dépassée : la seconde requête reçoit 429")
time.sleep(0.9)
ok(router._limiter.snapshot() == {}, "aucun créneau perdu après un refus")

# le routeur écrit l'état pour la console
limits_file = os.environ["OB_ROUTER_LIMITS"]
threading.Thread(target=router.limits_writer, daemon=True).start()
router._limiter.dirty.set(); time.sleep(0.5)
d = json.load(open(limits_file)); ok(d["tokens"]["k1"]["total"] > 0 and "queue" in d, "état de la file et jetons écrits pour la console")
