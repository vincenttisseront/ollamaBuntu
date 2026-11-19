#!/usr/bin/env python3
"""Répartition : durées mesurées, coût estimé, file centrale (ordre), popularité des modèles, plan de préchargement, réglages de la console."""
import json, os, sys, tempfile
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import balancing as b, limits, router, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)

# --- puissance mesurée
p = b.Perf()
ok(p.predict("a", "m", 0) is None, "serveur jamais mesuré : pas de prévision")
for _ in range(5):
    p.update("fast", "m", 0.2, 2.2, 100, now=1000); p.update("slow", "m", 1.0, 11.0, 100, now=1000)
f, s = p.predict("fast", "m", 1000), p.predict("slow", "m", 1000)
ok(f is not None and s is not None and s > 3 * f, "un serveur cinq fois plus lent est prévu plus long (%.1f s contre %.1f s)" % (s, f))
v, known = p.services([("fast", "m"), ("new", "m"), ("slow", "m")], 1000)
ok(known and v[1] in (v[0], v[2]), "serveur inconnu : valeur médiane des mesurés")
ok(p.services([("x", "m")], 0) == ([1.0], False), "personne n'est mesuré : durée neutre")
ok(p.predict("fast", "m", 1000 + b.STALE + 1) is None, "une mesure de plus de six heures est oubliée")
spt0 = p.snapshot(1000)["fast|m"]["spt"]
p.update("fast", "m", 0.2, 0.25, 3, now=1000)   # trop peu de jetons : la vitesse ne bouge pas
ok(p.snapshot(1000)["fast|m"]["spt"] == spt0, "réponse de 3 jetons : vitesse inchangée")
ok(p.ttft("slow", "m", 1000) is not None and 0.5 < p.ttft("slow", "m", 1000) < 1.5, "délai avant la première réponse mesuré")
# --- coût
ok(b.cost(2.0, 0, 1) == 2.0 and b.cost(2.0, 2, 1) == 6.0 and b.cost(2.0, 2, 2) == 4.0, "coût : durée × (1 + requêtes en cours / places)")
ok(b.cost(2.0, 0, 1, cold=1.5) == 5.0, "coût : modèle à charger")
ok(b.cost(1.0, 3, 1) > b.cost(3.0, 0, 1) and b.cost(1.0, 1, 1) < b.cost(3.0, 0, 1), "un serveur rapide déjà chargé reste préférable jusqu'à deux requêtes devant lui")
ok(b.queue_delay(4.0, 2, 2) == 4.0, "attente avant démarrage")
# --- file centrale
w = b.Waiters()
low, high, crit = w.ticket(3, "m", now=0), w.ticket(1, "m", now=1), w.ticket(0, "m", now=2)
for t in (low, high, crit): w.register(t, ["a"])
ok(w.must_yield(low, ["a"], 3) and w.must_yield(high, ["a"], 3) and not w.must_yield(crit, ["a"], 3), "la critique passe d'abord, puis la haute, puis la basse")
other = w.ticket(2, "m", now=4); w.register(other, ["b"])
ok(not w.must_yield(other, ["b"], 5) and not w.must_yield(crit, ["b"], 5), "une requête qui attend une autre place n'est pas bloquée")
old = w.ticket(3, "m", now=0 - 3 * limits.AGING); w.register(old, ["c"]); fresh = w.ticket(2, "m", now=0); w.register(fresh, ["c"])
ok(w.must_yield(fresh, ["c"], 0) is True, "une requête basse qui attend depuis 6 minutes passe devant une normale récente")
ok(b.eff_prio(0, 0, 10 ** 6) == 0, "la critique ne vieillit pas")
w.drop(crit)
ok(w.must_yield(low, ["a"], 3) and not w.must_yield(high, ["a"], 3), "critique retirée : la haute passe en tête")
ok(len(w.waiting(10)) == 5 and w.waiting(10)[-1]["prio"] in (2, 3), "la file est lisible pour la console (les moins prioritaires en fin)")
# --- popularité et préchargement
pop = b.Popularity(os.path.join(tmp, "pop.json"))
t0 = 1_700_000_000
for i in range(5): pop.hit("big:30b", t0)
pop.hit("rare:1b", t0)
ok(pop.expected(t0) == ["big:30b"], "modèle demandé 5 fois dans l'heure : attendu ; 1 fois : pas assez")
pop.hit("big:30b", t0 + 3600 * 5)   # changement d'heure : le compte entre dans la moyenne
pop.save()
pop2 = b.Popularity(os.path.join(tmp, "pop.json"))
ok(os.path.exists(os.path.join(tmp, "pop.json")) and pop2._avg.get("big:30b") is not None, "popularité enregistrée sur disque et relue")
router._local_models.update(t=10 ** 12, tags=[{"name": "big:30b"}, {"name": "small:1b"}], names={"big:30b", "small:1b"})
srvs = [{"id": "s1", "online": True, "token": "t", "loaded": [], "models": [{"name": "big:30b"}, {"name": "small:1b"}]},
        {"id": "s2", "online": True, "token": "t", "loaded": ["x"], "models": [{"name": "big:30b"}]},
        {"id": "s3", "online": True, "token": "t", "loaded": [], "models": [{"name": "small:1b"}]}]
fl = {"local": {"loaded": []}, "servers": srvs}
done = {}
plan = router.prewarm_plan(["big:30b", "small:1b"], fl, {}, 1000, done)
got = [(k, (s or {}).get("id"), m) for k, s, m in plan]
ok(len(got) == 3 and sorted(m for _, _, m in got) == sorted(set(m for _, _, m in got)) or len(set(m for _, _, m in got)) == len(got) == 2,
   "préchargement : un modèle attendu par serveur libre, jamais deux fois le même : %s" % [(k, (s or {}).get("id"), m) for k, s, m in plan])
ok(all(not (s and s["id"] == "s2") for k, s, m in plan), "un serveur qui a déjà un modèle en mémoire n'est pas touché")
again = router.prewarm_plan(["big:30b", "small:1b"], fl, {}, 1100, done)
ok(all((k, (s or {}).get("id"), m) not in got for k, s, m in again), "le même modèle n'est pas renvoyé au même serveur avant 10 minutes")
ok(len(router.prewarm_plan(["big:30b"], fl, {}, 1700, done)) >= 1, "au-delà de 10 minutes, il peut l'être de nouveau")
ok(router.prewarm_plan(["big:30b"], fl, {"local": 1, "s1": 1, "s3": 1}, 5000, {}) == [], "aucun serveur occupé n'est choisi")
ok(router.prewarm_plan([], fl, {}, 0, {}) == [], "rien d'attendu : rien à charger")
# --- candidats : la durée mesurée décide
router.BALANCE_FILE = os.path.join(tmp, "balance.json"); router._bal["mtime"] = None
router._health = limits.Health()
H = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
router._local_models.update(tags=[{"name": "m:1b"}], names={"m:1b"})
def mk(i): return {"id": "s%d" % i, "name": "S%d" % i, "online": True, "models": [{"name": "m:1b"}], "model_map": {}, "loaded": ["m:1b"], "load": 0}
fl = {"local": {"loaded": ["m:1b"], "load": 0}, "servers": [mk(1), mk(2)]}
router._perf = b.Perf()
for _ in range(4):
    router._perf.update("local", "m:1b", 0.1, 1.1, 100); router._perf.update("s1", "m:1b", 0.1, 3.1, 100); router._perf.update("s2", "m:1b", 0.1, 6.1, 100)
router._inflight.clear(); router._rr.clear()
order = [c[3]["id"] if c[3] and c[0] == "remote" else "local" for c in H.candidates("m:1b", fl)]
ok(order == ["local", "s1", "s2"], "à vide : le plus rapide d'abord (%s)" % order)
router._inflight.update({"local": 4})
order = [c[3]["id"] if c[0] == "remote" else "local" for c in H.candidates("m:1b", fl)]
ok(order[0] != "local" and order[0] == "s1", "serveur rapide encombré : le suivant passe devant (%s)" % order)
# places limitées et file
open(router.BALANCE_FILE, "w").write(json.dumps({"slots": {"local": 1, "s1": 1, "s2": 1}})); router._bal["mtime"] = None
router._inflight.clear(); router._inflight.update({"local": 1, "s1": 1, "s2": 1}); router._waiters = b.Waiters()
tk = router._waiters.ticket(2, "m:1b")
ok(H.candidates("m:1b", fl, ticket=tk) is b.WAIT and tk["queued"], "toutes les places prises : la requête attend dans la file centrale")
router._inflight["s2"] = 0
r = H.candidates("m:1b", fl, ticket=tk)
ok(r is not b.WAIT and r[0][3]["id"] == "s2" and not tk["queued"], "une place se libère : la requête part sur ce serveur")
router._inflight.update({"local": 1, "s1": 1, "s2": 0})
hi = router._waiters.ticket(1, "m:1b"); lo = router._waiters.ticket(3, "m:1b")
ok(H.candidates("m:1b", fl, ticket=hi) is not b.WAIT, "requête haute : prend la place libre")
router._inflight["s2"] = 0
hi2 = router._waiters.ticket(1, "m:1b")
router._inflight.update({"local": 1, "s1": 1, "s2": 1})
ok(H.candidates("m:1b", fl, ticket=lo) is b.WAIT, "toutes les places reprises : la requête basse attend")
router._inflight["s2"] = 0
router._waiters.register(hi2, ["local", "s1", "s2"])
ok(H.candidates("m:1b", fl, ticket=lo) is b.WAIT, "une place libre mais une requête haute attend aussi : la basse lui laisse la place")
router._waiters.drop(hi2); router._waiters.drop(lo)
# sans places réglées : comme avant, jamais d'attente
open(router.BALANCE_FILE, "w").write("{}"); router._bal["mtime"] = None
router._inflight.update({"local": 9, "s1": 9, "s2": 9})
ok(H.candidates("m:1b", fl, ticket=router._waiters.ticket(2, "m:1b")) is not b.WAIT, "places non réglées : aucune file centrale (Ollama gère sa file)")
# --- remplacement au débordement
tags = lambda n, s, fam: {"name": n, "size": s * 10 ** 9, "details": {"family": fam}}
router._local_models.update(tags=[tags("q:30b", 18, "q")], names={"q:30b"})
fl2 = {"local": {"loaded": [], "load": 0}, "servers": [{"id": "s1", "name": "S1", "online": True, "models": [tags("q:14b", 9, "q")], "model_map": {}, "loaded": ["q:14b"], "load": 0}]}
router._perf = b.Perf(); router._inflight.clear(); router._rr.clear()
open(router.BALANCE_FILE, "w").write(json.dumps({"substitute_mode": "overflow", "overflow_wait": 8})); router._bal["mtime"] = None
r = H.candidates("q:30b", fl2, flex=True)
ok([c[0] for c in r] == ["local"], "débordement : serveur du modèle libre, aucun remplacement")
router._perf.update("local", "q:30b", 1, 21, 100)
for _ in range(3): router._perf.update("local", "q:30b", 1, 21, 100)
router._inflight["local"] = 2
r = H.candidates("q:30b", fl2, flex=True)
ok(sorted(c[0] for c in r) == ["local", "remote"], "débordement : le serveur du modèle est chargé (attente ≈ 40 s), le remplacement entre en jeu")
r = H.candidates("q:30b", fl2, flex=True, mode="strict")
ok([c[0] for c in r] == ["local"], "clé « jamais » : le modèle demandé uniquement, même chargé")
r = H.candidates("q:30b", fl2, flex=True, mode="always"); router._inflight.clear()
ok(len(r) == 2, "clé « toujours » : le remplacement est un candidat dès le départ")
# --- console
server.BALANCE_FILE = router.BALANCE_FILE
server.load_fleet = lambda: [{"id": "s1", "name": "S1"}]
server.set_balance({"substitute_mode": "overflow", "overflow_wait": 12, "prewarm": True, "slots": {"local": 2, "s1": 3, "inconnu": 5}})
c = server.balance_conf()
ok(c["substitute_mode"] == "overflow" and c["overflow_wait"] == 12 and c["prewarm"] and c["slots"] == {"local": 2, "s1": 3}, "console : réglages enregistrés, serveur inconnu ignoré")
rc = router.balance_conf()
ok(rc["substitute_mode"] == "overflow" and rc["slots"] == {"local": 2, "s1": 3} and rc["prewarm"] and rc["overflow_wait"] == 12, "le routeur relit les mêmes réglages")
server.set_balance({"affinity": False})
ok(server.balance_conf()["slots"] == {"local": 2, "s1": 3} and server.balance_conf()["affinity"] is False, "un réglage modifié ne touche pas les autres")
for bad in ({"substitute_mode": "peut-être"}, {"overflow_wait": 0}, {"overflow_wait": 9999}, {"slots": {"local": 100}}, {"slots": [1]}, {"strategy": "x"}):
    try: server.set_balance(bad); ok(False, "refusé : %s" % bad)
    except ValueError: pass
ok(True, "valeurs invalides refusées")
open(server.BALANCE_FILE, "w").write(json.dumps({"substitute": True}))
ok(server.balance_conf()["substitute_mode"] == "always" and router.balance_conf()["substitute_mode"] == "always", "ancien réglage (case cochée) : mode « toujours »")
ok(router.key_substitution({"substitution": "strict"}) == "strict" and router.key_substitution({}) == "always" and router.key_substitution({"substitution": "x"}) == "always", "clé : son réglage, sinon celui de la console")
vl = server.validate_limits({"substitution": "overflow", "hedge": True}, {})
ok(vl == {"substitution": "overflow", "hedge": True}, "clé : remplacement et doublement acceptés")
try: server.validate_limits({"substitution": "zzz"}); ok(False, "remplacement inconnu refusé")
except ValueError: ok(True, "remplacement inconnu refusé")
print("%d contrôles réussis" % n)
