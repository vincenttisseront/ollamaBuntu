#!/usr/bin/env python3
"""Troisième lot : performances — mesure de débit, profils, contrôles système, préchauffage, garde-fou de débit."""
import json, os, sys, tempfile, time
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, os.path.join(LIB, "admin")); sys.path.insert(0, LIB)
tmp = tempfile.mkdtemp()
os.environ["OB_SYS_ROOT"] = tmp; os.environ["OB_ETC"] = os.path.join(tmp, "etc"); os.environ["OB_STATE"] = os.path.join(tmp, "state")
import perf, monitor, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a, exc=ValueError):
    try: f(*a); return False
    except exc: return True

# --- mesure
gen = {"eval_count": 128, "eval_duration": 2_000_000_000, "prompt_eval_count": 30, "prompt_eval_duration": 150_000_000, "load_duration": 850_000_000}
r = perf.bench_result("m:7b", gen, {"size": 5_000_000_000, "size_vram": 4_000_000_000}, {"used": 8 << 30, "total": 32 << 30}, {"OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_FLASH_ATTENTION": "1"}, now=1000)
ok(r["tps"] == 64.0 and r["ttft_ms"] == 1000 and r["load_ms"] == 850 and r["prompt_tps"] == 200.0, "débit, délai avant le premier jeton (chargement + analyse du prompt)")
ok(r["vram_pct"] == 80 and r["cfg"] == {"kv": "q8_0", "fa": True, "parallel": "auto", "ctx": "auto"}, "part en mémoire vidéo et réglages en vigueur consignés")
ok(raises(perf.bench_result, "m", {"eval_count": 0}), "réponse sans mesure refusée")
runs = [dict(r, tps=t, ttft_ms=x, load_ms=l) for t, x, l in ((10.0, 5000, 4000), (60.0, 900, 0), (62.0, 880, 0))]
m = perf.bench_median(runs)
ok(m["tps"] == 60.0 and m["ttft_ms"] == 900 and m["runs"] == 3 and m["load_ms"] == 4000, "médiane des passes : le chargement à froid ne fausse pas le résultat")
d = perf.bench_compare([dict(r, t=1, tps=50.0, ttft_ms=2000), dict(r, t=2, model="autre", tps=1.0)], dict(r, t=3, tps=60.0, ttft_ms=1000))
ok(d["tps_pct"] == 20.0 and d["ttft_pct"] == -50.0 and d["previous"] == 1, "comparaison avec la mesure précédente du même modèle")
ok(perf.bench_compare([], r) is None, "première mesure : pas de comparaison")

# --- profils
env = {"OLLAMA_NUM_PARALLEL": "4", "OLLAMA_KEEP_ALIVE": "5m"}
diff = perf.profile_diff("econome", env)
ok({d["key"]: (d["from"], d["to"]) for d in diff}["OLLAMA_NUM_PARALLEL"] == ("4", "1") and "OLLAMA_KV_CACHE_TYPE" in {d["key"] for d in diff}, "aperçu des changements d'un profil")
full = {k: v for k, v in perf.PROFILES["equilibre"]["env"].items()}
ok(perf.profile_diff("equilibre", full) == [] and perf.detect_profile(full) == "equilibre" and perf.detect_profile(env) == "", "profil reconnu ; réglages personnalisés signalés")
ok(raises(perf.profile_diff, "inconnu", {}), "profil inconnu refusé")
ok(all(perf.normalize_env(p["env"], {}) == p["env"] for p in perf.PROFILES.values()), "chaque profil est cohérent (cache quantifié => flash attention)")
ok(perf.normalize_env({"OLLAMA_KV_CACHE_TYPE": "q8_0"}, {})["OLLAMA_FLASH_ATTENTION"] == "1", "cache quantifié : flash attention forcée")
ok(raises(perf.normalize_env, {"OLLAMA_KV_CACHE_TYPE": "q2"}, {}) and raises(perf.normalize_env, {"OLLAMA_FLASH_ATTENTION": "0"}, {"OLLAMA_KV_CACHE_TYPE": "q4_0"}), "type de cache inconnu et flash attention coupée sous un cache quantifié refusés")

# --- contrôles système
c = {x["id"]: x for x in perf.sys_checks({"swappiness": 60, "governors": ["powersave"] * 4, "mem_total": 16 << 30, "swap_total": 32 << 30, "zram": False,
                                          "webui": {"deployed": True, "limit_mb": None, "rss_mb": 3500}})}
ok(c["swappiness"]["state"] == "warn" and c["governor"]["fix"] == "governor" and c["zram"]["state"] == "info" and c["swap_big"]["state"] == "info" and c["webui_mem"]["state"] == "warn", "réglages défavorables détectés")
c = {x["id"]: x for x in perf.sys_checks({"swappiness": 10, "governors": ["performance", "performance"], "mem_total": 64 << 30, "zram": True, "webui": {"deployed": True, "limit_mb": 2048}})}
ok(all(x["state"] == "ok" for x in c.values()), "réglages recommandés : tout est vert")
ok(perf.parse_limit("2g") == 2048 and perf.parse_limit("1536M") == 1536 and all(raises(perf.parse_limit, x) for x in ("100m", "99g", "2 Go", "")), "plafond de mémoire validé")

# --- préchauffage
cfg = perf.warmup_clean({"boot": ["a:7b", "a:7b", "mauvais nom;", "b"], "times": [{"at": "07:30", "models": ["a:7b"], "days": [0, 1, 2, 3, 4]}, {"at": "08:00", "models": ["!!"]}]})
ok(cfg["boot"] == ["a:7b", "b"] and len(cfg["times"]) == 1 and cfg["times"][0]["days"] == [0, 1, 2, 3, 4], "préchauffage nettoyé (doublons, noms invalides, créneau vide)")
ok(raises(perf.warmup_clean, {"times": [{"at": "7h30", "models": ["a"]}]}), "heure invalide refusée")
lt = time.strptime("2026-11-09 07:30", "%Y-%m-%d %H:%M")   # lundi
played = {}
ok(perf.warmup_due(cfg, lt, played) == ["a:7b"] and perf.warmup_due(cfg, lt, played) == [], "créneau joué une seule fois")
sat = time.strptime("2026-11-14 07:30", "%Y-%m-%d %H:%M")
ok(perf.warmup_due(cfg, sat, played) == [] and not any(k.endswith("2026-11-09") for k in played), "pas le week-end ; créneaux de la veille oubliés")

# --- garde-fou de débit
now = 1_800_000_000
samples = [{"t": now - 3000 + i * 30, "tps": 60.0, "req": 1} for i in range(40)] + [{"t": now - 100 + i * 10, "tps": 3.0, "req": 1} for i in range(5)]
g = perf.perf_guard(samples, now, [], {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "f16", "OLLAMA_NUM_PARALLEL": "2"})
ok(g and g["kind"] == "slow" and g["baseline"] == 60.0 and g["current"] == 3.0 and g["fix"]["changes"] == {"OLLAMA_KV_CACHE_TYPE": "q8_0"}, "chute de 60 à 3 jetons/s : cache q8_0 suggéré")
ok(perf.perf_guard([s for s in samples if s["tps"] > 10], now, [], {}) is None, "débit stable : rien à signaler")
ok(perf.perf_guard(samples[:3] + samples[-1:], now, [], {}) is None, "trop peu de mesures pour conclure")
g = perf.perf_guard(samples[:40], now, [{"name": "gemma3:12b", "cpu_pct": 60}], {})
ok(g["kind"] == "offload" and g["fix"]["changes"] == {"OLLAMA_FLASH_ATTENTION": "1"}, "débordement sur le processeur : premier pas = flash attention")
steps = []
e = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "f16", "OLLAMA_NUM_PARALLEL": "3", "OLLAMA_CONTEXT_LENGTH": "8192"}
while True:
    f = perf.next_fix(e)
    if not f: break
    e.update(f["changes"]); steps.append(f["text"])
ok(len(steps) == 5 and e["OLLAMA_KV_CACHE_TYPE"] == "q4_0" and e["OLLAMA_NUM_PARALLEL"] == "1" and e["OLLAMA_CONTEXT_LENGTH"] == "4096", "échelle de réglages : un pas à la fois, finit sur un état stable (%s)" % e)
ok("aucun réglage simple" in perf.perf_guard([], now, [{"name": "x", "cpu_pct": 50}], e)["text"], "plus rien à resserrer : conseil d'un modèle plus petit")

# --- console : mesure, profils, garde-fou automatique, contrôles système (Ollama et commandes simulés)
calls = {"env": []}
fake_env = {}
server.read_env = lambda: dict(fake_env)
def fake_update(ch, restart=True): calls["env"].append(dict(ch)); fake_env.update(ch)
server.update_env = fake_update
count = {"n": 0}
def fake_ollama(method, path, body=None, timeout=15, addr=None):
    if path == "/api/generate":
        count["n"] += 1
        return 200, dict(gen, eval_duration=2_000_000_000 if count["n"] > 1 else 20_000_000_000)
    if path == "/api/ps": return 200, {"models": [{"name": "m:7b", "size": 5 << 30, "size_vram": 5 << 30}]}
    return 200, {}
server.ollama_json = fake_ollama
server.gpu_metrics = lambda: [{"pci": "0000:01:00.0", "mem_used": 6 << 30, "mem_total": 8 << 30}]
server.load_pools = lambda: []
server.BENCH_FILE = os.path.join(tmp, "bench.json"); server.PERF_FILE = os.path.join(tmp, "perf.json"); server.WARMUP_FILE = os.path.join(tmp, "warmup.json")
server.WEBUI_LIMITS = os.path.join(tmp, "webui.limits")
ok(all(raises(server.bench_start, *a) for a in (("../x", 2), ("m:7b", 9), ("m:7b", "x"))), "mesure : modèle et nombre de passes validés")
server._bench["running"] = True
ok(raises(server.bench_start, "m:7b", 2), "une seule mesure à la fois")
server._bench["running"] = False
server.bench_run("m:7b", 3)
h = server.bench_history()
ok(len(h) == 1 and h[0]["runs"] == 3 and h[0]["tps"] == 64.0 and h[0]["vram_total"] == 8 << 30 and server._bench["error"] == "" and not server._bench["running"], "mesure enregistrée dans l'historique (3 passes, médiane)")
server.bench_run("m:7b", 1)
ok(server.bench_history()[-1]["delta"]["tps_pct"] == 0.0, "la mesure suivante est comparée à la précédente")
server.ollama_json = lambda *a, **k: (404, {"error": "model not found"})
server.bench_run("absent", 1)
ok("not found" in server._bench["error"] and len(server.bench_history()) == 2, "modèle absent : erreur affichée, historique intact")
server.ollama_json = fake_ollama
# le garde-fou automatique
res = {"text": "x", "fix": {"changes": {"OLLAMA_KV_CACHE_TYPE": "q8_0"}}}
server.perf_store(guard={"mode": "suggest", "drop_pct": 50})
ok(server.perf_auto_step(res) is False and calls["env"] == [], "mode « suggérer » : aucun changement automatique")
server.perf_store(guard={"mode": "auto", "drop_pct": 50})
ok(server.perf_auto_step(res) is True and calls["env"][-1] == {"OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_FLASH_ATTENTION": "1"}, "mode automatique : un pas appliqué, flash attention ajoutée")
ok(server.perf_auto_step(res) is False, "pas deux changements dans la même heure")
c = server.perf_config(); c["last_change"] = 0
for i in range(3): c["events"].append({"t": int(time.time()) - 100, "who": "automatique", "text": "x"})
json.dump(c, open(server.PERF_FILE, "w"))
ok(server.perf_auto_step(res) is False, "plafond de 3 changements automatiques par jour")
server.perf_store(guard={"mode": "auto", "drop_pct": 50}, changed=False)
server._bench["running"] = True; c = server.perf_config(); c["last_change"] = 0; c["events"] = []; json.dump(c, open(server.PERF_FILE, "w"))
ok(server.perf_auto_step(res) is False, "jamais pendant une mesure")
server._bench["running"] = False
server.perf_store(guard={"mode": "off", "drop_pct": 50})
ok(server.perf_snapshot() is None, "garde-fou désactivé")
# contrôles système
os.makedirs(tmp + "/proc/sys/vm"); open(tmp + "/proc/sys/vm/swappiness", "w").write("60\n")
os.makedirs(tmp + "/sys/devices/system/cpu/cpu0/cpufreq"); open(tmp + "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "w").write("powersave\n")
os.makedirs(tmp + "/etc/sysctl.d"); os.makedirs(tmp + "/etc/tmpfiles.d")
ran = []
server.run = lambda cmd, timeout=10, **kw: ran.append(cmd) or ""
server.webui_deployed = lambda: False
ids = {x["id"] for x in server.sys_view()}
ok({"swappiness", "governor"} <= ids, "contrôles système lus (swappiness 60, gouverneur powersave)")
server.sys_fix("swappiness"); server.sys_fix("governor")
ok("vm.swappiness=10" in open(tmp + "/etc/sysctl.d/90-ollamabuntu.conf").read() and ["sysctl", "-w", "vm.swappiness=10"] in ran, "swappiness : persistant et appliqué")
ok(open(tmp + "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read() == "performance" and "performance" in open(tmp + "/etc/tmpfiles.d/ollamabuntu-governor.conf").read(), "gouverneur : appliqué et conservé au redémarrage")
server.sys_fix("webui_mem", "2g")
ok(open(server.WEBUI_LIMITS).read() == "MEM=2048m\n" and raises(server.sys_fix, "rm -rf") and raises(server.sys_fix, "webui_mem", "9999g"), "plafond Open WebUI écrit ; réglages inconnus refusés")
# préchauffage exécuté
warmed = []
server.ollama_json = lambda m, p, body=None, timeout=15, addr=None: (warmed.append(body) or (200, {}))
server.read_env = lambda: {"OLLAMA_KEEP_ALIVE": "1h"}
ok(server.warm_model("m:7b", "test") is True and warmed[-1] == {"model": "m:7b", "prompt": "", "stream": False, "keep_alive": "1h"}, "préchauffage : requête vide avec la durée de maintien configurée")
# le monitor
a = monitor.evaluate({"perf": {"text": "Débit de 3 jetons/s au lieu de 60"}}, {"events": ["perf_fix"]})
ok(list(a) == ["perf_fix"] and monitor.evaluate({"perf": None}, {"events": ["perf_fix"]}) == {}, "alerte de chute de débit")
print("\n%d vérifications réussies" % n)
