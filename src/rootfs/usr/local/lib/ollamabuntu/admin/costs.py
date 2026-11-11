#!/usr/bin/env python3
"""OllamaBuntu - imputation des coûts par clé d'API et par équipe : jetons, temps de calcul, énergie estimée, coût.
Fonctions pures (aucun accès disque ni réseau) : testables hors de la console.

Les chiffres viennent du journal des requêtes. Comme ce journal est purgé après quelques jours, la console en tire chaque jour un « registre » compact
(par jour, par client, par modèle) qui sert aux totaux mensuels. Le temps de calcul et l'énergie sont des ESTIMATIONS :
- temps de calcul d'une requête = jetons produits ÷ débit mesuré ; à défaut de débit (embeddings), durée de la requête ;
- énergie = temps de calcul × puissance moyenne en charge indiquée par l'administrateur (aucun wattmètre n'est lu) ;
- coût = énergie × prix du kWh + heures de calcul × coût horaire du matériel (amortissement), tous deux réglables."""
import csv
import io
import re
import time

DEFAULTS = {"watts": 300, "kwh_price": 0.20, "gpu_hour": 0.0, "currency": "€"}
KEEP_DAYS = 400
NO_TEAM = "(sans équipe)"
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def config_clean(data, cur=None):
    """Valide les paramètres de coût (ValueError si invalides) ; les champs absents gardent leur valeur actuelle."""
    out = dict(cur or DEFAULTS)
    data = data if isinstance(data, dict) else {}
    for k, lo, hi, label in (("watts", 1, 5000, "puissance moyenne en charge : 1 à 5000 W"), ("kwh_price", 0, 100, "prix du kWh : 0 à 100"),
                             ("gpu_hour", 0, 10000, "coût horaire du matériel : 0 à 10000")):
        if k in data:
            try:
                v = float(str(data[k]).replace(",", "."))
            except (TypeError, ValueError):
                raise ValueError(label)
            if not lo <= v <= hi or v != v:
                raise ValueError(label)
            out[k] = round(v, 4) if k != "watts" else round(v)
    if "currency" in data:
        c = str(data["currency"] or "").strip()
        if not 1 <= len(c) <= 4 or re.search(r"[\x00-\x1f<>\"'&]", c):
            raise ValueError("devise : 1 à 4 caractères")
        out["currency"] = c
    return out


def team_clean(v):
    t = " ".join(str(v or "").split())
    if len(t) > 40 or re.search(r"[\x00-\x1f<>\"]", t):
        raise ValueError("équipe : 40 caractères au plus, sans < > \"")
    return t


def compute_seconds(r):
    """Temps de calcul estimé d'une requête réussie, en secondes."""
    if r.get("status") != 200:
        return 0.0
    out, tps = r.get("out_tok") or 0, r.get("tps") or 0
    if out and tps:
        return round(out / tps, 3)
    ms = r.get("ms") or 0
    return round(min(ms, 600000) / 1000.0, 3)   # embeddings et réponses sans débit mesuré ; plafonné à 10 min


def day_of(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _new():
    return {"n": 0, "e": 0, "i": 0, "o": 0, "g": 0.0}


def _add(d, r):
    d["n"] += 1
    if r.get("status") != 200:
        d["e"] += 1
    d["i"] += int(r.get("in_tok") or 0)
    d["o"] += int(r.get("out_tok") or 0)
    d["g"] = round(d["g"] + compute_seconds(r), 3)


def add_requests(days, reqs, name=lambda m: m):
    """Ajoute des requêtes au registre {jour: {client: {n, e, i, o, g, m: {modèle: {n, e, i, o, g}}}}} ; retourne le nombre ajouté."""
    n = 0
    for r in reqs:
        ts = r.get("ts")
        if not ts:
            continue
        c = days.setdefault(day_of(ts), {}).setdefault(str(r.get("client") or "?")[:60], dict(_new(), m={}))
        _add(c, r)
        _add(c["m"].setdefault(name(r.get("model")) if r.get("model") else "?", _new()), r)
        n += 1
    return n


def prune(days, now, keep=KEEP_DAYS):
    cut = day_of(now - keep * 86400)
    for d in [d for d in days if d < cut]:
        del days[d]


def select(days, dates):
    """Copie du registre limitée aux jours demandés (le registre d'origine n'est jamais modifié)."""
    out = {}
    for d in dates:
        if d in days:
            out[d] = {c: dict({k: v for k, v in e.items() if k != "m"}, m={m: dict(x) for m, x in e["m"].items()}) for c, e in days[d].items()}
    return out


def month_dates(days, month):
    return [d for d in days if d.startswith(month + "-")]


def last_dates(now, n=7):
    return [day_of(now - i * 86400) for i in range(n)]


def months(days, now):
    """Mois disponibles (le plus récent d'abord), le mois en cours toujours présent."""
    ms = {d[:7] for d in days}
    ms.add(day_of(now)[:7])
    return sorted(ms, reverse=True)


def flat(days):
    """Lignes client × modèle : [{client, model, n, e, i, o, g}] additionnées sur tous les jours fournis."""
    acc = {}
    for d in days.values():
        for client, e in d.items():
            for model, x in e["m"].items():
                a = acc.setdefault((client, model), _new())
                for k in ("n", "e", "i", "o"):
                    a[k] += x[k]
                a["g"] += x["g"]
    return [dict(client=c, model=m, **v) for (c, m), v in sorted(acc.items())]


def energy_kwh(gpu_seconds, cfg):
    return gpu_seconds / 3600.0 * cfg["watts"] / 1000.0


def cost_of(gpu_seconds, cfg):
    return energy_kwh(gpu_seconds, cfg) * cfg["kwh_price"] + gpu_seconds / 3600.0 * cfg["gpu_hour"]


def _out(name, a, cfg, team=None):
    g = a["g"]
    o = {"name": name, "n": a["n"], "e": a["e"], "i": a["i"], "o": a["o"], "gpu_h": round(g / 3600.0, 3), "kwh": round(energy_kwh(g, cfg), 4), "cost": round(cost_of(g, cfg), 4)}
    if team is not None:
        o["team"] = team
    return o


def summarize(rows, cfg, teams):
    """Totaux par client, par équipe et par modèle, avec la part de chacun dans le coût total.
    teams : {client: équipe}. Un client sans équipe est regroupé sous « (sans équipe) »."""
    tot, cl, tm, md = _new(), {}, {}, {}
    for r in rows:
        team = teams.get(r["client"]) or NO_TEAM
        for acc in (tot, cl.setdefault(r["client"], _new()), tm.setdefault(team, _new()), md.setdefault(r["model"], _new())):
            for f in ("n", "e", "i", "o"):
                acc[f] += r[f]
            acc["g"] += r["g"]
    total = _out("total", tot, cfg)
    base = cost_of(tot["g"], cfg)   # parts calculées sur les valeurs non arrondies

    def rank(d, withteam=False):
        items = []
        for k, v in d.items():
            x = _out(k, v, cfg, (teams.get(k) or NO_TEAM) if withteam else None)
            x["share"] = round(100.0 * cost_of(v["g"], cfg) / base) if base else (round(100.0 * v["n"] / tot["n"]) if tot["n"] else 0)
            items.append(x)
        return sorted(items, key=lambda x: (-x["cost"], -x["o"], x["name"]))
    return {"total": total, "clients": rank(cl, True), "teams": rank(tm), "models": rank(md), "config": cfg}


def csv_month(month, rows, cfg, teams):
    """CSV (UTF-8, virgule) d'un mois : une ligne par client et par modèle."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["month", "team", "client", "model", "requests", "errors", "input_tokens", "output_tokens", "gpu_hours", "kwh", "cost", "currency"])

    def cell(v):
        s = str(v)
        return "'" + s if s.startswith(_FORMULA) else s
    for r in sorted(rows, key=lambda r: (teams.get(r["client"]) or NO_TEAM, r["client"], r["model"])):
        g = r["g"]
        w.writerow([month, cell(teams.get(r["client"]) or NO_TEAM), cell(r["client"]), cell(r["model"]), r["n"], r["e"], r["i"], r["o"],
                    "%.3f" % (g / 3600.0), "%.4f" % energy_kwh(g, cfg), "%.2f" % cost_of(g, cfg), cell(cfg["currency"])])
    return out.getvalue()


def _num(v):
    return "{:,}".format(int(v or 0)).replace(",", " ")


def _dec(x, nd=1):
    return ("%." + str(nd) + "f") % x


def weekly_lines(summary, top=5):
    """Lignes pour le rapport hebdomadaire ; liste vide s'il n'y a eu aucune requête."""
    t, cfg = summary["total"], summary["config"]
    if not t["n"]:
        return []
    cur = cfg["currency"]
    lines = ["Total : %s jetons produits, %s h de calcul, %s kWh estimés, ≈ %s %s" % (_num(t["o"]), _dec(t["gpu_h"]), _dec(t["kwh"], 2), _dec(t["cost"], 2), cur)]
    for x in summary["teams"][:top]:
        lines.append("%s : %s jetons produits, %s h de calcul, ≈ %s %s (%d %%)" % (x["name"], _num(x["o"]), _dec(x["gpu_h"]), _dec(x["cost"], 2), cur, x["share"]))
    return lines
