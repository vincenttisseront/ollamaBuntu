#!/usr/bin/env python3
"""Limites du routeur : plafond de requêtes simultanées avec file d'attente, quotas de jetons, règles de routage."""
import os, sys, threading, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import limits
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)

L = limits.Limiter()
ok(L.acquire("k", 0, 1) and L.acquire(None, 3, 1), "sans plafond ou sans clé : toujours admis")
ok(L.acquire("k", 2, 1) and L.acquire("k", 2, 1), "deux requêtes admises sous le plafond de 2")
t0 = time.time(); ok(not L.acquire("k", 2, 0.3) and time.time() - t0 >= 0.25, "troisième : attente puis refus à l'échéance")
res = []
th = threading.Thread(target=lambda: res.append(L.acquire("k", 2, 5))); th.start(); time.sleep(0.2)
ok(L.snapshot() == {"k": {"running": 2, "waiting": 1}}, "la file d'attente est visible (2 en cours, 1 en attente)")
L.release("k"); th.join(2)
ok(res == [True] and L.snapshot() == {"k": {"running": 2, "waiting": 0}}, "une libération fait passer la requête en attente")
L.release("k"); L.release("k"); L.release("k"); L.release("k")
ok(L.snapshot() == {}, "tout libéré : file vide, jamais de compteur négatif")
ok(L.acquire("autre", 1, 0.1) and L.acquire("k2", 1, 0.1), "les clés sont indépendantes")

T = limits.Tokens(); now = time.mktime((2026, 11, 10, 12, 0, 0, 0, 0, -1))
T.add("k", 600, now); T.add("k", 500, now)
ok(T.exceeded("k", 1000, 0, now) and "journalier" in T.exceeded("k", 1000, 0, now), "quota journalier atteint : refus avec message")
ok(T.exceeded("k", 5000, 0, now) is None and T.exceeded("k", 0, 0, now) is None and T.exceeded(None, 1, 1, now) is None, "sous le quota, sans quota ou sans clé : admis")
lendemain = now + 86400
ok(T.exceeded("k", 1000, 0, lendemain) is None, "le quota journalier repart à zéro le lendemain")
ok("mensuel" in (T.exceeded("k", 0, 1000, lendemain) or ""), "le quota mensuel reste cumulé sur le mois")
ok(T.exceeded("k", 0, 1000, now + 40 * 86400) is None, "le quota mensuel repart à zéro le mois suivant")
T2 = limits.Tokens(); T2.load(T.snapshot()); ok(T2.snapshot()["k"]["total"] == 1100, "état rechargé après redémarrage")

c = [("local", True, 0, None), ("remote", False, 0, {"id": "s1"}), ("remote", False, 0, {"id": "s2"})]
ids = lambda x: [("local" if y[0] == "local" else y[3]["id"]) for y in x]
r, m = limits.apply_rules(c, [], "k", "gemma4:12b"); ok(ids(r) == ["local", "s1", "s2"] and not m, "aucune règle : rien ne change")
r, m = limits.apply_rules(c, [{"key": "k", "model": "gemma*", "server": "s1", "mode": "only"}], "k", "gemma4:12b"); ok(ids(r) == ["s1"] and m, "« uniquement s1 » pour ce client et ce modèle")
r, m = limits.apply_rules(c, [{"key": "k", "model": "gemma*", "server": "s1", "mode": "only"}], "autre", "gemma4:12b"); ok(ids(r) == ["local", "s1", "s2"] and not m, "règle d'un autre client : sans effet")
r, m = limits.apply_rules(c, [{"key": "*", "model": "*", "server": "local", "mode": "never"}], "k", "x"); ok(ids(r) == ["s1", "s2"] and m, "« jamais en local » pour tous")
r, m = limits.apply_rules(c, [{"key": "*", "model": "llama*", "server": "s9", "mode": "only"}], "k", "llama3:8b"); ok(r == [] and m, "serveur imposé absent : liste vide (le routeur répond 503)")
r, m = limits.apply_rules(c, [{"key": "*", "model": "llama*", "server": "s1", "mode": "only"}], "k", "gemma4:12b"); ok(not m, "le motif de modèle ne correspond pas : sans effet")
