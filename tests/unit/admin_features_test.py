#!/usr/bin/env python3
"""Console : limites par clé, règles de routage, réglages recommandés, test du parc, alertes (dépendances simulées)."""
import json, os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a); return False
    except ValueError: return True
tmp = tempfile.mkdtemp(); GB = 1024 ** 3

# --- limites par clé
ok(server.validate_limits({"max_concurrent": "3", "quota_day": 1000}) == {"max_concurrent": 3, "quota_day": 1000, "quota_month": 0, "max_ctx": 0, "max_output": 0}, "limites : valeurs lues, absentes = 0 (sans limite)")
ok(server.validate_limits({"quota_day": 5}, {"max_concurrent": 2}) == {"quota_day": 5}, "mise à jour partielle : seuls les champs envoyés changent")
ok(raises(server.validate_limits, {"max_concurrent": 999}) and raises(server.validate_limits, {"quota_day": -1}) and raises(server.validate_limits, {"quota_day": "abc"}), "limites hors bornes ou invalides refusées")

# --- règles de routage
server.RULES_FILE = os.path.join(tmp, "rules.json")
server.load_publication = lambda: {"keys": [{"id": "k1", "name": "RH"}]}
server.load_fleet = lambda: [{"id": "s1", "name": "Srv1", "route_token": "t", "url": "https://x", "fingerprint": "F", "model_map": {"*": "granite:8b"}}, {"id": "s2", "name": "Sans", "url": "https://y"}]
server.write_fleet_routes = lambda: None
server.rules_save([{"key": "k1", "model": "Gemma*", "server": "s1", "mode": "only"}, {"key": "*", "model": "*", "server": "local", "mode": "never"}])
saved = server.load_rules(); ok(len(saved) == 2 and saved[0]["model"] == "gemma*", "règles enregistrées (motif en minuscules)")
ok(oct(os.stat(server.RULES_FILE).st_mode & 0o777) == "0o600", "fichier de règles réservé à root")
for bad in ([{"key": "zz", "model": "*", "server": "s1", "mode": "only"}], [{"key": "*", "model": "*", "server": "s2", "mode": "only"}], [{"key": "*", "model": "*", "server": "local", "mode": "peut-être"}],
            [{"key": "*", "model": "a b;rm", "server": "local", "mode": "only"}], "pas une liste", [{"key": "*", "model": "*", "server": "local", "mode": "only"}] * 101):
    ok(raises(server.rules_save, bad), "règle refusée : %s" % str(bad)[:60])

# --- réglages recommandés
server.gpu_metrics = lambda: [{"name": "Quadro RTX 4000", "mem_total": 8 * GB}]
server.context_view = lambda: {"default": None, "parallel": 1, "kv_type": "f16", "models": [{"name": "m:12b", "max": 131072, "bytes_per_token": 200 * 1024}, {"name": "m-gpu0", "max": 1, "bytes_per_token": 1},
                                                                                              {"name": "x-cloud", "max": 1, "bytes_per_token": 1}, {"name": "gros:70b", "max": 8192, "bytes_per_token": 100 * 1024}]}
server.ollama_json = lambda *a, **k: (200, {"models": [{"name": "m:12b", "size": 5 * GB}, {"name": "gros:70b", "size": 40 * GB}]})
t = server.tuning_view(); by = {m["name"]: m for m in t["models"]}
ok(set(by) == {"m:12b", "gros:70b"} and t["vram"] == 8 * GB, "variantes épinglées et modèles cloud écartés")
ok(by["m:12b"]["fits"] and by["m:12b"]["parallel"] * by["m:12b"]["ctx"] <= by["m:12b"]["tokens"], "modèle de 5 Go : réglage qui tient en 8 Go")
ok(by["gros:70b"]["fits"] is False, "modèle de 40 Go : ne tient pas en 8 Go")
applied = {}
server.update_env = lambda ch, restart=True: applied.update(ch)
server.tuning_apply({"parallel": 2, "ctx": 8192}); ok(applied == {"OLLAMA_NUM_PARALLEL": "2", "OLLAMA_CONTEXT_LENGTH": "8192"}, "réglage appliqué (variables d'Ollama)")
ok(raises(server.tuning_apply, {"parallel": 0, "ctx": 8192}) and raises(server.tuning_apply, {"parallel": 2, "ctx": 5}) and raises(server.tuning_apply, {"parallel": "x", "ctx": 1}), "réglage invalide refusé")

# --- limites : vue console
server.ROUTER_LIMITS = os.path.join(tmp, "limits.json")
json.dump({"t": 1, "queue": {"k1": {"running": 2, "waiting": 1}}, "tokens": {"k1": {"day": 10, "month": 20, "total": 30, "req": 3}}}, open(server.ROUTER_LIMITS, "w"))
v = server.limits_view(); ok(v["keys"][0]["running"] == 2 and v["keys"][0]["waiting"] == 1 and v["keys"][0]["month"] == 20 and v["queue_total"] == {"running": 2, "waiting": 1}, "vue des limites : file d'attente et consommation par clé")

# --- test du parc
server.ollama_json = lambda m, p, body=None, **k: (200, {"models": [{"name": "gemma4:12b"}]}) if p == "/api/tags" else (200, {"response": "ok", "eval_count": 8, "eval_duration": 1e8})
server.short_name = server.short_name
server._fleet_state = {"s1": {"state": "en ligne", "data": {"model_tags": [{"name": "granite:8b"}]}}}
calls = []
def fake_req(url, path, token, fp, method, body, timeout=10):
    calls.append(body["model"]); return 200, {"response": "ok", "eval_count": 8, "eval_duration": 2e8}, None
server.fleet_request = fake_req
r = server.fleet_check("gemma4:12b"); by = {x["server"]: x for x in r["results"]}
ok(by["Srv1"]["ok"] and calls == ["granite:8b"] and "remplacement" in by["Srv1"]["note"] and by["Srv1"]["tps"] == 40.0, "serveur avec modèle de remplacement : testé avec le modèle de remplacement, débit mesuré")
ok(by["ce serveur"]["ok"] and by["ce serveur"]["tps"] == 80.0, "ce serveur testé aussi")
server._fleet_state = {"s1": {"state": "hors ligne"}}; r = server.fleet_check("gemma4:12b")
ok([x["error"] for x in r["results"] if x["server"] == "Srv1"] == ["hors ligne"], "serveur hors ligne signalé")

# --- alertes : configuration et envoi
server.ALERTS_FILE = os.path.join(tmp, "alerts.json")
server.alerts_save({"enabled": True, "webhook": {"url": "https://h.example/x"}, "smtp": {"host": "s", "to": ["a@b.fr"], "from": "c@d.fr", "password": "pw"}, "events": ["disk", "offload"]})
ok(oct(os.stat(server.ALERTS_FILE).st_mode & 0o777) == "0o600", "configuration des alertes réservée à root (mot de passe SMTP)")
v = server.alerts_view(); ok(v["config"]["smtp"].get("has_password") is True and "password" not in v["config"]["smtp"], "le mot de passe SMTP n'est jamais renvoyé à la console")
sent = {}
server.monitor.post_webhook = lambda url, payload, timeout=10: sent.update(hook=payload)
server.monitor.send_mail = lambda cfg, pw, subj, body, timeout=15: sent.update(mail=(pw, subj, body))
res = server.alerts_send(server.load_alerts(), [{"state": "alert", "key": "disk", "severity": "warning", "text": "Disque occupé à 95 %"}])
ok(res == {"webhook": "ok", "email": "ok"} and sent["hook"]["events"][0]["key"] == "disk" and sent["mail"][0] == "pw" and "ALERTE" in sent["mail"][2], "envoi par webhook et par e-mail")
def boom(*a, **k): raise OSError("connexion refusée")
server.monitor.post_webhook = boom
res = server.alerts_send(server.load_alerts(), [{"state": "alert", "key": "x", "severity": "info", "text": "t"}]); ok(res["webhook"] == "connexion refusée" and res["email"] == "ok", "un canal en échec n'empêche pas l'autre")
