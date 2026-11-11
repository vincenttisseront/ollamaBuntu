#!/usr/bin/env python3
"""OllamaBuntu - réveil (Wake-on-LAN) et mise en veille des serveurs du parc selon la demande.
Fonctions pures, sauf send_wol (un paquet UDP) et list_nics (lecture de /sys) : testables hors de la console.

Principe : la console principale réveille un serveur du parc quand la demande dépasse ce que les serveurs éveillés peuvent servir, et le met en veille
quand il n'a plus rien à faire depuis un moment. Trois signaux de demande :
- la file d'attente du routeur (demandes en attente depuis plus de N secondes) ;
- la saturation : tous les serveurs éveillés sont occupés depuis un moment ;
- un modèle demandé que seul un serveur endormi possède (le routeur le signale et répond « réessayez dans un instant »).
Le réveil par paquet magique dépend du matériel (carte réseau, BIOS, câble) : rien ici ne le garantit, d'où le suivi (« réveil sans effet ») et la reprise
manuelle. La mise en veille est une action distante que le serveur concerné doit avoir autorisée lui-même."""
import os
import re
import socket
import time

DEFAULTS = {"enabled": False, "wake_waiting": 1, "wake_after_s": 20, "wake_busy_pct": 85, "wake_busy_s": 60, "cooldown_s": 300, "wake_timeout_s": 240,
            "keep_awake": 0, "settle_s": 600}
LIMITS = {"wake_waiting": (0, 1000, "demandes en attente : 0 à 1000 (0 = ne pas réveiller selon la file)"),
          "wake_after_s": (5, 3600, "attente avant réveil : 5 à 3600 secondes"),
          "wake_busy_pct": (0, 100, "seuil de saturation : 0 à 100 % (0 = désactivé)"),
          "wake_busy_s": (10, 3600, "durée de saturation : 10 à 3600 secondes"),
          "cooldown_s": (30, 86400, "délai avant de réveiller de nouveau le même serveur : 30 à 86400 secondes"),
          "wake_timeout_s": (30, 3600, "délai pour qu'un serveur réveillé réponde : 30 à 3600 secondes"),
          "keep_awake": (0, 50, "serveurs toujours éveillés : 0 à 50"),
          "settle_s": (0, 86400, "durée minimale d'éveil après un réveil : 0 à 86400 secondes")}
HINT_TTL = 180          # un modèle demandé il y a moins de 3 minutes justifie encore un réveil
IDLE_LOAD = 5.0         # charge (%) en dessous de laquelle un serveur est considéré au repos
IDLE_RECENT = 120       # secondes sans requête routée vers lui
MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
MODES = ("", "suspend", "poweroff")
IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


def mac_clean(v):
    """Adresse MAC normalisée (aa:bb:cc:dd:ee:ff). Vide accepté ; ValueError sinon."""
    s = str(v or "").strip().lower()
    if not s:
        return ""
    hexa = re.sub(r"[:\-.]", "", s)
    if not re.fullmatch(r"[0-9a-f]{12}", hexa):
        raise ValueError("adresse MAC invalide (ex. 3c:ec:ef:12:34:56)")
    mac = ":".join(hexa[i:i + 2] for i in range(0, 12, 2))
    if mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        raise ValueError("adresse MAC invalide (ex. 3c:ec:ef:12:34:56)")
    return mac


def broadcast_clean(v):
    """Adresse de diffusion IPv4 du réseau du serveur (facultative ; défaut 255.255.255.255)."""
    s = str(v or "").strip()
    if not s:
        return ""
    parts = s.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 and str(int(p)) == p for p in parts):
        raise ValueError("adresse de diffusion invalide (ex. 192.168.1.255)")
    return s


def magic_packet(mac):
    raw = bytes.fromhex(mac_clean(mac).replace(":", ""))
    if len(raw) != 6:
        raise ValueError("adresse MAC manquante")
    return b"\xff" * 6 + raw * 16


def send_wol(mac, broadcast="", port=9):
    """Envoie le paquet magique en diffusion UDP. Retourne le nombre d'octets envoyés (102)."""
    pkt = magic_packet(mac)
    addr = broadcast_clean(broadcast) or "255.255.255.255"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(3)
        return s.sendto(pkt, (addr, int(port)))
    finally:
        s.close()


def config_clean(data, cur=None):
    """Réglages généraux (ValueError si invalides) ; les champs absents gardent leur valeur actuelle."""
    out = dict(DEFAULTS, **(cur or {}))
    data = data if isinstance(data, dict) else {}
    if "enabled" in data:
        out["enabled"] = bool(data["enabled"])
    for k, (lo, hi, label) in LIMITS.items():
        if k in data:
            try:
                v = int(str(data[k]).strip())
            except (TypeError, ValueError):
                raise ValueError(label)
            if not lo <= v <= hi:
                raise ValueError(label)
            out[k] = v
    return out


def server_clean(data, cur=None):
    """Réglages d'un serveur du parc : adresse MAC, réveil automatique, mise en veille automatique après inactivité."""
    out = dict({"mac": "", "broadcast": "", "wake": False, "sleep": "", "idle_min": 30}, **(cur or {}))
    data = data if isinstance(data, dict) else {}
    if "mac" in data:
        out["mac"] = mac_clean(data["mac"])
    if "broadcast" in data:
        out["broadcast"] = broadcast_clean(data["broadcast"])
    if "wake" in data:
        out["wake"] = bool(data["wake"])
    if "sleep" in data:
        if data["sleep"] not in MODES:
            raise ValueError("mise en veille : aucune, veille (suspend) ou extinction")
        out["sleep"] = data["sleep"]
    if "idle_min" in data:
        try:
            v = int(str(data["idle_min"]).strip())
        except (TypeError, ValueError):
            raise ValueError("inactivité avant mise en veille : 5 à 1440 minutes")
        if not 5 <= v <= 1440:
            raise ValueError("inactivité avant mise en veille : 5 à 1440 minutes")
        out["idle_min"] = v
    if out["wake"] and not out["mac"]:
        raise ValueError("le réveil automatique demande l'adresse MAC du serveur")
    if out["sleep"] and not out["mac"]:
        raise ValueError("la mise en veille automatique demande l'adresse MAC du serveur (sans elle, il ne pourrait plus être réveillé)")
    return out


def member_clean(data):
    """Réglage côté serveur géré : la console principale peut-elle le mettre en veille ? « » refuse, « suspend » ou « poweroff » autorise."""
    mode = (data or {}).get("allow", "") if isinstance(data, dict) else ""
    if mode not in MODES:
        raise ValueError("mise en veille à distance : refuser, veille (suspend) ou extinction")
    return {"allow": mode}


def allowed(allow, mode):
    """La console principale peut-elle demander `mode` à un serveur qui a autorisé `allow` ? (l'extinction autorise aussi la veille)"""
    return bool(mode) and (allow == mode or (allow == "poweroff" and mode == "suspend"))


def requestable(models, model_map):
    """Noms de modèles qu'un serveur peut servir : ses modèles, plus ceux pour lesquels il a un modèle de remplacement. « * » = tout."""
    have = set(models)
    out = set(have)
    for k, v in (model_map or {}).items():
        if v in have:
            out.add("*" if k == "*" else k)
    return out


def serves(models, wanted):
    """Un serveur sert-il l'un des modèles demandés ? Liste inconnue (vide) : on ne peut pas l'exclure."""
    return not models or "*" in models or bool(set(wanted) & set(models))


def state_of(online, wake_sent, slept_at, now, timeout):
    """awake (répond) / waking (paquet envoyé, délai non écoulé) / asleep (mis en veille par la console) / offline (injoignable, cause inconnue)."""
    if online:
        return "awake"
    if wake_sent and now - wake_sent < timeout:
        return "waking"
    if slept_at and (not wake_sent or wake_sent < slept_at):
        return "asleep"
    return "offline"


def is_idle(load, jobs, last_request, now):
    """Serveur au repos : charge faible, aucune tâche en cours, aucune requête routée vers lui depuis IDLE_RECENT secondes."""
    return load is not None and load < IDLE_LOAD and not jobs and (not last_request or now - last_request > IDLE_RECENT)


def track_idle(mem, idle, now):
    """Met à jour la mémoire d'un serveur : début du repos (None dès qu'il travaille)."""
    if idle:
        mem.setdefault("idle_since", now)
        if mem["idle_since"] is None:
            mem["idle_since"] = now
    else:
        mem["idle_since"] = None
    return mem


def track_busy(busy_since, busy, now):
    """Début de la saturation du parc (None quand elle cesse)."""
    if not busy:
        return None
    return busy_since if busy_since is not None else now


def saturated(loads, pct):
    """Tous les serveurs éveillés sont-ils au moins à `pct` % ? (loads : charges des serveurs éveillés, local compris)"""
    return bool(pct) and bool(loads) and all(l is not None and l >= pct for l in loads)


def decide(now, conf, servers, waiting, hints, busy_since):
    """Actions à mener : [{"action": "wake"|"sleep", "id", "name", "why"}]. Au plus un réveil ou une mise en veille par passage.
    servers : [{id, name, state, power, models, idle_since, woke_at, wake_sent}] ; waiting : [{model, waited}] ; hints : {modèle: heure}."""
    if not conf.get("enabled"):
        return []
    acts = []
    fresh = {m for m, t in (hints or {}).items() if now - t <= HINT_TTL}
    why, wanted = None, set()
    if conf["wake_waiting"] and waiting and len(waiting) >= conf["wake_waiting"]:
        old = max(w.get("waited", 0) for w in waiting)
        if old >= conf["wake_after_s"]:
            why = "%d demande(s) en attente, la plus ancienne depuis %d s" % (len(waiting), old)
            wanted = {w["model"] for w in waiting if w.get("model")}
    if not why and fresh:
        why = "modèle demandé que seul un serveur endormi possède : %s" % ", ".join(sorted(fresh))
        wanted = fresh
    if not why and conf["wake_busy_pct"] and busy_since is not None and now - busy_since >= conf["wake_busy_s"]:
        why = "tous les serveurs éveillés sont occupés (%d %% ou plus) depuis %d s" % (conf["wake_busy_pct"], now - busy_since)
    if why:
        if not any(s["state"] == "waking" for s in servers):
            cands = [s for s in servers if s["state"] in ("asleep", "offline") and s["power"].get("wake") and s["power"].get("mac")
                     and now - (s.get("wake_sent") or 0) >= conf["cooldown_s"]]
            if wanted:
                cands = [s for s in cands if serves(s["models"], wanted)]
            if cands:
                pick = min(cands, key=lambda s: (bool(wanted) and not (wanted & set(s["models"])) and "*" not in s["models"], s["state"] != "asleep", s["name"].lower()))
                acts.append({"action": "wake", "id": pick["id"], "name": pick["name"], "why": why})
        return acts   # demande en cours : aucune mise en veille
    if waiting or fresh:
        return acts   # une demande attend encore (sous le seuil de réveil) : on ne met rien en veille
    awake = [s for s in servers if s["state"] == "awake"]
    if any(s["state"] == "waking" for s in servers) or len(awake) <= conf["keep_awake"]:
        return acts
    for s in sorted(awake, key=lambda s: (s.get("idle_since") or now, s["name"].lower())):
        p = s["power"]
        if not p.get("sleep") or not p.get("mac") or s.get("idle_since") is None:
            continue
        idle = now - s["idle_since"]
        if idle < p.get("idle_min", 30) * 60:
            continue
        if s.get("woke_at") and now - s["woke_at"] < conf["settle_s"]:
            continue
        acts.append({"action": "sleep", "id": s["id"], "name": s["name"], "why": "inactif depuis %d min" % (idle // 60), "mode": p["sleep"]})
        break
    return acts


# ------------------------------------------------------------------ cartes réseau du serveur (côté serveur géré)
def list_nics(root="/sys/class/net", ethtool=None):
    """Cartes réseau filtrables pour le réveil : filaires et physiques seulement. ethtool(iface) -> texte de `ethtool iface` ou None."""
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        base = os.path.join(root, name)
        if name == "lo" or not IFACE_RE.match(name) or not os.path.exists(os.path.join(base, "device")) or os.path.exists(os.path.join(base, "wireless")):
            continue
        try:
            with open(os.path.join(base, "address"), encoding="ascii") as f:
                mac = mac_clean(f.read())
        except (OSError, ValueError):
            continue
        try:
            with open(os.path.join(base, "operstate"), encoding="ascii") as f:
                link = f.read().strip()
        except OSError:
            link = "?"
        wol, supported = parse_ethtool(ethtool(name)) if ethtool else ("?", None)
        out.append({"iface": name, "mac": mac, "link": link, "wol": wol, "supported": supported})
    return out


def parse_ethtool(text):
    """(état du réveil, pris en charge) d'après la sortie d'ethtool : « magic » / « off » / « ? », et si le paquet magique (g) est pris en charge."""
    if not text:
        return "?", None
    supports = re.search(r"Supports Wake-on:\s*(\S+)", text)
    cur = re.search(r"^\s*Wake-on:\s*(\S+)", text, re.M)
    sup = ("g" in supports.group(1)) if supports else None
    if not cur:
        return "?", sup
    return ("magic" if "g" in cur.group(1) else "off"), sup


def event_line(ts, kind, name, why, ok=True, detail=""):
    return {"ts": int(ts), "kind": kind, "server": name, "why": why, "ok": bool(ok), "detail": detail[:200]}
