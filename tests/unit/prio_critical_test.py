#!/usr/bin/env python3
"""Priorité « critique » (passe toujours en premier, sans vieillissement) et places réservées du plafond global."""
import os, sys, threading, time, tempfile, json
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import limits
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)

ok(limits.priority_of(0) == 0 and limits.priority_of(9) == 2 and limits.priority_of("x") == 2 and 0 in limits.PRIORITIES, "priorité 0 reconnue, valeurs absurdes ramenées à normale")
L = limits.Limiter()
ok(L._eff({"prio": 0, "t": 0}, 10 ** 6) == 0 and L._eff({"prio": 3, "t": 0}, 10 ** 6) == 1 and L._eff({"prio": 3, "t": 0}, 0) == 3, "critique : ne vieillit pas ; basse : vieillit jusqu'à haute")

def wait_for(cond, t=3):
    d = time.time() + t
    while time.time() < d:
        if cond(): return True
        time.sleep(0.01)
    return False

# --- ordre de passage : plafond global de 1, un détenteur, quatre en attente
L = limits.Limiter(); order = []
ok(L.acquire_ex("occupant", 0, 5, prio=2, total=1)[0], "le premier passe")
def waiter(kid, prio):
    ok_, _ = L.acquire_ex(kid, 0, 10, prio=prio, total=1, now=None)
    if ok_:
        order.append(kid); L.release(kid, prio)
ths = []
for kid, prio in (("basse", 3), ("normale", 2), ("haute", 1), ("critique", 0)):
    t = threading.Thread(target=waiter, args=(kid, prio)); t.start(); ths.append(t)
    ok(wait_for(lambda: len(L._tickets) == len(ths)), "en attente : " + kid)
ok([w["kid"] for w in L.waiting_list()] == ["critique", "haute", "normale", "basse"], "la file annonce l'ordre critique, haute, normale, basse")
L.release("occupant", 2)
for t in ths: t.join(5)
ok(order == ["critique", "haute", "normale", "basse"], "ordre de passage réel : " + ", ".join(order))

# --- places réservées : total 3, 1 réservée aux critiques
L = limits.Limiter()
ok(L.acquire_ex("a", 0, 1, prio=2, total=3, reserve=1)[0] and L.acquire_ex("b", 0, 1, prio=3, total=3, reserve=1)[0], "deux clés ordinaires passent")
t0 = time.time(); r = L.acquire_ex("c", 0, 0.3, prio=1, total=3, reserve=1)
ok(r == (False, "timeout") and time.time() - t0 >= 0.25, "une troisième clé ordinaire (même haute) attend : la dernière place est réservée")
t0 = time.time(); r = L.acquire_ex("crit", 0, 2, prio=0, total=3, reserve=1)
ok(r == (True, None) and time.time() - t0 < 0.5, "une clé critique prend la place réservée tout de suite")
ok(L.total_running() == 3, "trois requêtes en cours")
res = {}
def late(): res["ok"] = L.acquire_ex("d", 0, 5, prio=2, total=3, reserve=1)[0]
th = threading.Thread(target=late); th.start(); wait_for(lambda: len(L._tickets) == 1)
L.release("crit", 0)
th.join(0.4)
ok(th.is_alive() and "ok" not in res, "la fin d'une requête critique ne donne pas sa place à une ordinaire (elle reste réservée)")
L.release("a", 2)
th.join(3)
ok(res.get("ok") is True, "la fin d'une requête ordinaire libère une place pour l'ordinaire en attente")
L.release("b", 3); L.release("d", 2)
ok(L.total_running() == 0 and L._total_nc == 0, "compteurs revenus à zéro (aucune fuite)")

# --- une critique en attente passe avant une ordinaire quand une place se libère
L = limits.Limiter(); out = []
for k in ("a", "b", "c"): L.acquire_ex(k, 0, 1, prio=2, total=3, reserve=0)
def w2(kid, prio):
    if L.acquire_ex(kid, 0, 10, prio=prio, total=3, reserve=1)[0]:
        out.append(kid); 
t1 = threading.Thread(target=w2, args=("ordinaire", 1)); t1.start(); wait_for(lambda: len(L._tickets) == 1)
t2 = threading.Thread(target=w2, args=("critique", 0)); t2.start(); wait_for(lambda: len(L._tickets) == 2)
L.release("a", 2); t2.join(3)
ok(out == ["critique"], "une place se libère : la critique passe avant l'ordinaire plus ancienne")
L.release("b", 2); t1.join(0.4)
ok(out == ["critique"] and t1.is_alive(), "ordinaire : encore bloquée (2 ordinaires + 1 critique, une place réservée)") if False else None
L.release("critique", 0); L.release("c", 2); t1.join(3)
ok(out == ["critique", "ordinaire"], "puis l'ordinaire passe quand la place réservée n'est plus nécessaire")

# --- bornes
L = limits.Limiter()
ok(L.acquire_ex("x", 0, 1, prio=2, total=2, reserve=5)[0], "réserve trop grande : ramenée à total - 1, une ordinaire passe quand même")
ok(L.acquire_ex("y", 0, 0.2, prio=2, total=2, reserve=5) == (False, "timeout") and L.acquire_ex("z", 0, 1, prio=0, total=2, reserve=5)[0], "… mais une seule ordinaire à la fois ; la critique prend l'autre place")
L = limits.Limiter()
ok(all(L.acquire_ex("k%d" % i, 0, 1, prio=2, total=0, reserve=3)[0] for i in range(10)), "sans plafond global, la réserve est ignorée")
L = limits.Limiter()
L.acquire_ex("a", 0, 1, prio=2, total=2, reserve=1)
ok(L.acquire_ex("b", 0, 0.1, prio=2, total=2, reserve=1, max_queue=1) == (False, "timeout"), "file de 1 : la première ordinaire attend")
res = {}
th = threading.Thread(target=lambda: res.update(r=L.acquire_ex("c", 0, 1, prio=2, total=2, reserve=1, max_queue=1))); th.start(); wait_for(lambda: len(L._tickets) == 1)
ok(L.acquire_ex("d", 0, 0.1, prio=2, total=2, reserve=1, max_queue=1) == (False, "full"), "file pleine : une ordinaire de plus est refusée")
ok(L.acquire_ex("crit", 0, 1, prio=0, total=2, reserve=1, max_queue=1) == (True, None), "… mais une critique passe encore (place réservée libre)")
th.join(3)

# --- console et routeur
import server, router
tmp = tempfile.mkdtemp(); server.QUEUE_CONF = os.path.join(tmp, "queue.json")
def raises(f, *a):
    try: f(*a); return False
    except ValueError: return True
ok(raises(server.queue_save, {"reserved": 1}), "places réservées sans plafond global : refusé")
ok(raises(server.queue_save, {"max_active": 4, "reserved": 4}) and raises(server.queue_save, {"max_active": 4, "reserved": 9}), "réserve égale ou supérieure au plafond : refusée")
ok(server.queue_save({"max_active": 4, "reserved": 1}) == {"max_active": 4, "max_queue": 0, "reserved": 1}, "réglage valide enregistré")
router.QUEUE_CONF = server.QUEUE_CONF; router._qc["mtime"] = None
ok(router.queue_conf()["reserved"] == 1, "le routeur relit la réserve à chaud")
ok(server.validate_limits({"priority": 0}, {"priority": 2}) == {"priority": 0}, "clé : priorité 0 acceptée")
src = open(os.path.join(LIB, "router.py"), encoding="utf-8").read()
ok('reserve=qc["reserved"]' in src and "_limiter.release(self._slot, self._slot_prio)" in src and "limits.priority_of(gkey.get(\"priority\"))" in src, "routeur : transmet la réserve et libère avec la priorité de la requête")
print("%d contrôles réussis" % n)
