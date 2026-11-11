#!/usr/bin/env python3
"""Troisième lot : la carte graphique reste disponible et associée à Ollama (diagnostic, plan de réparation, exécution), santé du matériel."""
import json, os, sys, tempfile, time
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, os.path.join(LIB, "admin")); sys.path.insert(0, LIB)
import hw, monitor, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
codes = lambda r: sorted(i["code"] for i in r["issues"])
G = {"slot": "0000:01:00.0", "name": "Quadro RTX 4000", "vendor": "NVIDIA"}
base = {"pci": [G], "driver": ["01:00.0"], "ollama": ["0000:01:00.0"], "ollama_active": True, "loaded": [], "free": {}, "restricted": False, "log_errors": []}

# --- diagnostic
ok(hw.norm_pci("01:00.0") == "0000:01:00.0" and hw.norm_pci("PCI:0000:0A:00.0") == "0000:0a:00.0" and hw.norm_pci(None) == "", "adresse PCI normalisée")
r = hw.gpu_guard(base)
ok(r["state"] == "ok" and r["issues"] == [] and r["checks"][0]["driver"] and r["checks"][0]["ollama"], "carte saine et utilisée : aucun problème")
ok(hw.gpu_guard({"pci": []})["state"] == "none", "aucune carte : état « none »")
r = hw.gpu_guard(dict(base, driver=[], ollama=[]))
ok(codes(r) == ["driver_down"] and r["issues"][0]["fix"] == "reload-driver" and r["state"] == "critical", "pilote NVIDIA absent : rechargement du pilote proposé")
amd = {"slot": "0000:03:00.0", "name": "Radeon", "vendor": "AMD"}
ok(hw.gpu_guard(dict(base, pci=[amd], driver=[], ollama=[]))["issues"][0]["fix"] == "reboot", "pilote AMD absent : redémarrage, pas de rechargement")
r = hw.gpu_guard(dict(base, ollama=[]))
ok(codes(r) == ["ollama_blind"] and r["issues"][0]["fix"] == "restart-ollama", "carte saine mais invisible pour Ollama")
ok(hw.gpu_guard(dict(base, ollama=[], restricted=True))["issues"][0]["code"] == "restricted" and hw.gpu_guard(dict(base, ollama=[], restricted=True))["state"] == "info", "visibilité volontairement limitée : information, pas une panne")
ok(hw.gpu_guard(dict(base, ollama=[], ollama_active=False))["issues"] == [], "Ollama arrêté : l'alerte « service » s'en charge, pas la garde GPU")
cpu_only = [{"name": "gemma3:12b", "size": 9 << 30, "size_vram": 0}]
ok(codes(hw.gpu_guard(dict(base, loaded=cpu_only, free={"0000:01:00.0": 20 << 30}))) == ["gpu_unused"], "modèle entièrement sur le processeur alors que la carte a de la place")
ok(hw.gpu_guard(dict(base, loaded=cpu_only, free={"0000:01:00.0": 2 << 30}))["issues"] == [], "modèle trop gros pour la carte : normal, pas d'alerte")
ok(hw.gpu_guard(dict(base, loaded=[{"name": "m", "size": 5 << 30, "size_vram": 5 << 30}], free={"0000:01:00.0": 20 << 30}))["issues"] == [], "modèle en mémoire vidéo : rien à signaler")
ok(hw.log_errors(["ggml_cuda_init: failed", "CUDA error: an illegal memory access", "cudaMalloc failed: out of memory", "ok"]) == ["CUDA error: an illegal memory access"], "journal : erreur CUDA retenue, « out of memory » écarté")
ok(codes(hw.gpu_guard(dict(base, log_errors=["CUDA error: unknown error"]))) == ["gpu_error_log"], "erreur CUDA récente signalée")

# --- plan de réparation : persistance, délai, plafond horaire, désactivation
st, issue = {}, [{"code": "ollama_blind", "severity": "critical", "fix": "restart-ollama"}]
t0 = 1_800_000_000
ok(hw.guard_plan(issue, st, t0) is None, "1re détection : on attend (incident peut-être passager)")
p = hw.guard_plan(issue, st, t0 + 60)
ok(p and p["steps"] == ["load-uvm", "restart-ollama"] and p["codes"] == ["ollama_blind"], "2e détection : redémarrage d'Ollama (modules UVM vérifiés)")
ok(hw.guard_plan(issue, st, t0 + 120) is None, "délai de 10 min entre deux tentatives")
ok(hw.guard_plan([], st, t0 + 180) is None and st["streak"] == {}, "incident résolu : compteur remis à zéro")
for k in (1, 2, 3):
    hw.guard_plan(issue, st, t0 + 1000 * k); p = hw.guard_plan(issue, st, t0 + 1000 * k + 60)
ok(len(st["attempts"]) == 3 and hw.guard_plan(issue, st, t0 + 3300) is None, "3 tentatives par heure au plus")
ok(hw.guard_plan(issue, {"streak": {"ollama_blind": 5}}, t0, enabled=False) is None, "réparation automatique désactivée : aucun plan")
p = hw.guard_plan([{"code": "driver_down", "severity": "critical", "fix": "reload-driver"}], {"streak": {"driver_down": 5}}, t0)
ok(p["steps"][0] == "load-driver" and p["steps"][-1] == "restart-ollama", "pilote absent : chargement du pilote d'abord")
ok(hw.guard_plan([{"code": "restricted", "severity": "info", "fix": ""}], {"streak": {"restricted": 9}}, t0) is None, "information seule : aucune action")

# --- exécution (commandes simulées)
tmp = tempfile.mkdtemp()
server.GUARD_FILE = os.path.join(tmp, "gpu-guard.json")
server.DEV_UVM = os.path.join(tmp, "nvidia-uvm")
calls = []
def fake_run(cmd, timeout=10, **kw):
    calls.append(list(cmd))
    if cmd[:2] == ["modprobe", "nvidia_uvm"]: open(server.DEV_UVM, "w").close()
    return ""
server.run = fake_run
server.load_pools = lambda: [{"id": "p1"}]
server.time.sleep = lambda s: None
state = {"bad": True}
def fake_status(max_age=45):
    return {"issues": [{"code": "ollama_blind", "severity": "critical", "text": "x"}] if state["bad"] else []}
server.guard_status = fake_status
def restart_fixes(cmd, timeout=10, **kw):
    r = fake_run(cmd, timeout); 
    if cmd[:2] == ["systemctl", "restart"]: state["bad"] = False
    return r
server.run = restart_fixes
res = server.guard_remediate({"steps": ["load-uvm", "restart-ollama"], "codes": ["ollama_blind"]}, "test")
ev = server.guard_config()["events"][-1]
ok(res is True and ev["result"] == "résolu" and ev["who"] == "test" and ev["steps"] == ["load-uvm", "restart-ollama"], "réparation exécutée, vérifiée et journalisée")
ok(["modprobe", "nvidia_uvm"] in calls and ["systemctl", "restart", "ollama.service"] in calls and ["systemctl", "restart", "ollama-pool@p1.service"] in calls, "module UVM chargé, Ollama et ses instances redémarrés")
ok(not any(c[0] == "reboot" or c[:2] == ["systemctl", "reboot"] for c in calls), "jamais de redémarrage du serveur")
state["bad"] = True
server.run = fake_run
res = server.guard_remediate({"steps": ["restart-ollama"], "codes": ["ollama_blind"]})
ok(res is False and server.guard_config()["events"][-1]["result"] == "non résolu" and server._guard["busy"] is False, "échec consigné, verrou libéré")
server.guard_store(auto=False)
cfg = server.guard_config()
ok(cfg["auto"] is False and len(cfg["events"]) == 2, "réglage automatique conservé avec l'historique")
for i in range(40): server.guard_store(event={"t": i, "who": "x", "codes": [], "steps": [], "result": "résolu"})
ok(len(server.guard_config()["events"]) == 30, "historique limité à 30 réparations")

# --- alertes
snap = {"guard": [{"code": "driver_down", "severity": "critical", "pci": "0000:01:00.0", "text": "Carte absente"}, {"code": "restricted", "severity": "info", "text": "voulu"}],
        "hw": [{"key": "raid:md0", "severity": "critical", "text": "RAID"}, {"key": "hw_disk:/dev/sda:0", "severity": "warning", "text": "SMART"}, {"key": "gpu_xid:0000:01:00.0:79", "severity": "critical", "text": "Xid"}]}
a = monitor.evaluate(snap, {"events": ["gpu_guard", "raid", "hw_disk", "gpu_xid"]})
ok(sorted(a) == ["gpu_guard:driver_down:0000:01:00.0", "gpu_xid:0000:01:00.0:79", "hw_disk:/dev/sda:0", "raid:md0"], "alertes GPU, RAID, SMART et Xid (l'information seule n'alerte pas)")
ok(monitor.evaluate(snap, {"events": ["raid"]}).keys() == {"raid:md0"}, "chaque famille d'alerte se désactive séparément")

# --- Xid, SMART, RAID
log = ("1799999000.1 host kernel: NVRM: Xid (PCI:0000:01:00): 79, pid=1, GPU has fallen off the bus.\n"
       "1799999100.1 host kernel: NVRM: Xid (PCI:0000:01:00): 13, Graphics Exception\n"
       "1700000000.1 host kernel: NVRM: Xid (PCI:0000:01:00): 48, ancienne\n"
       "1799999200.1 host kernel: NVRM: Xid (PCI:0000:01:00): 79, doublon\n")
x = hw.parse_xid(log, 1_800_000_000)
ok([(e["xid"], e["severity"]) for e in x] == [(79, "critical"), (13, "info")], "Xid : récents seulement, doublons fusionnés, 13 sans gravité matérielle")
nvme = {"device": {"name": "/dev/nvme0", "protocol": "NVMe"}, "model_name": "X", "smart_status": {"passed": True}, "temperature": {"current": 72},
        "nvme_smart_health_information_log": {"percentage_used": 93, "media_errors": 2, "critical_warning": 0, "available_spare": 100, "available_spare_threshold": 10}}
d = hw.parse_smart(json.dumps(nvme))
ok(d["type"] == "NVMe" and d["state"] == "warning" and len(d["issues"]) == 3 and d["wear"] == 93, "NVMe : usure, erreurs de média et température signalées")
sata = {"device": {"name": "/dev/sda", "protocol": "ATA"}, "rotation_rate": 7200, "smart_status": {"passed": False}, "ata_smart_attributes": {"table": [{"id": 5, "raw": {"value": 8}}, {"id": 197, "raw": {"value": 0}}]}}
d = hw.parse_smart(sata)
ok(d["state"] == "critical" and d["type"] == "HDD" and d["errors"] == 8, "disque SATA : panne SMART et secteurs réalloués")
ok(hw.parse_smart("pas du json") is None and hw.parse_smart({"device": {"name": "/dev/sdb"}, "smart_status": {"passed": True}})["state"] == "ok", "sortie invalide ignorée ; disque sain")
md = "Personalities : [raid1]\nmd0 : active raid1 sdb1[1] sda1[0]\n      976630336 blocks [2/1] [U_]\n      [==>..]  recovery = 12.5% (1/2) finish=10min\nmd1 : active raid1 sdc1[1] sdd1[0]\n      100 blocks [2/2] [UU]\n"
r = hw.parse_mdstat(md)
ok(r[0]["degraded"] and r[0]["progress"]["percent"] == 12.5 and not r[1]["degraded"] and r[0]["members"] == ["sdb1", "sda1"], "RAID : grappe dégradée et reconstruction repérées")
iss = hw.hw_issues([hw.parse_smart(sata)], r, x)
ok({i["key"].split(":")[0] for i in iss} == {"hw_disk", "raid", "gpu_xid"} and all(i["severity"] != "info" for i in iss), "problèmes du matériel regroupés pour les alertes")
print("\n%d vérifications réussies" % n)
