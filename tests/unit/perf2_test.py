#!/usr/bin/env python3
"""Accélération (fonctions pures) : préchauffage prédictif, mesure continue et diagnostic, parallélisme adaptatif, contrôles machine."""
import os, sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import perf
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
def at(y, mo, d, h, mi=0): return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))
# 2026-11-13 est un vendredi ; 2026-11-14 un samedi
def lt(y, mo, d, h, mi): return time.localtime(at(y, mo, d, h, mi))

# ----------------------------------------------------------- préchauffage prédictif
st = {}
reqs = []
for day in (2, 3, 4, 5, 6, 9, 10, 11, 12):   # jours ouvrés de novembre 2026 : gemma à 8 h, qwen à 8 h seulement 2 jours, coder à 14 h
    reqs += [{"ts": at(2026, 11, day, 8, 15), "model": "gemma4:12b", "status": 200}, {"ts": at(2026, 11, day, 14, 5), "model": "coder:7b", "status": 200}]
    if day in (2, 3): reqs.append({"ts": at(2026, 11, day, 8, 40), "model": "qwen3:14b", "status": 200})
reqs += [{"ts": at(2026, 11, 7, 11, 0), "model": "gemma4:12b", "status": 200}, {"ts": at(2026, 11, 3, 8, 20), "model": "gemma4:12b", "status": 500},
         {"ts": at(2026, 11, 4, 8, 20), "model": "gemma4:12b", "status": 200, "cached": True}]
perf.hours_add(st, reqs)
ok(st["gemma4:12b"]["2026-11-02"][8] == 1 and sum(st["gemma4:12b"]["2026-11-03"]) == 1, "compteurs par modèle, jour et heure locale (les erreurs et les réponses du cache ne comptent pas)")
ok(all(isinstance(v, list) and len(v) == 24 for d in st.values() for v in d.values()) and not any("prompt" in str(st) for _ in [0]), "seuls des compteurs sont conservés")
ok(perf.warm_predict(st, lt(2026, 11, 13, 7, 40)) == [], "trop tôt avant l'heure visée : rien")
p = perf.warm_predict(st, lt(2026, 11, 13, 7, 52))
ok([x["model"] for x in p] == ["gemma4:12b"] and p[0]["hour"] == 8 and p[0]["hits"] == 9 and p[0]["days"] == 9, "à 7 h 52 un jour ouvré : gemma, utilisé 9 jours sur 9 à 8 h, est préchargé")
ok(all(x["model"] != "qwen3:14b" for x in p), "qwen3 (2 jours seulement) : pas assez régulier")
ok(perf.warm_predict(st, lt(2026, 11, 13, 7, 52), loaded=["gemma4:12b"]) == [], "déjà en mémoire : rien à faire")
ok([x["model"] for x in perf.warm_predict(st, lt(2026, 11, 13, 13, 55))] == ["coder:7b"], "13 h 55 : le modèle de l'après-midi")
ok(perf.warm_predict(st, lt(2026, 11, 14, 7, 55)) == [], "samedi : les jours ouvrés ne comptent pas pour un week-end")
ok(perf.warm_predict(st, lt(2026, 11, 13, 23, 55)) == [], "23 h 55 : l'heure visée est minuit, aucun historique")
ok(perf.warm_predict({}, lt(2026, 11, 13, 7, 52)) == [], "pas d'historique : rien")
ok(len(perf.warm_predict(st, lt(2026, 11, 13, 7, 52), cfg={"enabled": True, "min_days": 2, "max_models": 1})) == 1, "nombre de modèles limité")
for bad in ({"lead": 1}, {"max_models": 9}, {"min_days": "x"}):
    try: perf.predict_clean(bad); ok(False, "réglage invalide accepté")
    except ValueError: pass
ok(perf.predict_clean({})["enabled"] is False and perf.predict_clean({"enabled": True})["lead"] == 10, "prédiction désactivée par défaut ; réglages validés")
old = {"m": {"2020-01-01": [1] * 24}}; perf.hours_add(old, [])
ok(old == {}, "les jours trop anciens sont retirés")

# ----------------------------------------------------------- mesure continue
c = perf.bench_auto_clean({"enabled": True, "at": "02:45", "models": ["a:1b", "a:1b", "pas bon!", "b:2b"], "tolerance": 20})
ok(c["enabled"] and c["at"] == "02:45" and c["models"] == ["a:1b", "b:2b"] and c["tolerance"] == 20 and c["recalibrate"] is True, "réglages de la mesure continue validés (noms dédoublés ou invalides retirés)")
for bad in ({"at": "25:00"}, {"tolerance": 2}, {"tolerance": "x"}):
    try: perf.bench_auto_clean(bad); ok(False, "invalide accepté : %s" % bad)
    except ValueError: pass
last = {}
ok(not perf.bench_auto_due(perf.bench_auto_clean({}), lt(2026, 11, 13, 3, 30), last), "désactivée : jamais")
cfg = perf.bench_auto_clean({"enabled": True, "at": "03:30"})
ok(perf.bench_auto_due(cfg, lt(2026, 11, 13, 3, 30), last) and not perf.bench_auto_due(cfg, lt(2026, 11, 13, 3, 30), last), "déclenchée une seule fois par jour")
ok(not perf.bench_auto_due(cfg, lt(2026, 11, 13, 3, 31), last) and perf.bench_auto_due(cfg, lt(2026, 11, 14, 3, 30), last) and list(last) == ["2026-11-14"], "le lendemain à l'heure dite ; l'état est nettoyé")
cf = {"kv": "q8_0", "fa": True, "parallel": "2", "ctx": "auto"}
hist = [{"model": "m", "tps": t, "cfg": cf} for t in (70, 72, 71, 69, 73)] + [{"model": "autre", "tps": 5, "cfg": cf}]
cur = {"model": "m", "tps": 52, "cfg": cf, "vram_pct": 84, "ttft_ms": 900}
ok(perf.bench_baseline(hist, cur) == 71, "débit habituel : médiane des mesures précédentes du même modèle")
r = perf.bench_regression(hist, cur, 15)
ok(r and r["baseline"] == 71 and r["current"] == 52 and r["pct"] == -26.8, "baisse de 27 % détectée (tolérance 15 %)")
ok(perf.bench_regression(hist, dict(cur, tps=65), 15) is None and perf.bench_regression(hist[:1], cur) is None, "dans la tolérance, ou pas assez d'historique : pas d'alerte")
ok(perf.bench_baseline(hist, dict(cur, cfg=dict(cf, kv="f16"))) is None, "réglages différents : pas comparable")
prev = {"model": "m", "tps": 71, "cfg": cf, "vram_pct": 100, "ttft_ms": 400, "sys": {"kernel": "6.8.0-45", "ollama": "0.5.1", "driver": "mesa 24.0"}}
cur2 = dict(cur, sys={"kernel": "6.8.0-48", "ollama": "0.5.1", "driver": "mesa 24.2", "gpu_temp": 88}, ram_used=15.2e9, ram_total=16e9)
hs = perf.diagnose(cur2, prev)
txt = " ".join(hs)
ok("84 %" in txt and "contre 100 %" in txt and "88 °C" in txt and "6.8.0-45 -> 6.8.0-48" in txt and "mesa 24.0 -> mesa 24.2" in txt and "mémoire vive est presque pleine" in txt and "Ollama a changé" not in txt, "diagnostic : débordement, chaleur, noyau et pilote changés, mémoire pleine")
ok(any("délai avant le premier jeton" in h for h in hs), "diagnostic : premier jeton plus lent sans rechargement")
ok(perf.diagnose(dict(prev), prev) == [], "rien de changé : aucun diagnostic")
ok(any("réglages d'Ollama" in h for h in perf.diagnose(dict(prev, cfg=dict(cf, kv="f16")), prev)), "diagnostic : réglages modifiés")

# ----------------------------------------------------------- parallélisme adaptatif
now = 100000.0
def row(t, ms, ttft=300): return {"ts": t, "ms": ms, "ttft_ms": ttft, "status": 200, "instance": "127.0.0.1:11400"}
solo = [row(now - 80000 + i * 100, 3000, 300) for i in range(30)]
ok(perf.concurrency_profile(solo, now)["peak"] == 1 and perf.concurrency_profile(solo, now)["overlap_pct"] == 0, "requêtes qui ne se chevauchent jamais : pic de 1, 0 % de chevauchement")
busy = [row(now - 5000 + i * 2, 8000, 1400) for i in range(15)] + solo
pr = perf.concurrency_profile(busy, now)
ok(pr["peak"] >= 4 and 20 <= pr["overlap_pct"] <= 60 and pr["busy_ttft"] == 1400 and pr["solo_ttft"] == 300, "chevauchement mesuré : pic, part des demandes chevauchées, délais seul / en concurrence")
ok(perf.concurrency_profile(solo + [dict(row(now - 100, 5000), cached=True), dict(row(now - 90, 5000), status=500)], now)["requests"] == 30, "les erreurs et les réponses du cache ne comptent pas")
G = 1024 ** 3
a = perf.parallel_advice(pr, 1, 6 * G, 1 * G)
ok(a and a["to"] == 2 and a["why"] == "overlap" and "300 ms" in a["text"] and "1400 ms" in a["text"], "demandes qui se chevauchent et mémoire libre : passer à 2, avec les délais mesurés")
a = perf.parallel_advice(pr, 1, 0.5 * G, 1 * G)
ok(a and a["to"] is None and a["why"] == "memory", "pas assez de mémoire vidéo libre : on explique pourquoi on ne propose rien")
ok(perf.parallel_advice(pr, 4, 9 * G, G) is None, "déjà au plafond : rien")
a = perf.parallel_advice(perf.concurrency_profile(solo, now), 3, 2 * G, 1.5 * G)
ok(a and a["to"] == 2 and a["why"] == "unused" and "1.5 Go" in a["text"], "jamais de chevauchement avec 3 emplacements : en retirer un libère de la mémoire")
ok(perf.parallel_advice(perf.concurrency_profile(solo[:5], now), 3, 2 * G, G) is None, "trop peu de demandes : pas de conseil")
ok(perf.parallel_clean({"mode": "auto"})["mode"] == "auto" and perf.parallel_clean({"mode": "x"})["mode"] == "suggest", "mode par défaut : suggérer")

# ----------------------------------------------------------- contrôles machine
base = {"swappiness": 10, "governors": ["performance"], "mem_total": 32 * G, "swap_total": 0, "zram": True, "webui": {}}
ids = lambda s, **kw: {c["id"]: c for c in perf.sys_checks(dict(base, **kw))}
ch = ids(None, gpu_power=[{"card": "card0", "name": "AMD Radeon RX 7800 XT", "level": "auto"}])
ok(ch["gpu_power:card0"]["state"] == "info" and ch["gpu_power:card0"]["fix"] == "amd_power", "carte AMD en mode automatique : réglage proposé")
ok(ids(None, gpu_power=[{"card": "card0", "level": "low"}])["gpu_power:card0"]["state"] == "warn" and ids(None, gpu_power=[{"card": "card0", "level": "high"}])["gpu_power:card0"]["state"] == "ok", "bridée : alerte ; fréquences fixées : ok")
ch = ids(None, rebar={"checked": True, "enabled": False, "bar_gb": 0.25, "vram_gb": 16})
ok(ch["rebar"]["state"] == "info" and "BIOS" in ch["rebar"]["text"] and ids(None, rebar={"checked": True, "enabled": True, "bar_gb": 16})["rebar"]["state"] == "ok" and "rebar" not in ids(None, rebar={"checked": False}), "Resizable BAR : désactivé -> consigne BIOS ; non vérifiable -> rien")
ch = ids(None, memory={"dimms": 1, "rated": 3200, "configured": 2133})
ok(ch["mem_channels"]["state"] == "warn" and ch["mem_speed"]["state"] == "warn" and "2133" in ch["mem_speed"]["text"] and "XMP" in ch["mem_speed"]["text"], "une barrette et mémoire sous-cadencée : deux alertes")
ch = ids(None, memory={"dimms": 2, "rated": 3200, "configured": 3200})
ok("mem_channels" not in ch and ch["mem_speed"]["state"] == "ok", "double canal à pleine vitesse : ok")
ch = ids(None, pcie=[{"card": "card0", "name": "GPU", "width": 4, "max_width": 16}, {"card": "card1", "width": 16, "max_width": 16}])
ok(ch["pcie:card0"]["state"] == "warn" and "x4" in ch["pcie:card0"]["text"] and "pcie:card1" not in ch, "lien PCIe réduit : alerte ; lien complet : silence")
ok(all(c["id"] for c in perf.sys_checks(base)), "contrôles existants inchangés")
print("\n%d vérifications réussies" % n)
