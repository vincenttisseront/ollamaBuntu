#!/usr/bin/env python3
"""Routeur et serveurs endormis : un modèle que seul un serveur réveillable possède est signalé à la console (503 + Retry-After), sans toucher aux autres cas."""
import hashlib, http.client, http.server, json, os, ssl, subprocess, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"), OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import router
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", tmp + "/k.pem", "-out", tmp + "/c.pem", "-days", "2", "-subj", "/CN=127.0.0.1"], check=True, capture_output=True)
der = ssl.PEM_cert_to_DER_cert(open(tmp + "/c.pem").read())
FP = ":".join(hashlib.sha256(der).hexdigest().upper()[i:i + 2] for i in range(0, 64, 2))
def backend(name, tls):
    class Hd(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            out = (json.dumps({"response": "ok de " + name, "done": True}) + "\n").encode()
            self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
        do_GET = do_POST
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd); srv.daemon_threads = True
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(tmp + "/c.pem", tmp + "/k.pem"); srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
mainsrv, r1 = backend("local", False), backend("s1", True)
router.MAIN = "127.0.0.1:%d" % mainsrv.server_address[1]
def remote(i, name, models, online, wake, srv=None, model_map=None):
    return {"id": "s%d" % i, "name": name, "online": online, "wake": wake, "models": [{"name": m} for m in models], "model_map": model_map or {}, "loaded": [], "load": 0,
            "url": "https://127.0.0.1:%d" % (srv.server_address[1] if srv else 1), "fingerprint": FP, "token": "obr_x"}
FL = {"local": {"load": 0, "loaded": []}, "servers": [remote(1, "Alpha", ["m:1b"], True, False, r1), remote(2, "Beta", ["rare:1b"], False, True), remote(3, "Gamma", ["froid:1b"], False, False),
                                                      remote(4, "Delta", ["autre:7b"], False, True, model_map={"prefere:1b": "autre:7b"})]}
router.fleet = lambda: FL
router.local_models = lambda: {"names": set(), "tags": []}
Handler = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
Handler.rights = lambda self: None
httpd = router.make_server("127.0.0.1", 0, False, False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
threading.Thread(target=router.limits_writer, daemon=True).start()
PORT = httpd.server_address[1]
def ask(model):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request("POST", "/api/generate", body=json.dumps({"model": model, "prompt": "salut", "stream": False}), headers={"Content-Type": "application/json"})
    r = c.getresponse(); body = r.read(); c.close()
    return r.status, body.decode(), r.getheader("Retry-After")

ok(router.remote_use(FL["servers"][3], "prefere:1b") == "autre:7b" and router.remote_use(FL["servers"][0], "m:1b") == "m:1b" and router.remote_use(FL["servers"][0], "x:1b") is None, "modèle servi par un serveur : le même, ou le modèle de remplacement choisi")
st, body, ra = ask("m:1b"); ok(st == 200 and "ok de s1" in body and not router._wake, "modèle disponible sur un serveur éveillé : réponse normale, aucun signal")
st, body, ra = ask("rare:1b")
ok(st == 503 and ra == "60" and "Beta" in body and "en veille" in body, "modèle que seul Beta (endormi, réveillable) possède : 503 avec « Retry-After: 60 » et le nom du serveur")
ok("rare:1b" in router._wake and time.time() - router._wake["rare:1b"] < 5, "…et le modèle est noté pour la console")
st, body, ra = ask("froid:1b"); ok(st == 200 and ra is None and "froid:1b" not in router._wake, "serveur endormi non réveillable (réveil non réglé) : comportement habituel, pas de signal")
st, body, ra = ask("prefere:1b"); ok(st == 503 and "Delta" in body and "prefere:1b" in router._wake, "modèle de remplacement d'un serveur endormi : signalé aussi")
st, body, ra = ask("inconnu:1b"); ok(st == 200 and "inconnu:1b" not in router._wake, "modèle que personne ne possède : comportement habituel")
log = [json.loads(l) for l in open(os.environ["OB_ROUTER_REQLOG"]) if l.strip()]
ok(any(r.get("waking") == "Beta" and r.get("status") == 503 for r in log), "la demande est journalisée (503, serveur à réveiller)")
t0 = time.time(); data = {}
while time.time() - t0 < 10:
    try: data = json.load(open(os.environ["OB_ROUTER_LIMITS"]))
    except (OSError, ValueError): data = {}
    if {"rare:1b", "prefere:1b"} <= set(data.get("wake") or {}): break
    time.sleep(0.2)
ok("rare:1b" in (data.get("wake") or {}) and "prefere:1b" in data["wake"], "signal écrit dans le fichier lu par la console")
FL["servers"][1].update(online=True, url="https://127.0.0.1:%d" % r1.server_address[1]); router._wake.clear()
st, body, ra = ask("rare:1b"); ok(st == 200 and not router._wake, "une fois Beta réveillé et joignable : la demande est servie, plus de signal")
print("\n%d vérifications réussies" % n)
