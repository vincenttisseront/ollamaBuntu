#!/usr/bin/env python3
"""Troisième lot : journal d'audit, rapport hebdomadaire par e-mail, espace disque des modèles (routes HTTP réelles de la console)."""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp()
os.environ.update(OB_ETC=tmp + "/etc", OB_STATE=tmp + "/state", OB_MODELS=tmp + "/models")
LIB = os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, os.path.join(LIB, "admin")); sys.path.insert(0, LIB)
import audit, report, monitor, usage, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a, exc=ValueError):
    try: f(*a); return False
    except exc: return True

# --- audit : pur
label, detail = audit.describe("/api/users/create", {"name": "marie", "role": "administrateur", "password": "Secret!123", "token": "abc", "api_key": "k", "new": "x", "models": ["a", "b"], "enabled": True})
ok(label == "Création d'un compte" and "name=marie" in detail and "models=2 élément(s)" in detail and "enabled=True" in detail, "libellé en français et détail lisible : %s" % detail)
ok(not any(w in detail for w in ("Secret", "abc", "password", "token", "api_key")), "aucun secret dans le détail (mot de passe, jeton, clé)")
_, d2 = audit.describe("/api/ollama-env", {"values": {"OLLAMA_KEEP_ALIVE": "30m", "OLLAMA_NUM_PARALLEL": "2"}})
ok("values.OLLAMA_KEEP_ALIVE=30m" in d2, "réglages imbriqués aplatis")
ok(audit.describe("/api/inconnu/action", {})[0] == "inconnu › action", "route inconnue : libellé dérivé du chemin")
ok(audit.skipped("/api/chat") and audit.skipped("/api/fleet/ollama/x") and audit.skipped("/api/login") and not audit.skipped("/api/users/create"), "conversations de test et relais d'inférence non journalisés")
e = audit.entry("marie", "admin", "10.0.0.5", "/api/models/delete", {"model": "x"}, 403, now=1_800_000_000)
ok(e["ok"] is False and e["status"] == 403 and e["label"] == "Suppression d'un modèle", "refus consigné avec son code")
entries = [audit.entry("a", "admin", "1.1.1.1", "/api/models/pull", {"model": "m1"}, 200, now=1), audit.entry("b", "admin", "1.1.1.2", "/api/users/delete", {"name": "z"}, 403, now=2), audit.entry("a", "admin", "1.1.1.1", "/api/perf/profile", {"id": "econome"}, 200, now=3)]
ok([x["ts"] for x in audit.search(entries)] == [3, 2, 1] and [x["ts"] for x in audit.search(entries, user="a")] == [3, 1] and [x["ts"] for x in audit.search(entries, status="error")] == [2], "recherche : plus récent d'abord, filtres utilisateur et résultat")
ok([x["ts"] for x in audit.search(entries, q="économe")] == [] and [x["ts"] for x in audit.search(entries, q="econome")] == [3] and [x["ts"] for x in audit.search(entries, q="1.1.1.2")] == [2], "recherche libre dans l'action, le détail et l'adresse")
c = audit.to_csv([audit.entry("=cmd|' /C calc'!A0", "admin", "1.1.1.1", "/api/x", {}, 200, now=5)])
ok(c.startswith("date,utilisateur") and "'=cmd" in c, "export CSV : injection de formule neutralisée")

# --- audit : console (fichier, rotation)
server.AUDIT_FILE = tmp + "/state/audit.jsonl"
server.audit_record("marie", "admin", "10.0.0.5", "/api/keys/create", {"name": "RH", "password": "x"}, 200)
rows = server.audit_entries()
ok(len(rows) == 1 and rows[0]["user"] == "marie" and "x" not in rows[0]["detail"].replace("name=RH", "") and oct(os.stat(server.AUDIT_FILE).st_mode & 0o777) == "0o600", "écriture : une ligne, droits 0600, aucun secret")
server.AUDIT_MAX = 1200
for i in range(8): server.audit_record("u", "admin", "1.1.1.1", "/api/perf/fix", {"id": "swappiness"}, 200)
ok(os.path.exists(server.AUDIT_FILE + ".1") and len(server.audit_entries()) >= 8, "rotation : l'ancien fichier est conservé, rien de perdu")

# --- routes HTTP
role = {"v": "admin"}
server.session_get = lambda tok: ("adm", role["v"]) if tok == "T" else None
srv = server.make_server(0, server.Handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path):
    try:
        r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), headers={"Cookie": "ob_session=T"}), timeout=10); return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e: return e.code, e.headers, e.read()
def post(path, data):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode(), headers={"X-OB": "1", "Content-Type": "application/json", "Cookie": "ob_session=T"})
    try:
        x = urllib.request.urlopen(r, timeout=10); return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
server.audit_clear()
server.guard_status = lambda max_age=45: {"issues": []}
st, res = post("/api/gpu/guard/config", {"auto": False, "token": "SECRET-TOKEN"})
st2, res2 = post("/api/audit/clear", {})
st3, _, b = get("/api/audit")
a = json.loads(b)
ok(st == 200 and [x["label"] for x in a["entries"]] == ["Effacement du journal d'audit"], "l'effacement du journal est lui-même consigné (et seul)")
post("/api/gpu/guard/config", {"auto": True, "password": "P@ss"})
post("/api/perf/profile", {"id": "inconnu"})
c, h, b = get("/api/audit?status=error")
a = json.loads(b)
ok(c == 200 and len(a["entries"]) == 1 and a["entries"][0]["status"] == 400 and a["entries"][0]["detail"] == "id=inconnu", "action refusée (400) consignée avec son détail")
c, h, b = get("/api/audit?q=GPU")
ok(len(json.loads(b)["entries"]) == 1 and "P@ss" not in b.decode() and "SECRET-TOKEN" not in b.decode(), "recherche ; aucun secret dans la réponse")
c, h, b = get("/api/audit/export")
ok(c == 200 and "attachment" in h["Content-Disposition"] and b.startswith(b"\xef\xbb\xbf") and "P@ss" not in b.decode("utf-8-sig"), "export CSV de l'audit")
role["v"] = "utilisateur"
ok(get("/api/audit")[0] == 403 and get("/api/report")[0] == 403 and get("/api/models/disk")[0] == 403, "réservé aux administrateurs")
role["v"] = "admin"

# --- rapport : pur
lt_mon = time.strptime("2026-11-09 08:30", "%Y-%m-%d %H:%M")
cfg = {"enabled": True, "day": 0, "hour": 8}
ok(report.due(cfg, lt_mon, "") and not report.due(cfg, lt_mon, "2026-11-09") and not report.due(dict(cfg, enabled=False), lt_mon, "") and not report.due(dict(cfg, hour=9), lt_mon, "") and not report.due(dict(cfg, day=1), lt_mon, ""), "envoi dû le bon jour, à partir de l'heure choisie, une fois par jour")
ok(raises(report.clean_config, {"hour": 24}) and raises(report.clean_config, {"day": "x"}) and report.clean_config({"enabled": 1, "day": "2"})["day"] == 2, "réglage validé")
u = usage.aggregate([{"ts": 100, "client": "RH", "model": "a", "status": 200, "in_tok": 10, "out_tok": 20}, {"ts": 101, "client": "RH", "model": "a", "status": 500}], 200, 7 * 86400)
obj, text, page = report.build({"host": "srv<1>", "since": 0, "until": 604800, "usage": u, "tps_avg": 41.5, "uptime_days": 12, "disk": {"used": 50, "total": 100}, "alerts": ["Disque presque plein"],
                                "guard_events": [{"codes": ["ollama_blind"], "result": "résolu"}], "perf_events": ["Profil appliqué"], "hw": ["RAID md0 dégradé"],
                                "keys_expiring": ["Clé « RH » expire dans 3 jour(s)"], "update": "2026.12.01-0900", "models_unused": [{"name": "vieux:7b", "size": 5 << 30}]})
ok("2 requêtes, 1 en erreur (50.0 %)" in text and "Débit moyen : 41.5" in text and "a : 2 requêtes" in text and "Réparation GPU (ollama_blind) : résolu" in text and "vieux:7b (5.0 Go)" in text, "texte : usage, incidents, matériel et à-faire")
ok("&lt;1&gt;" in page and "srv<1>" not in page and [s["title"] for s in obj["sections"]][0] == "Usage", "HTML : contenu échappé")
ok("Aucun incident." in report.build({"usage": {}, "since": 0, "until": 1})[1] and "Rien à signaler." in report.build({"usage": {}, "since": 0, "until": 1})[1], "semaine calme : rapport sobre")

# --- rapport : console (SMTP simulé)
os.makedirs(tmp + "/etc", exist_ok=True); server.REPORT_FILE = tmp + "/etc/report.json"; server.ALERTS_FILE = tmp + "/etc/alerts.json"
server.hw_view = lambda max_age=120: {"issues": [{"text": "RAID md0 dégradé", "severity": "critical", "key": "raid:md0"}]}
server.status = lambda: {"uptime": 3 * 86400, "disk": {"used": 10, "total": 100}, "update_available": None}
server.ollama_json = lambda *a, **k: (200, {"models": []})
server.read_requests = lambda n=5000: []
server.load_publication = lambda: {"keys": [{"name": "Stage", "enabled": True, "expires": "2020-01-01"}]}
mails = []
monitor.send_mail = lambda cfg, pw, subj, body, timeout=15, html=None: mails.append((subj, body, html))
ok(raises(server.report_send), "sans serveur SMTP : message clair")
json.dump({"smtp": {"host": "smtp.test", "from": "ob@test", "to": ["adm@test"], "port": 587}, "enabled": False}, open(server.ALERTS_FILE, "w"))
st, res = post("/api/report/send", {})
ok(st == 200 and mails and mails[0][0].startswith("[OllamaBuntu") and "TEST" in mails[0][0] and "<h3" in mails[0][2] and "Clé d'API « Stage » expirée" in mails[0][1] and "RAID md0 dégradé" in mails[0][1], "envoi d'essai : objet, texte, HTML, clé expirée et RAID repris")
st, res = post("/api/report/config", {"enabled": True, "day": 4, "hour": 17})
c, h, b = get("/api/report")
r = json.loads(b)
ok(st == 200 and r["config"]["enabled"] is True and r["config"]["day"] == 4 and r["config"]["hour"] == 17 and r["smtp"] is True and "Usage" in r["text"], "réglage enregistré ; aperçu du rapport")
ok(post("/api/report/config", {"hour": 99})[0] == 400, "heure invalide : 400")

# --- espace disque des modèles
day = 86400
now = time.time()
iso = lambda d: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - d * day))
tags = [{"name": "actif:7b", "size": 4 << 30, "modified_at": iso(100)}, {"name": "vieux:7b", "size": 5 << 30, "modified_at": iso(100)}, {"name": "recent:3b", "size": 2 << 30, "modified_at": iso(1)},
        {"name": "charge:8b", "size": 6 << 30, "modified_at": iso(100)}, {"name": "dormant:1b", "size": 1 << 30, "modified_at": iso(100)}, {"name": "x-cloud", "size": 0}]
def fake_ollama(m, p, body=None, timeout=15, addr=None):
    if p == "/api/tags": return 200, {"models": tags}
    if p == "/api/ps": return 200, {"models": [{"name": "charge:8b"}]}
    return 200, {}
server.ollama_json = fake_ollama
server.read_requests = lambda n=5000: [{"ts": now - 2 * day, "model": "actif:7b"}, {"ts": now - 50 * day, "model": "dormant:1b"}]
server.load_pools = lambda: []
json.dump({"boot": ["recent:3b"], "times": []}, open(tmp + "/etc/warmup.json", "w")); server.WARMUP_FILE = tmp + "/etc/warmup.json"
server.reqlog_settings = lambda: {"days": 7, "prompt_excerpt": False, "chars": 120}
m = {x["name"]: x for x in server.models_disk(30)["models"]}
ok(m["vieux:7b"]["unused"] and m["dormant:1b"]["unused"] and m["dormant:1b"]["idle_days"] == 50, "inutilisés : jamais vu dans le journal et installé depuis longtemps, ou sans requête depuis plus de 30 jours")
ok(not m["actif:7b"]["unused"] and not m["recent:3b"]["unused"] and not m["charge:8b"]["unused"] and m["charge:8b"]["loaded"] and m["recent:3b"]["pinned"], "jamais proposés : modèle utilisé, récent, chargé en mémoire ou préchauffé")
ok("x-cloud" not in m and server.models_disk(30)["reclaimable"] == 6 << 30 and server.models_disk(30)["models"][0]["unused"], "modèles cloud ignorés ; espace récupérable = 6 Go ; inutilisés en tête de liste")
ok(not {x["name"]: x for x in server.models_disk(60)["models"]}["dormant:1b"]["unused"], "le seuil d'inactivité est réglable (60 jours : plus proposé)")
c, h, b = get("/api/models/disk?days=30")
ok(c == 200 and json.loads(b)["journal_days"] == 7 and json.loads(b)["disk"]["total"] > 0, "route /api/models/disk")
print("\n%d vérifications réussies" % n)
