import os, sys, json, time, shutil
sys.dont_write_bytecode = True   # ne laisse aucun fichier compilé dans src/
ETC = "/tmp/rta-bal-etc"; shutil.rmtree(ETC, ignore_errors=True); os.makedirs(ETC); os.environ["OB_ETC"] = ETC
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")); import router
H = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates")); n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
router.local_models = lambda: {"names": {router.norm("ob-tiny"), router.norm("autre")}, "tags": []}
def srv(i, models, load=3.1, loaded=(), online=True):
    return {"id": "s%d" % i, "name": "Srv%d" % i, "online": online, "models": [{"name": m} for m in models], "loaded": list(loaded), "load": load, "url": "", "fingerprint": "", "token": ""}
def pick(model, fl, release=True):
    c = H.candidates(router.norm(model), fl)[0]; key = "local" if c[0] == "local" else c[3]["id"]
    if release: router.inflight_add(key, -1)   # la requête se termine aussitôt
    return key
def reset(): router._inflight.clear(); router._rr.clear()
def conf(name, data):
    p = os.path.join(ETC, name); open(p, "w").write(json.dumps(data)); conf.k += 2; t = time.time() + conf.k; os.utime(p, (t, t))
conf.k = 0
def tally(keys): return {k: keys.count(k) for k in sorted(set(keys))}
# --- stratégie « répartir » (défaut) : les situations qui bloquaient la répartition
reset(); fl = {"local": {"load": 0.0, "loaded": ["ob-tiny:latest"]}, "servers": [srv(1, ["ob-tiny:latest"])]}
t = tally([pick("ob-tiny", fl) for _ in range(8)]); ok(router.balance_strategy() == "spread" and t == {"local": 4, "s1": 4}, "défaut « répartir » : modèle déjà chargé en local, 8 requêtes l'une après l'autre -> %s (avant : 8 en local)" % t)
reset(); fl = {"local": {"load": 0.0, "loaded": []}, "servers": [srv(1, ["ob-tiny:latest"], load=3.1)]}
t = tally([pick("ob-tiny", fl) for _ in range(8)]); ok(t == {"local": 4, "s1": 4}, "serveur local sans GPU (charge 0) et distant à 3,1 %% de processeur : %s (avant : 8 en local)" % t)
reset(); router._inflight["local"] = 2; fl = {"local": {"load": 0.0, "loaded": ["ob-tiny:latest"]}, "servers": [srv(1, ["ob-tiny:latest"])]}
seq = [pick("ob-tiny", fl, release=False) for _ in range(6)]; ok(seq[:2] == ["s1", "s1"] and tally(seq) == {"local": 2, "s1": 4}, "ce serveur a déjà 2 requêtes en cours : les suivantes vont au serveur libre, puis alternent %s" % seq)
reset(); fl = {"local": {"load": 0.0, "loaded": []}, "servers": [srv(1, ["ob-tiny:latest"])]}
seq = [pick("ob-tiny", fl, release=False) for _ in range(4)]; ok(tally(seq) == {"local": 2, "s1": 2} and router._inflight == {"local": 2, "s1": 2}, "4 requêtes simultanées : 2 et 2, réservées d'un seul geste (%s)" % router._inflight)
reset(); fl = {"local": {"load": 0.0, "loaded": []}, "servers": [srv(1, ["ob-tiny:latest", "autre:latest"])]}
a, b = [], []
for _ in range(6): a.append(pick("ob-tiny", fl)); b.append(pick("autre", fl))
ok(tally(a) == {"local": 3, "s1": 3} and tally(b) == {"local": 3, "s1": 3}, "deux modèles qui alternent (A, B, A, B...) : chacun est réparti 3 et 3 (tour de rôle propre à chaque modèle)")
reset(); fl = {"local": {"load": 0.0, "loaded": []}, "servers": [srv(1, ["ob-tiny:latest"], online=False)]}
ok(tally([pick("ob-tiny", fl) for _ in range(4)]) == {"local": 4} and router._inflight.get("local", 0) == 0, "serveur hors ligne : tout reste en local, aucune réservation perdue")
reset(); fl = {"local": {"load": 0.0, "loaded": []}, "servers": [srv(1, ["ob-tiny:latest"])]}
c = H.candidates(router.norm("autre"), fl); ok([x[0] for x in c] == ["local"] and not router._inflight, "modèle absent du serveur distant : local seul, aucune réservation")
reset(); s1 = srv(1, ["granite:8b"]); s1["model_map"] = {"autre:latest": "granite:8b"}; fl = {"local": {"load": 0.0, "loaded": []}, "servers": [s1]}
c = H.candidates(router.norm("autre"), fl); ok(sorted(x[0] for x in c) == ["local", "remote"] and [x[3]["use_model"] for x in c if x[0] == "remote"] == ["granite:8b"], "modèle de remplacement : le serveur aux GPU différents devient candidat avec son propre modèle")
reset(); s1 = srv(1, ["granite:8b"]); s1["model_map"] = {"*": "granite:8b"}; fl = {"local": {"load": 0.0, "loaded": []}, "servers": [s1]}
ok(len([x for x in H.candidates(router.norm("autre"), fl) if x[0] == "remote"]) == 1, "remplacement « * » : tout modèle absent est redirigé")
reset(); s1 = srv(1, ["granite:8b"]); s1["model_map"] = {"autre:latest": "absent:1b"}; fl = {"local": {"load": 0.0, "loaded": []}, "servers": [s1]}
ok([x[0] for x in H.candidates(router.norm("autre"), fl)] == ["local"], "remplacement absent du serveur : ignoré")
# --- stratégie « modèle déjà chargé »
conf("balance.json", {"strategy": "warm"}); ok(router.balance_strategy() == "warm", "stratégie lue à chaud depuis balance.json")
reset(); fl = {"local": {"load": 5.0, "loaded": ["ob-tiny:latest"]}, "servers": [srv(1, ["ob-tiny:latest"])]}
ok(tally([pick("ob-tiny", fl) for _ in range(8)]) == {"local": 8}, "« modèle chargé » : 8 requêtes calmes restent sur le serveur qui a le modèle en mémoire")
reset(); router._inflight["local"] = 2
ok(pick("ob-tiny", fl, release=False) == "s1", "« modèle chargé » : ce serveur a 2 requêtes en cours, le serveur libre prend la suivante (charger le modèle vaut moins que d'attendre)")
reset(); router._inflight["local"] = 1
ok(pick("ob-tiny", fl, release=False) == "local", "« modèle chargé » : avec 1 seule requête en cours, on garde le modèle chargé")
reset(); fl = {"local": {"load": 60.0, "loaded": ["ob-tiny:latest"]}, "servers": [srv(1, ["ob-tiny:latest"], load=10.0, loaded=["ob-tiny:latest"])]}
ok(pick("ob-tiny", fl) == "s1", "« modèle chargé » : modèle chargé des deux côtés, le moins chargé (GPU) l'emporte")
os.remove(os.path.join(ETC, "balance.json")); t0 = time.time() + 99; 
conf("balance.json", {"strategy": "n'importe quoi"}); ok(router.balance_strategy() == "spread", "valeur inconnue dans balance.json : retour au défaut « répartir »")
# --- extrait de la demande
ex = lambda path, d, chars=120: router.prompt_excerpt(path, json.dumps(d).encode(), chars)
ok(ex("/api/generate", {"prompt": "  Bonjour\n  le   monde "}) == "Bonjour le monde", "extrait : /api/generate, espaces normalisés")
ok(ex("/api/chat", {"messages": [{"role": "system", "content": "CONSIGNE SECRETE"}, {"role": "user", "content": "première"}, {"role": "assistant", "content": "réponse"}, {"role": "user", "content": "dernière question"}]}) == "dernière question", "extrait : /api/chat, seule la dernière question de l'utilisateur (ni consigne système ni réponses)")
ok(ex("/v1/chat/completions", {"messages": [{"role": "user", "content": [{"type": "text", "text": "décris"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]}) == "décris", "extrait : API compatible OpenAI avec image, texte seul")
ok(ex("/api/embed", {"input": ["a", "b"]}) == "(embeddings) a b", "extrait : embeddings signalés comme tels")
r = ex("/api/chat", {"messages": [{"role": "user", "content": "x" * 500}]}, 80); ok(len(r) == 80 and r.endswith("…"), "extrait : coupé à la longueur choisie (80)")
secret = "IBAN FR7630006000011234567890189 ou FR76 3000 6000 0112 3456 7890 189, carte 4970 1012 3456 7890, clé sk-abcdefghijklmnop1234, jeton obf_abcdefghijklmnopqrstuvwx, Bearer abcdefghijklmnop1234, mail jean.martin+rh@exemple.fr"
r = ex("/api/generate", {"prompt": secret}, 300)
bad = [x for x in ("FR76", "4970", "abcdefghij", "jean.martin", "exemple.fr") if x in r]
ok(not bad and all(x in r for x in ("[IBAN]", "[numéro]", "[clé]", "[jeton]", "[e-mail]")), "masquage : IBAN, carte, clés, jetons et e-mail remplacés -> « %s »" % r[:110])
ok(ex("/api/generate", "pas un objet") == "" and router.prompt_excerpt("/api/chat", b"pas du json", 80) == "", "corps invalide : aucun extrait, aucune erreur")
ok(router.reqlog_conf()["prompt_excerpt"] is False, "extrait désactivé par défaut")
conf("request-log.json", {"prompt_excerpt": True, "chars": 60}); ok(router.reqlog_conf() == {"prompt_excerpt": True, "chars": 60}, "réglage lu à chaud (activé, 60 caractères)")
conf("request-log.json", {"prompt_excerpt": "oui", "chars": 99999}); c = router.reqlog_conf(); ok(c["prompt_excerpt"] is False and c["chars"] == 300, "valeurs hors norme : ni activation par erreur (« oui » refusé), ni longueur démesurée (plafond 300)")
