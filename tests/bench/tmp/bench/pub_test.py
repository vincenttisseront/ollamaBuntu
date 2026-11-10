import json, ssl, http.client, os, sys, time, subprocess, stat
T = "/tmp/target"; E = T + "/etc/ollamabuntu"; n = 0
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE; cookie = {}
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
def api(method, path, body=None):
    c = http.client.HTTPSConnection("127.0.0.1", 18443, context=ctx, timeout=60); h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = "; ".join("%s=%s" % kv for kv in cookie.items())
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
    for k, v in r.getheaders():
        if k.lower() == "set-cookie": kv = v.split(";")[0].split("=", 1); cookie[kv[0]] = kv[1]
    return r.status, json.loads(raw or b"{}")
calls = lambda: open(T + "/tmp/systemctl-calls.log").read() if os.path.exists(T + "/tmp/systemctl-calls.log") else ""
def reset_calls(): open(T + "/tmp/systemctl-calls.log", "w").close()
api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
s, p = api("GET", "/api/publication")
ok(s == 200 and p["enabled"] is False and p["tls"] and p["port"] == 11443 and p["auth"] and p["keys"] == [], "par défaut : accès réseau désactivé, HTTPS 11443 et clé exigée prévus")
for body, why in [({"enabled": True, "tls": True, "port": 11434}, "HTTPS sur le port local 11434"), ({"port": 18443}, "port de la console"), ({"port": 11500}, "port d'une instance Ollama"),
                  ({"port": 80}, "port privilégié"), ({"allow": ["10.0.0.0/33"]}, "réseau invalide"), ({"port": "abc"}, "port non numérique")]:
    s, d = api("POST", "/api/publication", body); ok(s == 400, "refus : %s -> « %s »" % (why, d.get("error")))
reset_calls()
s, d = api("POST", "/api/publication", {"enabled": True, "tls": True, "port": 11443, "auth": True, "allow": ["192.0.2.0/24", " 10.1.2.3 "]})
pub = json.load(open(E + "/publication.json"))
ok(s == 200 and pub["enabled"] and pub["allow"] == ["192.0.2.0/24", "10.1.2.3/32"], "publication HTTPS 11443 activée, réseaux normalisés : %s" % pub["allow"])
ok(oct(os.stat(E + "/publication.json").st_mode & 0o777) == "0o640", "publication.json en 0640 (lisible par le routeur, pas par les autres comptes)")
ks = os.stat(E + "/router-tls/key.pem")
ok(open(E + "/router-tls/cert.pem").read() == open(E + "/tls/cert.pem").read() and oct(ks.st_mode & 0o777) == "0o640", "certificat de la console copié pour le routeur (clé privée 0640)")
ok("restart ollamabuntu-router.service" in calls(), "écoute modifiée : routeur redémarré")
reset_calls()
s, d = api("POST", "/api/publication/keys/create", {"name": "Appli RH", "perms": ["inference", "read"], "models": ["ob-tiny"]})
token = d.get("token", "")
ok(s == 200 and token.startswith("ob_") and len(token) > 40 and d["key"]["models"] == ["ob-tiny:latest"], "clé créée : %s… (%d caractères), modèles %s" % (token[:9], len(token), d["key"]["models"]))
raw = open(E + "/publication.json").read()
ok(token not in raw and "hash" in raw, "la clé n'est stockée que sous forme d'empreinte (absente en clair du fichier)")
s, v = api("GET", "/api/publication")
ok(all("hash" not in k for k in v["keys"]) and v["keys"][0]["prefix"] == token[:9], "la console n'expose ni la clé ni son empreinte (préfixe seulement)")
ok("restart ollamabuntu-router" not in calls(), "création de clé : aucun redémarrage du routeur (relu à chaud)")
for body, why in [({"name": "Appli RH", "perms": ["read"]}, "nom déjà utilisé"), ({"name": "X", "perms": []}, "aucun droit"), ({"name": "Y", "perms": ["read"], "models": ["bad name!"]}, "modèle invalide"), ({"name": "<i>", "perms": ["read"]}, "nom invalide")]:
    s, d2 = api("POST", "/api/publication/keys/create", body); ok(s == 400, "refus : %s -> « %s »" % (why, d2.get("error")))
s, st = api("GET", "/api/status")
ok(st["ollama"]["publication"] == {"enabled": True, "port": 11443, "tls": True, "auth": True}, "tableau de bord : publication HTTPS 11443 avec clés")
# --- intégration : vrai routeur (utilisateur ollama) + vrai Ollama
rt = subprocess.Popen(["chroot", "--userspec=ollama:ollama", T, "/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "OB_MAIN=127.0.0.1:11434", "OB_ROUTER_LISTEN=127.0.0.1:18434",
                       "OB_ROUTER_USAGE=/tmp/router-usage.json", "python3", "/usr/local/lib/ollamabuntu/router.py"], stdout=open("/tmp/router-int.log", "w"), stderr=subprocess.STDOUT)
time.sleep(2)
def net(method, path, body=None, key=None):
    c = http.client.HTTPSConnection("192.0.2.2", 11443, context=ctx, timeout=120); h = {"Content-Type": "application/json"}
    if key: h["Authorization"] = "Bearer " + key
    c.request(method, path, body=json.dumps(body) if body else None, headers=h); r = c.getresponse(); raw = r.read(); return r.status, raw
try:
    ok(rt.poll() is None, "routeur démarré en utilisateur ollama : fichiers de la console lisibles (publication 0640, certificat)")
    s, raw = net("POST", "/api/generate", {"model": "ob-tiny", "prompt": "Bonjour", "stream": False, "options": {"num_predict": 8}}, key=token)
    ok(s == 200 and json.loads(raw).get("response") is not None, "réseau HTTPS + clé « Appli RH » : génération réelle par Ollama")
    s, raw = net("POST", "/api/generate", {"model": "qwen3.5:2b", "prompt": "x", "stream": False}, key=token); ok(s == 403, "modèle hors de la clé : refusé")
    s, raw = net("GET", "/api/tags"); ok(s == 401, "réseau sans clé : 401")
    s, raw = net("GET", "/api/tags", key=token); ok(s == 200 and [m["name"] for m in json.loads(raw)["models"]] == ["ob-tiny:latest"], "liste des modèles vue par la clé : ob-tiny:latest seulement")
    kid = v["keys"][0]["id"]; api("POST", "/api/publication/keys/update", {"id": kid, "enabled": False}); time.sleep(0.3)
    s, raw = net("GET", "/api/tags", key=token); ok(s == 401, "clé désactivée depuis la console : refusée immédiatement, sans redémarrage")
    c = http.client.HTTPConnection("127.0.0.1", 18434, timeout=60); c.request("POST", "/api/generate", json.dumps({"model": "qwen3.5:2b", "prompt": "x", "stream": False, "options": {"num_predict": 4}}))
    ok(c.getresponse().status == 200, "accès local (Open WebUI, console) : toujours sans clé")
    s, d = api("POST", "/api/publication/keys/delete", {"id": kid}); ok(s == 200 and api("GET", "/api/publication")[1]["keys"] == [], "clé supprimée")
finally:
    rt.terminate()
