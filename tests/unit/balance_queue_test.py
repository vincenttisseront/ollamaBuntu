#!/usr/bin/env python3
"""Routeur : file centrale (places par serveur), refus après attente, requêtes doublées (vrais échanges HTTP/HTTPS avec des serveurs simulés)."""
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
# --- serveurs simulés
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", tmp + "/k.pem", "-out", tmp + "/c.pem", "-days", "2", "-subj", "/CN=127.0.0.1"], check=True, capture_output=True)
der = ssl.PEM_cert_to_DER_cert(open(tmp + "/c.pem").read())
FP = ":".join(hashlib.sha256(der).hexdigest().upper()[i:i + 2] for i in range(0, 64, 2))
def backend(name, tls):
    st = {"mode": "ok", "hits": 0, "name": name, "delay": 0.0, "cur": 0, "max": 0}
    class Hd(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)); st["hits"] += 1
            st["cur"] += 1; st["max"] = max(st["max"], st["cur"])
            try: time.sleep(st["delay"])
            finally: st["cur"] -= 1
            st["last_model"] = (json.loads(body or b"{}") or {}).get("model")
            mode = "503" if st["last_model"] in st.get("fail", ()) else st["mode"]   # « fail » : modèles que ce serveur ne sait pas servir
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
router.QUEUE_WAIT = 1.5
def remote(i, srv):
    return {"id": "s%d" % i, "name": "Srv%d" % i, "online": True, "models": [{"name": "m:1b"}], "loaded": ["m:1b"], "load": 0, "url": "https://127.0.0.1:%d" % srv.server_address[1], "fingerprint": FP, "token": "obr_x"}
FL = {"local": {"load": 0, "loaded": []}, "servers": [remote(1, r1), remote(2, r2)]}
router.fleet = lambda: FL
router.local_models = lambda: {"names": set(), "tags": []}
router.BALANCE_FILE = os.path.join(tmp, "balance.json")
Handler = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
KEY = {"v": {}}
Handler.rights = lambda self: setattr(self, "_key", dict(KEY["v"]))
httpd = router.make_server("127.0.0.1", 0, False, False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
PORT = httpd.server_address[1]
def conf(d):
    open(router.BALANCE_FILE, "w").write(json.dumps(d)); router._bal["mtime"] = None
def ask(out, i, model="m:1b"):
    t = time.time()
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    c.request("POST", "/api/generate", body=json.dumps({"model": model, "prompt": "salut %s" % i, "stream": False}), headers={"Content-Type": "application/json"})
    r = c.getresponse(); b = r.read(); c.close()
    out[i] = (r.status, b.decode(), r.getheader("X-OllamaBuntu-Instance"), time.time() - t)
def burst(n):
    out = [None] * n
    ts = [threading.Thread(target=ask, args=(out, i)) for i in range(n)]
    for t in ts: t.start()
    for t in ts: t.join(40)
    return out
def reset():
    router._inflight.clear(); router._rr.clear(); router._health._fails.clear(); router._perf = router.balancing.Perf(); router._waiters = router.balancing.Waiters()
    for s in (s1, s2, main): s.update(mode="ok", hits=0, delay=0.0, cur=0, max=0)
def log():
    time.sleep(0.3)
    try: return [json.loads(l) for l in open(router.REQ_LOG)]
    except OSError: return []
def clear_log():
    try: os.remove(router.REQ_LOG)
    except OSError: pass

# --- sans places réglées : comportement d'avant (tout part tout de suite, Ollama gère sa file)
reset(); conf({}); s1["delay"] = s2["delay"] = 0.6
out = burst(6)
ok(all(o[0] == 200 for o in out) and s1["max"] + s2["max"] >= 4, "sans places réglées : les requêtes partent immédiatement vers les serveurs (%d et %d en même temps)" % (s1["max"], s2["max"]))
# --- une place par serveur : la file centrale n'envoie jamais plus d'une requête à la fois à chacun
reset(); clear_log(); conf({"slots": {"s1": 1, "s2": 1}}); s1["delay"] = s2["delay"] = 0.5; router.QUEUE_WAIT = 20
out = burst(6)
ok(all(o[0] == 200 for o in out), "6 requêtes pour 2 places : toutes réussissent (%s)" % [o[0] for o in out])
ok(s1["max"] == 1 and s2["max"] == 1, "jamais plus d'une requête à la fois par serveur (%d, %d)" % (s1["max"], s2["max"]))
ok(abs(s1["hits"] - s2["hits"]) <= 2 and s1["hits"] + s2["hits"] == 6, "la file se vide sur les deux serveurs (%d et %d)" % (s1["hits"], s2["hits"]))
LG = log(); q = [r.get("queued_s") or 0 for r in LG if r.get("status") == 200]
ok(sum(1 for x in q if x) >= 3 and max(q or [0]) > 0.4, "les requêtes qui ont attendu portent la durée d'attente dans le journal (%s)" % q)
ok(all(v == 0 for v in router._inflight.values()) and not router._waiters.items, "aucune place ni file oubliée à la fin")
# --- attente trop longue : refus 429 propre
reset(); clear_log(); conf({"slots": {"s1": 1, "s2": 1}}); s1["delay"] = s2["delay"] = 3.0; router.QUEUE_WAIT = 1.0
out = burst(3)
codes = sorted(o[0] for o in out)
ok(codes == [200, 200, 429], "3 requêtes, 2 places occupées 3 s, attente maximale 1 s : la troisième reçoit 429 (%s)" % codes)
late = [o for o in out if o[0] == 429][0]
ok("occupés" in late[1] and 0.9 < late[3] < 2.5, "message clair après environ 1 s (%.1f s)" % late[3])
time.sleep(3.2)
ok(all(v == 0 for v in router._inflight.values()) and not router._waiters.items, "aucune place ni file oubliée après le refus")
# --- priorité : la requête critique doit passer avant une basse qui attend
reset(); clear_log(); conf({"slots": {"s1": 1}}); FL["servers"] = [remote(1, r1)]; s1["delay"] = 0.7; router.QUEUE_WAIT = 20
done_at = {}
def ask_prio(name, prio):
    KEY["v"] = {"priority": prio}
    ask(out2, name)
    done_at[name] = time.time()
out2 = {}
first = threading.Thread(target=ask, args=(out2, "bloquant")); first.start(); time.sleep(0.15)
KEY["v"] = {"priority": 3}; low = threading.Thread(target=ask, args=(out2, "basse")); low.start(); time.sleep(0.15)
KEY["v"] = {"priority": 0}; crit = threading.Thread(target=ask, args=(out2, "critique")); crit.start()
for t in (first, low, crit): t.join(30)
KEY["v"] = {}
ok(all(out2[k][0] == 200 for k in ("bloquant", "basse", "critique")) and out2["critique"][3] < out2["basse"][3], "une requête critique arrivée après une basse passe avant elle (%.1f s contre %.1f s)" % (out2["critique"][3], out2["basse"][3]))
FL["servers"] = [remote(1, r1), remote(2, r2)]
# --- requêtes doublées
reset(); clear_log(); conf({}); router.HEDGE_MIN = 0.3
for _ in range(4):
    router._perf.update("s1", "m:1b", 0.1, 1.1, 100); router._perf.update("s2", "m:1b", 0.1, 3.1, 100)
s1["delay"] = 2.5; s2["delay"] = 0.0
KEY["v"] = {"hedge": True}
out = [None]; ask(out, 0)
ok(out[0][0] == 200 and "s2" in out[0][1] and out[0][3] < 2.0, "serveur habituel lent : la copie sur l'autre serveur répond la première (%.1f s)" % out[0][3])
ok(s1["hits"] == 1 and s2["hits"] == 1, "les deux serveurs ont reçu la requête")
time.sleep(2.8)
ok(all(v == 0 for v in router._inflight.values()), "la place du serveur abandonné est libérée (%s)" % dict(router._inflight))
ok(any(r.get("hedged") for r in log()), "le journal indique que la requête a été doublée")
# serveur rapide : pas de doublon
reset(); clear_log(); s1["delay"] = 0.0
for _ in range(4):
    router._perf.update("s1", "m:1b", 0.1, 1.1, 100); router._perf.update("s2", "m:1b", 0.1, 3.1, 100)
out = [None]; ask(out, 0)
ok(out[0][0] == 200 and "s1" in out[0][1] and s2["hits"] == 0, "serveur habituel rapide : une seule requête part")
# premier serveur en panne : simple basculement
reset(); s1["mode"] = "503"
for _ in range(4):
    router._perf.update("s1", "m:1b", 0.1, 1.1, 100); router._perf.update("s2", "m:1b", 0.1, 3.1, 100)
out = [None]; ask(out, 0)
ok(out[0][0] == 200 and "s2" in out[0][1], "premier serveur en erreur : le second répond")
reset(); s1["mode"] = "503"; s2["mode"] = "503"; FL["servers"][0]["id"]; 
out = [None]; ask(out, 0)
ok(out[0][0] in (502, 503), "les deux en erreur : erreur claire (%s)" % out[0][0])
ok(all(v == 0 for v in router._inflight.values()), "aucune place oubliée après l'échec des deux")
# clé sans doublement : une seule requête même si lent
reset(); KEY["v"] = {}
for _ in range(4):
    router._perf.update("s1", "m:1b", 0.1, 1.1, 100); router._perf.update("s2", "m:1b", 0.1, 3.1, 100)
s1["delay"] = 1.0
out = [None]; ask(out, 0)
ok(out[0][0] == 200 and "s1" in out[0][1] and s2["hits"] == 0, "clé ordinaire : jamais de doublon")
# doublement + pannes : le basculement et l'erreur finale restent propres
KEY["v"] = {"hedge": True}
reset(); s1["mode"] = "503"
for _ in range(4):
    router._perf.update("s1", "m:1b", 0.1, 1.1, 100); router._perf.update("s2", "m:1b", 0.1, 3.1, 100)
out = [None]; ask(out, 0)
ok(out[0][0] == 200 and "s2" in out[0][1], "clé à requêtes doublées, premier serveur en erreur : le second répond")
ok(all(v == 0 for v in router._inflight.values()) or time.sleep(0.5) or all(v == 0 for v in router._inflight.values()), "places libérées")
reset(); s1["mode"] = "503"; s2["mode"] = "503"
out = [None]; ask(out, 0)
ok(out[0][0] in (502, 503), "clé à requêtes doublées, les deux serveurs en erreur : erreur claire (%s)" % out[0][0])
time.sleep(0.3)
ok(all(v == 0 for v in router._inflight.values()), "places libérées après l'échec des deux")
KEY["v"] = {}
print("%d vérifications réussies" % n)
