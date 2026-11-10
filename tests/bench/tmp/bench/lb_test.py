import json, ssl, http.client, os, sys, time, subprocess, shutil, stat
T = "/tmp/target"; M = T + "/tmp/member"; R = T + "/tmp/rt-etc"; n = 0
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
procs = []
def stop_all():
    for p in procs:
        if p.poll() is None: p.terminate()
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: stop_all(); sys.exit(1)
class C:
    def __init__(s, port): s.port, s.cookie = port, {}
    def api(s, method, path, body=None, headers=None, timeout=120):
        c = http.client.HTTPSConnection("127.0.0.1", s.port, context=ctx, timeout=timeout); h = {"X-OB": "1", "Content-Type": "application/json"}
        if s.cookie: h["Cookie"] = "; ".join("%s=%s" % kv for kv in s.cookie.items())
        h.update(headers or {}); c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
        for k, v in r.getheaders():
            if k.lower() == "set-cookie": kv = v.split(";")[0].split("=", 1); s.cookie[kv[0]] = kv[1]
        try: d = json.loads(raw.splitlines()[0] if raw.strip() else b"{}")
        except ValueError: d = {}
        return r.status, d, r
def chroot_py(args, env, log):
    base = ["chroot", "--userspec=%s" % env.pop("_user", "root"), T, "/usr/bin/env", "-i", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8"]
    p = subprocess.Popen(base + ["%s=%s" % kv for kv in env.items()] + args, stdout=open(log, "w"), stderr=subprocess.STDOUT); procs.append(p); return p
shutil.rmtree(M, ignore_errors=True); os.makedirs(M + "/etc"); os.makedirs(M + "/state")
shutil.copy(T + "/etc/ollamabuntu/users.json", M + "/etc/users.json"); open(M + "/etc/ollama.env", "w").write("OLLAMA_NO_CLOUD=1\n")
for f in ("fleet.json", "fleet-routes.json"):
    if os.path.exists(T + "/etc/ollamabuntu/" + f): os.remove(T + "/etc/ollamabuntu/" + f)
member = chroot_py(["python3", "/usr/local/lib/ollamabuntu/admin/server.py"], {"OB_ETC": "/tmp/member/etc", "OB_STATE": "/tmp/member/state", "OB_HTTPS_PORT": "18444", "OB_HTTP_PORT": "0",
    "OB_OLLAMA_MAIN": "127.0.0.1:11434", "OB_NFT": "/usr/local/bin/nft-stub", "OB_PCI_ROOT": "/tmp/gpufake/pci", "OB_OLLAMA_LOG": "/tmp/gpufake/ollama.log"}, "/tmp/member.log")
time.sleep(3)
P, S = C(18443), C(18444)
P.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"}); S.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
FP = S.api("GET", "/api/fleet/member")[1]["fingerprint"]; MT = S.api("POST", "/api/fleet/member/create", {"name": "Console principale"})[1]["token"]
s, d, _ = P.api("POST", "/api/fleet/servers/add", {"name": "GPU-Lyon-02", "url": "https://127.0.0.1:18444", "token": MT, "fingerprint": FP}); SID = d["id"]
ok(s == 200, "serveur géré ajouté à la console principale")
s, d, _ = P.api("POST", "/api/fleet/servers/route", {"id": SID, "enabled": True})
fl = json.load(open(T + "/etc/ollamabuntu/fleet.json"))["servers"][0]; RT = fl.get("route_token", "")
ok(s == 200 and RT.startswith("obr_") and RT != MT, "répartition activée : jeton de routage dédié reçu (%s…), distinct du jeton de gestion" % RT[:8])
mem = json.load(open(M + "/etc/fleet-member.json"))["consoles"]
ok(any(c.get("scope") == "route" and c.get("parent") for c in mem) and RT not in json.dumps(mem), "serveur géré : jeton de routage rattaché à la console principale, empreinte seule conservée")
ok(C(18444).api("GET", "/api/fleet/status", headers={"Authorization": "Bearer " + RT})[0] == 401, "jeton de routage : aucun accès à l'état ni aux actions (401)")
ok(C(18444).api("GET", "/api/fleet/ollama/api/tags", headers={"Authorization": "Bearer " + MT})[0] == 401, "jeton de gestion : aucun accès aux modèles (401)")
ok(C(18444).api("POST", "/api/fleet/ollama/api/pull", {"model": "x"}, headers={"Authorization": "Bearer " + RT})[0] == 403, "jeton de routage : téléchargement de modèle refusé (403, utilisation et consultation seulement)")
s, d, r = C(18444).api("POST", "/api/fleet/ollama/api/generate", {"model": "ob-tiny", "prompt": "Bonjour", "stream": False, "options": {"num_predict": 6}}, headers={"Authorization": "Bearer " + RT})
ok(s == 200 and "response" in d and r.getheader("X-OllamaBuntu-Node"), "relais du serveur géré : génération réelle via son routeur local (nœud %s)" % r.getheader("X-OllamaBuntu-Node"))
t0 = time.time()
while time.time() - t0 < 30:
    try:
        rt = json.load(open(T + "/etc/ollamabuntu/fleet-routes.json"))
        if rt["servers"] and rt["servers"][0]["online"]: break
    except (OSError, ValueError, KeyError, IndexError): pass
    time.sleep(0.5)
st = os.stat(T + "/etc/ollamabuntu/fleet-routes.json"); raw = open(T + "/etc/ollamabuntu/fleet-routes.json").read()
ok(oct(st.st_mode & 0o777) == "0o640" and RT in raw and MT not in raw, "fichier de routes du routeur : 0640, jeton de routage seul (jamais le jeton de gestion)")
ok("ob-tiny:latest" in {m["name"] for m in rt["servers"][0]["models"]}, "modèles du serveur géré connus du routeur (%d)" % len(rt["servers"][0]["models"]))
# routeur réel (utilisateur ollama) sur une copie modifiable des routes
shutil.rmtree(R, ignore_errors=True); os.makedirs(R); shutil.copy(T + "/etc/ollamabuntu/fleet-routes.json", R + "/fleet-routes.json"); os.chmod(R, 0o755); os.chmod(R + "/fleet-routes.json", 0o644)
open(R + "/balance.json", "w").write('{"strategy": "warm"}'); os.chmod(R + "/balance.json", 0o644)   # ces scénarios fixent les charges à la main : seule la stratégie « modèle chargé » en tient compte
def routes_edit(f):
    d = json.load(open(R + "/fleet-routes.json")); f(d); json.dump(d, open(R + "/fleet-routes.json", "w")); t = time.time() + 1; os.utime(R + "/fleet-routes.json", (t, t))
def router(port, extra=None):
    env = {"_user": "ollama", "OB_ETC": "/tmp/rt-etc", "OB_MAIN": "127.0.0.1:11434", "OB_ROUTER_LISTEN": "127.0.0.1:%d" % port, "OB_ROUTER_USAGE": "/tmp/rt-usage-%d.json" % port}
    env.update(extra or {}); return chroot_py(["python3", "/usr/local/lib/ollamabuntu/router.py"], env, "/tmp/router-%d.log" % port)
def gen(port, model="ob-tiny", stream=False):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    c.request("POST", "/api/generate", json.dumps({"model": model, "prompt": "Bonjour", "stream": stream, "options": {"num_predict": 12}})); r = c.getresponse()
    if stream:
        t0 = time.time(); first = r.readline(); tf = time.time() - t0; rest = r.read().splitlines(); return r.status, r.getheader("X-OllamaBuntu-Instance"), 1 + len(rest), tf
    return r.status, r.getheader("X-OllamaBuntu-Instance"), json.loads(r.read() or b"{}")
r1 = router(18434); time.sleep(2)
routes_edit(lambda d: (d["local"].update(load=90.0, loaded=[]), d["servers"][0].update(load=10.0, loaded=[])))
s, inst, d = gen(18434); ok(s == 200 and inst == "serveur:GPU-Lyon-02", "stratégie « modèle chargé » : ce serveur chargé à 90 %, GPU-Lyon-02 à 10 % : requête envoyée à GPU-Lyon-02 (génération réelle)")
routes_edit(lambda d: (d["local"].update(load=5.0), d["servers"][0].update(load=95.0)))
s, inst, d = gen(18434); ok(s == 200 and inst == "127.0.0.1:11434", "ce serveur à 5 %, GPU-Lyon-02 à 95 % : requête traitée localement")
routes_edit(lambda d: (d["local"].update(load=5.0, loaded=[]), d["servers"][0].update(load=95.0, loaded=["ob-tiny:latest"])))
s, inst, d = gen(18434); ok(inst == "serveur:GPU-Lyon-02", "modèle déjà en mémoire sur GPU-Lyon-02 : priorité à ce serveur, malgré sa charge (pas de temps de chargement)")
routes_edit(lambda d: (d["local"].update(load=20.0, loaded=[]), d["servers"][0].update(load=20.0, loaded=[])))
insts = [gen(18434)[1] for _ in range(6)]
ok(set(insts) == {"127.0.0.1:11434", "serveur:GPU-Lyon-02"}, "charges égales : alternance entre les serveurs (%s)" % ", ".join(i.split(":")[0] if i.startswith("serveur") else "local" for i in insts))
routes_edit(lambda d: (d["local"].update(load=90.0), d["servers"][0].update(load=10.0)))
s, inst, lines, tf = gen(18434, stream=True); ok(s == 200 and inst == "serveur:GPU-Lyon-02" and lines > 2, "flux à travers deux relais (routeur principal, puis console du serveur géré) : %d morceaux" % lines)
# modèle présent uniquement sur le serveur géré
r2 = router(18435, {"OB_ROUTER_LOCAL_EXCLUDE": "ob-tiny:latest"}); time.sleep(2)
s, inst, d = gen(18435); ok(s == 200 and inst == "serveur:GPU-Lyon-02", "modèle absent de ce serveur, présent sur GPU-Lyon-02 : servi par GPU-Lyon-02")
c = http.client.HTTPConnection("127.0.0.1", 18435); c.request("GET", "/api/tags"); names = {m["name"] for m in json.loads(c.getresponse().read())["models"]}
ok("ob-tiny:latest" in names, "liste unifiée /api/tags : le modèle du parc apparaît pour les clients (Open WebUI...)")
c = http.client.HTTPConnection("127.0.0.1", 18435); c.request("GET", "/v1/models"); ids = {m["id"] for m in json.loads(c.getresponse().read())["data"]}
ok("ob-tiny:latest" in ids, "liste unifiée /v1/models (API compatible OpenAI) également")
# bascule
member.terminate(); member.wait(10); time.sleep(0.5)
s, inst, d = gen(18434); ok(s == 200 and inst == "127.0.0.1:11434", "GPU-Lyon-02 arrêté (encore marqué en ligne) : bascule automatique sur ce serveur, requête réussie")
s, inst, d = gen(18435); ok(s == 503 and "aucun serveur disponible" in d.get("error", ""), "modèle présent seulement sur le serveur arrêté : 503 explicite « %s »" % d.get("error", "")[:70])
routes_edit(lambda d: d["servers"][0].update(fingerprint="00" + d["servers"][0]["fingerprint"][2:]))
member = chroot_py(["python3", "/usr/local/lib/ollamabuntu/admin/server.py"], {"OB_ETC": "/tmp/member/etc", "OB_STATE": "/tmp/member/state", "OB_HTTPS_PORT": "18444", "OB_HTTP_PORT": "0",
    "OB_OLLAMA_MAIN": "127.0.0.1:11434", "OB_NFT": "/usr/local/bin/nft-stub", "OB_PCI_ROOT": "/tmp/gpufake/pci", "OB_OLLAMA_LOG": "/tmp/gpufake/ollama.log"}, "/tmp/member.log"); time.sleep(3)
s, inst, d = gen(18435); ok(s == 503 and "certificat inattendu pour GPU-Lyon-02" in open("/tmp/router-18435.log").read(), "certificat différent de l'empreinte approuvée : serveur écarté (aucune requête envoyée)")
s, d, _ = P.api("POST", "/api/fleet/servers/route", {"id": SID, "enabled": False}); time.sleep(1)
mem = json.load(open(M + "/etc/fleet-member.json"))["consoles"]; routes = json.load(open(T + "/etc/ollamabuntu/fleet-routes.json"))
ok(s == 200 and not any(c.get("scope") == "route" for c in mem) and routes["servers"] == [], "répartition désactivée : jeton de routage révoqué sur le serveur géré, retiré des routes")
stop_all()
