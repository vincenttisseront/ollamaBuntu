#!/usr/bin/env python3
"""Laboratoire : comparateur de modèles et jeux de tests de non-régression (module pur + enregistrement côté console, Ollama simulé)."""
import os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import evals
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a); return False
    except ValueError: return True

# --- comparaison : validation
ok(evals.compare_clean(["a:1b", "b:2b"], None, None) == (["a:1b", "b:2b"], evals.COMPARE_PROMPTS[:2], 200), "valeurs par défaut : 2 questions, 200 jetons")
ok(raises(evals.compare_clean, ["a"], ["q"], 100) and raises(evals.compare_clean, ["a", "a"], ["q"], 100) and raises(evals.compare_clean, ["a", "b", "c", "d"], ["q"], 100), "2 ou 3 modèles distincts")
ok(raises(evals.compare_clean, ["a", "b"], [""], 100) and raises(evals.compare_clean, ["a", "b"], ["x" * 2001], 100) and raises(evals.compare_clean, ["a", "b"], ["q"], 5) and raises(evals.compare_clean, ["a", "b"], ["q"] * 6, 100), "questions et longueur bornées")
# --- mesures
gen = lambda txt, ev=100, evd=2_000_000_000: {"response": txt, "eval_count": ev, "eval_duration": evd, "prompt_eval_duration": 100_000_000, "load_duration": 400_000_000, "total_duration": 3_000_000_000}
r = evals.compare_row("m", 0, gen("Bonjour"), {"size": 1000, "size_vram": 500})
ok(r["tps"] == 50.0 and r["ttft_ms"] == 500 and r["vram_pct"] == 50 and r["tokens"] == 100, "débit, délai avant le 1er jeton (chargement compris) et part en mémoire vidéo")
ok(evals.compare_row("m", 0, gen("x" * 5000))["truncated"] and len(evals.compare_row("m", 0, gen("x" * 5000))["response"]) == 4000, "réponse tronquée à 4000 caractères")
rows = [evals.compare_row("a", 0, gen("le chat dort sur le canapé", 100, 1_000_000_000)), evals.compare_row("a", 1, gen("deux plus deux font quatre", 100, 1_000_000_000)),
        evals.compare_row("b", 0, gen("le chat dort sur le canapé", 50, 1_000_000_000)), evals.compare_row("b", 1, gen("la capitale est Paris", 50, 1_000_000_000))]
rows[1]["ttft_ms"] = 100; rows[0]["ttft_ms"] = 900
sm = evals.compare_summary(["a", "b"], rows)
ok(sm["best"]["tps"] == "a" and sm["models"][0]["tps"] == 100.0 and sm["models"][0]["ttft_ms"] == 100, "plus rapide : a ; délai : la 1re question (chargement) est écartée")
ok(sm["models"][1]["similarity"] is not None and 0 < sm["models"][1]["similarity"] < 100 and sm["models"][0]["similarity"] is None, "recouvrement avec le modèle de référence (le 1er)")
ok(evals.similarity("a b c d", "a b c d") == 100 and evals.similarity("chat chien", "voiture train") == 0, "recouvrement : identique 100, disjoint 0")
# --- critères
good = evals.expect_clean({"contains": "Paris\nFrance", "not_contains": ["Londres"], "json": False, "max_chars": 300, "language": "fr"})
ok(good == {"contains": ["Paris", "France"], "not_contains": ["Londres"], "max_chars": 300, "language": "fr"}, "critères normalisés (liste de lignes acceptée)")
ok(raises(evals.expect_clean, {"regex": "("}) and raises(evals.expect_clean, {"language": "de"}) and raises(evals.expect_clean, {"max_chars": "abc"}) and raises(evals.expect_clean, {"contains": ["x"] * 11}), "critères invalides refusés")
txt = "La capitale de la France est Paris, une grande ville pleine de monuments et de musées."
ok(evals.check_expect(txt, good) == (True, []), "réponse conforme")
ko, why = evals.check_expect("The capital of France is Paris and it is the biggest city in the country.", good)
ok(not ko and any("langue" in w for w in why), "langue anglaise détectée quand le français est exigé")
ok(evals.check_expect("Londres est belle", {"not_contains": ["londres"]})[0] is False and evals.check_expect("rien", {"contains": ["PARIS"]})[0] is False, "contains / not_contains insensibles à la casse")
ok(evals.check_expect('```json\n{"a": 1}\n```', {"json": True})[0] and not evals.check_expect("pas du json", {"json": True})[0], "JSON valide (balises ```json tolérées)")
ok(evals.check_expect("prix : 42 euros", {"regex": r"\d+\s*euros"})[0] and not evals.check_expect("rien", {"regex": r"\d+"})[0], "expression régulière")
ok(not evals.check_expect("court", {"min_chars": 50})[0] and not evals.check_expect("long" * 100, {"max_chars": 50})[0], "longueurs minimale et maximale")
# --- jeux de tests
suite = evals.suite_clean({"name": " Contrôle ", "model": "m:1b", "auto": 1, "cases": [{"prompt": "Capitale de la France ?", "expect": {"contains": ["paris"]}}, {"name": "JSON", "prompt": "Donne {\"a\":1}", "expect": {"json": True}}]})
ok(suite["name"] == "Contrôle" and suite["auto"] is True and suite["cases"][0]["name"] == "Cas 1" and suite["cases"][1]["name"] == "JSON", "jeu normalisé (noms par défaut)")
ok(raises(evals.suite_clean, {"name": "", "cases": []}) and raises(evals.suite_clean, {"name": "x", "cases": [{"prompt": "q", "expect": {}}]}) and raises(evals.suite_clean, {"name": "x", "cases": [{"prompt": "", "expect": {"json": True}}]}), "jeu sans nom, sans cas, sans critère ou sans question refusé")
c = evals.case_result(suite["cases"][0], gen("Paris."))
ok(c["ok"] and c["tps"] == 50.0, "résultat d'un cas")
prev = {"t": 1, "results": [{"name": "A", "ok": True}, {"name": "B", "ok": False}, {"name": "C", "ok": True}], "summary": {"tps": 50}}
cur = {"results": [{"name": "A", "ok": False}, {"name": "B", "ok": True}, {"name": "C", "ok": True}], "summary": {"tps": 45}}
d = evals.compare_runs(prev, cur)
ok(d["regressions"] == ["A"] and d["fixed"] == ["B"] and d["tps_pct"] == -10.0 and d["degraded"], "régression repérée, cas réparé, variation du débit")
ok(not evals.compare_runs(prev, {"results": prev["results"], "summary": {"tps": 40}})["degraded"] and evals.compare_runs(prev, {"results": prev["results"], "summary": {"tps": 30}})["degraded"], "chute de débit de 30 % ou plus = dégradation")
ok(evals.compare_runs(None, cur) is None and evals.run_summary([{"ok": True, "tps": 10, "ttft_ms": 5}, {"ok": False, "error": "x"}]) == {"total": 2, "passed": 1, "errors": 1, "tps": 10, "ttft_ms": 5}, "première exécution sans comparaison ; résumé")

# --- côté console : enregistrement, exécution (Ollama simulé), rejeu automatique
import server
tmp = tempfile.mkdtemp()
server.LAB_FILE = os.path.join(tmp, "lab.json")
ids = {}
sid = server.lab_suite_save({"name": "Contrôle", "model": "m:1b", "auto": True, "cases": [{"prompt": "Capitale ?", "expect": {"contains": ["paris"]}}]})
ok(len(sid) == 8 and oct(os.stat(server.LAB_FILE).st_mode & 0o777) == "0o600", "jeu enregistré (fichier réservé à root)")
sid2 = server.lab_suite_save({"id": sid, "name": "Contrôle 2", "model": "m:1b", "auto": True, "cases": [{"prompt": "Capitale ?", "expect": {"contains": ["paris"]}}]})
ok(sid2 == sid and [x["name"] for x in server.lab_load()["suites"]] == ["Contrôle 2"], "modification d'un jeu existant")
ok(raises(server.lab_suite_save, {"id": "zzzz", "name": "x", "cases": [{"prompt": "q", "expect": {"json": True}}]}), "jeu inconnu refusé")
state = {"answer": "Paris est la capitale."}
def fake_ollama(method, path, body=None, timeout=5, addr=None):
    if path == "/api/generate":
        return 200, {"response": state["answer"] if "Capitale" in body["prompt"] else "Londres.", "eval_count": 60, "eval_duration": 1_000_000_000, "prompt_eval_duration": 50_000_000, "load_duration": 0, "total_duration": 1_200_000_000}
    if path == "/api/ps":
        return 200, {"models": [{"name": body and body.get("model") or "m:1b", "size": 100, "size_vram": 100}]}
    if path == "/api/tags":
        return 200, {"models": [{"name": "m:1b"}, {"name": "n:2b"}, {"name": "x-cloud"}, {"name": "m-gpu0"}]}
    return 404, {}
server.ollama_json = fake_ollama
server.bench_addr = lambda model: None
server.read_env = lambda: {}
server.load_alerts = lambda: {"enabled": False}
sent = []
server.alerts_send = lambda cfg, ev, test=False: sent.append(ev)
def wait(key):
    t = time.time()
    while server._lab[key]["running"] and time.time() - t < 10: time.sleep(0.05)
server.lab_eval_start(sid, None, "adm"); wait("eval")
d = server.lab_load()
ok(len(d["runs"]) == 1 and d["runs"][0]["summary"]["passed"] == 1 and d["runs"][0]["diff"] is None and d["runs"][0]["who"] == "adm", "1re exécution : réussie, sans comparaison")
state["answer"] = "Je ne sais pas."
server.lab_eval_start(sid, None, "adm"); wait("eval")
last = server.lab_load()["runs"][-1]
ok(last["summary"]["passed"] == 0 and last["diff"]["regressions"] == ["Cas 1"] and last["diff"]["degraded"], "2e exécution : régression détectée")
ok(raises(server.lab_eval_start, "zzz", "m", "adm") and raises(server.lab_eval_start, sid, "", "adm") is False, "jeu inconnu refusé ; modèle repris du jeu")
wait("eval")
server.lab_autorun("le profil « test »")
t = time.time()
while time.time() - t < 10 and len(server.lab_load()["runs"]) < 4: time.sleep(0.05)
last = server.lab_load()["runs"][-1]
ok(len(server.lab_load()["runs"]) >= 4 and last["who"] == "automatique" and "profil" in last["reason"], "rejeu automatique après un changement de profil")
view = server.lab_view()
ok(view["models"] == ["m:1b", "n:2b"] and view["suites"][0]["id"] == sid and view["runs"][0]["t"] >= view["runs"][-1]["t"], "vue : modèles installés (hors cloud et copies de GPU), jeux, exécutions récentes d'abord")
server.lab_compare_start(["m:1b", "n:2b"], ["Capitale ?"], 64); wait("cmp")
cmpd = server.lab_load()["compare"]
ok(cmpd and len(cmpd["rows"]) == 2 and cmpd["summary"]["models"][0]["model"] == "m:1b" and not server._lab["cmp"]["error"], "comparaison exécutée et enregistrée")
ok(raises(server.lab_compare_start, ["m:1b"], None, None) and raises(server.lab_compare_start, ["m:1b", "a b;"], None, None), "comparaison : 2 modèles valides exigés")
server.lab_suite_delete(sid)
ok(server.lab_load()["suites"] == [] and server.lab_load()["runs"] == [], "suppression d'un jeu : ses exécutions aussi")
print("\n%d vérifications réussies" % n)
