import hashlib, http.client, json, os, ssl, subprocess, sys, time
E = "/tmp/rta/etc"; NET = "192.0.2.2"; n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
KA, KB, KR = "ob-cleA-" + "a" * 32, "ob-cleB-" + "b" * 32, "ob-revoquee-" + "c" * 28
H = lambda k: hashlib.sha256(k.encode()).hexdigest()
pub = {"enabled": True, "port": 18600, "tls": True, "auth": True, "allow": [], "anonymous": {"perms": [], "models": []},
       "keys": [{"id": "ka", "name": "Appli RH", "hash": H(KA), "perms": ["inference", "read"], "models": ["llama3.2:3b"], "enabled": True},
                {"id": "kb", "name": "Exploitation", "hash": H(KB), "perms": ["inference", "read", "manage"], "models": [], "enabled": True},
                {"id": "kr", "name": "Ancienne", "hash": H(KR), "perms": ["inference"], "models": [], "enabled": False}]}
def save(): json.dump(pub, open(E + "/publication.json", "w")); t = time.time() + n; os.utime(E + "/publication.json", (t, t))
save(); json.dump({"pools": []}, open(E + "/pools.json", "w"))
USAGE = "/tmp/rta/state/usage-%d.json" % os.getpid()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
def req(method, path, body=None, key=None, host=NET, port=18600, tls=True, hdr="auth"):
    c = http.client.HTTPSConnection(host, port, context=ctx, timeout=20) if tls else http.client.HTTPConnection(host, port, timeout=20)
    h = {"Content-Type": "application/json"}
    if key: h.update({"Authorization": "Bearer " + key} if hdr == "auth" else {"X-API-Key": key})
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
    first = raw.splitlines()[0] if raw.strip() else b"{}"
    return r.status, json.loads(first), r
ups = [subprocess.Popen([sys.executable, "/tmp/rta/upstream.py", str(p)]) for p in (11400,)]
rt = subprocess.Popen([sys.executable, "/home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/router.py"], env=dict(os.environ, OB_ETC=E, OB_ROUTER_LISTEN="127.0.0.1:18434", OB_ROUTER_USAGE=USAGE), stdout=open("/tmp/rta/router.log", "w"), stderr=subprocess.STDOUT)
time.sleep(1.5)
try:
    s, d, _ = req("POST", "/api/chat", {"model": "qwen3:32b"}, host="127.0.0.1", port=18434, tls=False); ok(s == 200, "accès local 127.0.0.1:11434 (console, Open WebUI) : sans clé, tous droits")
    s, d, r = req("POST", "/api/chat", {"model": "llama3.2:3b"}); ok(s == 401 and r.getheader("WWW-Authenticate", "").startswith("Bearer"), "réseau sans clé : 401 « %s »" % d["error"])
    s, d, _ = req("POST", "/api/chat", {"model": "llama3.2:3b"}, key="ob-faux-" + "z" * 32); ok(s == 401 and "invalide" in d["error"], "clé inconnue : 401 « %s »" % d["error"])
    s, d, _ = req("POST", "/api/chat", {"model": "llama3.2:3b"}, key=KR); ok(s == 401, "clé désactivée (révoquée) : 401")
    s, d, _ = req("POST", "/api/chat", {"model": "llama3.2:3b"}, key=KA); ok(s == 200 and d["served_by"] == 11400, "clé « Appli RH » : chat llama3.2:3b autorisé (HTTPS, en flux)")
    ok(d["auth_seen"] is False, "la clé n'est pas transmise à Ollama (en-tête Authorization retiré)")
    s, d, _ = req("POST", "/api/chat", {"model": "qwen3:32b"}, key=KA); ok(s == 403 and "non autorisé" in d["error"], "clé « Appli RH » : qwen3:32b refusé « %s »" % d["error"])
    s, d, _ = req("POST", "/v1/chat/completions", {"model": "qwen3:32b"}, key=KA); ok(s == 403, "même refus par l'API compatible OpenAI")
    s, d, _ = req("POST", "/api/pull", {"model": "llama3.2:3b"}, key=KA); ok(s == 403 and "gestion" in d["error"], "clé « Appli RH » : téléchargement refusé « %s »" % d["error"])
    s, d, _ = req("POST", "/api/foo", {}, key=KA); ok(s == 403, "point d'API inconnu : réservé aux droits de gestion")
    s, d, _ = req("GET", "/api/tags", key=KA); ok([m["name"] for m in d["models"]] == ["llama3.2:3b"], "liste des modèles filtrée pour « Appli RH » : %s" % [m["name"] for m in d["models"]])
    s, d, _ = req("GET", "/v1/models", key=KA); ok([m["id"] for m in d["data"]] == ["llama3.2:3b"], "/v1/models filtré de même")
    s, d, _ = req("GET", "/api/ps", key=KA); ok([m["name"] for m in d["models"]] == ["llama3.2:3b"], "/api/ps filtré de même")
    s, d, _ = req("GET", "/api/tags", key=KB); ok(len(d["models"]) == 3, "clé « Exploitation » (tous modèles) : liste complète")
    s, d, _ = req("POST", "/api/pull", {"model": "mistral"}, key=KB); ok(s == 200 and d["served_by"] == 11400, "clé « Exploitation » (droit de gestion) : téléchargement autorisé")
    s, d, _ = req("GET", "/api/tags", key=KB, hdr="x"); ok(s == 200, "en-tête X-API-Key accepté en alternative")
    pub["keys"][0]["models"].append("qwen3:32b"); save(); time.sleep(0.2)
    s, d, _ = req("POST", "/api/chat", {"model": "qwen3:32b"}, key=KA); ok(s == 200, "modèle ajouté à la clé : pris en compte à chaud, sans redémarrer")
    pub["allow"] = ["10.0.0.0/8"]; save(); time.sleep(0.2)
    s, d, _ = req("GET", "/api/tags", key=KB); ok(s == 403 and "non autorisée" in d["error"], "filtrage IP : 192.0.2.2 hors de 10.0.0.0/8 refusée « %s »" % d["error"])
    pub["allow"] = ["192.0.2.0/24"]; save(); time.sleep(0.2)
    s, d, _ = req("GET", "/api/tags", key=KB); ok(s == 200, "filtrage IP : 192.0.2.0/24 autorisé")
    pub["auth"] = False; pub["anonymous"] = {"perms": ["read"], "models": []}; save(); time.sleep(0.2)
    s1, _, _ = req("GET", "/api/tags"); s2, d2, _ = req("POST", "/api/chat", {"model": "llama3.2:3b"})
    ok(s1 == 200 and s2 == 403, "sans clé, droits anonymes « consultation » seulement : liste 200, chat 403")
    pub["auth"] = True; save(); time.sleep(0.2)
    try:
        c = http.client.HTTPConnection(NET, 18600, timeout=5); c.request("GET", "/api/tags"); c.getresponse(); plain = True
    except Exception: plain = False
    ok(not plain, "HTTP en clair sur le port HTTPS : refusé")
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; c.maximum_version = ssl.TLSVersion.TLSv1_1
    try:
        c.minimum_version = ssl.TLSVersion.TLSv1
        import socket; s_ = c.wrap_socket(socket.create_connection((NET, 18600), timeout=5)); weak = True
    except Exception: weak = False
    ok(not weak, "TLS 1.0 / 1.1 : refusés (TLS 1.2 minimum)")
    t0 = time.time(); u = {}
    while time.time() - t0 < 25:   # écriture différée du routeur (10 s après la dernière requête)
        try:
            u = json.load(open(USAGE))
            if u.get("ka", {}).get("count", 0) >= 4 and u.get("kb", {}).get("count", 0) >= 4: break
        except (OSError, ValueError): pass
        time.sleep(0.5)
    ok(u["ka"]["count"] >= 4 and u["kb"]["count"] >= 4 and "last" in u["ka"], "usage enregistré par clé (Appli RH : %d requêtes, dernière %s)" % (u["ka"]["count"], u["ka"]["last"]))
finally:
    rt.terminate(); [x.terminate() for x in ups]
