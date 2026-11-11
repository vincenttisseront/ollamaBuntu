#!/usr/bin/env python3
"""Réveil et veille du parc, côté console : réglages, réveil manuel et automatique (paquet simulé), mise en veille à distance (parc simulé),
autorisation côté serveur géré, signal du routeur, journal, routes HTTP, audit."""
import http.client, json, os, subprocess, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_STATE=os.path.join(tmp, "state"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import power, server, backup
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a, **k):
    try: f(*a, **k)
    except ValueError as e: return str(e)
    return None
os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
server.POWER_FILE = os.path.join(ETC, "power.json"); server.POWER_MEMBER = os.path.join(ETC, "power-member.json"); server.POWER_LOG = os.path.join(tmp, "state", "power-log.json")
server.ROUTER_LIMITS = os.path.join(tmp, "limits.json"); server.AUDIT_FILE = os.path.join(tmp, "audit.jsonl")
server.FLEET_ROUTES = os.path.join(ETC, "fleet-routes.json")
server.save_users({"admin": dict(server.hash_password("Secret-123"), role="admin", linux=False, rev="r0", created=1, updated=1),
                   "jean": dict(server.hash_password("Secret-456"), role="utilisateur", linux=False, rev="r1", created=1, updated=1)})
NOW = time.time()
WOL = []
power.send_wol = lambda mac, broadcast="", port=9: WOL.append((mac, broadcast)) or 102
CALLS = []; REPLY = [(200, {"ok": True})]
def fake_request(url, path, token=None, fingerprint=None, method="GET", body=None, timeout=10):
    CALLS.append((url, path, body)); return REPLY[0][0], REPLY[0][1], fingerprint
server.fleet_request = fake_request
server.read_requests = lambda n=5000: []
FP = ":".join(["AA"] * 32)

# --- réglages généraux
ok(server.power_config() == power.DEFAULTS and server.power_config()["enabled"] is False, "réglages par défaut : automatisme désactivé")
c = server.power_save({"enabled": True, "wake_after_s": 20, "keep_awake": 0}); ok(c["enabled"] and oct(os.stat(server.POWER_FILE).st_mode & 0o777) == "0o644", "enregistrés")
before = open(server.POWER_FILE).read(); ok(raises(server.power_save, {"wake_after_s": 1}) and open(server.POWER_FILE).read() == before, "réglage invalide refusé sans toucher au fichier")
open(server.POWER_FILE, "w").write("{cassé"); ok(server.power_config() == power.DEFAULTS, "fichier corrompu : valeurs par défaut")
server.power_save({"enabled": True})
ok("power.json" in backup.FILES and "power-member.json" in backup.FILES, "réglages inclus dans la sauvegarde")

# --- parc simulé
def mk(i, name, models, load=2.0, state="en ligne", route=True):
    s = {"id": i, "name": name, "url": "https://10.0.0.%s" % i, "token": "obf_" + i, "fingerprint": FP, "added": 1}
    if route: s["route_token"] = "obr_" + i
    server._fleet_state[i] = {"state": state, "data": {"cpu": {"usage": load}, "gpu_live": [], "model_tags": [{"name": m} for m in models], "jobs": [], "ollama": {"running": []}}, "checked": NOW}
    return s
fleet = [mk("1", "Alpha", ["m:1b"]), mk("2", "Beta", ["m:1b", "grand:70b"], state="hors ligne"), mk("3", "Gamma", ["rare:1b"], state="hors ligne")]
server.save_fleet(fleet)
ok(raises(server.fleet_set_power, "2", {"wake": True}) is not None and raises(server.fleet_set_power, "zz", {}) == "serveur inconnu", "réveil automatique sans MAC refusé ; serveur inconnu refusé")
p = server.fleet_set_power("2", {"mac": "3C-EC-EF-00-00-02", "wake": True, "sleep": "suspend", "idle_min": 20})
ok(p["mac"] == "3c:ec:ef:00:00:02" and server.load_fleet()[1]["power"] == p and oct(os.stat(server.FLEET_FILE).st_mode & 0o777) == "0o600", "réglages d'un serveur enregistrés dans le parc (fichier réservé)")
server.fleet_set_power("3", {"mac": "3c:ec:ef:00:00:03", "wake": True, "broadcast": "10.0.0.255"})
server.fleet_set_power("1", {"mac": "3c:ec:ef:00:00:01", "sleep": "suspend", "idle_min": 10})
v = server.power_view()
ok([s["state"] for s in v["servers"]] == ["awake", "offline", "offline"] and v["servers"][1]["power"]["mac"] == "3c:ec:ef:00:00:02" and "token" not in json.dumps(v), "vue : états, réglages, aucun jeton")

# --- signal du routeur dans fleet-routes.json
server.write_fleet_routes()
fr = json.load(open(server.FLEET_ROUTES)); byid = {s["id"]: s for s in fr["servers"]}
ok(byid["2"]["wake"] is True and byid["3"]["wake"] is True and byid["1"]["wake"] is False, "routes du routeur : serveurs réveillables signalés")
server.power_save({"enabled": False}); server.write_fleet_routes()
ok(not any(s["wake"] for s in json.load(open(server.FLEET_ROUTES))["servers"]), "automatisme désactivé : plus aucun serveur signalé réveillable")
server.power_save({"enabled": True})

# --- réveil manuel
r = server.power_wake("2", "demandé par admin")
ok(WOL == [("3c:ec:ef:00:00:02", "")] and server.power_server_state(fleet[1], time.time()) == "waking", "réveil manuel : paquet envoyé à la bonne MAC, état « en réveil »")
ev = server.power_log()[-1]; ok(ev["kind"] == "wake" and ev["server"] == "Beta" and ev["ok"] and "admin" in ev["why"], "…et consigné au journal")
nomac = mk("9", "Sans", [], route=False); saved = server.load_fleet(); server.save_fleet(saved + [nomac])
ok("MAC" in (raises(server.power_wake, "9") or ""), "réveil sans MAC : refusé")
server.save_fleet(saved)
power.send_wol = lambda mac, broadcast="", port=9: (_ for _ in ()).throw(OSError("réseau inaccessible"))
ok("réseau inaccessible" in (raises(server.power_wake, "3") or "") and server.power_log()[-1]["ok"] is False, "envoi impossible : message clair et événement en échec")
power.send_wol = lambda mac, broadcast="", port=9: WOL.append((mac, broadcast)) or 102

# --- passage automatique : file d'attente
server._power_mem.clear(); WOL.clear(); server._power_run.update(busy_since=None, last=0)
def limits(waiting=(), wake=None, age=0):
    json.dump({"t": int(time.time() - age), "waiting": list(waiting), "wake": wake or {}, "queue": {}, "active": 0}, open(server.ROUTER_LIMITS, "w"))
limits([{"who": "x", "model": "m:1b", "waited": 5}])
ok(server.power_tick() == [] and not WOL, "demande en attente depuis 5 s : rien")
limits([{"who": "x", "model": "m:1b", "waited": 40}])
d = server.power_tick()
ok(len(d) == 1 and d[0]["action"] == "wake" and d[0]["id"] == "2" and WOL == [("3c:ec:ef:00:00:02", "")], "file d'attente depuis 40 s : Beta (qui a le modèle) est réveillé ; Gamma (qui ne l'a pas) ne l'est pas")
ok("40 s" in server.power_log()[-1]["why"], "motif en clair dans le journal")
WOL.clear(); ok(server.power_tick() == [] and not WOL, "réveil en cours : pas de second paquet")
limits([{"who": "x", "model": "m:1b", "waited": 40}], age=100)
server._power_mem["2"]["wake_sent"] = time.time() - 30
ok(server.power_tick() == [], "fichier du routeur périmé (plus de 30 s) : ignoré")
# le serveur répond
server._fleet_state["2"]["state"] = "en ligne"; limits()
server.power_tick()
m = server._power_mem["2"]; ok(m.get("woke_at") and server.power_log()[-1]["kind"] == "wake-ok", "le serveur répond : événement « réveillé » et heure de réveil retenue")
# réveil sans effet
server._fleet_state["3"]["state"] = "hors ligne"; server._power_mem["3"] = {"wake_sent": time.time() - 500}
limits(); server.power_tick()
ok(server.power_log()[-1]["kind"] == "wake-failed" and server.power_log()[-1]["ok"] is False and server._power_mem["3"].get("failed"), "aucune réponse après le délai : « réveil sans effet » consigné")
nlog = len(server.power_log()); server.power_tick(); ok(len(server.power_log()) == nlog, "…une seule fois")
v = server.power_view(); ok(v["servers"][2]["failed"] is True, "…et visible dans la vue")

# --- signal « modèle absent » du routeur
server._power_mem.clear(); WOL.clear(); server._fleet_state["2"]["state"] = "hors ligne"; server._fleet_state["3"]["state"] = "hors ligne"
limits(wake={"rare:1b": time.time() - 5})
d = server.power_tick()
ok(len(d) == 1 and d[0]["id"] == "3" and WOL == [("3c:ec:ef:00:00:03", "10.0.0.255")], "modèle que seul Gamma possède : Gamma réveillé, sur son adresse de diffusion")

# --- saturation
server._power_mem.clear(); WOL.clear(); limits()
server._fleet_state["1"]["data"]["cpu"]["usage"] = 95.0
import server as S
S.gpu_metrics = lambda: []; S._metrics["samples"].clear(); S._metrics["samples"].append({"cpu": 97.0})
server._power_run["busy_since"] = None
server.power_tick(); ok(not WOL and server._power_run["busy_since"] is not None, "saturation constatée : le chronomètre démarre")
server._power_run["busy_since"] = time.time() - 120
d = server.power_tick(); ok(len(d) == 1 and d[0]["action"] == "wake" and "occupés" in d[0]["why"], "saturation depuis plus de 60 s : réveil")
server._fleet_state["1"]["data"]["cpu"]["usage"] = 2.0; S._metrics["samples"].append({"cpu": 3.0})
server._power_mem.clear(); WOL.clear(); server.power_tick(); ok(server._power_run["busy_since"] is None, "charge retombée : le chronomètre est remis à zéro")

# --- mise en veille automatique
server._fleet_state["2"]["state"] = "hors ligne"; server._fleet_state["3"]["state"] = "hors ligne"
server._power_mem.clear(); CALLS.clear(); limits()
server.power_tick(); ok("idle_since" in server._power_mem["1"] and server._power_mem["1"]["idle_since"] is not None and not CALLS, "serveur au repos : début du repos noté, pas encore de mise en veille")
server._power_mem["1"]["idle_since"] = time.time() - 3600
d = server.power_tick()
ok(len(d) == 1 and d[0]["action"] == "sleep" and CALLS and CALLS[-1][1] == "/api/fleet/action" and CALLS[-1][2] == {"action": "power-sleep", "data": {"mode": "suspend"}}, "au repos depuis 1 h (seuil 10 min) : demande de mise en veille envoyée à Alpha")
ok(server._power_mem["1"].get("slept_at") and server.power_log()[-1]["kind"] == "sleep" and "60 min" in server.power_log()[-1]["why"], "mise en veille consignée avec son motif")
server._fleet_state["1"]["state"] = "hors ligne"
ok(server.power_server_state(fleet[0], time.time()) == "asleep", "puis état « endormi » (mis en veille par la console)")
# travail récent : pas de veille
server._fleet_state["1"]["state"] = "en ligne"; server._power_mem.clear(); CALLS.clear()
server.read_requests = lambda n=5000: [{"instance": "serveur:Alpha", "ts": time.time() - 10}]
server.power_tick()
ok(server._power_mem["1"].get("idle_since") is None and not CALLS, "requête routée vers lui il y a 10 s : pas considéré au repos")
server.read_requests = lambda n=5000: []
server._fleet_state["1"]["data"]["jobs"] = [{"id": "j", "done": False}]; server.power_tick()
ok(server._power_mem["1"].get("idle_since") is None, "tâche en cours sur le serveur : pas au repos")
server._fleet_state["1"]["data"]["jobs"] = []
# refus du serveur
server._power_mem.clear(); server._power_mem["1"] = {"idle_since": time.time() - 3600}; REPLY[0] = (400, {"error": "ce serveur n'autorise pas sa mise en veille à distance"}); CALLS.clear()
ok(server.power_tick() == [] and server.power_log()[-1]["ok"] is False and "n'autorise pas" in server.power_log()[-1]["detail"], "refus du serveur : consigné en échec, aucune action comptée")
ok("autorise" in (raises(server.power_sleep, "1") or ""), "mise en veille manuelle refusée par le serveur : message du serveur repris")
REPLY[0] = (200, {"ok": True})
ok(raises(server.power_sleep, "1", "x", "hibernate") == "mode inconnu", "mode inconnu refusé")
server.fleet_set_power("1", {"mac": "3c:ec:ef:00:00:01", "sleep": "", "idle_min": 10})
server._power_mem["1"] = {"idle_since": time.time() - 3600}; CALLS.clear(); server.power_tick()
ok(not CALLS, "mise en veille désactivée pour ce serveur : jamais")
server.power_save({"enabled": False}); server.fleet_set_power("1", {"sleep": "suspend"}); server._power_mem["1"] = {"idle_since": time.time() - 3600}; server.power_tick()
ok(not CALLS, "automatisme général désactivé : aucune mise en veille, même au repos")
server.power_save({"enabled": True})

# --- côté serveur géré : autorisation et exécution
ok(server.power_member_allow() == "" and server.power_member_save({"allow": "suspend"}) == {"allow": "suspend"} and server.power_member_allow() == "suspend" and oct(os.stat(server.POWER_MEMBER).st_mode & 0o777) == "0o600", "autorisation locale enregistrée (fichier réservé)")
ok(raises(server.power_member_save, {"allow": "reboot"}) is not None, "autorisation inconnue refusée")
OUT = os.path.join(tmp, "executed"); server.POWER_SUSPEND = ["sh", "-c", 'echo "$0" > ' + OUT]
real_sleep, real_run = time.sleep, server.run
time.sleep = lambda s: real_sleep(0.05) if s == 3 else real_sleep(s)
server.run = lambda cmd, timeout=10, **kw: "yes\n" if cmd == ["systemctl", "can-suspend"] else real_run(cmd, timeout, **kw)
server.list_jobs = lambda: []
server.power_member_save({"allow": ""})
ok("n'autorise pas" in (raises(server.power_member_sleep, "suspend") or "") and not os.path.exists(OUT), "autorisation refusée : rien n'est exécuté")
server.power_member_save({"allow": "suspend"})
ok("n'autorise pas" in (raises(server.power_member_sleep, "poweroff") or ""), "autorisation « veille » : l'extinction reste refusée")
server.list_jobs = lambda: [{"id": "j", "done": False}]
ok("tâche" in (raises(server.power_member_sleep, "suspend") or "") and not os.path.exists(OUT), "tâche en cours : mise en veille refusée")
server.list_jobs = lambda: []
server.run = lambda cmd, timeout=10, **kw: "no\n" if cmd == ["systemctl", "can-suspend"] else real_run(cmd, timeout, **kw)
ok("ne prend pas en charge" in (raises(server.power_member_sleep, "suspend") or "") and not os.path.exists(OUT), "matériel sans veille (can-suspend : no) : refusée avec explication")
server.run = lambda cmd, timeout=10, **kw: "yes\n" if cmd == ["systemctl", "can-suspend"] else real_run(cmd, timeout, **kw)
server.power_member_sleep("suspend"); t0 = time.time()
while not os.path.exists(OUT) and time.time() - t0 < 5: real_sleep(0.05)
ok(os.path.exists(OUT) and open(OUT).read().strip() == "suspend", "autorisée : la commande de veille est exécutée")
os.remove(OUT); server.power_member_save({"allow": "poweroff"}); server.power_member_sleep("poweroff")
t0 = time.time()
while not os.path.exists(OUT) and time.time() - t0 < 5: real_sleep(0.05)
ok(open(OUT).read().strip() == "poweroff", "autorisation « extinction » : exécutée")
ok(server.member_action("power-sleep", {"name": "c"}, {"mode": "suspend"}) is None, "action distante « power-sleep » acceptée par le serveur géré")
real_sleep(0.3)
server.power_member_save({"allow": ""})
ok("n'autorise pas" in (raises(server.member_action, "power-sleep", {"name": "c"}, {"mode": "suspend"}) or ""), "…et refusée dès que l'autorisation est retirée")
ok("power-sleep" not in server.FLEET_ACTIONS, "l'action n'est pas dans la liste des actions de maintenance habituelles")

# --- réveil réseau d'une carte (côté serveur géré)
nics = [{"iface": "enp3s0", "mac": "3c:ec:ef:12:34:56", "link": "up", "wol": "off", "supported": True}, {"iface": "enp4s0", "mac": "3c:ec:ef:12:34:57", "link": "down", "wol": "off", "supported": False}]
server.power_nics = lambda: (nics, False)
ok("ethtool" in (raises(server.power_wol_set, "enp3s0", True) or ""), "ethtool absent : message d'installation")
server.power_nics = lambda: (nics, True)
ok(raises(server.power_wol_set, "eth9", True) == "carte réseau inconnue" and "paquet magique" in (raises(server.power_wol_set, "enp4s0", True) or ""), "carte inconnue ou sans réveil par paquet magique : refusée")
SYS = []
real_srun = subprocess.run
subprocess.run = lambda cmd, **kw: (SYS.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1]
server.power_wol_set("enp3s0", True); server.power_wol_set("enp3s0", False)
subprocess.run = real_srun
ok(SYS[0] == ["systemctl", "enable", "--now", "ollamabuntu-wol@enp3s0.service"] and SYS[1] == ["systemctl", "disable", "--now", "ollamabuntu-wol@enp3s0.service"], "activation / désactivation par l'unité systemd de la carte")
unit = open(os.path.join(LIB, "..", "..", "..", "..", "etc", "systemd", "system", "ollamabuntu-wol@.service")).read()
ok("ethtool -s %i wol g" in unit and "Type=oneshot" in unit and "ConditionPathExists=/sys/class/net/%i" in unit, "unité systemd fournie : réveil par paquet magique à chaque démarrage")

# --- routes HTTP
httpd = server.make_server(0, server.Handler); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
def req(method, path, cookie="", body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = cookie
    try:
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = c.getresponse(); out = r.read(); cookies = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    except (ConnectionError, OSError) as e:
        return 0, [], {"error": str(e)}
    finally: c.close()
    try: return r.status, cookies, json.loads(out or b"{}")
    except ValueError: return r.status, cookies, {}
def login(u, p):
    st, ck, d = req("POST", "/api/login", body={"user": u, "password": p}); return next(c.split(";")[0] for c in ck if c.startswith("ob_session="))
adm, usr = login("admin", "Secret-123"), login("jean", "Secret-456")
st, _, d = req("GET", "/api/power", adm); ok(st == 200 and len(d["servers"]) == 3 and d["settings"]["enabled"] is True and "limits" in d, "GET /api/power")
ok(req("GET", "/api/power", usr)[0] == 403 and req("GET", "/api/power")[0] == 401, "réservé aux administrateurs")
st, _, d = req("POST", "/api/power/config", adm, {"keep_awake": 1, "wake_after_s": 30}); ok(st == 200 and d["settings"]["keep_awake"] == 1 and server.power_config()["wake_after_s"] == 30, "POST /api/power/config")
ok(req("POST", "/api/power/config", adm, {"keep_awake": 99})[0] == 400 and req("POST", "/api/power/config", usr, {"keep_awake": 1})[0] == 403, "valeur invalide : 400 ; simple utilisateur : 403")
st, _, d = req("POST", "/api/power/server", adm, {"id": "3", "mac": "3c:ec:ef:00:00:33", "wake": True}); ok(st == 200 and d["power"]["mac"] == "3c:ec:ef:00:00:33", "POST /api/power/server")
ok(req("POST", "/api/power/server", adm, {"id": "3", "mac": "zz"})[0] == 400, "MAC invalide : 400")
WOL.clear(); st, _, d = req("POST", "/api/power/wake", adm, {"id": "3"}); ok(st == 200 and WOL and WOL[0][0] == "3c:ec:ef:00:00:33", "POST /api/power/wake")
CALLS.clear(); server.fleet_set_power("1", {"sleep": "suspend"}); st, _, d = req("POST", "/api/power/sleep", adm, {"id": "1"}); ok(st == 200 and CALLS and CALLS[-1][2]["data"]["mode"] == "suspend", "POST /api/power/sleep")
ok(req("POST", "/api/power/wake", usr, {"id": "3"})[0] == 403, "réveil refusé à un simple utilisateur")
st, _, d = req("POST", "/api/power/member", adm, {"allow": "suspend"}); ok(st == 200 and server.power_member_allow() == "suspend", "POST /api/power/member")
st, _, d = req("GET", "/api/fleet/member", adm); ok(st == 200 and d["power_allow"] == "suspend" and "nics" in d, "la vue « gestion centralisée » donne l'autorisation et les cartes réseau")
audit = open(server.AUDIT_FILE).read()
ok("Réveil d'un serveur" in audit and "Mise en veille d'un serveur" in audit and "Réveil et veille du parc" in audit, "actions consignées au journal d'audit")
print("\n%d vérifications réussies" % n)
