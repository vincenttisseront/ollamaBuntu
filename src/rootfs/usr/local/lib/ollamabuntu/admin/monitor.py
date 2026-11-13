#!/usr/bin/env python3
"""OllamaBuntu - supervision : débordement CPU/GPU, recommandation de réglages, moteur d'alertes (webhook, e-mail).
Fonctions pures, sans état global ni réseau (sauf les envois, injectables) : testable hors de la console."""
import json
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage

GB = 1024 ** 3
EVENTS = {
    "offload": "Modèle partiellement sur le processeur (débit très réduit)",
    "service": "Service Ollama arrêté",
    "disk": "Disque presque plein",
    "gpu_temp": "GPU trop chaud",
    "tps_low": "Débit de génération trop bas",
    "server_offline": "Serveur du parc hors ligne",
    "update": "Nouvelle version d'OllamaBuntu disponible",
    "key_expiry": "Clé d'API expirée ou bientôt expirée",
    "gpu_guard": "Carte graphique indisponible ou inutilisée par Ollama",
    "hw_disk": "Disque en mauvaise santé (SMART)",
    "raid": "Grappe RAID dégradée",
    "gpu_xid": "Erreur matérielle de la carte graphique (Xid)",
    "perf_fix": "Chute de débit avec réglage suggéré",
}
DEFAULTS = {"enabled": False, "webhook": {"url": ""}, "smtp": {"host": "", "port": 587, "user": "", "from": "", "to": [], "starttls": True},
            "events": ["offload", "service", "disk", "gpu_temp", "tps_low", "server_offline", "key_expiry", "gpu_guard", "hw_disk", "raid", "gpu_xid", "perf_fix"], "disk_pct": 90, "gpu_temp": 85, "tps_min": 0}


def offload(running, has_gpu=True):
    """Modèles chargés en partie hors de la mémoire vidéo (d'après /api/ps). Sans GPU, tout est sur le processeur : pas d'alerte."""
    out = []
    if not has_gpu:
        return out
    for m in running or []:
        if m.get("engine"):
            continue   # moteur llama.cpp : les experts en mémoire système sont voulus (ils ne sont pas un débordement subi)
        size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
        if size <= 0 or vram >= size:
            continue
        cpu = round(100.0 * (1 - vram / size))
        if cpu >= 5:
            out.append({"name": m.get("name") or m.get("model") or "?", "cpu_pct": cpu, "size": size, "vram": vram})
    return out


def recommend(vram_total, weights, bytes_per_token, ctx_max=None, max_parallel=4, reserve=0.08, overhead=GB // 2):
    """Contexte et parallélisme qui tiennent en mémoire vidéo.
    La mémoire du cache est (contexte x requêtes parallèles) jetons ; poids du modèle et marge déduits d'abord."""
    if not vram_total or not weights or not bytes_per_token:
        return {"known": False}
    free = vram_total * (1 - reserve) - weights - overhead
    if free <= 0:
        return {"known": True, "fits": False, "tokens": 0, "parallel": 1, "ctx": None}
    tokens = int(free // bytes_per_token)
    cap = int(ctx_max) if ctx_max else 131072
    for min_ctx in (8192, 4096):   # d'abord le plus de parallélisme avec un contexte confortable
        for p in range(max_parallel, 0, -1):
            ctx = (min(cap, tokens // p) // 1024) * 1024
            if ctx >= min_ctx:
                return {"known": True, "fits": True, "tokens": tokens, "parallel": p, "ctx": ctx}
    return {"known": True, "fits": True, "tokens": tokens, "parallel": 1, "ctx": max((tokens // 256) * 256, 0) or None, "tight": True}


def evaluate(snap, cfg):
    """Alertes actives d'après l'instantané : {clé: {severity, text}}. snap : service, disk{used,total}, gpus[{name,temp}],
    offload[{name,cpu_pct}], servers[{name,online}], tps{avg,count}, update, keys, guard[{code,severity,pci,text}], hw[{key,severity,text}]."""
    on = set(cfg.get("events") or [])
    out = {}
    if "service" in on and snap.get("service") not in (None, "active"):
        out["service"] = {"severity": "critical", "text": "Ollama : service %s" % snap.get("service")}
    if "offload" in on:
        for m in snap.get("offload") or []:
            out["offload:%s" % m["name"]] = {"severity": "warning", "text": "%s tourne à %d %% sur le processeur : débit fortement réduit" % (m["name"], m["cpu_pct"])}
    d = snap.get("disk") or {}
    if "disk" in on and d.get("total") and 100.0 * d.get("used", 0) / d["total"] >= cfg.get("disk_pct", 90):
        out["disk"] = {"severity": "warning", "text": "Disque occupé à %d %%" % round(100.0 * d["used"] / d["total"])}
    if "gpu_temp" in on:
        for g in snap.get("gpus") or []:
            if g.get("temp") is not None and g["temp"] >= cfg.get("gpu_temp", 85):
                out["gpu_temp:%s" % g.get("name")] = {"severity": "warning", "text": "GPU %s à %d °C" % (g.get("name"), g["temp"])}
    t = snap.get("tps") or {}
    if "tps_low" in on and cfg.get("tps_min") and t.get("count", 0) >= 3 and t.get("avg") is not None and t["avg"] < cfg["tps_min"]:
        out["tps_low"] = {"severity": "warning", "text": "Débit moyen de %s jetons/s sur les dernières requêtes (seuil %s)" % (t["avg"], cfg["tps_min"])}
    if "server_offline" in on:
        for s in snap.get("servers") or []:
            if not s.get("online"):
                out["server_offline:%s" % s.get("name")] = {"severity": "critical", "text": "Serveur « %s » hors ligne" % s.get("name")}
    if "key_expiry" in on:
        for k in snap.get("keys") or []:
            d = k.get("days_left")
            if d is None or d > 7:
                continue
            out["key_expiry:%s" % k.get("name")] = ({"severity": "warning", "text": "Clé d'API « %s » expirée" % k.get("name")} if d < 0 else
                                                     {"severity": "info", "text": "Clé d'API « %s » expire %s" % (k.get("name"), "aujourd'hui" if d == 0 else "dans %d jour(s)" % d)})
    if "gpu_guard" in on:
        for i in snap.get("guard") or []:
            if i.get("severity") != "info":
                out["gpu_guard:%s:%s" % (i.get("code"), i.get("pci") or "")] = {"severity": i["severity"], "text": i.get("text", "")}
    pf = snap.get("perf")
    if "perf_fix" in on and pf:
        out["perf_fix"] = {"severity": "warning", "text": pf.get("text", "")}
    for i in snap.get("hw") or []:
        kind = str(i.get("key", "")).split(":")[0]
        ev = {"hw_disk": "hw_disk", "raid": "raid", "gpu_xid": "gpu_xid"}.get(kind)
        if ev and ev in on and i.get("severity") != "info":
            out[i["key"]] = {"severity": i["severity"], "text": i.get("text", "")}
    if "update" in on and snap.get("update"):
        out["update"] = {"severity": "info", "text": "Version %s d'OllamaBuntu disponible" % snap["update"]}
    return out


class Notifier:
    """Notifie à l'apparition d'une alerte (après `hold` secondes pour éviter les à-coups) et à sa résolution."""

    def __init__(self, hold=120):
        self.hold = hold
        self.seen = {}      # clé -> date d'apparition
        self.sent = set()   # clés notifiées

    def step(self, active, now):
        events = []
        for k, a in active.items():
            self.seen.setdefault(k, now)
            if k not in self.sent and now - self.seen[k] >= self.hold:
                self.sent.add(k)
                events.append({"state": "alert", "key": k, **a})
        for k in list(self.seen):
            if k not in active:
                if k in self.sent:
                    self.sent.discard(k)
                    events.append({"state": "resolved", "key": k, "severity": "info", "text": "Rétabli : %s" % k})
                del self.seen[k]
        return events


def post_webhook(url, payload, timeout=10):
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("adresse du webhook invalide (http ou https)")
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json", "User-Agent": "OllamaBuntu"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def send_mail(cfg, password, subject, body, timeout=15, html=None):
    if not cfg.get("host") or not cfg.get("to") or not cfg.get("from"):
        raise ValueError("serveur SMTP, expéditeur et destinataires requis")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["from"], ", ".join(cfg["to"])
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    port = int(cfg.get("port") or 587)
    if port == 465:
        s = smtplib.SMTP_SSL(cfg["host"], port, timeout=timeout, context=ssl.create_default_context())
    else:
        s = smtplib.SMTP(cfg["host"], port, timeout=timeout)
        if cfg.get("starttls", True):
            s.starttls(context=ssl.create_default_context())
    try:
        if cfg.get("user"):
            s.login(cfg["user"], password or "")
        s.send_message(msg)
    finally:
        s.quit()


def clean_config(data, old=None):
    """Valide la configuration reçue de la console. Le mot de passe SMTP est conservé s'il n'est pas renvoyé."""
    old = old or {}
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["enabled"] = bool(data.get("enabled"))
    url = str((data.get("webhook") or {}).get("url") or "").strip()
    if url:
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname or len(url) > 500:
            raise ValueError("adresse du webhook invalide (http ou https)")
    cfg["webhook"]["url"] = url
    sm = data.get("smtp") or {}
    port = int(sm.get("port") or 587)
    if not 1 <= port <= 65535:
        raise ValueError("port SMTP invalide")
    to = [str(x).strip() for x in (sm.get("to") or []) if str(x).strip()]
    if len(to) > 20 or any("@" not in x or len(x) > 200 or "\n" in x for x in to):
        raise ValueError("destinataires invalides")
    frm = str(sm.get("from") or "").strip()
    if frm and ("@" not in frm or "\n" in frm):
        raise ValueError("expéditeur invalide")
    cfg["smtp"] = {"host": str(sm.get("host") or "").strip()[:200], "port": port, "user": str(sm.get("user") or "").strip()[:200], "from": frm, "to": to,
                   "starttls": bool(sm.get("starttls", True))}
    pw = sm.get("password")
    cfg["smtp"]["password"] = str(pw) if pw else (old.get("smtp") or {}).get("password", "")
    cfg["events"] = [e for e in EVENTS if e in (data.get("events") or [])]
    for k, lo, hi in (("disk_pct", 50, 99), ("gpu_temp", 50, 120), ("tps_min", 0, 10000)):
        try:
            v = float(data.get(k, DEFAULTS[k]))
        except (TypeError, ValueError):
            raise ValueError("valeur invalide : %s" % k)
        if not lo <= v <= hi:
            raise ValueError("%s hors limites (%d à %d)" % (k, lo, hi))
        cfg[k] = int(v)
    return cfg
