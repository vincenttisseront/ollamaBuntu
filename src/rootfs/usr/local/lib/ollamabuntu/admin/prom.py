#!/usr/bin/env python3
"""OllamaBuntu - exposition des mesures au format texte Prometheus (version 0.0.4).
Fonction pure : reçoit un instantané, retourne le texte. Aucune donnée sensible (ni clé, ni contenu de requête)."""
import hashlib
import hmac
import re


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class _Out:
    def __init__(self):
        self.lines, self.seen = [], set()

    def add(self, metric, help_, kind, value, **labels):   # « name » reste disponible comme étiquette
        if value is None:
            return
        if metric not in self.seen:
            self.seen.add(metric)
            self.lines += ["# HELP %s %s" % (metric, help_), "# TYPE %s %s" % (metric, kind)]
        lab = "{%s}" % ",".join('%s="%s"' % (k, _esc(v)) for k, v in sorted(labels.items())) if labels else ""
        self.lines.append("%s%s %s" % (metric, lab, float(value) if not isinstance(value, bool) else int(value)))


def render(snap):
    """snap : cpu, mem (pourcentages), gpus[{pci,name,util,mem_used,mem_total,temp,power}], counters{requests,errors,tokens_in,tokens_out},
    queue{running,waiting}, servers[{name,online}], alerts (nombre), ollama_up (bool), version."""
    o = _Out()
    o.add("ollamabuntu_info", "Version de l'appliance", "gauge", 1, version=snap.get("version", ""))
    o.add("ollamabuntu_ollama_up", "Service Ollama actif (1) ou non (0)", "gauge", snap.get("ollama_up"))
    o.add("ollamabuntu_cpu_usage_percent", "Utilisation du processeur", "gauge", snap.get("cpu"))
    o.add("ollamabuntu_memory_usage_percent", "Utilisation de la mémoire", "gauge", snap.get("mem"))
    for g in snap.get("gpus") or []:
        lab = {"gpu": g.get("pci", "?"), "name": g.get("name", "?")}
        o.add("ollamabuntu_gpu_utilization_percent", "Charge du GPU", "gauge", g.get("util"), **lab)
        o.add("ollamabuntu_gpu_memory_used_bytes", "Mémoire vidéo utilisée", "gauge", g.get("mem_used"), **lab)
        o.add("ollamabuntu_gpu_memory_total_bytes", "Mémoire vidéo totale", "gauge", g.get("mem_total"), **lab)
        o.add("ollamabuntu_gpu_temperature_celsius", "Température du GPU", "gauge", g.get("temp"), **lab)
        o.add("ollamabuntu_gpu_power_watts", "Puissance consommée par le GPU", "gauge", g.get("power"), **lab)
    c = snap.get("counters") or {}
    o.add("ollamabuntu_requests_total", "Requêtes d'inférence traitées depuis le démarrage de la console", "counter", c.get("requests"))
    o.add("ollamabuntu_request_errors_total", "Requêtes d'inférence en erreur", "counter", c.get("errors"))
    o.add("ollamabuntu_tokens_total", "Jetons traités", "counter", c.get("tokens_in"), direction="input")
    o.add("ollamabuntu_tokens_total", "Jetons traités", "counter", c.get("tokens_out"), direction="output")
    q = snap.get("queue") or {}
    o.add("ollamabuntu_queue_running", "Requêtes en cours (clés plafonnées)", "gauge", q.get("running"))
    o.add("ollamabuntu_queue_waiting", "Requêtes en file d'attente", "gauge", q.get("waiting"))
    for s in snap.get("servers") or []:
        o.add("ollamabuntu_fleet_server_up", "Serveur du parc en ligne (1) ou non (0)", "gauge", bool(s.get("online")), server=s.get("name", "?"))
    o.add("ollamabuntu_alerts_active", "Alertes actives", "gauge", snap.get("alerts"))
    return "\n".join(o.lines) + "\n"


def token_ok(token, digest):
    """Jeton présenté (Bearer) comparé à l'empreinte SHA-256 enregistrée, en temps constant."""
    if not token or not digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), digest)
