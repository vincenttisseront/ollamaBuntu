#!/usr/bin/env python3
"""Requête relayée par un autre serveur du parc : son origine apparaît dans le journal des requêtes (avec l'extrait si activé sur ce serveur)."""
import http.client, http.server, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp()
os.environ.update(OB_ETC=tmp, OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"), OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"), OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB)
import router
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
class Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        raw = json.dumps({"message": {"content": "ok"}, "done": True, "prompt_eval_count": 5, "eval_count": 6, "eval_duration": 10 ** 9}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=up.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % up.server_address[1]
router.REQ_LOG = os.environ["OB_ROUTER_REQLOG"]
next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates")).rights = lambda self: None
srv = router.make_server("127.0.0.1", 0, False, False); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
def call(extra=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    h = {"Content-Type": "application/json"}; h.update(extra or {})
    c.request("POST", "/api/chat", json.dumps({"model": "m", "messages": [{"role": "user", "content": "Bonjour, résume ce contrat"}], "stream": False}), h)
    r = c.getresponse(); r.read(); c.close(); return r.status
def last():
    for _ in range(40):
        try:
            rows = [json.loads(l) for l in open(router.REQ_LOG, encoding="utf-8") if l.strip()]
            if rows: return rows[-1]
        except OSError:
            pass
        time.sleep(0.1)
    return {}
def reset():
    try: os.remove(router.REQ_LOG)
    except OSError: pass

ok(router.origin_label("srv\nA;rm -rf /") == "srv?A?rm -rf /" and len(router.origin_label("x" * 200)) == 60, "nom transmis nettoyé (pas de saut de ligne) et limité à 60 caractères")
ok(call() == 200 and last().get("client") == "local" and "via" not in last(), "requête locale ordinaire : client « local »")
reset()
ok(call({"X-OB-Via": "console-principale"}) == 200 and last().get("client") == "via console-principale" and last().get("via") == "console-principale", "relayée par la console principale : « via console-principale »")
reset()
ok(call({"X-OB-Via": "console-principale", "X-OB-Origin": "RH"}) == 200 and last().get("client") == "RH via console-principale", "clé d'origine connue : « RH via console-principale »")
reset()
ok(call({"X-OB-Via": "console-principale", "X-OB-Origin": "local"}) == 200 and last().get("client") == "via console-principale", "origine « local » : seulement le serveur relais")
reset()
# extrait de la demande : réglage de ce serveur
open(os.path.join(tmp, "request-log.json"), "w").write(json.dumps({"prompt_excerpt": True, "chars": 120})); router._rqc["mtime"] = None
router.REQLOG_CONF = os.path.join(tmp, "request-log.json")
ok(call({"X-OB-Via": "console-principale", "X-OB-Origin": "RH"}) == 200 and "résume ce contrat" in (last().get("prompt") or ""), "extrait activé sur ce serveur : le contenu de la demande relayée est enregistré")
reset()
router.REQLOG_CONF = os.path.join(tmp, "absent.json"); router._rqc["mtime"] = "force"
ok(call({"X-OB-Via": "console-principale"}) == 200 and "prompt" not in last(), "extrait désactivé (défaut) : aucun contenu enregistré")
# émetteur et relais
src = open(os.path.join(LIB, "router.py"), encoding="utf-8").read()
adm = open(os.path.join(LIB, "admin", "server.py"), encoding="utf-8").read()
ok('"X-OB-From": origin_label(socket.gethostname())' in src and '"X-OB-Client"' in src, "le routeur émetteur annonce son nom et le client d'origine")
ok('hdrs["X-OB-Via"] = via' in adm and 'hdrs["X-OB-Origin"]' in adm and 'headers.get("X-OB-From")' in adm, "la console de ce serveur transmet l'origine à son routeur")
print("%d contrôles réussis" % n)
