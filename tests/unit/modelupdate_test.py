#!/usr/bin/env python3
"""Mise à jour des modèles avec retour arrière : fenêtre de maintenance (module pur) et déroulé complet côté console avec un Ollama simulé."""
import os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import modelupdate as mu, evals
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a); return False
    except ValueError: return True
lt = lambda y, mo, d, h, mi: time.strptime("%04d-%02d-%02d %02d:%02d" % (y, mo, d, h, mi), "%Y-%m-%d %H:%M")

# --- noms
ok(mu.prev_name("llama3.2:3b") == "ob-prev/llama3.2:3b" and mu.prev_name("hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M") == "ob-prev/hf.co-unsloth-qwen3-14b-gguf:Q4_K_M".lower().replace("q4_k_m", "Q4_K_M"), "nom de la copie : aplati, étiquette conservée")
ok(mu.is_prev("ob-prev/x:1") and not mu.is_prev("llama3.2:3b"), "copies de sécurité reconnues")
# --- configuration
c = mu.config_clean({})
ok(c == {"enabled": False, "days": [6], "start": "03:00", "window": 180, "scope": "all", "suite": "", "keep_days": 7, "drop_pct": 30}, "valeurs par défaut : dimanche 3 h, 3 h de fenêtre, 7 jours de conservation")
ok(mu.config_clean({"enabled": 1, "days": [5, 6, 5], "start": "23:30", "window": 120, "scope": [" a:1 "], "suite": "s1", "keep_days": 3, "drop_pct": 40}) == {"enabled": True, "days": [5, 6], "start": "23:30", "window": 120, "scope": ["a:1"], "suite": "s1", "keep_days": 3, "drop_pct": 40}, "configuration normalisée")
ok(all(raises(mu.config_clean, x) for x in ({"days": [7]}, {"days": ["a"]}, {"days": [True]}, {"start": "25:00"}, {"start": "3h"}, {"window": 10}, {"window": "x"}, {"keep_days": 0}, {"drop_pct": 5}, {"scope": []}, {"scope": [""]}, {"scope": ["a"] * 51})), "configurations invalides refusées")
# --- fenêtre de maintenance (dimanche = 6)
cfg = mu.config_clean({"enabled": True, "days": [6], "start": "23:00", "window": 180})
ok(mu.window_key(cfg, lt(2026, 11, 8, 23, 30)) == "2026-11-08", "dimanche 23 h 30 : dans le créneau du dimanche")
ok(mu.window_key(cfg, lt(2026, 11, 9, 1, 0)) == "2026-11-08", "lundi 1 h : toujours le créneau du dimanche (passe minuit)")
ok(mu.window_key(cfg, lt(2026, 11, 9, 2, 30)) is None and mu.window_key(cfg, lt(2026, 11, 8, 22, 59)) is None, "hors créneau : fin à 2 h, début à 23 h")
ok(mu.window_key(cfg, lt(2026, 11, 10, 23, 30)) is None, "un mardi : pas de créneau")
ok(mu.due(cfg, lt(2026, 11, 8, 23, 30), "") == "2026-11-08" and mu.due(cfg, lt(2026, 11, 8, 23, 31), "2026-11-08") is None and mu.due(dict(cfg, enabled=False), lt(2026, 11, 8, 23, 30), "") is None, "un créneau n'est joué qu'une fois ; désactivé : jamais")
# --- décision
ok(mu.decide(True, "", None, 50, 48)["keep"] and mu.decide(True, "", None, None, 10)["keep"], "tout va bien : on garde (pas de mesure avant = pas de comparaison de débit)")
d = mu.decide(False, "réponse vide", None, 50, 50)
ok(not d["keep"] and "réponse vide" in d["reasons"][0], "le modèle ne répond plus : retour arrière")
ok(not mu.decide(True, "", {"regressions": ["A", "B"]}, 50, 50)["keep"] and not mu.decide(True, "", None, 100, 60)["keep"] and mu.decide(True, "", None, 100, 80)["keep"], "cas de test devenus faux ou débit en baisse de 30 % : retour arrière ; -20 % : on garde")
ok(mu.expired({"a": {"t": 0}, "b": {"t": 1000000}}, 1000000 + 86400 * 2, 7) == ["a"] and mu.alert_text([mu.entry(1, "m", "updated", "x", "y")]) is None and "ancienne version rétablie" in mu.alert_text([mu.entry(1, "m", "rolled_back", "x", "y", "débit")]), "copies expirées ; texte d'alerte seulement en cas de problème")

# --- côté console, Ollama simulé
import server
tmp = tempfile.mkdtemp()
server.MU_FILE = os.path.join(tmp, "mu.json"); server.LAB_FILE = os.path.join(tmp, "lab.json")
oll = {"models": {"m:1b": "A" * 64, "other:2b": "C" * 64}, "pull": {"m:1b": "B" * 64, "other:2b": "C" * 64}, "broken": set(), "slow": set(), "pull_error": False, "bad_json": False, "calls": []}
def fake(method, path, body=None, timeout=5, addr=None):
    oll["calls"].append((method, path, (body or {}).get("model") or (body or {}).get("destination")))
    if path == "/api/tags": return 200, {"models": [{"name": k, "digest": v, "size": 1000} for k, v in oll["models"].items()]}
    if path == "/api/copy":
        if body["source"] not in oll["models"]: return 404, {"error": "model not found"}
        oll["models"][body["destination"]] = oll["models"][body["source"]]; return 200, {}
    if path == "/api/delete": oll["models"].pop(body["model"], None); return 200, {}
    if path == "/api/pull":
        if oll["pull_error"]: return 500, {"error": "connexion refusée"}
        oll["models"][body["model"]] = oll["pull"][body["model"]]; return 200, {"status": "success"}
    if path == "/api/ps": return 200, {"models": []}
    if path == "/api/generate":
        if body.get("keep_alive") == 0: return 200, {}
        dg = oll["models"].get(body["model"])
        if dg in oll["broken"]: return 200, {"response": "", "eval_count": 0, "eval_duration": 0}
        ev, evd = 60, (1_000_000_000 if dg not in oll["slow"] else 4_000_000_000)
        ans = "Paris" if "Capitale" in body["prompt"] else "OK"
        if dg == "B" * 64 and oll["bad_json"] and "Capitale" in body["prompt"]: ans = "Je ne sais pas"
        return 200, {"response": ans, "eval_count": ev, "eval_duration": evd, "prompt_eval_duration": 1000, "load_duration": 0, "total_duration": 1}
    return 404, {}
server.ollama_json = fake
server.bench_addr = lambda m: None
server.read_env = lambda: {}
server.load_alerts = lambda: {"enabled": True}
sent = []
server.alerts_send = lambda cfg, ev, test=False: sent.append(ev[0]["text"])
class W:
    def __enter__(self): return self
    def __exit__(self, *a): return False
server.egress_window = W
cfgd = mu.config_clean({"keep_days": 5})
def run(name="m:1b"):
    server._mu.update(running=True)
    return server.mu_run([name], "adm", "manuelle")
# 1. mise à jour réussie : la nouvelle version est gardée, l'ancienne reste sous ob-prev/
e = run()[0]
st = server.mu_load()
ok(e["status"] == "updated" and oll["models"]["m:1b"] == "B" * 64 and "ob-prev/m:1b" in oll["models"] and oll["models"]["ob-prev/m:1b"] == "A" * 64 and st["prev"]["m:1b"]["prev"] == "ob-prev/m:1b", "mise à jour réussie : nouvelle version gardée, ancienne conservée sous le nom ob-prev/m:1b")
ok(e["old"] == "A" * 12 and e["new"] == "B" * 12 and e["tps_before"] == 60.0, "historique : empreintes et débit avant")
ok(not any(m["name"].startswith("ob-prev/") for m in server.mu_installed()) and "ob-prev/m:1b" not in server.lab_view()["models"], "les copies de sécurité n'apparaissent dans aucune liste")
# 2. retour arrière manuel
server.mu_rollback("m:1b", "adm")
ok(oll["models"]["m:1b"] == "A" * 64 and "ob-prev/m:1b" not in oll["models"] and "m:1b" not in server.mu_load()["prev"] and server.mu_load()["history"][-1]["status"] == "manual_rollback", "retour arrière manuel : ancienne version rétablie, copie supprimée")
ok(raises(server.mu_rollback, "m:1b", "adm"), "plus de copie : refusé")
# 3. le modèle cassé après mise à jour : retour automatique
oll["broken"] = {"B" * 64}
sent.clear()
e = run()[0]
ok(e["status"] == "rolled_back" and oll["models"]["m:1b"] == "A" * 64 and "ob-prev/m:1b" not in oll["models"] and "m:1b" not in server.mu_load()["prev"] and "réponse vide" in e["detail"], "nouvelle version qui ne répond plus : retour automatique, copie supprimée")
ok(len(sent) == 1 and "ancienne version rétablie" in sent[0], "alerte envoyée après le retour arrière")
oll["broken"] = set()
# 4. débit en chute
oll["slow"] = {"B" * 64}
e = run()[0]
ok(e["status"] == "rolled_back" and "débit en baisse de 75 %" in e["detail"] and oll["models"]["m:1b"] == "A" * 64, "débit en baisse de 75 % : retour automatique")
oll["slow"] = set()
# 5. jeu de tests : régression
sid = server.lab_suite_save({"name": "Contrôle", "model": "m:1b", "cases": [{"prompt": "Capitale ?", "expect": {"contains": ["paris"]}}]})
server.mu_config_set(dict(cfgd, suite=sid))
oll["bad_json"] = True
e = run()[0]
ok(e["status"] == "rolled_back" and "cas de test" in e["detail"] and oll["models"]["m:1b"] == "A" * 64, "jeu de tests : un cas devient faux, retour automatique")
oll["bad_json"] = False
e = run()[0]
runs = server.lab_load()["runs"]
ok(e["status"] == "updated" and [r["reason"] for r in runs[-2:]] == ["avant la mise à jour de m:1b", "après la mise à jour de m:1b"], "jeu de tests réussi : exécuté avant et après")
server.mu_rollback("m:1b", "adm")
# 6. déjà à jour
oll["pull"]["m:1b"] = "A" * 64
e = run()[0]
ok(e["status"] == "unchanged" and "ob-prev/m:1b" not in oll["models"], "déjà à jour : copie supprimée, aucun changement")
# 7. échec du téléchargement
oll["pull"]["m:1b"] = "B" * 64; oll["pull_error"] = True
e = run()[0]
ok(e["status"] == "failed" and "téléchargement" in e["detail"] and oll["models"]["m:1b"] == "A" * 64 and "ob-prev/m:1b" not in oll["models"], "téléchargement impossible : ancienne version intacte, copie supprimée")
oll["pull_error"] = False
# 8. nettoyage des copies expirées
e = run()[0]
d = server.mu_load(); d["prev"]["m:1b"]["t"] = int(time.time()) - 86400 * 9; server.mu_save(d)
ok(server.mu_cleanup() == ["m:1b"] and "ob-prev/m:1b" not in oll["models"] and server.mu_load()["prev"] == {}, "copie de plus de 5 jours supprimée (la nouvelle version reste)")
# 9. démarrage manuel : validations
ok(raises(server.mu_start, [], "adm") and raises(server.mu_start, ["inconnu:1b"], "adm") and raises(server.mu_start, ["a b;"], "adm"), "démarrage : modèles installés exigés")
server._mu["running"] = True
ok(raises(server.mu_start, ["m:1b"], "adm"), "une mise à jour à la fois")
server._mu["running"] = False
view = server.mu_view()
ok(view["config"]["suite"] == sid and view["history"][0]["t"] >= view["history"][-1]["t"] and view["models"] == ["m:1b", "other:2b"] and view["suites"][0]["id"] == sid, "vue : configuration, historique récent d'abord, modèles, jeux de tests")
ok(raises(server.mu_config_set, dict(cfgd, suite="zzzz")) and raises(server.mu_config_set, dict(cfgd, scope=["a b;"])), "configuration : jeu inconnu et modèle invalide refusés")
server.registry_manifest = lambda name: {"digest": "Z" * 64, "layers": ["l1"], "sizes": {"l1": 2_000_000_000}} if name == "m:1b" else {"digest": "C" * 64, "layers": [], "sizes": {}}
chk = {x["name"]: x["update"]["state"] for x in server.mu_check()}
ok(chk == {"m:1b": "maj", "other:2b": "a_jour"}, "vérification : mise à jour disponible pour m:1b seulement")
print("\n%d vérifications réussies" % n)
