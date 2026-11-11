#!/usr/bin/env python3
"""Supervision : débordement CPU/GPU, recommandation de réglages, alertes."""
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import monitor
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
GB = monitor.GB

r = monitor.offload([{"name": "gemma4:12b", "size": 10 * GB, "size_vram": 6 * GB}, {"name": "petit", "size": 2 * GB, "size_vram": 2 * GB}, {"name": "x", "size": 100, "size_vram": 98}])
ok(len(r) == 1 and r[0]["name"] == "gemma4:12b" and r[0]["cpu_pct"] == 40, "débordement : 40 % sur le processeur détecté, 100 % GPU et écart < 5 % ignorés")
ok(monitor.offload([{"name": "a", "size": GB, "size_vram": 0}], has_gpu=False) == [], "machine sans GPU : pas d'alerte")
ok(monitor.offload([{"name": "a", "size": GB, "size_vram": 0}])[0]["cpu_pct"] == 100, "modèle entièrement sur le processeur : 100 %")

# 8 Go de VRAM, modèle de 5 Go, 100 ko de cache par jeton
r = monitor.recommend(8 * GB, 5 * GB, 100 * 1024)
ok(r["fits"] and r["parallel"] * r["ctx"] <= r["tokens"] and r["ctx"] % 1024 == 0 and r["parallel"] >= 1, "recommandation : (contexte x parallélisme) tient dans la mémoire restante")
big = monitor.recommend(24 * GB, 5 * GB, 100 * 1024, ctx_max=32768)
ok(big["parallel"] == 4 and big["ctx"] == 32768, "grosse carte : parallélisme maximal et contexte plafonné à celui du modèle")
ok(monitor.recommend(8 * GB, 9 * GB, 1000) == {"known": True, "fits": False, "tokens": 0, "parallel": 1, "ctx": None}, "poids du modèle > VRAM : « ne tient pas »")
ok(monitor.recommend(0, 1, 1) == {"known": False} and monitor.recommend(8 * GB, 5 * GB, None) == {"known": False}, "données manquantes : inconnu")
tight = monitor.recommend(8 * GB, 6.5 * GB, 1024 * 1024)
ok(tight.get("tight") and tight["parallel"] == 1, "peu de place : un seul en parallèle, signalé serré")

cfg = dict(monitor.DEFAULTS, tps_min=20, events=list(monitor.EVENTS))
snap = {"service": "failed", "disk": {"used": 95, "total": 100}, "gpus": [{"name": "G", "temp": 90}], "offload": [{"name": "m", "cpu_pct": 60}],
        "servers": [{"name": "s1", "online": False}, {"name": "s2", "online": True}], "tps": {"avg": 3.0, "count": 5}, "update": "2026.11.12-0900"}
a = monitor.evaluate(snap, cfg)
ok(set(a) == {"service", "offload:m", "disk", "gpu_temp:G", "tps_low", "server_offline:s1", "update"}, "toutes les alertes se déclenchent : %s" % sorted(a))
ok(monitor.evaluate(snap, dict(cfg, events=["disk"])).keys() == {"disk"}, "seuls les événements choisis sont évalués")
ok("tps_low" not in monitor.evaluate(dict(snap, tps={"avg": 3.0, "count": 2}), cfg) and "tps_low" not in monitor.evaluate(snap, dict(cfg, tps_min=0)), "débit bas : au moins 3 requêtes, seuil 0 = désactivé")
ok(monitor.evaluate({"service": "active", "disk": {"used": 10, "total": 100}}, cfg) == {}, "tout va bien : aucune alerte")

N = monitor.Notifier(hold=120)
act = {"disk": {"severity": "warning", "text": "d"}}
ok(N.step(act, 0) == [] and N.step(act, 60) == [], "pas de notification avant le délai de maintien")
e = N.step(act, 130); ok(len(e) == 1 and e[0]["state"] == "alert", "notification après le délai")
ok(N.step(act, 200) == [], "une alerte déjà notifiée n'est pas renvoyée")
e = N.step({}, 260); ok(len(e) == 1 and e[0]["state"] == "resolved", "résolution notifiée")
ok(N.step(act, 300) == [] and N.step({}, 320) == [], "alerte brève (jamais notifiée) : aucun message, ni à l'apparition ni à la fin")

c = monitor.clean_config({"enabled": True, "webhook": {"url": "https://hooks.example/x"}, "smtp": {"host": "smtp.example", "port": "587", "from": "a@b.fr", "to": ["c@d.fr"], "password": "s3cret"},
                          "events": ["disk", "inconnu"], "disk_pct": 85, "tps_min": 15})
ok(c["events"] == ["disk"] and c["smtp"]["password"] == "s3cret" and c["disk_pct"] == 85 and c["tps_min"] == 15, "configuration validée, événements inconnus écartés")
c2 = monitor.clean_config({"smtp": {"host": "h", "to": ["c@d.fr"], "from": "a@b.fr"}}, old=c); ok(c2["smtp"]["password"] == "s3cret", "mot de passe SMTP conservé s'il n'est pas renvoyé")
for bad in ({"webhook": {"url": "file:///etc/passwd"}}, {"smtp": {"port": 99999}}, {"smtp": {"to": ["pas-un-mail"]}}, {"disk_pct": 5}, {"smtp": {"from": "a@b.fr\nBcc: x@y"}}):
    try: monitor.clean_config(bad); ok(False, "refusée : %s" % bad)
    except ValueError: ok(True, "configuration refusée : %s" % str(bad)[:50])
