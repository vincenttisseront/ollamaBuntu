#!/usr/bin/env python3
"""Répartition avec modèle différent : choix automatique du remplacement, candidats, réécriture du modèle."""
import os, sys, json, tempfile
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import router, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
G = 10 ** 9
def tag(name, size, fam): return {"name": name, "size": size * G, "details": {"family": fam}}
want = tag("qwen3:30b", 18, "qwen3")
srv = [tag("llama3.2:3b", 2, "llama"), tag("qwen3:8b", 5, "qwen3"), tag("qwen3:14b", 9, "qwen3"), tag("nomic-embed-text:latest", 1, "nomic-bert"), tag("x:cloud", 0, "x")]
ok(router.auto_substitute(srv, "qwen3:30b", want, set()) == "qwen3:14b", "même famille, taille la plus proche")
ok(router.auto_substitute(srv, "qwen3:30b", want, {"qwen3:8b"}) == "qwen3:8b", "même famille : le modèle déjà en mémoire d'abord")
ok(router.auto_substitute(srv, "qwen3:30b", None, {"llama3.2:3b"}) == "llama3.2:3b", "modèle demandé inconnu : celui en mémoire")
ok(router.auto_substitute(srv, "nomic-embed-text", tag("nomic-embed-text", 1, "nomic-bert"), set()) == "nomic-embed-text:latest", "embeddings : on reste sur un modèle d'embeddings")
ok(router.auto_substitute([tag("llama3.2:3b", 2, "llama")], "nomic-embed-text", tag("e", 1, "nomic-bert"), set()) is None, "pas de modèle d'embeddings : aucun remplacement (pas de chat à la place)")
ok(router.auto_substitute([tag("a:cloud", 0, "a")], "m", None, set()) is None, "les modèles cloud ne servent pas de remplacement")
s1 = {"models": srv, "model_map": {}, "loaded": []}
ok(router.remote_use(s1, "qwen3:30b") is None and router.remote_use(s1, "qwen3:30b", True, want) == "qwen3:14b", "sans l'option : absent ; avec : remplacement automatique")
ok(router.remote_use(dict(s1, model_map={"qwen3:30b": "qwen3:8b"}), "qwen3:30b", True, want) == "qwen3:8b", "le remplacement réglé par l'administrateur garde la priorité")
ok(router.remote_use(s1, "qwen3:8b", True, want) == "qwen3:8b", "modèle présent : inchangé")

# candidats
tmp = tempfile.mkdtemp(); router.BALANCE_FILE = os.path.join(tmp, "balance.json"); router._bal["mtime"] = None
router._local_models.update(t=10 ** 12, tags=[want], names={"qwen3:30b"})
fl = {"local": {"loaded": [], "load": 0}, "servers": [{"id": "s1", "name": "B", "online": True, "models": srv, "model_map": {}, "loaded": [], "load": 0}]}
H = router.Handler if hasattr(router, "Handler") else None
cand = (H or [c for c in vars(router).values() if isinstance(c, type) and hasattr(c, "candidates")][0]).candidates
router._health = router.limits.Health()
r = cand("qwen3:30b", fl, flex=True)
ok(len(r) == 1 and r[0][0] == "local", "option éteinte : seul le serveur qui a le modèle")
open(router.BALANCE_FILE, "w").write(json.dumps({"substitute": True})); router._bal["mtime"] = None
router._inflight.clear(); router._rr.clear()
r = cand("qwen3:30b", fl, flex=True)
ok(sorted(c[0] for c in r) == ["local", "remote"] and [c[3]["use_model"] for c in r if c[0] == "remote"] == ["qwen3:14b"], "option allumée : les deux serveurs, le second avec son remplacement")
r = cand("qwen3:30b", fl, flex=False)
ok(len(r) == 1, "requête avec images : pas de remplacement automatique")
# la charge se répartit : 6 requêtes, les deux serveurs servent
router._inflight.clear(); router._rr.clear()
seen = {}
for i in range(6):
    c = cand("qwen3:30b", fl, flex=True)[0]
    k = c[0]; seen[k] = seen.get(k, 0) + 1
ok(seen.get("local", 0) >= 2 and seen.get("remote", 0) >= 2, "6 requêtes simultanées réparties : %s" % seen)
# modèle absent partout : local reçoit un remplacement
router._local_models.update(tags=[tag("llama3.2:3b", 2, "llama")], names={"llama3.2:3b"})
router._inflight.clear()
r = cand("qwen3:30b", fl, flex=True)
ok(any(c[0] == "local" and c[3]["use_model"] == "llama3.2:3b" for c in r), "ce serveur n'a pas le modèle : il répond avec son remplacement")
# console
server.BALANCE_FILE = router.BALANCE_FILE
server.set_balance_strategy("spread", None, False)
ok(server.balance_substitute() is False, "console : option éteinte enregistrée")
server.set_balance_strategy("spread", None, True)
ok(server.balance_substitute() is True and server.balance_affinity() is True, "console : option allumée, affinité conservée")
server.set_balance_strategy("warm")
ok(server.balance_substitute() is True, "changer la stratégie ne touche pas l'option")
src = open(os.path.join(LIB, "router.py"), encoding="utf-8").read()
ok("lbody" in src and "flex=not uses_vision(body)" in src, "routeur : réécrit le modèle en local et exclut les requêtes avec images")
print("%d contrôles réussis" % n)
