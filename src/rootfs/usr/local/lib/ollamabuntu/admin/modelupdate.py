#!/usr/bin/env python3
"""OllamaBuntu - mise à jour des modèles avec retour arrière : fenêtre de maintenance, nom de la copie de sécurité, décision de conserver ou de revenir.
Fonctions pures (aucun accès disque, réseau ni commande) : testables hors de la console.

Principe : avant de télécharger la nouvelle version, on copie l'ancienne sous un autre nom (`ollama cp`, sans dupliquer les fichiers : les deux noms
partagent les mêmes couches). La copie garde donc l'ancienne version même si Ollama nettoie les couches devenues inutiles. Après la mise à jour, un test
rapide (et, si on en a choisi un, un jeu de tests de non-régression) décide : on garde la nouvelle version ou on recopie l'ancienne à sa place."""
import re

PREV_NS = "ob-prev/"
DAYS = list(range(7))
MAX_MODELS = 50


def prev_name(name):
    """Nom de la copie de sécurité d'un modèle : ob-prev/<nom aplati>:<étiquette>. Un nom Hugging Face (hf.co/depot/modèle:quant) devient un nom simple."""
    base, _, tag = str(name).partition(":")
    slug = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip("-.") or "modele"
    return "%s%s:%s" % (PREV_NS, slug[:100], (tag or "latest")[:60])


def is_prev(name):
    return str(name).startswith(PREV_NS)


def config_clean(c):
    """Valide la configuration (ValueError si invalide) ; les champs absents prennent leur valeur par défaut."""
    c = c if isinstance(c, dict) else {}
    days = c.get("days", [6])
    if not isinstance(days, list) or any(not isinstance(d, int) or isinstance(d, bool) or d not in DAYS for d in days):
        raise ValueError("jours invalides")
    start = str(c.get("start", "03:00"))
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", start):
        raise ValueError("heure de début invalide (HH:MM)")
    try:
        window = int(c.get("window", 180))
        keep = int(c.get("keep_days", 7))
        drop = int(c.get("drop_pct", 30))
    except (TypeError, ValueError):
        raise ValueError("nombre invalide")
    if not 30 <= window <= 720:
        raise ValueError("durée de la fenêtre : 30 à 720 minutes")
    if not 1 <= keep <= 60:
        raise ValueError("conservation de l'ancienne version : 1 à 60 jours")
    if not 10 <= drop <= 90:
        raise ValueError("chute de débit tolérée : 10 à 90 %")
    scope = c.get("scope", "all")
    if scope != "all":
        if not isinstance(scope, list) or not 1 <= len(scope) <= MAX_MODELS or any(not isinstance(m, str) or not m.strip() for m in scope):
            raise ValueError("modèles à mettre à jour invalides")
        scope = [m.strip() for m in scope]
    return {"enabled": bool(c.get("enabled")), "days": sorted(set(days)), "start": start, "window": window, "scope": scope,
            "suite": str(c.get("suite") or ""), "keep_days": keep, "drop_pct": drop}


def _minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def window_key(cfg, lt):
    """Identifiant (date de début, AAAA-MM-JJ) du créneau de maintenance en cours, ou None. lt : time.struct_time local.
    Le créneau commence à l'heure de début d'un jour choisi et peut passer minuit."""
    now, start = lt.tm_hour * 60 + lt.tm_min, _minutes(cfg["start"])
    since = (now - start) % 1440
    if since >= cfg["window"]:
        return None
    day = lt.tm_wday if now >= start else (lt.tm_wday - 1) % 7
    if day not in cfg["days"]:
        return None
    import datetime
    d = datetime.date(lt.tm_year, lt.tm_mon, lt.tm_mday) - datetime.timedelta(days=0 if now >= start else 1)
    return d.isoformat()


def due(cfg, lt, last_key):
    """Clé du créneau à jouer maintenant, ou None (désactivé, hors créneau, ou déjà joué)."""
    if not cfg.get("enabled"):
        return None
    key = window_key(cfg, lt)
    return key if key and key != last_key else None


def tps_drop(before, after):
    """Chute de débit en % (positive = plus lent), ou None si une mesure manque."""
    if not before or not after:
        return None
    return round(100.0 * (before - after) / before, 1)


def decide(smoke_ok, smoke_why, diff, before_tps, after_tps, drop_pct=30):
    """Faut-il garder la nouvelle version ? Retourne {keep, reasons, drop}.
    smoke_ok/smoke_why : le modèle répond-il après la mise à jour ; diff : evals.compare_runs(avant, après) ou None."""
    reasons = []
    if not smoke_ok:
        reasons.append("le modèle ne répond pas correctement : %s" % smoke_why)
    if diff and diff.get("regressions"):
        reasons.append("%d cas de test devenu(s) faux : %s" % (len(diff["regressions"]), ", ".join(diff["regressions"][:5])))
    drop = tps_drop(before_tps, after_tps)
    if drop is not None and drop >= drop_pct:
        reasons.append("débit en baisse de %d %%" % round(drop))
    return {"keep": not reasons, "reasons": reasons, "drop": drop}


def entry(t, model, status, who, reason, detail="", **extra):
    """Ligne d'historique. status : updated | unchanged | rolled_back | failed | manual_rollback."""
    out = {"t": int(t), "model": model, "status": status, "who": who, "reason": reason, "detail": str(detail)[:400]}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def expired(prevs, now, keep_days):
    """Copies de sécurité à supprimer : celles créées il y a plus de keep_days jours. prevs : {nom_du_modèle: {prev, t}}."""
    return [m for m, p in prevs.items() if now - int(p.get("t", 0)) > keep_days * 86400]


def alert_text(entries):
    """Texte d'alerte pour les mises à jour qui ont mal tourné (retour arrière ou échec) ; None si tout va bien."""
    bad = [e for e in entries if e["status"] in ("rolled_back", "failed")]
    if not bad:
        return None
    return "Mise à jour des modèles : " + " ; ".join("%s : %s (%s)" % (e["model"], "ancienne version rétablie" if e["status"] == "rolled_back" else "échec", e["detail"]) for e in bad)
