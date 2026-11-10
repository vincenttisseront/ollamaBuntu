import json, ssl, http.client, os, sys, time, subprocess, shutil, threading
T = "/tmp/target"; M = T + "/tmp/member"; LOG = T + "/tmp/reqs/requests.jsonl"; n = 0
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
    def api(s, method, path, body=None, timeout=300):
        c = http.client.HTTPSConnection("127.0.0.1", s.port, context=ctx, timeout=timeout); h = {"X-OB": "1", "Content-Type": "application/json"}
        if s.cookie: h["Cookie"] = "; ".join("%s=%s" % kv for kv in s.cookie.items())
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
        for k, v in r.getheaders():
            if k.lower() == "set-cookie": kv = v.split(";")[0].split("=", 1); s.cookie[kv[0]] = kv[1]
        try: d = json.loads(raw.splitlines()[0] if raw.strip() else b"{}")
        except ValueError: d = {}
        return r.status, d
def chroot_py(args, env, log):
    env = dict(env); base = ["chroot", "--userspec=%s" % env.pop("_user", "root"), T, "/usr/bin/env", "-i", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8"]
    p = subprocess.Popen(base + ["%s=%s" % kv for kv in env.items()] + args, stdout=open(log, "w"), stderr=subprocess.STDOUT); procs.append(p); return p
MEMBER_ENV = {"OB_ETC": "/tmp/member/etc", "OB_STATE": "/tmp/member/state", "OB_HTTPS_PORT": "18444", "OB_HTTP_PORT": "0", "OB_OLLAMA_MAIN": "127.0.0.1:11434", "OB_NFT": "/usr/local/bin/nft-stub", "OB_PCI_ROOT": "/tmp/gpufake/pci", "OB_OLLAMA_LOG": "/tmp/gpufake/ollama.log"}
def rq(path, body, port=18434):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=120); c.request("POST", path, json.dumps(body)); r = c.getresponse(); r.read(); return r.status, r.getheader("X-OllamaBuntu-Instance")
def gen(prompt="Bonjour", n_pred=6): return rq("/api/generate", {"model": "ob-tiny", "prompt": prompt, "stream": False, "options": {"num_predict": n_pred}})
def log_lines():
    try: return [json.loads(l) for l in open(LOG, "rb").read().splitlines() if l.strip()]
    except OSError: return []
def tally(xs): return {k: xs.count(k) for k in sorted(set(xs))}
LOCAL, REMOTE = "127.0.0.1:11434", "serveur:GPU-Lyon-02"
shutil.rmtree(M, ignore_errors=True); os.makedirs(M + "/etc"); os.makedirs(M + "/state")
shutil.copy(T + "/etc/ollamabuntu/users.json", M + "/etc/users.json"); open(M + "/etc/ollama.env", "w").write("OLLAMA_NO_CLOUD=1\n")
for f in ("fleet.json", "fleet-routes.json", "balance.json", "request-log.json"):
    if os.path.exists(T + "/etc/ollamabuntu/" + f): os.remove(T + "/etc/ollamabuntu/" + f)
for f in ("requests.jsonl", "requests.jsonl.1"):
    if os.path.exists(T + "/tmp/reqs/" + f): os.remove(T + "/tmp/reqs/" + f)
member = chroot_py(["python3", "/usr/local/lib/ollamabuntu/admin/server.py"], MEMBER_ENV, "/tmp/member.log")
router = chroot_py(["python3", "/usr/local/lib/ollamabuntu/router.py"], {"_user": "ollama", "OB_ETC": "/etc/ollamabuntu", "OB_MAIN": "127.0.0.1:11434", "OB_ROUTER_LISTEN": "127.0.0.1:18434", "OB_ROUTER_REQLOG": "/tmp/reqs/requests.jsonl", "OB_ROUTER_USAGE": "/tmp/reqs/usage.json"}, "/tmp/router-lb2.log")
time.sleep(3)
P, S = C(18443), C(18444)
P.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"}); S.api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
FP = S.api("GET", "/api/fleet/member")[1]["fingerprint"]; MT = S.api("POST", "/api/fleet/member/create", {"name": "Console principale"})[1]["token"]
s, d = P.api("POST", "/api/fleet/servers/add", {"name": "GPU-Lyon-02", "url": "https://127.0.0.1:18444", "token": MT, "fingerprint": FP}); SID = d["id"]
# ---- votre situation : serveur ajouté, répartition non activée
s, bv = P.api("GET", "/api/fleet/balance")
ok(s == 200 and bv["servers"][0]["issues"] == ["route-off"] and not bv["active"], "serveur ajouté sans activer la répartition : le diagnostic en donne la raison (%s)" % bv["servers"][0]["issues"])
ins = [gen()[1] for _ in range(6)]; ok(set(ins) == {LOCAL}, "dans cet état, les 6 requêtes restent sur ce serveur : c'est ce que vous observiez %s" % tally(ins))
# ---- répartition activée, sans aucun réglage manuel des charges
P.api("POST", "/api/fleet/servers/route", {"id": SID, "enabled": True}); t0 = time.time(); rt = {}
while time.time() - t0 < 30:
    try:
        rt = json.load(open(T + "/etc/ollamabuntu/fleet-routes.json"))
        if rt["servers"] and rt["servers"][0]["online"] and rt["servers"][0]["models"]: break
    except (OSError, ValueError, KeyError, IndexError): pass
    time.sleep(0.5)
s, bv = P.api("GET", "/api/fleet/balance")
ok(bv["servers"][0]["issues"] == [] and bv["active"] and bv["servers"][0]["common"] >= 1, "répartition activée : plus aucun obstacle, %d modèle(s) en commun" % bv["servers"][0]["common"])
ok(rt["local"]["load"] is not None and rt["servers"][0]["load"] is not None, "charges calculées par la console : ce serveur %s %%, distant %s %%" % (rt["local"]["load"], rt["servers"][0]["load"]))
ins = [gen()[1] for _ in range(8)]; t = tally(ins)
ok(set(ins) == {LOCAL, REMOTE} and min(t.values()) >= 3, "8 requêtes l'une après l'autre : réparties sur les deux serveurs %s" % t)
res = []; th = [threading.Thread(target=lambda: res.append(gen(n_pred=60)[1])) for _ in range(4)]
for x in th: x.start()
for x in th: x.join()
ok(set(res) == {LOCAL, REMOTE}, "4 requêtes simultanées : les deux serveurs sont sollicités %s" % tally(res))
time.sleep(6); s, bv = P.api("GET", "/api/fleet/balance")
ok(bv["servers"][0]["served"] == 6 and bv["local"]["served"] == 12 and bv["servers"][0]["last"], "compteurs sur 24 h d'après le journal : distant %d (4 + 2), local %d (6 avant l'activation + 4 + 2)" % (bv["servers"][0]["served"], bv["local"]["served"]))
s, d = P.api("POST", "/api/fleet/balance/test", {"model": "ob-tiny"}); ok(s == 200 and d["ok"] == 4 and set(d["by"]) == {"", "GPU-Lyon-02"}, "test de répartition intégré : 4 requêtes réussies, serveurs sollicités %s" % d["by"])
# ---- stratégie
s, d = P.api("POST", "/api/fleet/balance/strategy", {"strategy": "warm"}); ok(s == 200 and json.load(open(T + "/etc/ollamabuntu/balance.json")) == {"strategy": "warm"} and P.api("GET", "/api/fleet/balance")[1]["strategy"] == "warm", "stratégie « modèle chargé » enregistrée et relue")
ok(P.api("POST", "/api/fleet/balance/strategy", {"strategy": "n'importe"})[0] == 400, "stratégie inconnue refusée (400)")
P.api("POST", "/api/fleet/balance/strategy", {"strategy": "spread"})
P.api("POST", "/api/users/create", {"user": "lucie", "password": "Lucie-2026!", "role": "utilisateur", "linux": False}); U = C(18443); U.api("POST", "/api/login", {"user": "lucie", "password": "Lucie-2026!"})
ok(U.api("POST", "/api/fleet/balance/strategy", {"strategy": "warm"})[0] == 403 and U.api("GET", "/api/fleet/balance")[0] == 403 and U.api("POST", "/api/fleet/balance/test", {"model": "ob-tiny"})[0] == 403, "simple utilisateur : stratégie, diagnostic et test refusés (403)")
# ---- extrait de la demande : désactivé par défaut
SECRET = "Résume le contrat de Mme Martin, IBAN FR7630006000011234567890189, carte 4970 1012 3456 7890, clé sk-abcdefghijklmnop1234, mail martin@exemple.fr et le reste du texte qui est long"
ok(P.api("GET", "/api/requests/settings")[1] == {"prompt_excerpt": False, "chars": 120, "days": 7}, "réglage de l'extrait : désactivé par défaut (120 caractères, 7 jours)")
gen(SECRET); last = log_lines()[-1]; raw = open(LOG).read()
ok("prompt" not in last and "FR7630" not in raw and "Martin" not in raw, "extrait désactivé : le journal ne contient aucun texte de la demande")
ok(oct(os.stat(LOG).st_mode & 0o777) == "0o600", "journal des requêtes : lisible du seul compte du routeur et de root (0600)")
s, d = P.api("POST", "/api/requests/settings", {"prompt_excerpt": True, "chars": 60}); ok(s == 200 and d["settings"]["prompt_excerpt"] is True, "extrait activé (60 caractères)")
time.sleep(0.3); gen(SECRET); last = log_lines()[-1]; raw = open(LOG).read()
bad = [x for x in ("FR7630", "4970", "abcdefghij", "martin@") if x in raw]
ok(len(last.get("prompt", "")) <= 60 and not bad and "[IBAN]" in raw, "extrait activé : %d caractères au plus, secrets masqués dans le fichier même -> « %s »" % (len(last["prompt"]), last["prompt"]))
rq("/api/chat", {"model": "ob-tiny", "messages": [{"role": "system", "content": "CONSIGNE"}, {"role": "user", "content": "Question posée dans le chat"}], "stream": False, "options": {"num_predict": 4}})
ok(log_lines()[-1]["prompt"] == "Question posée dans le chat", "/api/chat : la dernière question seulement, pas la consigne système")
s, rv = P.api("GET", "/api/requests?limit=5"); ok(rv["prompt_excerpt"] is True and rv["requests"][0]["prompt"] == "Question posée dans le chat", "console : l'extrait est renvoyé aux administrateurs")
ok(U.api("GET", "/api/requests")[0] == 403 and U.api("GET", "/api/requests/settings")[0] == 403 and U.api("POST", "/api/requests/settings", {"prompt_excerpt": False})[0] == 403 and U.api("POST", "/api/requests/clear", {})[0] == 403, "simple utilisateur : historique, réglage et effacement refusés (403)")
ok(P.api("POST", "/api/requests/settings", {"chars": 5})[0] == 400 and P.api("POST", "/api/requests/settings", {"days": 0})[0] == 400, "valeurs hors limites refusées (400)")
P.api("POST", "/api/requests/settings", {"prompt_excerpt": "oui"}); ok(P.api("GET", "/api/requests/settings")[1]["prompt_excerpt"] is False, "« oui » n'active rien : seul un vrai booléen active l'extrait")
P.api("POST", "/api/requests/settings", {"prompt_excerpt": True, "chars": 60})
# ---- conservation et effacement
uid = int(subprocess.check_output(["chroot", T, "id", "-u", "ollama"])); before = len(log_lines())
with open(LOG, "ab") as f: f.write((json.dumps({"ts": time.time() - 10 * 86400, "model": "vieux", "status": 200, "client": "local", "prompt": "très ancien"}) + "\n").encode())
P.api("POST", "/api/requests/settings", {"days": 1}); lines = log_lines(); st = os.stat(LOG)
ok(not any(l.get("model") == "vieux" for l in lines) and len(lines) == before and st.st_uid == uid and oct(st.st_mode & 0o777) == "0o600", "conservation 1 jour : la requête de 10 jours est retirée, les %d récentes restent, propriétaire et droits conservés" % len(lines))
gen("après purge"); ok(log_lines()[-1].get("prompt") == "après purge", "après la purge, le routeur continue d'écrire dans le journal")
s, _ = P.api("POST", "/api/requests/clear", {}); ok(s == 200 and os.path.getsize(LOG) == 0 and P.api("GET", "/api/requests?limit=5")[1]["requests"] == [], "effacement de l'historique : journal vide")
gen("après effacement"); ok(len(log_lines()) == 1, "après l'effacement, le routeur écrit toujours")
# ---- panne : repli sur ce serveur
member.terminate(); member.wait(10)
res = [gen()[0] for _ in range(6)]; ok(res == [200] * 6, "serveur distant arrêté : les 6 requêtes aboutissent quand même (repli sur ce serveur)")
t0 = time.time()
while time.time() - t0 < 25 and "offline" not in P.api("GET", "/api/fleet/balance")[1]["servers"][0]["issues"]: time.sleep(0.5)
ok(P.api("GET", "/api/fleet/balance")[1]["servers"][0]["issues"] == ["offline"], "diagnostic : « hors ligne » signalé")
stop_all()
