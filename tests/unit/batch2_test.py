#!/usr/bin/env python3
"""Second lot : statistiques d'usage, export CSV, expiration des clés (console + routeur), export Prometheus, alertes d'expiration."""
import json, os, sys, tempfile, time
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, os.path.join(LIB, "admin")); sys.path.insert(0, LIB)
import usage, prom, monitor, server
import router
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a, exc=ValueError):
    try: f(*a); return False
    except exc: return True
tmp = tempfile.mkdtemp()

# --- statistiques d'usage
now = 1_800_000_000
reqs = [{"ts": now - 600, "client": "RH", "model": "a:latest", "status": 200, "in_tok": 10, "out_tok": 100, "ms": 1000},
        {"ts": now - 300, "client": "RH", "model": "a:latest", "status": 500, "ms": 50},
        {"ts": now - 7200, "client": "local", "model": "b:7b", "status": 200, "in_tok": 5, "out_tok": 20, "ms": 400},
        {"ts": now - 90000, "client": "vieux", "model": "c", "status": 200, "out_tok": 999}]
u = usage.aggregate(reqs, now, 86400)
ok(u["total"]["count"] == 3 and u["total"]["errors"] == 1 and u["total"]["out_tok"] == 120, "totaux : requêtes hors période écartées, erreurs et jetons comptés")
ok(u["models"][0]["name"] == "a:latest" and u["models"][0]["count"] == 2 and u["clients"][0]["name"] == "RH", "classement par modèle et par client")
ok(len(u["buckets"]) == 24 and sum(b["count"] for b in u["buckets"]) == 3, "24 tranches, aucune requête perdue")
ok(usage.aggregate(reqs, now, 10)["span"] == 3600 and usage.aggregate(reqs, now, 10 ** 9)["span"] == 7 * 86400, "période bornée (1 h à 7 j)")
ok(usage.aggregate([{"ts": now, "model": "A"}], now, 3600, name=str.lower)["models"][0]["name"] == "a", "regroupement des noms de modèle injectable")
ok(usage.aggregate([], now)["total"]["count"] == 0, "journal vide : pas d'erreur")

# --- export CSV
c = usage.to_csv([{"ts": now, "client": "=cmd|' /C calc'!A0", "model": "m", "status": 200, "out_tok": 5, "tps": -1.5, "ip": "10.0.0.1"},
                  {"ts": now - 10, "client": "+x", "model": "n, avec virgule", "status": 200}])
rows = c.strip().split("\n")
ok(rows[0].startswith("ts,client,ip,path,model") and len(rows) == 3, "en-tête et une ligne par requête")
ok("'=cmd" in c and "'+x" in c, "injection de formule neutralisée (=, +)")
ok(",-1.5\n" in c, "nombre négatif conservé tel quel")
ok('"n, avec virgule"' in c, "virgule échappée par des guillemets")
ok(rows[1].split(",")[0] < rows[2].split(",")[0], "tri chronologique")

# --- expiration des clés : console
ok(server.validate_expiry("") == "" and server.validate_expiry(None) == "" and server.validate_expiry("2030-12-31") == "2030-12-31", "date d'expiration : vide ou valide")
ok(all(raises(server.validate_expiry, x) for x in ("31/12/2030", "2030-13-01", "2030-02-30", "demain")), "date d'expiration invalide refusée")
ok(server.expiry_days("", "2030-01-01") is None and server.expiry_days("2030-01-10", "2030-01-01") == 9 and server.expiry_days("2030-01-01", "2030-01-01") == 0 and server.expiry_days("2029-12-30", "2030-01-01") == -2,
   "jours restants (0 = dernier jour, négatif = expirée)")
pub = {"enabled": True, "port": 11434, "tls": False, "auth": True, "allow": [], "keys": []}
server.load_publication = lambda: pub
server.save_publication = lambda p: None
tok, key = server.key_create({"name": "Stage", "perms": ["inference"], "expires": "2031-06-30"})
ok(key["expires"] == "2031-06-30" and "hash" not in key, "clé créée avec échéance")
server.key_update({"id": key["id"], "expires": ""})
ok(pub["keys"][0]["expires"] == "", "échéance retirée par mise à jour")
server.key_update({"id": key["id"], "enabled": False})
ok(pub["keys"][0]["expires"] == "", "mise à jour sans « expires » : échéance inchangée")
ok(raises(server.key_update, {"id": key["id"], "expires": "bientôt"}), "mise à jour avec date invalide refusée")

# --- expiration des clés : routeur
ok(not router.key_expired({}) and not router.key_expired({"expires": ""}), "routeur : sans échéance, jamais expirée")
ok(router.key_expired({"expires": "2020-01-01"}) and not router.key_expired({"expires": "2999-01-01"}), "routeur : échéance passée refusée, future acceptée")
ok(not router.key_expired({"expires": "2030-05-05"}, "2030-05-05") and router.key_expired({"expires": "2030-05-05"}, "2030-05-06"), "routeur : valable jusqu'à la fin du jour d'expiration")

# --- alertes d'expiration
cfg = {"events": ["key_expiry"]}
a = monitor.evaluate({"keys": [{"name": "A", "days_left": None}, {"name": "B", "days_left": 30}, {"name": "C", "days_left": 3}, {"name": "D", "days_left": 0}, {"name": "E", "days_left": -1}]}, cfg)
ok(set(a) == {"key_expiry:C", "key_expiry:D", "key_expiry:E"}, "alertes : seulement les clés expirant sous 7 jours ou expirées")
ok(a["key_expiry:E"]["severity"] == "warning" and a["key_expiry:C"]["severity"] == "info" and "aujourd'hui" in a["key_expiry:D"]["text"], "gravité et libellés")
ok("key_expiry" in monitor.EVENTS and "key_expiry" in monitor.DEFAULTS["events"], "événement proposé par défaut")

# --- Prometheus
txt = prom.render({"version": "0.5.0", "ollama_up": True, "cpu": 12.5, "mem": 40.0,
                   "gpus": [{"pci": "0000:01:00.0", "name": 'Quadro "RTX"\n4000', "util": 70, "mem_used": 1024, "mem_total": 8192, "temp": 61, "power": None}],
                   "counters": {"requests": 7, "errors": 1, "tokens_in": 100, "tokens_out": 300}, "queue": {"running": 2, "waiting": 0},
                   "servers": [{"name": "Srv1", "online": True}, {"name": "Srv2", "online": False}], "alerts": 1})
ok("# TYPE ollamabuntu_requests_total counter" in txt and "ollamabuntu_requests_total 7.0" in txt, "compteurs au format Prometheus")
ok('ollamabuntu_tokens_total{direction="output"} 300.0' in txt and txt.count("# TYPE ollamabuntu_tokens_total") == 1, "une seule déclaration TYPE par métrique")
ok('ollamabuntu_fleet_server_up{server="Srv2"} 0\n' in txt and 'ollamabuntu_ollama_up 1\n' in txt, "booléens en 0/1")
ok('name="Quadro \\"RTX\\" 4000"' in txt and "ollamabuntu_gpu_power_watts" not in txt, "étiquettes échappées ; valeur absente = métrique omise")
ok(txt.endswith("\n") and all(l.startswith("#") or " " in l for l in txt.strip().split("\n")), "format ligne à ligne valide")
import hashlib
d = hashlib.sha256(b"obm_secret").hexdigest()
ok(prom.token_ok("obm_secret", d) and not prom.token_ok("obm_autre", d) and not prom.token_ok("", d) and not prom.token_ok("x", "") and not prom.token_ok("x", "pas-un-hash"), "jeton : comparaison de l'empreinte")

# --- jeton Prometheus de la console
server.PROM_FILE = os.path.join(tmp, "prometheus.json")
ok(server.prom_status()["enabled"] is False, "export désactivé par défaut")
try:
    server.prom_auth({"Authorization": "Bearer x"}, "1.1.1.1"); ok(False, "refus attendu")
except PermissionError as e:
    ok(e.args[0] == 404, "export désactivé : 404 (aucune information)")
t = server.prom_token("create")
ok(t.startswith("obm_") and oct(os.stat(server.PROM_FILE).st_mode & 0o777) == "0o600" and t not in open(server.PROM_FILE).read(), "jeton généré, seule l'empreinte est stockée (0600)")
server.prom_auth({"Authorization": "Bearer " + t}, "1.1.1.1"); ok(True, "jeton valide accepté")
codes = []
for _ in range(11):
    try: server.prom_auth({"Authorization": "Bearer faux"}, "2.2.2.2")
    except PermissionError as e: codes.append(e.args[0])
ok(codes[:10] == [401] * 10 and codes[10] == 429, "essais invalides limités (429 après 10)")
server.prom_token("revoke")
ok(server.prom_status()["enabled"] is False and raises(server.prom_token, "autre"), "jeton révoqué ; action inconnue refusée")
server.prom_token("revoke"); ok(True, "révocation idempotente")

# --- échantillons : température et puissance GPU, compteurs
server.gpu_metrics = lambda: [{"pci": "0000:01:00.0", "name": "G", "util": 50, "mem_used": 1, "mem_total": 2, "temp": 70, "power": 120}]
server.new_requests = lambda: [{"status": 200, "in_tok": 3, "out_tok": 7, "tps": 10}, {"status": 500}]
server.take_sample()
s = server._metrics["samples"][-1]
ok(s["gpus"]["0000:01:00.0"]["t"] == 70 and s["gpus"]["0000:01:00.0"]["p"] == 120, "échantillon : température et puissance enregistrées")
ok(server._counters == {"requests": 2, "errors": 1, "tokens_in": 3, "tokens_out": 7}, "compteurs cumulés")
v = server.metrics_view(3600)
ok(v["series"][-1]["gpus"]["0000:01:00.0"]["t"] == 70 and v["series"][-1]["gpus"]["0000:01:00.0"]["p"] == 120, "vue des mesures : température et puissance moyennées")
server._metrics["samples"].append({"t": int(time.time()), "cpu": 1, "mem": 1, "gpus": {"0000:01:00.0": {"u": 1, "m": 1}}, "req": 0, "tok": 0, "tps": None, "ttft": None})
ok(server.metrics_view(3600)["series"], "anciens échantillons (sans température) toujours lisibles")

# --- routes HTTP réelles de la console (session simulée)
import threading, urllib.request, urllib.error
reqlog = os.path.join(tmp, "requests.jsonl")
with open(reqlog, "w") as f:
    for r in ({"ts": time.time() - 30, "client": "RH", "model": "gemma4:12b", "status": 200, "in_tok": 4, "out_tok": 9, "ms": 100, "path": "/api/chat", "prompt": "=SOMME(A1)"},
              {"ts": time.time() - 20, "client": "local", "model": "llama3.2:3b", "status": 500, "path": "/api/chat"},
              {"ts": time.time() - 10, "client": "RH", "model": "llama3.2:3b", "status": 200, "aborted": True, "path": "/api/generate"}):
        f.write(json.dumps(r) + "\n")
server.REQ_LOG = reqlog
role = {"v": "admin"}
server.session_get = lambda tok: ("adm", role["v"]) if tok == "T" else None
srv = server.make_server(0, server.Handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path, cookie=True, headers=None):
    h = dict(headers or {})
    if cookie: h["Cookie"] = "ob_session=T"
    try:
        r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), headers=h), timeout=10)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
def post(path, data):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode(), headers={"X-OB": "1", "Content-Type": "application/json", "Cookie": "ob_session=T"})
    try:
        x = urllib.request.urlopen(r, timeout=10); return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
c, h, b = get("/api/requests/export")
ok(c == 200 and h["Content-Type"].startswith("text/csv") and "attachment" in h["Content-Disposition"] and b.startswith(b"\xef\xbb\xbf"), "export CSV : en-tête, pièce jointe, BOM UTF-8")
txt = b.decode("utf-8-sig")
ok(len(txt.strip().split("\n")) == 4 and "SOMME" not in txt, "export CSV : 3 requêtes ; l'extrait de la demande n'est jamais exporté")
ok(len(get("/api/requests/export?status=error")[2].decode("utf-8-sig").strip().split("\n")) == 3, "export CSV : « erreurs » inclut l'erreur 500 et la requête interrompue")
ok(len(get("/api/requests/export?status=ok")[2].decode("utf-8-sig").strip().split("\n")) == 2, "export CSV : « réussies »")
ok(len(get("/api/requests/export?q=generate")[2].decode("utf-8-sig").strip().split("\n")) == 2 and len(get("/api/requests/export?client=rh&model=llama")[2].decode("utf-8-sig").strip().split("\n")) == 2, "export CSV : recherche libre et filtres modèle/client")
c, h, b = get("/api/usage?span=86400")
u = json.loads(b); ok(c == 200 and u["total"]["count"] == 3 and u["total"]["errors"] == 1 and {m["name"] for m in u["models"]} == {"gemma4:12b", "llama3.2:3b"}, "route /api/usage")
ok(get("/api/usage", cookie=False)[0] == 401 and get("/api/requests/export", cookie=False)[0] == 401, "usage et export : session exigée")
role["v"] = "utilisateur"
ok(get("/api/usage")[0] == 403 and get("/api/requests/export")[0] == 403 and get("/api/prom")[0] == 403, "usage, export et Prometheus : administrateurs seulement")
role["v"] = "admin"
c, d = post("/api/prom/token", {"action": "create"}); tok = d["token"]
ok(c == 200 and tok.startswith("obm_") and get("/api/prom")[0] == 200, "jeton Prometheus créé par la route")
server.gpu_metrics = lambda: [{"pci": "0000:01:00.0", "name": "G", "util": 50, "mem_used": 1, "mem_total": 2, "temp": 70, "power": 120}]
server.run = lambda *a, **k: "active\n"
c, h, b = get("/metrics", cookie=False, headers={"Authorization": "Bearer " + tok})
ok(c == 200 and h["Content-Type"].startswith("text/plain; version=0.0.4") and b"ollamabuntu_gpu_temperature_celsius" in b and b"ollamabuntu_ollama_up 1" in b, "/metrics : texte Prometheus avec le jeton, sans session")
ok(get("/metrics", cookie=False)[0] == 401 and get("/metrics", cookie=False, headers={"Authorization": "Bearer faux"})[0] == 401, "/metrics : sans jeton ou avec un faux jeton, 401")
ok(get("/metrics", headers={"Authorization": "Bearer faux"})[0] == 401, "/metrics : la session ne remplace pas le jeton")
ok(tok.encode() not in b and b"ob_" not in b, "/metrics : aucune clé ni jeton dans la sortie")
post("/api/prom/token", {"action": "revoke"})
ok(get("/metrics", cookie=False, headers={"Authorization": "Bearer " + tok})[0] == 404, "/metrics : 404 après révocation")
srv.shutdown()
print("\n%d vérifications réussies" % n)
