import hashlib, http.client, json, os, ssl, subprocess, sys, time
E = "/tmp/rta/etc"; NET = "192.0.2.2"; n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
H = lambda k: hashlib.sha256(k.encode()).hexdigest()
KL, KF = "ob_limitee_" + "x" * 30, "ob_complete_" + "y" * 30
pub = {"enabled": True, "port": 18600, "tls": True, "auth": True, "allow": [], "anonymous": {"perms": [], "models": []},
       "keys": [{"id": "kl", "name": "Appli limitée", "hash": H(KL), "perms": ["inference", "read"], "models": [], "deny": ["vision", "audio", "tools"], "enabled": True},
                {"id": "kf", "name": "Appli complète", "hash": H(KF), "perms": ["inference", "read"], "models": [], "enabled": True}]}
json.dump(pub, open(E + "/publication.json", "w")); json.dump({"pools": []}, open(E + "/pools.json", "w"))
if os.path.exists(E + "/ai-policy.json"): os.remove(E + "/ai-policy.json")
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
def req(method, path, body=None, key=None, local=False):
    c = http.client.HTTPConnection("127.0.0.1", 18434, timeout=20) if local else http.client.HTTPSConnection(NET, 18600, context=ctx, timeout=20)
    h = {"Content-Type": "application/json"}
    if key: h["Authorization"] = "Bearer " + key
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
    return r.status, json.loads(raw.splitlines()[0] if raw.strip() else b"{}")
ups = subprocess.Popen([sys.executable, "/tmp/rta/upstream.py", "11400"])
rt = subprocess.Popen([sys.executable, "/home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/router.py"], env=dict(os.environ, OB_ETC=E, OB_ROUTER_LISTEN="127.0.0.1:18434", OB_ROUTER_USAGE="/tmp/rta/state/usage.json"), stdout=subprocess.DEVNULL)
time.sleep(1.5)
try:
    s, d = req("POST", "/api/chat", {"model": "gpt-oss:120b-cloud", "messages": []}, local=True)
    ok(s == 403 and "cloud" in d["error"], "par défaut, modèle « gpt-oss:120b-cloud » refusé même en accès local : « %s »" % d["error"][:80])
    s, d = req("POST", "/api/chat", {"model": "kimi-k2:cloud"}, local=True); ok(s == 403, "modèle « kimi-k2:cloud » refusé")
    for p in ("/api/web_search", "/api/web_fetch", "/api/experimental/web_search", "/api/me"):
        s, d = req("POST", p, {"query": "x"}, local=True); ok(s == 403, "%s (fonction cloud d'Ollama) refusé" % p)
    s, d = req("POST", "/api/chat", {"model": "llama3.2:3b"}, local=True); ok(s == 200, "modèle local : autorisé")
    json.dump({"cloud": True}, open(E + "/ai-policy.json", "w")); time.sleep(0.2)
    s, d = req("POST", "/api/chat", {"model": "kimi-k2:cloud"}, local=True); s2, _ = req("POST", "/api/web_search", {"query": "x"}, local=True)
    ok(s == 200 and s2 == 200, "politique « cloud autorisé » : modèle cloud et recherche web acceptés (relu à chaud)")
    json.dump({"cloud": False}, open(E + "/ai-policy.json", "w")); time.sleep(0.2)
    img = {"model": "llama3.2:3b", "messages": [{"role": "user", "content": "décris", "images": ["iVBORw0KGgo="]}]}
    s, d = req("POST", "/api/chat", img, key=KL); ok(s == 403 and "images" in d["error"], "clé limitée : image (format Ollama) refusée « %s »" % d["error"])
    oai = {"model": "llama3.2:3b", "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}]}
    s, d = req("POST", "/v1/chat/completions", oai, key=KL); ok(s == 403, "clé limitée : image (format OpenAI) refusée")
    anth = {"model": "llama3.2:3b", "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "data": "AA"}}]}]}
    s, d = req("POST", "/v1/messages", anth, key=KL); ok(s == 403, "clé limitée : image (format Anthropic /v1/messages) refusée")
    s, d = req("POST", "/v1/audio/speech", {"model": "x", "input": "bonjour"}, key=KL); ok(s == 403 and "audio" in d["error"], "clé limitée : synthèse vocale refusée")
    s, d = req("POST", "/api/chat", {"model": "llama3.2:3b", "messages": [], "tools": [{"type": "function", "function": {"name": "f"}}]}, key=KL)
    ok(s == 403 and "outils" in d["error"], "clé limitée : appel d'outils refusé « %s »" % d["error"])
    s, d = req("POST", "/api/chat", {"model": "llama3.2:3b", "messages": [{"role": "user", "content": "bonjour"}]}, key=KL); ok(s == 200, "clé limitée : texte simple autorisé")
    s, d = req("POST", "/api/chat", img, key=KF); s2, _ = req("POST", "/api/chat", {"model": "llama3.2:3b", "tools": [{"type": "function"}]}, key=KF)
    ok(s == 200 and s2 == 200, "clé sans restriction : image et outils autorisés")
finally:
    rt.terminate(); ups.terminate()
