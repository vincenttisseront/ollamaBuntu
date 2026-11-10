import json, ssl, http.client, os, sys, time, signal
T = "/tmp/target"; n = 0
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
# faux apt-get : 3 s, journal début/fin pour détecter tout chevauchement
open(T + "/usr/local/bin/apt-get", "w").write('#!/bin/sh\necho "debut $(date +%s.%N) $$ $*" >> /tmp/apt-trace.log\nsleep 3\necho "fin $(date +%s.%N) $$" >> /tmp/apt-trace.log\n')
os.chmod(T + "/usr/local/bin/apt-get", 0o755)
for f in ("/tmp/apt-trace.log",):
    if os.path.exists(T + f): os.remove(T + f)
api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
ids = []
for kind in ("apt-refresh", "update-security", "install-vulkan", "apt-refresh"):
    s, d = api("POST", "/api/action", {"action": kind}); ids.append(d.get("job"))
ok(all(ids) and len(set(ids)) == 4, "4 tâches APT demandées coup sur coup : 4 identifiants distincts (dont 2 fois la même tâche)")
time.sleep(1)
st = [api("GET", "/api/jobs/" + j)[1] for j in ids]
ok(not st[0]["queued"] and not st[0]["done"] and all(x["queued"] for x in st[1:]), "1re en cours, les 3 autres en attente")
ok([x["position"] for x in st[1:]] == [1, 2, 3], "rangs dans la file : %s" % [x["position"] for x in st[1:]])
s, d = api("POST", "/api/jobs/cancel", {"id": ids[2]}); st2 = api("GET", "/api/jobs/" + ids[2])[1]
ok(s == 200 and st2["done"] and st2["rc"] == 130 and "annulée" in st2["output"], "annulation de la 3e (en attente) : code 130, « %s »" % st2["output"].strip())
s, d = api("POST", "/api/jobs/cancel", {"id": ids[0]}); ok(s == 400, "annuler une tâche déjà démarrée : refusé (« %s »)" % d.get("error"))
ok(api("GET", "/api/jobs/" + ids[3])[1]["position"] == 2, "la 4e remonte au rang 2 après l'annulation")
t0 = time.time()
while time.time() - t0 < 120 and not all(api("GET", "/api/jobs/" + j)[1]["done"] for j in ids): time.sleep(1)
ok(all(api("GET", "/api/jobs/" + j)[1]["done"] for j in ids), "toutes les tâches terminées en %.0f s" % (time.time() - t0))
ev = [l.split() for l in open(T + "/tmp/apt-trace.log").read().splitlines()]
depth, maxd = 0, 0
for e in sorted(ev, key=lambda e: float(e[1])):
    depth += 1 if e[0] == "debut" else -1; maxd = max(maxd, depth)
ok(maxd == 1, "aucun chevauchement : %d appels apt-get, jamais plus d'un à la fois" % (len(ev) // 2))
starts = [api("GET", "/api/jobs/" + j)[1]["output"] for j in (ids[0], ids[1], ids[3])]
first = [float(next(e[1] for e in ev if e[0] == "debut" and e[2] == pid)) for pid in []] or None
order = [e for e in ev if e[0] == "debut"]
ok(order[0][3:4] == ["update"] and len(order) >= 3, "ordre respecté : la 1re tâche a démarré en premier (%s)" % " / ".join(" ".join(e[3:5]) for e in order[:3]))
# tâche tuée en cours : la file ne reste pas bloquée
s, d1 = api("POST", "/api/action", {"action": "apt-refresh"}); s, d2 = api("POST", "/api/action", {"action": "update-security"}); time.sleep(1.5)
pid = int(open(T + "/var/lib/ollamabuntu/jobs/" + d1["job"] + ".started").read().split(":")[1]); os.killpg(pid, signal.SIGKILL)
t0 = time.time()
while time.time() - t0 < 30 and api("GET", "/api/jobs/" + d2["job"])[1]["queued"]: time.sleep(0.5)
j1 = api("GET", "/api/jobs/" + d1["job"])[1]
ok(j1["done"] and j1["rc"] == 255 and "interrompue" in j1["output"], "tâche tuée en cours : détectée « interrompue » (code 255)")
ok(not api("GET", "/api/jobs/" + d2["job"])[1]["queued"], "la tâche suivante a démarré en %.1f s : la file n'est pas bloquée" % (time.time() - t0))
