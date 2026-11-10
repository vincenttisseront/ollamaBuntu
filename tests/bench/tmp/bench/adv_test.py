import json, ssl, http.client, os, sys, time
T = "/tmp/target"; E = T + "/etc/ollamabuntu"; n = 0
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE; cookie = {}
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
def api(method, path, body=None, timeout=300):
    c = http.client.HTTPSConnection("127.0.0.1", 18443, context=ctx, timeout=timeout); h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = "; ".join("%s=%s" % kv for kv in cookie.items())
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
    for k, v in r.getheaders():
        if k.lower() == "set-cookie": kv = v.split(";")[0].split("=", 1); cookie[kv[0]] = kv[1]
    try: return r.status, json.loads(raw.splitlines()[-1] if raw.strip() else b"{}")
    except ValueError: return r.status, {"raw": raw[:200]}
def ollama(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", 11434, timeout=120); c.request(method, path, body=json.dumps(body) if body else None); r = c.getresponse(); return r.status, json.loads(r.read() or b"{}")
api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
# ---------- modèles personnalisés (vrai Ollama)
s, d = api("POST", "/api/models/custom/create", {"name": "assistant-rh", "base": "ob-tiny", "system": "Tu es l'assistant RH. Réponds en français.", "params": {"temperature": 0.2, "num_ctx": 2048}})
ok(s == 200 and d["name"] == "assistant-rh:latest", "modèle personnalisé créé : %s" % d.get("name", d))
s, show = ollama("POST", "/api/show", {"model": "assistant-rh"})
ok("Tu es l'assistant RH" in show.get("system", "") and "temperature" in show.get("parameters", "") and "2048" in show.get("parameters", ""),
   "Ollama confirme le prompt système et les paramètres (« %s »)" % " ".join(show.get("parameters", "").split()))
ok(api("POST", "/api/models/custom/create", {"name": "x", "base": "ob-tiny", "params": {"temperature": 5}})[0] == 400, "température hors limites (5) : refusée")
s, d = api("POST", "/api/models/custom/create", {"name": "assistant-rh", "base": "ob-tiny", "system": "Réponds en anglais.", "params": {"temperature": 0.7}})
s2, show = ollama("POST", "/api/show", {"model": "assistant-rh"})
ok(s == 200 and show.get("system") == "Réponds en anglais." and "0.7" in show.get("parameters", ""), "mise à jour : nouveau prompt et température 0.7 pris en compte")
s, lst = api("GET", "/api/models/custom")
ok([c["name"] for c in lst["custom"]] == ["assistant-rh:latest"] and lst["custom"][0]["base"] == "ob-tiny:latest", "liste des modèles personnalisés : assistant-rh (base ob-tiny)")
# ---------- préchargement (vrai Ollama)
s, d = api("POST", "/api/models/preload", {"models": ["ob-tiny"]})
t0 = time.time(); exp = None
while time.time() - t0 < 60:
    ps = {m["name"]: m for m in ollama("GET", "/api/ps")[1].get("models", [])}
    if "ob-tiny:latest" in ps and ps["ob-tiny:latest"]["expires_at"][:4] > "2100": exp = ps["ob-tiny:latest"]["expires_at"]; break
    time.sleep(1)
ok(exp is not None, "préchargement : ob-tiny chargé par Ollama sans échéance (expires_at %s) en %.0f s" % ((exp or "?")[:10], time.time() - t0))
s, lst = api("GET", "/api/models/custom"); ok(lst["preload"] == ["ob-tiny:latest"] and lst["preload_state"].get("ob-tiny:latest") == "chargé", "état affiché : « chargé »")
s, d = api("POST", "/api/models/custom/delete", {"name": "assistant-rh:latest"})
tags = {m["name"] for m in ollama("GET", "/api/tags")[1]["models"]}
ok(s == 200 and "assistant-rh:latest" not in tags and "ob-tiny:latest" in tags, "suppression : modèle personnalisé retiré, modèle de base conservé")
api("POST", "/api/models/preload", {"models": []})
# ---------- politique d'usage de l'IA
open(E + "/open-webui.env", "w").write("WEBUI_NAME=test\n")
s, p = api("GET", "/api/security/policy")
ok(len(p["webui_features"]) == 7 and p["webui_deployed"], "politique : 7 fonctions d'Open WebUI réglables, Open WebUI détecté")
s, d = api("POST", "/api/security/policy", {"cloud": False, "webui": {"web_search": True}, "webui_locked": True})
envf = open(E + "/ollama.env").read(); wenv = open(E + "/open-webui-policy.env").read()
ok(s == 200 and "OLLAMA_NO_CLOUD=1" in envf, "fonctions cloud coupées : OLLAMA_NO_CLOUD=1 dans la configuration d'Ollama")
ok("ENABLE_WEB_SEARCH=true" in wenv and "ENABLE_CODE_INTERPRETER=false" in wenv and "ENABLE_PERSISTENT_CONFIG=false" in wenv, "Open WebUI : recherche web autorisée, interpréteur de code refusé, configuration verrouillée")
ok(d.get("job") and d["job"].endswith("webui-apply"), "Open WebUI déployé : tâche « appliquer la politique » mise en file (%s)" % d.get("job"))
pol = json.load(open(E + "/ai-policy.json")); ok(pol["cloud"] is False and pol["webui"]["web_search"] is True, "ai-policy.json (lu par le routeur) à jour")
if os.path.exists(T + "/tmp/nft-loads.log"): os.remove(T + "/tmp/nft-loads.log")
s, d = api("POST", "/api/security/policy", {"ollama_internet": False})
time.sleep(1); rules = open(T + "/tmp/nft-loaded").read()
ok("meta skuid" in rules and "Ollama : pas d'accès Internet" in rules, "accès Internet d'Ollama coupé : règle de sortie du compte ollama chargée (validée par nft -c)")
open(T + "/tmp/nft-loads.log", "w").close()
s, d = api("POST", "/api/models/pull", {"name": "modele-inexistant-test:1b"}, timeout=120)
loads = open(T + "/tmp/nft-loads.log").read().split()
ok(loads.count("CHARGE") >= 2 and "sans-blocage-ollama" in loads and loads[-1] == "avec-blocage-ollama",
   "téléchargement depuis la console : accès ouvert le temps du téléchargement, puis refermé (%s)" % " -> ".join(x for x in loads if x != "CHARGE"))
s, d = api("POST", "/api/security/policy", {"ollama_internet": True, "webui_locked": False}); time.sleep(1)
ok("meta skuid" not in open(T + "/tmp/nft-loaded").read(), "accès Internet rétabli : règle retirée")
# ---------- clés d'API : restrictions
s, d = api("POST", "/api/publication/keys/create", {"name": "Appli sans images", "perms": ["inference"], "deny": ["vision", "tools", "inconnu"]})
ok(s == 200 and d["key"]["deny"] == ["vision", "tools"], "clé d'API avec restrictions : %s (valeur inconnue ignorée)" % d["key"]["deny"])
api("POST", "/api/publication/keys/delete", {"id": d["key"]["id"]})
