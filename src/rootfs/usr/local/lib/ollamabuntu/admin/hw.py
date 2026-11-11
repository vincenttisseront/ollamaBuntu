#!/usr/bin/env python3
"""OllamaBuntu - disponibilité des cartes graphiques pour Ollama, et santé du matériel (disques, RAID, erreurs GPU).
Fonctions pures : elles reçoivent des relevés déjà faits (nvidia-smi, journal, smartctl, /proc/mdstat) et retournent
un diagnostic. Testables hors de la console, sans matériel."""
import json
import re

SEV_ORDER = {"info": 0, "warning": 1, "critical": 2}
NO_PCI = ""


def norm_pci(p):
    """0000:01:00.0 en minuscules, domaine PCI complété ; chaîne vide si absent."""
    p = str(p or "").strip().lower()
    if p.startswith("pci:"):
        p = p[4:]
    if p and re.fullmatch(r"[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]", p):
        p = "0000:" + p
    return p


def _worst(issues):
    return max((i["severity"] for i in issues), key=lambda s: SEV_ORDER[s], default="ok") if issues else "ok"


# ------------------------------------------------------------- GPU <-> Ollama ---
def gpu_guard(s):
    """Chaque carte de calcul présente sur le bus PCI doit avoir un pilote fonctionnel ET être vue par Ollama.
    s : pci [{slot, name, vendor}] cartes de calcul ; driver [pci] cartes mesurables (nvidia-smi, amdgpu) ;
    ollama [pci] cartes détectées par Ollama ; ollama_active (bool) ; loaded [{name, size, size_vram}] (/api/ps) ;
    free {pci: octets libres} ; restricted (bool) : visibilité volontairement limitée (groupes de GPU, CUDA_VISIBLE_DEVICES) ;
    log_errors [str] : erreurs CUDA/ROCm récentes d'Ollama.
    Retourne {state, checks, issues[{code, severity, pci, text, fix}]} ; fix : reload-driver, restart-ollama ou reboot."""
    gpus = s.get("pci") or []
    if not gpus:
        return {"state": "none", "checks": [], "issues": []}
    driver = {norm_pci(x) for x in s.get("driver") or []}
    seen = {norm_pci(x) for x in s.get("ollama") or []}
    restricted = bool(s.get("restricted"))
    active = s.get("ollama_active", True)
    checks, issues = [], []
    healthy = []
    for g in gpus:
        pci, name, vendor = norm_pci(g["slot"]), g.get("name") or g["slot"], g.get("vendor") or ""
        has_driver, has_ollama = pci in driver, pci in seen
        checks.append({"pci": pci, "name": name, "vendor": vendor, "present": True, "driver": has_driver, "ollama": has_ollama})
        if not has_driver:
            issues.append({"code": "driver_down", "severity": "critical", "pci": pci,
                           "text": "Carte %s détectée mais pilote inactif : elle ne peut pas calculer." % name,
                           "fix": "reload-driver" if vendor.upper() == "NVIDIA" else "reboot"})
            continue
        healthy.append(pci)
        if active and not has_ollama and not restricted:
            issues.append({"code": "ollama_blind", "severity": "critical", "pci": pci,
                           "text": "Carte %s fonctionnelle mais Ollama ne l'utilise pas (détection absente)." % name, "fix": "restart-ollama"})
    # Perte en cours de route : le modèle chargé tourne entièrement sur le processeur alors qu'une carte saine a la place
    if healthy and active and not any(i["code"] == "ollama_blind" for i in issues):
        free = max((s.get("free") or {}).get(p, 0) for p in healthy) if s.get("free") else 0
        for m in s.get("loaded") or []:
            size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
            if size > 0 and vram == 0 and free > size * 1.1:
                issues.append({"code": "gpu_unused", "severity": "warning", "pci": NO_PCI,
                               "text": "%s tourne entièrement sur le processeur alors qu'une carte a de la place libre." % (m.get("name") or "?"), "fix": "restart-ollama"})
                break
    errs = [e for e in s.get("log_errors") or [] if e]
    if errs and active:
        issues.append({"code": "gpu_error_log", "severity": "warning", "pci": NO_PCI, "text": "Ollama signale une erreur GPU : %s" % errs[-1][:160], "fix": "restart-ollama"})
    if restricted and any(c["driver"] and not c["ollama"] for c in checks):
        issues.append({"code": "restricted", "severity": "info", "pci": NO_PCI,
                       "text": "Visibilité des cartes limitée par un réglage (groupes de GPU ou CUDA_VISIBLE_DEVICES) : c'est voulu si vous l'avez configurée.", "fix": ""})
    return {"state": _worst(issues), "checks": checks, "issues": issues}


GUARD_COOLDOWN = 600     # secondes entre deux tentatives
GUARD_MAX_HOUR = 3       # tentatives par heure
GUARD_PERSIST = 2        # évaluations consécutives avant d'agir (évite de réagir à un incident passager)


def guard_plan(issues, state, now, enabled=True):
    """Décide d'une réparation. state : {attempts: [ts], streak: {code: n}} (mis à jour en place).
    Retourne None ou {steps: [...], reason, codes}. Jamais de redémarrage du serveur : seulement pilote et Ollama."""
    streak = state.setdefault("streak", {})
    codes = {i["code"] for i in issues if i.get("fix") in ("reload-driver", "restart-ollama")}
    for c in list(streak):
        if c not in codes:
            streak.pop(c)
    for c in codes:
        streak[c] = streak.get(c, 0) + 1
    state["attempts"] = [t for t in state.get("attempts", []) if now - t < 3600]
    if not enabled or not codes or max(streak[c] for c in codes) < GUARD_PERSIST:
        return None
    if state["attempts"] and now - state["attempts"][-1] < GUARD_COOLDOWN:
        return None
    if len(state["attempts"]) >= GUARD_MAX_HOUR:
        return None
    steps = (["load-driver"] if "driver_down" in codes else []) + ["load-uvm", "restart-ollama"]
    state["attempts"].append(now)
    return {"steps": steps, "codes": sorted(codes), "reason": ", ".join(sorted(codes))}


ERR_RE = re.compile(r"(?i)(cuda error|cuda_error|failed to initialize nvml|nvml.*(error|fail)|no cuda-capable|unable to load cuda|cudagetdevice|gpu.*(lost|fallen)|rocm.*(error|fail)|hip error|out of memory)")


def log_errors(lines):
    """Erreurs GPU dans les dernières lignes d'Ollama (« out of memory » est normal pour un modèle trop gros : écarté)."""
    out = []
    for l in lines:
        if ERR_RE.search(l) and "out of memory" not in l.lower():
            out.append(l.strip())
    return out[-5:]


# ------------------------------------------------------------ erreurs Xid NVIDIA ---
XID_RE = re.compile(r"NVRM: Xid \(PCI:([0-9a-fA-F:.]+)\): (\d+),?\s*(.*)")
XID_CRITICAL = {48, 63, 64, 74, 79, 95, 119, 120, 140}
XID_APP = {13, 31, 43, 45, 69}   # erreurs d'application : sans gravité pour le matériel


def parse_xid(text, now=None, window=86400):
    """Erreurs Xid du journal du noyau (« journalctl -k -o short-unix »), sur `window` secondes."""
    out, seen = [], set()
    for line in text.splitlines():
        m = XID_RE.search(line)
        if not m:
            continue
        ts = None
        t = re.match(r"^(\d{9,}(?:\.\d+)?)\s", line)
        if t:
            ts = float(t.group(1))
        if now and ts and now - ts > window:
            continue
        pci, xid = norm_pci(m.group(1)), int(m.group(2))
        if (pci, xid) in seen:
            continue
        seen.add((pci, xid))
        sev = "info" if xid in XID_APP else "critical" if xid in XID_CRITICAL else "warning"
        out.append({"pci": pci, "xid": xid, "ts": ts, "severity": sev, "text": m.group(3).strip()[:160]})
    return out


# ------------------------------------------------------------------ SMART, RAID ---
def parse_smart(raw):
    """Sortie de « smartctl -j -a » : état résumé d'un disque et problèmes."""
    try:
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except (ValueError, TypeError):
        return None
    dev = d.get("device") or {}
    proto = (dev.get("protocol") or "").upper()
    out = {"name": dev.get("name") or "?", "model": d.get("model_name") or "", "type": "NVMe" if proto == "NVME" else ("SSD" if d.get("rotation_rate") == 0 else "HDD" if d.get("rotation_rate") else proto or "?"),
           "size": (d.get("user_capacity") or {}).get("bytes"), "temp": (d.get("temperature") or {}).get("current"),
           "hours": (d.get("power_on_time") or {}).get("hours"), "passed": (d.get("smart_status") or {}).get("passed"), "wear": None, "errors": 0}
    issues = []
    if out["passed"] is False:
        issues.append({"severity": "critical", "text": "Disque %s : l'auto-diagnostic SMART annonce une panne." % out["name"]})
    nv = d.get("nvme_smart_health_information_log")
    if nv:
        out["wear"] = nv.get("percentage_used")
        out["errors"] = nv.get("media_errors") or 0
        if nv.get("critical_warning"):
            issues.append({"severity": "critical", "text": "Disque %s : alerte critique NVMe (code %s)." % (out["name"], nv["critical_warning"])})
        if out["errors"]:
            issues.append({"severity": "warning", "text": "Disque %s : %d erreur(s) de média." % (out["name"], out["errors"])})
        if (nv.get("percentage_used") or 0) >= 90:
            issues.append({"severity": "warning", "text": "Disque %s : usure à %s %%, à remplacer bientôt." % (out["name"], nv["percentage_used"])})
        if nv.get("available_spare") is not None and nv.get("available_spare_threshold") is not None and nv["available_spare"] <= nv["available_spare_threshold"]:
            issues.append({"severity": "critical", "text": "Disque %s : réserve de cellules épuisée." % out["name"]})
    table = (d.get("ata_smart_attributes") or {}).get("table") or []
    bad = {a.get("id"): (a.get("raw") or {}).get("value", 0) for a in table if a.get("id") in (5, 197, 198)}
    for aid, label in ((5, "secteurs réalloués"), (197, "secteurs en attente"), (198, "secteurs irrécupérables")):
        if bad.get(aid):
            out["errors"] += bad[aid]
            issues.append({"severity": "warning" if aid == 5 else "critical", "text": "Disque %s : %d %s." % (out["name"], bad[aid], label)})
    if (out["temp"] or 0) >= 70:
        issues.append({"severity": "warning", "text": "Disque %s : %s °C, trop chaud." % (out["name"], out["temp"])})
    out["issues"] = issues
    out["state"] = _worst(issues) if issues else "ok"
    return out


def parse_mdstat(text):
    """/proc/mdstat : grappes RAID logicielles et état (dégradée si un membre manque)."""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^(md\d+)\s*:\s*(\w+)\s+(\S+)\s*(.*)$", line)
        if m:
            cur = {"name": m.group(1), "state": m.group(2), "level": m.group(3), "members": re.findall(r"(\w+)\[\d+\]", m.group(4)), "degraded": False, "progress": None}
            out.append(cur)
            continue
        if cur:
            s = re.search(r"\[(\d+)/(\d+)\]\s*\[([U_]+)\]", line)
            if s:
                cur["degraded"] = "_" in s.group(3) or s.group(1) != s.group(2)
            p = re.search(r"(recovery|resync|reshape)\s*=\s*([\d.]+)%", line)
            if p:
                cur["progress"] = {"action": p.group(1), "percent": float(p.group(2))}
    return out


def hw_issues(smart, raid, xid):
    """Liste unique de problèmes pour les alertes : [{key, severity, text}]."""
    out = []
    for d in smart or []:
        for n, i in enumerate(d.get("issues") or []):
            out.append({"key": "hw_disk:%s:%d" % (d["name"], n), "severity": i["severity"], "text": i["text"]})
    for r in raid or []:
        if r.get("degraded"):
            out.append({"key": "raid:%s" % r["name"], "severity": "critical", "text": "Grappe RAID %s dégradée (un disque manque ou a été retiré)%s." % (
                r["name"], " : reconstruction à %s %%" % r["progress"]["percent"] if r.get("progress") else "")})
    for x in xid or []:
        if x["severity"] != "info":
            out.append({"key": "gpu_xid:%s:%d" % (x["pci"], x["xid"]), "severity": x["severity"], "text": "GPU %s : erreur matérielle Xid %d%s." % (x["pci"], x["xid"], " (%s)" % x["text"] if x["text"] else "")})
    return out
