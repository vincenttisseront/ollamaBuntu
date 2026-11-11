#!/usr/bin/env python3
"""OllamaBuntu - statistiques d'usage et export du journal des requêtes.
Fonctions pures (aucun accès disque ni réseau) : testables hors de la console."""
import csv
import io

CSV_COLUMNS = ["ts", "client", "ip", "path", "model", "instance", "status", "aborted", "ms", "ttft_ms", "in_tok", "out_tok", "tps"]
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _iso(ts):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)) if ts else ""


def _cell(v):
    """Valeur de cellule CSV : neutralise l'injection de formules des tableurs (=, +, -, @ en tête)."""
    if v is None:
        return ""
    s = str(v)
    return "'" + s if s.startswith(_FORMULA) and not _is_number(s) else s


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def to_csv(reqs):
    """CSV (UTF-8, séparateur virgule) du journal des requêtes, de la plus ancienne à la plus récente."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in sorted(reqs, key=lambda r: r.get("ts") or 0):
        w.writerow([_cell(_iso(r.get("ts")) if c == "ts" else r.get(c)) for c in CSV_COLUMNS])
    return out.getvalue()


def aggregate(reqs, now, span=86400, name=lambda m: m):
    """Usage sur `span` secondes : totaux, par modèle, par client, par heure (ou par tranche de span/24)."""
    span = max(3600, min(int(span), 7 * 86400))
    since = now - span
    rs = [r for r in reqs if (r.get("ts") or 0) >= since]
    step = span / 24.0

    def new():
        return {"count": 0, "errors": 0, "in_tok": 0, "out_tok": 0, "ms": 0}

    def add(d, r):
        d["count"] += 1
        if r.get("status") != 200:
            d["errors"] += 1
        d["in_tok"] += r.get("in_tok") or 0
        d["out_tok"] += r.get("out_tok") or 0
        d["ms"] += r.get("ms") or 0

    total, models, clients = new(), {}, {}
    buckets = [dict(new(), t=int(since + i * step)) for i in range(24)]
    for r in rs:
        add(total, r)
        add(models.setdefault(name(r.get("model")) if r.get("model") else "?", new()), r)
        add(clients.setdefault(r.get("client") or "?", new()), r)
        i = min(23, max(0, int((r["ts"] - since) // step)))
        add(buckets[i], r)

    def rows(d):
        return sorted(({"name": k, **v} for k, v in d.items()), key=lambda x: (-x["count"], x["name"]))[:20]

    return {"span": span, "total": total, "models": rows(models), "clients": rows(clients), "buckets": buckets}
