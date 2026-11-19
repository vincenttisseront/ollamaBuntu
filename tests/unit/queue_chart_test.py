#!/usr/bin/env python3
"""Graphique « File d'attente » du tableau de bord : pic du limiteur, échantillon de la console, agrégation par intervalle."""
import json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
L = os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, L); sys.path.insert(0, os.path.join(L, "admin"))
import limits, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)

# --- limiteur : le pic reste visible après la fin de l'attente
lim = limits.Limiter()
ok(lim.peak_waiting() == 0, "file vide : pic 0")
lim.acquire_ex("k", 1, 5, total=1)                       # admise (la file est vide)
res = []
ths = [threading.Thread(target=lambda: res.append(lim.acquire_ex("k", 1, 5, total=1)[0])) for _ in range(3)]
for t in ths: t.start()
time.sleep(0.4)
ok(lim.peak_waiting() == 3 and len(lim.waiting_list()) == 3, "3 requêtes en attente : pic 3")
for _ in range(4):
    lim.release("k"); time.sleep(0.2)
for t in ths: t.join(5)
ok(len(lim.waiting_list()) == 0 and lim.peak_waiting() == 3, "file vidée : le pic des 15 dernières secondes reste visible")
ok(lim.peak_waiting(window=15, now=time.time() + 60) == 0, "au-delà de la fenêtre : pic retombé à 0")

# --- échantillon de la console
tmp = tempfile.mkdtemp()
server.ROUTER_LIMITS = os.path.join(tmp, "limits.json")
server.cpu_times = lambda: (0, 1); server.meminfo = lambda: {"MemTotal": 10, "MemAvailable": 5}; server.gpu_metrics = lambda: []; server.new_requests = lambda: []
def sample(obj):
    if obj is not None: json.dump(obj, open(server.ROUTER_LIMITS, "w"))
    elif os.path.exists(server.ROUTER_LIMITS): os.remove(server.ROUTER_LIMITS)
    server.take_sample(); return server._metrics["samples"][-1]
s = sample({"t": int(time.time()), "peak": 4, "waiting": [{}, {}], "active": 2})
ok(s["qw"] == 4 and s["qa"] == 2, "échantillon : pic de file et requêtes en cours lus du routeur")
s = sample({"t": int(time.time()), "waiting": [{}, {}, {}], "active": 1})
ok(s["qw"] == 3 and s["qa"] == 1, "routeur sans « peak » (ancienne version) : taille actuelle de la file")
s = sample({"t": int(time.time()) - 120, "peak": 9, "active": 5})
ok(s["qw"] == 0 and s["qa"] == 0, "état du routeur périmé (arrêté) : 0, pas de valeur fantôme")
s = sample(None); ok(s["qw"] == 0 and s["qa"] == 0, "fichier absent : 0")

# --- agrégation : pic par intervalle, anciens échantillons sans la mesure
now = time.time()
base = {"cpu": 1, "mem": 1, "gpus": {}, "req": 0, "tok": 0, "tps": None, "ttft": None}
with server._metrics_lock:
    server._metrics["samples"].clear(); server._metrics["names"].clear()
    server._metrics["samples"].extend([dict(base, t=now - 3000)] + [dict(base, t=now - 100 + i * 10, qw=w, qa=a) for i, (w, a) in enumerate([(0, 1), (5, 2), (1, 2), (0, 0)])])
v = server.metrics_view(3600); ser = v["series"]
old = [p for p in ser if p["t"] < now - 2000]
ok(old and old[0]["qw"] is None and old[0]["qa"] is None, "ancien échantillon sans mesure : aucune valeur (trou, pas 0)")
new = [p for p in ser if p["t"] >= now - 200]
ok(max(p["qw"] for p in new) == 5, "pic de 5 requêtes en attente conservé après regroupement")
ok(all(p["qa"] is not None for p in new), "requêtes en cours moyennées")
print("%d contrôles réussis" % n)
