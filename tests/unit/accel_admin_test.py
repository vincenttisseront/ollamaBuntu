#!/usr/bin/env python3
"""Console : accélération (caches du routeur, préchauffage prédictif, mesure continue, cache de contexte validé par le Laboratoire,
parallélisme adaptatif, contrôles de la machine), routes HTTP, droits, audit, sauvegarde, alertes."""
import http.client, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC); ST = os.path.join(tmp, "state"); os.makedirs(ST)
os.environ.update(OB_ETC=ETC, OB_STATE=ST, OB_SYS_ROOT=os.path.join(tmp, "sys"), OB_PCI_ROOT=os.path.join(tmp, "pci"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import fit, perf, rcache, monitor, server, backup, audit
GIB = fit.GIB
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a, **k):
    try: f(*a, **k)
    except ValueError as e: return str(e)
    return None
server.AUDIT_FILE = os.path.join(tmp, "audit.jsonl")
for name in ("ACCEL_FILE", "CACHE_FILE", "HOURS_FILE", "CACHE_STATS_FILE"):
    setattr(server, name, os.path.join(tmp, name.lower() + ".json"))
server.FIT_FILE = os.path.join(ETC, "fit.json"); server.CONTEXT_FILE = os.path.join(ETC, "model-context.json"); server.BENCH_FILE = os.path.join(ST, "bench.json")
server.save_users({"admin": dict(server.hash_password("Secret-123"), role="admin", linux=False, rev="r0", created=1, updated=1),
                   "jean": dict(server.hash_password("Secret-456"), role="utilisateur", linux=False, rev="r1", created=1, updated=1)})
ENV = {}
UPD = []
def upd(ch, restart=True): UPD.append(dict(ch)); ENV.update(ch)
server.read_env = lambda: dict(ENV); server.update_env = upd
server.gpu_inventory = lambda: [{"description": "AMD Radeon RX 7800 XT", "total": "16.0 GiB", "library": "ROCm", "key": "k"}]
server.meminfo = lambda: {"MemTotal": int(15.4 * GIB), "MemAvailable": int(13.8 * GIB)}
server.gpu_metrics = lambda: [{"pci": "0000:03:00.0", "name": "AMD Radeon RX 7800 XT", "temp": 70.0, "mem_used": 9 * GIB, "mem_total": 16 * GIB}]
GEMMA = {"general.architecture": "gemma3", "general.parameter_count": 12e9, "gemma3.block_count": 48, "gemma3.embedding_length": 3840, "gemma3.attention.head_count": 16, "gemma3.attention.head_count_kv": 8,
         "gemma3.attention.key_length": 256, "gemma3.attention.value_length": 256, "gemma3.context_length": 131072}
BIG = dict(GEMMA, **{"gemma3.block_count": 60, "gemma3.attention.head_count_kv": 16})
INFO = {"gemma4:12b": GEMMA, "big:14b": BIG}
TAGS = [{"name": "gemma4:12b", "size": int(8.1 * GIB), "digest": "g"}, {"name": "big:14b", "size": int(13.2 * GIB), "digest": "b"}]
PS = {"models": [{"name": "gemma4:12b"}]}
WARMED = []
def fake(method, path, body=None, timeout=15, addr=None):
    if path == "/api/tags": return 200, {"models": TAGS}
    if path == "/api/show": return 200, {"model_info": INFO.get(body["model"], {})}
    if path == "/api/ps": return 200, PS
    if path == "/api/version": return 200, {"version": "0.9.9"}
    if path == "/api/generate":
        if body.get("prompt") == "": WARMED.append((body["model"], body.get("keep_alive"))); return 200, {"done": True}
    raise OSError("inattendu : " + path)
server.ollama_json = fake
server.instances = lambda: [("ollama.service", "127.0.0.1:11400", None)]
NOW = time.time()
LOG = []
server.read_requests = lambda n=5000: LOG
server.read_request_log = lambda since: [r for r in LOG if r.get("ts", 0) >= since]

# ---------------------------------------------------------------- caches du routeur
v = server.cache_view()
ok(v["config"]["responses"] is False and v["config"]["embeddings"] is False and v["config"]["ttl"] == 3600 and v["stats"] == {}, "au départ : caches désactivés, aucune statistique")
c = server.cache_conf_save({"responses": True, "ttl": 1800})
ok(c["responses"] is True and c["ttl"] == 1800 and c["purged"] == 0 and oct(os.stat(server.CACHE_FILE).st_mode & 0o777) == "0o644", "réglages enregistrés (lisibles par le routeur)")
ok(raises(server.cache_conf_save, {"ttl": 5}) and raises(server.cache_conf_save, {"max_mb": 99999}), "valeurs hors limites refusées")
ok(server.cache_conf_read()["ttl"] == 1800, "…et sans effet quand elles sont refusées")
c = server.cache_conf_save({}, purge=True)
ok(c["purged"] >= int(NOW) - 1 and c["responses"] is True, "purge : horodatage écrit, réglages conservés (le routeur vide ses caches à chaud)")
json.dump({"t": int(time.time()), "responses": {"entries": 3, "hits": 5, "misses": 2, "bytes": 2048}, "saved_ms": 12000, "saved_tokens": 900, "prefixes": {"distinct": 2, "models": [{"model": "gemma4:12b", "distinct": 4, "requests": 30, "frequent": 4}]}}, open(server.CACHE_STATS_FILE, "w"))
v = server.cache_view()
ok(v["stats"]["responses"]["hits"] == 5 and v["stats"]["saved_tokens"] == 900, "statistiques du routeur relues")
json.dump({"t": int(time.time()) - 7200, "responses": {}}, open(server.CACHE_STATS_FILE, "w"))
ok(server.cache_view()["stats"] == {}, "statistiques périmées (routeur arrêté depuis plus d'une heure) : ignorées")
json.dump({"t": int(time.time()), "responses": {"entries": 3, "hits": 5, "misses": 2, "bytes": 2048}, "prefixes": {"distinct": 2, "models": [{"model": "gemma4:12b", "distinct": 4, "requests": 30, "frequent": 4}]}}, open(server.CACHE_STATS_FILE, "w"))
notes = server.prefix_advice(server.cache_view()["stats"], 1)
ok(len(notes) == 1 and "4 débuts d'invite" in notes[0] and "1 emplacement" in notes[0] and server.prefix_advice(server.cache_view()["stats"], 4) == [], "débuts d'invite fréquents plus nombreux que les emplacements : explication ; assez d'emplacements : silence")

# ---------------------------------------------------------------- usage par heure et préchauffage prédictif
def at(d, h, m=0): return time.mktime((2026, 11, d, h, m, 0, 0, 0, -1))
LOG[:] = []
for day in (2, 3, 4, 5, 6, 9, 10, 11, 12):
    LOG.append({"ts": at(day, 8, 20), "model": "gemma4:12b", "status": 200, "instance": "x"}); LOG.append({"ts": at(day, 14, 10), "model": "big:14b", "status": 200, "instance": "x"})
h = server.hours_update()
ok(set(h["data"]) == {"gemma4:12b", "big:14b"} and h["last"] == at(12, 14, 10) and oct(os.stat(server.HOURS_FILE).st_mode & 0o777) == "0o600", "compteurs par heure alimentés par le journal (fichier privé)")
before = json.dumps(server.hours_load())
server.hours_update(); ok(json.dumps(server.hours_load()) == before, "mise à jour idempotente : une requête n'est comptée qu'une fois")
server.accel_set("predict", {"enabled": True}, "admin")
WARMED.clear()
PS["models"] = []
done = server.predict_step(at(13, 7, 52))
ok(done == ["gemma4:12b"] and WARMED == [("gemma4:12b", "75m")], "7 h 52 : le modèle habituel de 8 h est préchargé, gardé 75 minutes")
ok(server.predict_step(at(13, 7, 55)) == [] and len(WARMED) == 1, "pas deux fois pour la même heure")
PS["models"] = [{"name": "big:14b"}]; WARMED.clear()
ok(server.predict_step(at(13, 13, 55)) == [] and WARMED == [], "modèle déjà en mémoire : rien à charger")
ev = server.accel_conf()["events"]
ok(ev and ev[-1]["who"] == "prédiction" and "gemma4:12b" in ev[-1]["text"] and "9 jours sur 9" in ev[-1]["text"], "l'événement est consigné")
server.accel_set("predict", {"enabled": False}, "admin"); PS["models"] = []; WARMED.clear()
ok(server.predict_step(at(16, 7, 52)) == [] and WARMED == [], "prédiction désactivée : rien ne se charge")

# ---------------------------------------------------------------- mesure continue
HIST = {"history": []}
def bench_entry(model, tps, vram=100, t=0, temp=70, kernel="6.8.0-45", driver="mesa 24.0"):
    return {"t": int(NOW) - t, "model": model, "tps": tps, "ttft_ms": 400, "load_ms": 0, "vram_pct": vram, "cfg": {"kv": "f16", "fa": False, "parallel": "auto", "ctx": "auto"},
            "sys": {"kernel": kernel, "ollama": "0.9.9", "driver": driver, "gpu_temp": temp}}
hist = [bench_entry("gemma4:12b", t) for t in (74, 75, 73, 74, 76)]
json.dump({"history": hist}, open(server.BENCH_FILE, "w"))
server.accel_set("bench_auto", {"enabled": True, "at": "03:30", "models": ["gemma4:12b"], "tolerance": 15}, "admin")
server.bench_sys = lambda: {"kernel": "6.8.0-48", "ollama": "0.9.9", "driver": "mesa 24.2", "gpu_temp": 88}
good = dict(bench_entry("gemma4:12b", 74), t=int(NOW))
server.bench_after_auto(good, hist)
ok(server.accel_conf()["regress"] == {}, "débit habituel : aucune régression")
bad = dict(bench_entry("gemma4:12b", 50, vram=82, temp=88, kernel="6.8.0-48", driver="mesa 24.2"), t=int(NOW))
server.bench_after_auto(bad, hist)
r = server.accel_conf()["regress"]["gemma4:12b"]
ok(r["pct"] < -30 and "50 jetons/s au lieu de 74" in r["text"] and any("82 %" in x for x in r["hints"]) and any("88 °C" in x for x in r["hints"]) and any("noyau" in x for x in r["hints"]), "baisse de 32 % : consignée avec ses causes probables (mémoire, chaleur, noyau)")
ok(server.accel_conf()["events"][-1]["kind"] == "regression", "événement de régression dans le journal")
snap = {"regress": [dict(v, model=m) for m, v in server.accel_conf()["regress"].items()]}
a = monitor.evaluate(snap, {"events": ["perf_regress"]})
ok(list(a) == ["perf_regress:gemma4:12b"] and a["perf_regress:gemma4:12b"]["severity"] == "warning" and "50 jetons/s" in a["perf_regress:gemma4:12b"]["text"], "alerte « perf_regress » émise par la supervision")
ok(monitor.evaluate(snap, {"events": ["offload"]}) == {} and "perf_regress" in monitor.EVENTS and "perf_regress" in monitor.DEFAULTS["events"], "alerte désactivable ; événement connu des réglages d'alertes")
server.bench_after_auto(good, hist + [bad])
ok(server.accel_conf()["regress"] == {}, "retour à la normale : l'alerte disparaît")
CAL = []
server.fit_calibrate = lambda m: (CAL.append(m), {"gpu_gbps": 640.0, "tps": 74})[1]
server.bench_after_auto(good, hist)
ok(CAL == ["gemma4:12b"] and "recalées" in server.accel_conf()["events"][-1]["text"], "mesure saine d'un modèle entièrement en mémoire vidéo : estimations d'ajustement recalées")
CAL.clear(); server.bench_after_auto(dict(good, vram_pct=80), hist)
ok(CAL == [], "modèle qui déborde : pas de recalage (il ne mesure pas la carte)")
ok(raises(server.accel_set, "bench_auto", {"at": "99:99"}, "x") and raises(server.accel_set, "inconnu", {}, "x") and raises(server.accel_set, "kv", {"mode": "x"}, "x"), "réglages invalides refusés")
d = {"n": 0}
LOG[:] = [{"ts": time.time() - 30, "model": "gemma4:12b", "status": 200}]
ok(server.wait_idle(120, tries=1) is False, "mesure continue : attend que le serveur soit au repos")
LOG[:] = [{"ts": time.time() - 30, "model": "x", "status": 200, "instance": "cache", "cached": True}]
ok(server.wait_idle(120, tries=1) is True, "les réponses du cache ne comptent pas comme activité")
LOG[:] = [{"ts": time.time() - 300, "model": "gemma4:12b", "status": 200, "instance": "a"}] * 3 + [{"ts": time.time() - 100, "model": "big:14b", "status": 200}]
server.accel_set("bench_auto", {"enabled": True, "models": []}, "admin")
ok(server.bench_auto_models() == ["gemma4:12b"], "sans modèle choisi : le plus utilisé de la semaine")
STARTED = []
server.bench_start = lambda m, runs, auto=False: STARTED.append((m, runs, auto))
server.wait_idle = lambda *a, **k: True
server.accel_set("bench_auto", {"enabled": True, "models": ["gemma4:12b", "big:14b"]}, "admin")
server.bench_auto_run()
ok(STARTED == [("gemma4:12b", 2, True), ("big:14b", 2, True)], "mesure programmée : chaque modèle mesuré en 2 passes, marquée « automatique »")

# ---------------------------------------------------------------- cache de contexte validé par le Laboratoire
ENV.clear(); UPD.clear()
server.CONTEXT_FILE and json.dump({"models": {"big:14b": 65536}}, open(server.CONTEXT_FILE, "w"))
adv = server.kv_advice()
items = {i["model"]: i for i in adv["items"]}
ok(adv["current"] == "f16" and "big:14b" in items and items["big:14b"]["kv"] in ("q8_0", "q4_0") and "gemma4:12b" not in items and "tient en mémoire vidéo" in items["big:14b"]["text"], "conseil : le modèle qui déborde avec un cache f16 tiendrait en q8_0 ; celui qui tient déjà n'est pas concerné")
ENV["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
ok(server.kv_advice()["items"] == [] and server.kv_advice()["current"] == "q8_0", "cache déjà quantifié : plus de conseil")
ENV.clear()
server.lab_load = lambda: {"suites": [], "runs": []}
ok("aucun jeu de tests" in (raises(server.kv_apply_start, "big:14b", "q8_0", "admin") or ""), "sans jeu de tests : refus (la qualité ne pourrait pas être vérifiée), avec la marche à suivre")
ok(raises(server.kv_apply_start, "../x", "q8_0", "admin") and raises(server.kv_apply_start, "big:14b", "q5", "admin"), "nom ou type invalides refusés")
SUITES = [{"id": "s1", "name": "Réponses clés", "cases": [{"name": "c1", "prompt": "p"}]}, {"id": "s2", "name": "Format JSON", "cases": [{"name": "c2", "prompt": "p"}]}]
server.lab_load = lambda: {"suites": SUITES, "runs": []}
RUNS = []
OUTCOME = {"degraded": False}
def fake_eval(sid, model, who, reason, step=None, notify=True):
    RUNS.append((sid, model, reason, dict(ENV)))
    after = "après" in reason
    return {"id": "r", "diff": ({"degraded": OUTCOME["degraded"] and sid == "s2", "regressions": ["c2"] if OUTCOME["degraded"] and sid == "s2" else []} if after else None)}
server.lab_eval_core = fake_eval
server.wait_ollama = lambda seconds=180: True
def run_kv(force=False):
    server.kv_apply_start("big:14b", "q8_0", "admin", force)
    for _ in range(100):
        if not server._accel["kv"]["running"]: break
        time.sleep(0.05)
RUNS.clear(); UPD.clear(); run_kv()
ok(server._accel["kv"]["result"] == "valide" and [r[2] for r in RUNS][:2] == ["référence avant passage du cache en q8_0"] * 2 and all("après" in r[2] for r in RUNS[2:]) and len(RUNS) == 4, "validation : référence sur chaque jeu AVANT le changement, contrôle sur chaque jeu APRÈS")
ok(UPD == [{"OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_FLASH_ATTENTION": "1"}] and RUNS[0][3] == {} and RUNS[2][3].get("OLLAMA_KV_CACHE_TYPE") == "q8_0", "le cache est changé (avec la flash attention) entre les deux séries de tests")
ok("validé" in server.accel_conf()["events"][-1]["text"] and server.accel_conf()["last"].get("kv_change"), "événement « validé » ; date du changement mémorisée")
ENV.clear(); UPD.clear(); RUNS.clear(); OUTCOME["degraded"] = True; run_kv()
ok(server._accel["kv"]["result"] == "annule" and ENV.get("OLLAMA_KV_CACHE_TYPE", "") == "" and UPD[-1].get("OLLAMA_KV_CACHE_TYPE", "x") == "", "dégradation d'un jeu : retour automatique au réglage précédent")
ok("annulé" in server.accel_conf()["events"][-1]["text"] and "Format JSON" in server.accel_conf()["events"][-1]["text"] and "1 cas échoue(nt)" in server.accel_conf()["events"][-1]["text"], "l'événement dit quel jeu et combien de cas")
ENV.clear(); UPD.clear(); OUTCOME["degraded"] = False
server.wait_ollama = lambda seconds=180: False
run_kv()
ok(server._accel["kv"]["error"] and ENV.get("OLLAMA_KV_CACHE_TYPE", "") == "", "Ollama qui ne redémarre pas : réglages précédents rétablis, erreur signalée")
server.wait_ollama = lambda seconds=180: True
server.lab_load = lambda: {"suites": [], "runs": []}; RUNS.clear(); ENV.clear()
run_kv(force=True)
ok(server._accel["kv"]["result"] == "valide" and RUNS == [] and "sans vérification" in server.accel_conf()["events"][-1]["text"], "forcé sans jeu de tests : appliqué sans vérification, et l'événement le dit")
server._accel["kv"]["running"] = True
ok("déjà en cours" in (raises(server.kv_apply_start, "big:14b", "q8_0", "admin") or ""), "un seul changement à la fois")
server._accel["kv"]["running"] = False

# ---------------------------------------------------------------- parallélisme adaptatif
ENV.clear(); UPD.clear(); json.dump({"models": {}}, open(server.CONTEXT_FILE, "w"))
def row(t, ms, ttft=300, model="gemma4:12b"): return {"ts": t, "ms": ms, "ttft_ms": ttft, "status": 200, "instance": "127.0.0.1:11400", "model": model}
now = time.time()
LOG[:] = [row(now - 80000 + i * 100, 3000) for i in range(30)]
pv = server.parallel_view()
ok(pv["parallel"] == 1 and pv["model"] == "gemma4:12b" and pv["profile"]["peak"] == 1 and pv["advice"] is None and pv["slot"] > 0 and pv["headroom"] is not None, "demandes jamais chevauchées : aucun conseil ; mémoire libre et coût d'un emplacement calculés d'après le modèle le plus utilisé")
LOG[:] = [row(now - 5000 + i * 2, 8000, 1400) for i in range(15)] + [row(now - 80000 + i * 100, 3000) for i in range(30)]
pv = server.parallel_view()
ok(pv["advice"] and pv["advice"]["to"] == 2 and pv["advice"]["why"] == "overlap" and pv["profile"]["overlap_pct"] > 15, "demandes qui se chevauchent : passer à 2 requêtes en parallèle")
server.parallel_apply(2, "admin")
ok(UPD == [{"OLLAMA_NUM_PARALLEL": "2"}] and server.accel_conf()["last"].get("parallel_change") and "1 -> 2" in server.accel_conf()["events"][-1]["text"], "changement appliqué et consigné")
ok(raises(server.parallel_apply, 2, "admin") and raises(server.parallel_apply, 0, "admin") and raises(server.parallel_apply, "x", "admin"), "même valeur, hors limites ou illisible : refusé")
# mode automatique : conditions strictes
ENV["OLLAMA_NUM_PARALLEL"] = "1"; UPD.clear()
server.accel_set("parallel", {"mode": "auto"}, "admin")
server.accel_store(last={"parallel_change": 0})
LOG[:] = [row(now - 5000 + i * 2, 8000, 1400) for i in range(15)] + [row(now - 80000 + i * 100, 3000) for i in range(30)] + [row(time.time() - 60, 1000)]
server.accel_auto_steps(server.accel_conf())
ok(UPD == [], "mode automatique : rien tant que le serveur a servi une demande dans les 10 dernières minutes")
LOG[:] = [row(now - 5000 + i * 2, 8000, 1400) for i in range(15)] + [row(now - 80000 + i * 100, 3000) for i in range(30)]
server.accel_auto_steps(server.accel_conf())
ok(UPD == [{"OLLAMA_NUM_PARALLEL": "2"}] and server.accel_conf()["events"][-1]["who"] == "automatique", "serveur au repos : l'augmentation est appliquée, au nom de « automatique »")
UPD.clear(); ENV["OLLAMA_NUM_PARALLEL"] = "1"
server.accel_auto_steps(server.accel_conf())
ok(UPD == [], "au plus un changement par jour")
server.accel_set("parallel", {"mode": "suggest"}, "admin")

# ---------------------------------------------------------------- contrôles de la machine
PCI = os.environ["OB_PCI_ROOT"]; server.PCI_ROOT = PCI
dev = os.path.join(PCI, "0000:03:00.0"); os.makedirs(dev)
def w(name, text): open(os.path.join(dev, name), "w").write(text)
w("class", "0x030000\n"); w("vendor", "0x1002\n"); w("power_dpm_force_performance_level", "auto\n"); w("current_link_width", "8\n"); w("max_link_width", "16\n")
w("mem_info_vram_total", str(16 * GIB) + "\n"); w("gpu_busy_percent", "0\n")
w("resource", "0x00000000d0000000 0x00000000dfffffff 0x000000000014220c\n0x00000000e0000000 0x00000000e01fffff 0x000000000014220c\n0x0000000000000000 0x0000000000000000 0x0000000000000000\n")
server.run = lambda cmd, timeout=10, **kw: ""
server.shutil.which = lambda x: None if x in ("dmidecode", "nvidia-smi") else "/usr/bin/" + x
m = server.sys_machine()
ok(m["gpu_power"] == [{"card": server.norm_pci("0000:03:00.0"), "name": "AMD Radeon RX 7800 XT", "level": "auto"}] and m["pcie"][0]["width"] == 8 and m["pcie"][0]["max_width"] == 16, "carte AMD lue : niveau de puissance, largeur du lien PCIe")
ok(m["rebar"]["checked"] and m["rebar"]["enabled"] is False and m["rebar"]["bar_gb"] == 0.25 and m["rebar"]["vram_gb"] == 16 and m["memory"] is None, "Resizable BAR : fenêtre de 256 Mo pour 16 Go -> désactivé ; mémoire non lisible sans dmidecode : ignorée")
w("resource", "0x00000000d0000000 0x00000004cfffffff 0x000000000014220c\n")
ok(server.sys_machine()["rebar"]["enabled"] is True, "fenêtre de 16 Go : Resizable BAR actif")
DMI = """Handle 0x0010
Memory Device
\tSize: 16 GB
\tSpeed: 3200 MT/s
\tConfigured Memory Speed: 2133 MT/s
Handle 0x0011
Memory Device
\tSize: No Module Installed
\tSpeed: Unknown
"""
server.shutil.which = lambda x: "/usr/sbin/dmidecode" if x == "dmidecode" else None
server.run = lambda cmd, timeout=10, **kw: DMI if cmd[0] == "dmidecode" else ""
m = server.sys_machine()
ok(m["memory"] == {"dimms": 1, "rated": 3200, "configured": 2133}, "dmidecode : une barrette, 3200 MT/s prévus, 2133 MT/s configurés")
checks = {c["id"]: c for c in server.sys_view()}
ok(checks["mem_channels"]["state"] == "warn" and checks["mem_speed"]["state"] == "warn" and checks["pcie:" + server.norm_pci("0000:03:00.0")]["state"] == "warn" and checks["rebar"]["state"] == "ok", "écran Performance : contrôles ajoutés à ceux d'avant")
ok("swappiness" in checks or "governor" in checks or len(checks) >= 4, "contrôles existants toujours présents")
server.atomic_write = server.atomic_write
server.sys_fix("amd_power")
conf = server.sysp("/etc/tmpfiles.d/ollamabuntu-gpu-power.conf")
ok(os.path.exists(conf) and "high" in open(conf).read() and open(os.path.join(dev, "power_dpm_force_performance_level")).read() == "high", "carte AMD : « high » écrit tout de suite et rendu permanent (tmpfiles.d)")
server.sys_fix("amd_power_auto")
ok(not os.path.exists(conf) and open(os.path.join(dev, "power_dpm_force_performance_level")).read() == "auto", "retour au mode automatique")

# ---------------------------------------------------------------- vue d'ensemble, routes, droits, audit, sauvegarde
server.read_env = lambda: dict(ENV)
LOG[:] = []
view = server.accel_view()
ok({"config", "cache", "parallel", "kv", "predict", "bench_auto", "events", "env"} <= set(view) and "notes" in view["parallel"], "vue d'ensemble : toutes les sections")
httpd = server.make_server(0, server.Handler); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
def req(method, path, cookie="", body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = cookie
    try:
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = c.getresponse(); out = r.read(); cookies = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    finally: c.close()
    try: return r.status, cookies, json.loads(out or b"{}")
    except ValueError: return r.status, cookies, {}
def login(u, p):
    st, ck, d = req("POST", "/api/login", body={"user": u, "password": p}); return next(c.split(";")[0] for c in ck if c.startswith("ob_session="))
adm, usr = login("admin", "Secret-123"), login("jean", "Secret-456")
st, _, d = req("GET", "/api/accel", adm); ok(st == 200 and "cache" in d and "kv" in d, "GET /api/accel")
ok(req("GET", "/api/accel", usr)[0] == 403 and req("GET", "/api/accel")[0] == 401, "lecture réservée aux administrateurs (403 / 401)")
for path, body in (("/api/accel/cache", {"responses": True}), ("/api/accel/predict", {"enabled": True}), ("/api/accel/bench-auto", {"enabled": True}), ("/api/accel/bench-auto/run", {}),
                   ("/api/accel/parallel", {"mode": "auto"}), ("/api/accel/parallel/apply", {"to": 2}), ("/api/accel/kv", {"mode": "off"}), ("/api/accel/kv/apply", {"model": "big:14b", "kv": "q8_0"})):
    if req("POST", path, usr, body)[0] != 403: ok(False, "droits : " + path)
ok(True, "toutes les écritures sont refusées à un non-administrateur")
st, _, d = req("POST", "/api/accel/cache", adm, {"embeddings": True, "ttl": 900}); ok(st == 200 and d["config"]["embeddings"] is True and d["config"]["ttl"] == 900, "POST /api/accel/cache")
st, _, d = req("POST", "/api/accel/cache", adm, {"ttl": 1}); ok(st == 400 and "hors limites" in d["error"], "valeur hors limites : 400 avec message")
st, _, d = req("POST", "/api/accel/cache", adm, {"purge": True}); ok(st == 200 and d["config"]["purged"] > 0, "purge")
st, _, d = req("POST", "/api/accel/predict", adm, {"enabled": True, "lead": 15}); ok(st == 200 and d["config"]["lead"] == 15 and server.accel_conf()["predict"]["enabled"], "POST /api/accel/predict")
st, _, d = req("POST", "/api/accel/predict", adm, {"lead": 99}); ok(st == 400, "avance hors limites : 400")
st, _, d = req("POST", "/api/accel/bench-auto", adm, {"enabled": True, "at": "04:15", "models": ["gemma4:12b"], "tolerance": 25}); ok(st == 200 and server.accel_conf()["bench_auto"]["at"] == "04:15" and server.accel_conf()["bench_auto"]["tolerance"] == 25, "POST /api/accel/bench-auto")
st, _, d = req("POST", "/api/accel/parallel", adm, {"mode": "off"}); ok(st == 200 and server.accel_conf()["parallel"]["mode"] == "off", "POST /api/accel/parallel")
st, _, d = req("POST", "/api/accel/parallel/apply", adm, {"to": 3}); ok(st == 200 and UPD[-1] == {"OLLAMA_NUM_PARALLEL": "3"}, "POST /api/accel/parallel/apply")
st, _, d = req("POST", "/api/accel/parallel/apply", adm, {"to": 99}); ok(st == 400, "valeur hors limites : 400")
st, _, d = req("POST", "/api/accel/kv", adm, {"mode": "auto"}); ok(st == 200 and server.accel_conf()["kv"]["mode"] == "auto", "POST /api/accel/kv")
st, _, d = req("POST", "/api/accel/kv/apply", adm, {"model": "../x", "kv": "q8_0"}); ok(st == 400, "nom invalide : 400")
st, _, d = req("POST", "/api/perf/fix", adm, {"id": "amd_power_auto"}); ok(st == 200, "POST /api/perf/fix amd_power_auto")
time.sleep(0.3)
lines = [json.loads(l) for l in open(server.AUDIT_FILE) if l.strip()]
labels = {l.get("label") or l.get("action") for l in lines}
ok(any("Caches du routeur" in str(l) for l in lines) and any("Requêtes en parallèle modifiées" in str(l) for l in lines), "audit : les écritures sont journalisées avec un libellé lisible")
ok("perf2.json" in backup.FILES and "cache.json" in backup.FILES, "sauvegarde : réglages d'accélération et de caches inclus")
print("\n%d vérifications réussies" % n)
