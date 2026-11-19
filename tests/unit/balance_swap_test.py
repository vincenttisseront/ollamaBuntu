#!/usr/bin/env python3
"""Carte « Répartition de charge » : avec l'option « modèle différent », un serveur sans modèle commun est utilisable et le dit."""
import os, sys, json, tempfile
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
G = 10 ** 9
def tag(name, size, fam): return {"name": name, "size": size * G, "details": {"family": fam}}
local = [tag("gemma4:12b", 8, "gemma4"), tag("qwen3-14b:q4", 9, "qwen3")]
remote = [tag("granite4.2:8b", 5, "granite")]
tmp = tempfile.mkdtemp(); server.BALANCE_FILE = os.path.join(tmp, "balance.json")
server.ollama_json = lambda *a, **k: (200, {"models": local})
server.read_request_log = lambda since: []
server.load_fleet = lambda: [{"id": "s1", "name": "vmesx10", "route_token": "t"}]
server._fleet_state.clear(); server._fleet_state["s1"] = {"state": "en ligne", "data": {"model_tags": remote, "ollama": {"running": []}}}
server.set_balance_strategy("spread", None, False)
v = server.balance_view()
ok(v["servers"][0]["issues"] == ["no-common-model"] and not v["active"], "option éteinte : « aucun modèle en commun », répartition inactive")
ok(all(not m["swap"] for m in v["models"]), "option éteinte : aucun remplacement annoncé")
server.set_balance_strategy("spread", None, True)
v = server.balance_view()
ok(v["servers"][0]["issues"] == [] and v["servers"][0]["swaps"] == 2 and v["active"], "option allumée : le serveur est utilisable avec 2 modèles en remplacement")
g = next(m for m in v["models"] if m["name"].startswith("gemma4"))
ok(g["swap"] == [{"server": "vmesx10", "use": "granite4.2:8b"}], "gemma4:12b : vmesx10 répondrait avec granite4.2:8b")
ok(any(m["name"] == "granite4.2:8b" and m["on"] == ["vmesx10"] and not m["swap"] for m in v["models"]), "granite4.2:8b (absent ici) : aucun remplacement inventé")
server._fleet_state["s1"]["data"]["model_tags"] = [tag("nomic-embed-text:latest", 1, "nomic-bert")]
v = server.balance_view()
ok(v["servers"][0]["swaps"] == 0 and v["servers"][0]["issues"] == ["no-common-model"], "serveur qui n'a que des embeddings : aucun remplacement de conversation")
server._fleet_state["s1"]["state"] = "hors ligne"
v = server.balance_view()
ok(v["servers"][0]["swaps"] == 0 and "offline" in v["servers"][0]["issues"], "serveur hors ligne : rien annoncé")
print("%d contrôles réussis" % n)
