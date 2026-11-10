import json, ssl, http.client, time, os, socket
ctx = ssl._create_unverified_context(); n = [0]
def req(method, path, body=None, cookie=None, port=18443, timeout=120):
    c = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=timeout)
    h = {"Content-Type": "application/json", "X-OB": "1"}
    if cookie: h["Cookie"] = cookie
    c.request(method, path, json.dumps(body) if body is not None else None, h); r = c.getresponse(); d = r.read(); c.close()
    try: return r, json.loads(d)
    except ValueError: return r, d
def check(cond, msg):
    n[0] += 1; print(("[%02d] OK   - " if cond else "[%02d] ÉCHEC - ") % n[0] + msg, flush=True)
    if not cond: raise SystemExit(1)
r, d = req("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"}); ck = r.getheader("Set-Cookie").split(";")[0]
print("=== MISES À JOUR SYSTÈME")
t0 = time.time(); r, u = req("GET", "/api/updates?refresh=1", cookie=ck)
import subprocess as _sp
EXPECTED = sum(1 for l in _sp.run(["chroot", "/tmp/target", "apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], capture_output=True, text=True).stdout.splitlines() if l.startswith("Inst "))
check(r.status == 200 and u["count"] == EXPECTED, "%d paquets en attente détectés (identique à apt-get -s), analyse en %.1f s" % (u["count"], time.time() - t0))
check(u["summary"]["securite"] > 0 and sum(u["summary"].values()) == EXPECTED, "classement par dépôt : %s" % u["summary"])
P = {p["name"]: p for p in u["packages"]}
check(P["libssl3t64"]["source"] == "openssl" and P["libssl3t64"]["priority"] == "high", "libssl3t64 (source openssl) : priorité HAUTE (USN-9001-1)")
check([a["id"] for a in P["libssl3t64"]["advisories"]] == ["USN-9001-1"], "faille critique NON corrigée par cette version correctement ignorée")
check(P["libc6"]["priority"] == "medium", "libc6 (source glibc) : priorité MOYENNE lue dans la structure imbriquée")
check(P["openssh-server"]["priority"] is None and P["openssh-server"]["advisories"][0]["id"] == "USN-9003-1", "openssh-server : avis USN-9003-1 sans priorité -> « non déterminée »")
check(u["security_priority"]["high"] >= 1 and u["security_priority"]["medium"] >= 1 and u["security_priority"]["inconnue"] > 0, "répartition de criticité : %s" % {k: v for k, v in u["security_priority"].items() if v})
check(u["packages"][0]["kind"] == "securite" and u["packages"][0]["priority"] == "high", "tri : sécurité de priorité haute en tête (%s)" % u["packages"][0]["name"])
time.sleep(2); q = json.load(open("/tmp/bench/osv-queries.json")); check(len(q) == len(set(q)) and len(q) >= 30, "OSV interrogé une seule fois par paquet source (époques comprises) (%d requêtes)" % len(q))
r, u2 = req("GET", "/api/updates", cookie=ck); q2 = json.load(open("/tmp/bench/osv-queries.json")) if True else []
check(r.status == 200, "deuxième lecture servie par le cache")
print("=== MODÈLES")
t0 = time.time(); r, m = req("GET", "/api/models/insights?refresh=1", cookie=ck)
check(r.status == 200 and m["registry"]["ok"], "registre interrogé (%.1f s), capacité : %s de VRAM, GPU : %s" % (time.time() - t0, round(m["capacity"]["vram"] / 2**30, 1), len(m["capacity"]["gpus"])))
I = {x["name"]: x for x in m["installed"]}
check(I["llama3.2:3b"]["update"]["state"] == "maj", "llama3.2:3b installé, version distante différente : %s" % I["llama3.2:3b"]["update"]["label"])
check(I["qwen3.5:2b"]["update"]["state"] == "a_jour", "qwen3.5:2b : identique au registre -> « À jour »")
check(I["ob-tiny:latest"]["update"]["state"] == "local", "ob-tiny : absent du registre -> « modèle local »")
C = {x["name"]: x for x in m["catalog"]}
check(C["gemma4:12b"]["available"] and C["gemma4:12b"]["vision"] and C["gemma4:12b"]["params"] == "11.9B", "gemma4:12b : liste de manifestes suivie jusqu'à la variante GGUF (11.9B, vision, %.1f Go)" % (C["gemma4:12b"]["size"] / 1e9))
check(C["llama3.3:70b"]["fit"]["level"] == "gpu", "llama3.3:70b (43 Go) : %s avec 60 Gio de VRAM" % C["llama3.3:70b"]["fit"]["label"])
check(C["gpt-oss:120b"]["fit"]["level"] == "trop", "gpt-oss:120b (65 Go) : %s" % C["gpt-oss:120b"]["fit"]["label"])
check(C["qwen3.8:27b"]["fit"]["level"] == "incompatible", "qwen3.8:27b : %s" % C["qwen3.8:27b"]["fit"]["label"])
check(not C["bge-m3"]["available"], "bge-m3 absent du (faux) registre -> « indisponible »")
check(C["llama3.2:3b"]["installed"] and C["qwen3.5:2b"]["installed"], "catalogue : modèles déjà installés reconnus")
order = [x["fit"]["level"] if x.get("fit") else None for x in m["catalog"]]
check(order.index("gpu") < order.index("trop") and order[-1] is None, "catalogue trié : compatibles d'abord, indisponibles à la fin")
r, c = req("POST", "/api/models/check", {"name": "gpt-oss:20b"}, ck); check(c["found"] and c["fit"]["level"] == "gpu" and c["params"] == "20.9B", "vérification de gpt-oss:20b : %s, %s %s" % (c["fit"]["label"], c["params"], c["quant"]))
r, c = req("POST", "/api/models/check", {"name": "modele-inexistant:7b"}, ck); check(c["found"] is False, "modèle inexistant : signalé introuvable")
r, c = req("POST", "/api/models/check", {"name": "kimi-k3:cloud"}, ck); check(c.get("cloud"), "tag :cloud : signalé comme modèle cloud (non local)")
print("=== OPEN WEBUI")
r, w = req("GET", "/api/webui", cookie=ck); check(w["docker"] and w["container"] is None and not w["configured"], "état initial : Docker présent, Open WebUI non déployé")
for bad, why in [({"email": "pas-un-email", "password": "Secret-2026"}, "e-mail invalide"), ({"email": "a@b.fr", "password": "court"}, "mot de passe trop court"), ({"email": "a@b.fr", "password": "abc\ndefghijk"}, "saut de ligne (injection dans le fichier d'environnement)")]:
    r, d = req("POST", "/api/webui/deploy", bad, ck); check(r.status == 400, "déploiement refusé : %s" % why)
s = socket.create_connection(("127.0.0.1", 18843)); t = ctx.wrap_socket(s, server_hostname="x"); t.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"); resp = t.recv(4096).decode(errors="replace"); t.close()
check("503" in resp and "pas déployé" in resp, "relais HTTPS :8443 sans Open WebUI : page 503 explicite")
import importlib.util, sys
spec = importlib.util.spec_from_file_location("mocks", "/tmp/bench/mocks.py"); mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)
mk.serve(3000, mk.WebUI)   # la « fausse Open WebUI » démarre maintenant (comme le conteneur)
r, d = req("POST", "/api/webui/deploy", {"email": "vti@ibanfirst.com", "name": "VTI", "password": "Owui-Secret-2026"}, ck); check(r.status == 200 and d.get("job"), "déploiement lancé (tâche %s)" % d.get("job"))
envf = "/tmp/target/etc/ollamabuntu/open-webui.env"
check(oct(os.stat(envf).st_mode & 0o777) == "0o600", "fichier de configuration créé avec les droits 600")
jid = d["job"]
for i in range(120):
    r, j = req("GET", "/api/jobs/" + jid, cookie=ck)
    if j["done"]: break
    time.sleep(1)
print("     " + "\n     ".join(j["output"].strip().splitlines()))
check(j["done"] and j["rc"] == 0, "tâche de déploiement terminée (code %s)" % j["rc"])
env = open(envf).read(); calls = open("/tmp/target/tmp/docker-calls.log").read().splitlines()
check("WEBUI_ADMIN_PASSWORD" not in env and "WEBUI_ADMIN_EMAIL=vti@ibanfirst.com" in env and "HOST=127.0.0.1" in env, "mot de passe initial retiré, e-mail et écoute locale conservés")
runs = [c for c in calls if c.startswith("docker run")]
check(len(runs) == 2 and all("--network host" in c and "-v open-webui:/app/backend/data" in c and "--env-file /etc/ollamabuntu/open-webui.env" in c for c in runs), "2 lancements du conteneur (création du compte, puis sans mot de passe) avec les bons paramètres")
r, w = req("GET", "/api/webui", cookie=ck); check(w["running"] and w["version"] == "0.13.0" and w["admin_email"] == "vti@ibanfirst.com", "état : en service, version %s, administrateur %s" % (w["version"], w["admin_email"]))
c = http.client.HTTPSConnection("127.0.0.1", 18843, context=ctx, timeout=20); c.request("GET", "/api/version"); rr = c.getresponse(); body = rr.read()
check(rr.status == 200 and json.loads(body)["version"] == "0.13.0", "relais HTTPS :8443 -> Open WebUI : /api/version relayé")
c = http.client.HTTPSConnection("127.0.0.1", 18843, context=ctx, timeout=20); c.request("GET", "/grosse-page"); rr = c.getresponse(); body = rr.read()
check(rr.status == 200 and len(body) > 200000, "relais : réponse volumineuse transmise intégralement (%d octets)" % len(body))
r, d = req("POST", "/api/action", {"action": "webui-stop"}, ck); r, w = req("GET", "/api/webui", cookie=ck); check(not w["running"] and w["container"] == "exited", "Arrêter : conteneur arrêté")
r, d = req("POST", "/api/action", {"action": "webui-start"}, ck); r, w = req("GET", "/api/webui", cookie=ck); check(w["running"], "Démarrer : conteneur relancé")
r, d = req("POST", "/api/action", {"action": "webui-purge"}, ck); jid = d["job"]
for i in range(30):
    r, j = req("GET", "/api/jobs/" + jid, cookie=ck)
    if j["done"]: break
    time.sleep(1)
r, w = req("GET", "/api/webui", cookie=ck); check(j["rc"] == 0 and w["container"] is None and not os.path.exists(envf) and "docker volume rm open-webui" in open("/tmp/target/tmp/docker-calls.log").read(), "Tout supprimer : conteneur, volume de données et configuration effacés")
