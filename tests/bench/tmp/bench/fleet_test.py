import json, ssl, http.client, os, sys, time, subprocess, shutil
T = "/tmp/target"; M = T + "/tmp/member"; n = 0
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: stop_member(); sys.exit(1)
class Client:
    def __init__(self, port): self.port, self.cookie = port, {}
    def api(self, method, path, body=None, headers=None, timeout=60):
        c = http.client.HTTPSConnection("127.0.0.1", self.port, context=ctx, timeout=timeout); h = {"X-OB": "1", "Content-Type": "application/json"}
        if self.cookie: h["Cookie"] = "; ".join("%s=%s" % kv for kv in self.cookie.items())
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
        for k, v in r.getheaders():
            if k.lower() == "set-cookie": kv = v.split(";")[0].split("=", 1); self.cookie[kv[0]] = kv[1]
        return r.status, json.loads(raw or b"{}")
member = None
def start_member():
    global member
    member = subprocess.Popen(["chroot", T, "/usr/bin/env", "-i", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8",
        "OB_ETC=/tmp/member/etc", "OB_STATE=/tmp/member/state", "OB_HTTPS_PORT=18444", "OB_HTTP_PORT=0", "OB_OLLAMA_MAIN=127.0.0.1:11434",
        "OB_NFT=/usr/local/bin/nft-stub", "OB_PCI_ROOT=/tmp/gpufake/pci", "OB_OLLAMA_LOG=/tmp/gpufake/ollama.log",
        "python3", "/usr/local/lib/ollamabuntu/admin/server.py"], stdout=open("/tmp/member.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(40):
        try: Client(18444).api("GET", "/api/ping"); return
        except OSError: time.sleep(0.3)
def stop_member():
    if member and member.poll() is None:
        member.terminate(); member.wait(10)
shutil.rmtree(M, ignore_errors=True); os.makedirs(M + "/etc"); os.makedirs(M + "/state")
shutil.copy(T + "/etc/ollamabuntu/users.json", M + "/etc/users.json")
open(M + "/etc/ollama.env", "w").write("OLLAMA_NO_CLOUD=1\n")
for f in ("fleet.json",):
    if os.path.exists(T + "/etc/ollamabuntu/" + f): os.remove(T + "/etc/ollamabuntu/" + f)
start_member()
P, S = Client(18443), Client(18444)
P.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"}); S.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
s, mv = S.api("GET", "/api/fleet/member"); FP = mv["fingerprint"]
ok(s == 200 and FP and len(FP) == 95, "serveur géré : empreinte de son certificat affichée (%s…)" % FP[:23])
s, d = S.api("POST", "/api/fleet/member/create", {"name": "Console principale Paris"}); TOKEN = d.get("token", "")
ok(s == 200 and TOKEN.startswith("obf_") and len(TOKEN) > 40, "console principale autorisée : jeton %s… généré, affiché une seule fois" % TOKEN[:10])
ok(TOKEN not in open(M + "/etc/fleet-member.json").read() and oct(os.stat(M + "/etc/fleet-member.json").st_mode & 0o777) == "0o600", "serveur géré : seule l'empreinte du jeton est conservée (fichier 0600)")
s, pr = P.api("POST", "/api/fleet/servers/probe", {"url": "https://127.0.0.1:18444"})
ok(s == 200 and pr["fingerprint"] == FP, "console principale : vérification du serveur, empreinte identique à celle affichée sur le serveur")
s, d = P.api("POST", "/api/fleet/servers/add", {"name": "GPU-Paris-01", "url": "https://127.0.0.1:18444", "token": "obf_faux" + "x" * 40, "fingerprint": FP})
ok(s == 400 and "jeton refusé" in d["error"], "ajout avec un mauvais jeton : refusé « %s »" % d["error"])
s, d = P.api("POST", "/api/fleet/servers/add", {"name": "GPU-Paris-01", "url": "https://127.0.0.1:18444", "token": TOKEN, "fingerprint": FP})
ok(s == 200, "serveur ajouté avec le bon jeton et l'empreinte vérifiée")
fl = json.load(open(T + "/etc/ollamabuntu/fleet.json"))
ok(fl["servers"][0]["token"] == TOKEN and oct(os.stat(T + "/etc/ollamabuntu/fleet.json").st_mode & 0o777) == "0o600", "console principale : jeton conservé dans un fichier réservé à root (0600)")
s, v = P.api("GET", "/api/fleet/servers"); sv = v["servers"][0]
ok(sv["state"] == "en ligne" and "token" not in sv and sv["data"]["version"] and sv["data"]["hostname"], "état collecté : « en ligne », %s, version %s (jeton jamais renvoyé au navigateur)" % (sv["data"]["hostname"], sv["data"]["version"]))
ok("gpu_live" in sv["data"] and "models" in sv["data"] and "firewall_active" in sv["data"] and "cpu" in sv["data"], "résumé : charge GPU, modèles (%d), pare-feu, processeur, mémoire, disque" % sv["data"]["models"]["count"])
open(T + "/tmp/systemctl-calls.log", "w").close()
s, d = P.api("POST", "/api/fleet/servers/action", {"id": sv["id"], "action": "restart-ollama"})
ok(s == 200 and "restart ollama.service" in open(T + "/tmp/systemctl-calls.log").read(), "action à distance : redémarrage d'Ollama exécuté sur le serveur géré")
s, d = P.api("POST", "/api/fleet/servers/action", {"id": sv["id"], "action": "apt-refresh"})
ok(s == 200 and str(d["result"].get("job", "")).endswith("apt-refresh"), "action à distance : recherche des mises à jour mise en file sur le serveur géré (%s)" % d["result"].get("job"))
s, d = P.api("POST", "/api/fleet/servers/action", {"id": sv["id"], "action": "reboot"})
ok(s == 400, "action hors liste (redémarrage du serveur) : refusée")
s, d = Client(18444).api("GET", "/api/fleet/status"); ok(s == 401, "accès direct au serveur géré sans jeton : 401")
s, d = Client(18444).api("GET", "/api/fleet/status", headers={"Authorization": "Bearer " + TOKEN}); ok(s == 200, "accès direct avec le jeton : 200 (état seulement)")
s, d = Client(18444).api("GET", "/api/users", headers={"Authorization": "Bearer " + TOKEN}); ok(s == 401, "le jeton ne donne accès à rien d'autre (comptes : 401)")
codes = [Client(18444).api("GET", "/api/fleet/status", headers={"Authorization": "Bearer faux%d" % i})[0] for i in range(11)]
ok(codes[-1] == 429, "anti-force brute : après 10 essais de jetons faux, 429 (%s)" % codes[-3:])
time.sleep(0.2)
# changement de certificat
stop_member(); os.remove(M + "/etc/tls/cert.pem"); os.remove(M + "/etc/tls/key.pem"); start_member()
s, mv2 = S.api("GET", "/api/fleet/member") if False else (None, None)
S = Client(18444); S.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"}); FP2 = S.api("GET", "/api/fleet/member")[1]["fingerprint"]
t0 = time.time()
while time.time() - t0 < 20 and P.api("GET", "/api/fleet/servers")[1]["servers"][0]["state"] != "certificat changé": time.sleep(0.5)
sv = P.api("GET", "/api/fleet/servers")[1]["servers"][0]
ok(sv["state"] == "certificat changé" and sv["new_fingerprint"] == FP2 and FP2 != FP, "certificat du serveur changé : connexion refusée, nouvelle empreinte présentée (%s…)" % FP2[:23])
ok(P.api("POST", "/api/fleet/servers/repin", {"id": sv["id"], "fingerprint": FP})[0] == 400, "approbation avec une autre empreinte : refusée")
s, d = P.api("POST", "/api/fleet/servers/repin", {"id": sv["id"], "fingerprint": FP2}); sv = P.api("GET", "/api/fleet/servers")[1]["servers"][0]
ok(s == 200 and sv["state"] == "en ligne", "nouveau certificat approuvé : de nouveau « en ligne »")
stop_member(); t0 = time.time()
while time.time() - t0 < 20 and P.api("GET", "/api/fleet/servers")[1]["servers"][0]["state"] != "hors ligne": time.sleep(0.5)
ok(P.api("GET", "/api/fleet/servers")[1]["servers"][0]["state"] == "hors ligne", "serveur arrêté : « hors ligne » (dernières données conservées)")
start_member(); S = Client(18444); S.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
cid = S.api("GET", "/api/fleet/member")[1]["consoles"][0]["id"]; S.api("POST", "/api/fleet/member/revoke", {"id": cid}); t0 = time.time()
while time.time() - t0 < 20 and P.api("GET", "/api/fleet/servers")[1]["servers"][0]["state"] != "jeton refusé": time.sleep(0.5)
ok(P.api("GET", "/api/fleet/servers")[1]["servers"][0]["state"] == "jeton refusé", "accès révoqué sur le serveur géré : « jeton refusé » sur la console principale")
s, d = P.api("POST", "/api/fleet/servers/remove", {"id": sv["id"]}); ok(s == 200 and P.api("GET", "/api/fleet/servers")[1]["servers"] == [], "serveur retiré de la console principale")
stop_member()
