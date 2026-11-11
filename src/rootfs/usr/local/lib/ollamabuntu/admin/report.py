#!/usr/bin/env python3
"""OllamaBuntu - rapport hebdomadaire : synthèse de la semaine (usage, débit, incidents, matériel) en texte et en HTML.
Fonction pure : reçoit les chiffres déjà calculés, ne touche ni au disque ni au réseau."""
import html
import time

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _n(v):
    return "{:,}".format(int(v or 0)).replace(",", " ")


def _gb(b):
    return "%.1f Go" % (b / 1024 ** 3) if b else "—"


def due(cfg, lt, last_sent):
    """Faut-il envoyer maintenant ? cfg : enabled, day (0 = lundi), hour ; lt : heure locale ; last_sent : « AAAA-MM-JJ » du dernier envoi."""
    if not cfg.get("enabled"):
        return False
    today = "%04d-%02d-%02d" % (lt.tm_year, lt.tm_mon, lt.tm_mday)
    return lt.tm_wday == cfg.get("day", 0) and lt.tm_hour >= cfg.get("hour", 8) and last_sent != today


def build(d):
    """d : host, version, since, until (secondes), usage (usage.aggregate sur 7 jours), tps_avg, uptime_days, disk {used,total}, alerts [str],
    guard_events [{result,codes}], perf_events [str], hw [str], keys_expiring [str], update (version|None), models_unused [{name,size}].
    Retourne (objet, texte, html)."""
    u = d.get("usage") or {}
    t = u.get("total") or {}
    day = lambda ts: time.strftime("%d/%m/%Y", time.localtime(ts))
    errors = t.get("errors", 0)
    rate = " (%.1f %%)" % (100.0 * errors / t["count"]) if t.get("count") else ""
    sections = [
        ("Usage", ["%s requêtes, %s en erreur%s" % (_n(t.get("count")), _n(errors), rate),
                   "%s jetons en entrée, %s en sortie" % (_n(t.get("in_tok")), _n(t.get("out_tok")))] +
                  (["Débit moyen : %s jetons/s" % d["tps_avg"]] if d.get("tps_avg") else [])),
        ("Modèles les plus utilisés", ["%s : %s requêtes" % (m["name"], _n(m["count"])) for m in (u.get("models") or [])[:5]] or ["Aucune requête cette semaine."]),
        ("Clients les plus actifs", ["%s : %s requêtes, %s jetons" % (c["name"], _n(c["count"]), _n(c["in_tok"] + c["out_tok"])) for c in (u.get("clients") or [])[:5]] or ["Aucun client."]),
    ]
    inc = list(d.get("alerts") or [])
    inc += ["Réparation GPU (%s) : %s" % (", ".join(e.get("codes") or []) or "?", e.get("result", "?")) for e in d.get("guard_events") or []]
    inc += list(d.get("perf_events") or [])
    sections.append(("Incidents et réglages", inc[:12] or ["Aucun incident."]))
    health = list(d.get("hw") or [])
    disk = d.get("disk") or {}
    if disk.get("total"):
        health.append("Disque système occupé à %d %% (%s libres)" % (round(100.0 * disk["used"] / disk["total"]), _gb(disk["total"] - disk["used"])))
    if d.get("uptime_days") is not None:
        health.append("Serveur démarré depuis %d jour(s)" % d["uptime_days"])
    sections.append(("Santé du serveur", health or ["Rien à signaler."]))
    todo = list(d.get("keys_expiring") or [])
    if d.get("update"):
        todo.append("Version %s d'OllamaBuntu disponible" % d["update"])
    for m in (d.get("models_unused") or [])[:5]:
        todo.append("Modèle inutilisé : %s (%s)" % (m["name"], _gb(m.get("size"))))
    sections.append(("À faire", todo or ["Rien."]))
    title = "OllamaBuntu %s — rapport du %s au %s" % (d.get("host", ""), day(d.get("since", 0)), day(d.get("until", 0)))
    text = title + "\n\n" + "\n\n".join("%s\n%s\n%s" % (h, "-" * len(h), "\n".join("• " + x for x in rows)) for h, rows in sections) + "\n"
    esc = html.escape
    body = "".join("<h3 style='margin:18px 0 6px;font-size:15px'>%s</h3><ul style='margin:0;padding-left:20px'>%s</ul>" % (esc(h), "".join("<li>%s</li>" % esc(x) for x in rows)) for h, rows in sections)
    page = "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:640px;color:#1a1a1a'><h2 style='font-size:18px'>%s</h2>%s</div>" % (esc(title), body)
    return {"title": title, "sections": [{"title": h, "rows": r} for h, r in sections]}, text, page


def clean_config(data, cur=None):
    cur = cur or {"enabled": False, "day": 0, "hour": 8}
    out = dict(cur)
    if "enabled" in data:
        out["enabled"] = bool(data["enabled"])
    for k, lo, hi in (("day", 0, 6), ("hour", 0, 23)):
        if k in data:
            try:
                v = int(data[k])
            except (TypeError, ValueError):
                raise ValueError("%s invalide" % k)
            if not lo <= v <= hi:
                raise ValueError("%s hors limites (%d à %d)" % (k, lo, hi))
            out[k] = v
    return out
