#!/usr/bin/env python3
"""Imputation des coûts : calculs (module pur), registre mensuel alimenté par le journal des requêtes, export CSV, équipes, rapport hebdomadaire."""
import csv, io, json, os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import costs, report, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a); return False
    except ValueError: return True

NOW = time.mktime((2026, 11, 11, 15, 0, 0, 0, 0, -1)); D = lambda d, h=12: time.mktime((2026, 11, d, h, 0, 0, 0, 0, -1))
CFG = {"watts": 300, "kwh_price": 0.20, "gpu_hour": 1.0, "currency": "€"}
def R(ts, client, model, out=100, tps=50, inn=20, status=200, ms=3000):
    return {"ts": ts, "client": client, "model": model, "status": status, "in_tok": inn, "out_tok": out, "tps": tps, "ms": ms}

# --- 1. temps de calcul, énergie, coût
ok(costs.compute_seconds(R(1, "a", "m", out=100, tps=50)) == 2.0, "temps de calcul = jetons produits ÷ débit mesuré (100 ÷ 50 = 2 s)")
ok(costs.compute_seconds(R(1, "a", "m", out=0, tps=None, ms=1500)) == 1.5, "sans débit (embeddings) : durée de la requête")
ok(costs.compute_seconds(R(1, "a", "m", status=500)) == 0.0 and costs.compute_seconds(R(1, "a", "m", out=0, tps=None, ms=9_999_999)) == 600.0, "requête en erreur : 0 ; durée plafonnée à 10 minutes")
ok(abs(costs.energy_kwh(3600, CFG) - 0.3) < 1e-9 and abs(costs.cost_of(3600, CFG) - (0.3 * 0.2 + 1.0)) < 1e-9, "1 h à 300 W = 0,3 kWh ; coût = énergie × prix du kWh + coût horaire du matériel")
ok(costs.config_clean({}) == costs.DEFAULTS and costs.config_clean({"watts": "450", "kwh_price": "0,18"}, costs.DEFAULTS)["kwh_price"] == 0.18, "paramètres par défaut ; virgule décimale acceptée")
ok(all(raises(costs.config_clean, x) for x in ({"watts": 0}, {"watts": 9999}, {"kwh_price": -1}, {"gpu_hour": "abc"}, {"currency": ""}, {"currency": "<b>"}, {"watts": float("nan")})), "paramètres hors bornes refusés")
ok(costs.team_clean("  Équipe   RH ") == "Équipe RH" and raises(costs.team_clean, "x" * 41) and raises(costs.team_clean, "a<b"), "nom d'équipe normalisé, borné, sans balisage")

# --- 2. registre
days = {}
reqs = [R(D(2), "RH", "llama3.2:3b"), R(D(2), "RH", "llama3.2:3b"), R(D(2, 13), "Compta", "gemma4:12b", out=200, tps=40), R(D(3), "RH", "gemma4:12b", status=500),
        R(D(10), "Compta", "llama3.2:3b"), {"client": "x"}, R(time.mktime((2026, 10, 30, 12, 0, 0, 0, 0, -1)), "RH", "llama3.2:3b")]
ok(costs.add_requests(days, reqs) == 6 and sorted(days) == ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-10"], "6 requêtes versées au registre (une sans date ignorée), rangées par jour")
rh = days["2026-11-02"]["RH"]
ok(rh["n"] == 2 and rh["o"] == 200 and rh["i"] == 40 and rh["g"] == 4.0 and rh["m"]["llama3.2:3b"]["n"] == 2, "par jour, par client et par modèle : requêtes, jetons, temps de calcul")
ok(days["2026-11-03"]["RH"]["e"] == 1 and days["2026-11-03"]["RH"]["g"] == 0, "erreurs comptées, sans temps de calcul")
nov = costs.select(days, costs.month_dates(days, "2026-11"))
ok(sorted(nov) == ["2026-11-02", "2026-11-03", "2026-11-10"] and "2026-10-30" not in nov, "sélection d'un mois")
nov["2026-11-02"]["RH"]["n"] = 999
ok(days["2026-11-02"]["RH"]["n"] == 2, "la sélection est une copie : le registre n'est pas modifié")
ok(costs.months(days, NOW) == ["2026-11", "2026-10"] and costs.months({}, NOW) == ["2026-11"], "mois disponibles, le mois en cours toujours présent")
rows = costs.flat(costs.select(days, costs.month_dates(days, "2026-11")))
ok(sorted((r["client"], r["model"], r["n"]) for r in rows) == [("Compta", "gemma4:12b", 1), ("Compta", "llama3.2:3b", 1), ("RH", "gemma4:12b", 1), ("RH", "llama3.2:3b", 2)], "lignes client × modèle")
costs.prune(days, NOW, keep=10)
ok("2026-10-30" not in days and "2026-11-02" in days, "les jours trop anciens sont retirés du registre")

# --- 3. synthèse par client, équipe et modèle
s = costs.summarize(rows, CFG, {"RH": "Ressources humaines", "Compta": "Finance"})
t = s["total"]
ok(t["n"] == 5 and t["o"] == 600 and t["i"] == 100 and t["gpu_h"] == 0.003 and t["e"] == 1, "totaux : requêtes, erreurs, jetons, heures de calcul")
cl = {x["name"]: x for x in s["clients"]}
ok(cl["RH"]["team"] == "Ressources humaines" and cl["Compta"]["team"] == "Finance" and cl["RH"]["n"] == 3, "chaque client porte son équipe")
ok(sorted(x["name"] for x in s["teams"]) == ["Finance", "Ressources humaines"] and abs(sum(x["share"] for x in s["teams"]) - 100) <= 1, "équipes et parts du coût (total ≈ 100 %)")
ok(s["clients"][0]["cost"] >= s["clients"][-1]["cost"], "classement par coût décroissant")
s2 = costs.summarize(rows, CFG, {"RH": "Ressources humaines"})
ok([x["name"] for x in s2["teams"] if x["name"] == costs.NO_TEAM] == [costs.NO_TEAM] and {x["name"]: x["team"] for x in s2["clients"]}["Compta"] == costs.NO_TEAM, "client sans équipe regroupé sous « (sans équipe) »")
ok(costs.summarize([], CFG, {})["total"]["n"] == 0 and costs.weekly_lines(costs.summarize([], CFG, {})) == [], "aucune requête : synthèse vide, aucune ligne de rapport")

# --- 4. CSV
c = costs.csv_month("2026-11", rows, CFG, {"RH": "Ressources humaines"})
rd = list(csv.reader(io.StringIO(c)))
ok(rd[0] == ["month", "team", "client", "model", "requests", "errors", "input_tokens", "output_tokens", "gpu_hours", "kwh", "cost", "currency"] and len(rd) == 5, "CSV : en-tête et une ligne par client × modèle")
row = next(r for r in rd[1:] if r[2] == "RH" and r[3] == "llama3.2:3b")
ok(row[:2] == ["2026-11", "Ressources humaines"] and row[4:8] == ["2", "0", "40", "200"] and row[8] == "0.001" and row[11] == "€" and row[10] == "0.00", "valeurs : requêtes, jetons, heures de calcul, kWh, coût, devise")
evil = costs.csv_month("2026-11", [dict(client="=HYPERLINK(1)", model="+cmd", n=1, e=0, i=0, o=0, g=0.0)], CFG, {})
ok("'=HYPERLINK" in evil and "'+cmd" in evil, "cellules neutralisées contre l'injection de formules")
wl = costs.weekly_lines(s)
ok(wl[0].startswith("Total : 600 jetons produits") and wl[1].startswith("Finance : ") and wl[2].startswith("Ressources humaines : "), "lignes du rapport : total puis équipes, la plus coûteuse d'abord")

# --- 5. console : registre sur disque, requêtes récentes non versées, équipes, export
tmp = tempfile.mkdtemp()
server.COSTS_CONF = os.path.join(tmp, "costs.json"); server.COSTS_LEDGER = os.path.join(tmp, "ledger.json"); server.REQ_LOG = os.path.join(tmp, "requests.jsonl")
server.load_publication = lambda: {"keys": [{"id": "1", "name": "RH", "team": "Ressources humaines"}, {"id": "2", "name": "Compta"}]}
server._reqlog_cache["t"] = 0
def write_log(rs):
    with open(server.REQ_LOG, "w") as f:
        for r in rs: f.write(json.dumps(r) + "\n")
    server._reqlog_cache["t"] = 0
write_log(reqs[:5] + [R(NOW - 600, "RH", "llama3.2:3b", out=300, tps=100)])
ok(server.costs_ingest(NOW) == 5, "versement : seules les requêtes terminées depuis plus de 30 minutes entrent au registre")
ok(oct(os.stat(server.COSTS_LEDGER).st_mode & 0o777) == "0o600", "registre réservé à root")
ok(server.costs_ingest(NOW + 60) == 0, "second passage : rien de plus (aucun doublon)")
v = server.costs_view("2026-11", NOW)
ok(v["summary"]["total"]["n"] == 6 and v["summary"]["total"]["o"] == 900, "vue du mois : registre + requête récente pas encore versée")
server._reqlog_cache["t"] = 0
ok(server.costs_ingest(NOW + 3600) == 1 and server.costs_view("2026-11", NOW + 3600)["summary"]["total"]["n"] == 6, "plus tard la requête récente est versée sans être comptée deux fois")
write_log([])
ok(server.costs_view("2026-11", NOW + 3600)["summary"]["total"]["n"] == 6, "le journal des requêtes purgé, les totaux du mois restent (registre)")
ok(server.costs_view("2026-10", NOW)["summary"]["total"]["n"] == 0 and server.costs_view("pas-un-mois", NOW)["month"] == "2026-11", "mois sans données : vide ; mois invalide : mois en cours")
ok(v["teams"] == ["Ressources humaines"] and [(k["name"], k["team"]) for k in v["keys"]] == [("RH", "Ressources humaines"), ("Compta", "")], "équipes lues sur les clés")
ok(server.costs_config() == costs.DEFAULTS, "paramètres par défaut")
ok(server.costs_save({"watts": 450, "gpu_hour": "0,5"})["watts"] == 450 and server.costs_config()["gpu_hour"] == 0.5 and server.costs_config()["kwh_price"] == 0.2, "paramètres enregistrés (mise à jour partielle)")
ok(oct(os.stat(server.COSTS_CONF).st_mode & 0o777) == "0o644" and raises(server.costs_save, {"watts": -5}), "fichier de paramètres sans secret ; valeurs invalides refusées")
csvtext = server.costs_export("2026-11")
ok(csvtext.splitlines()[0].startswith("month,team,client") and "Ressources humaines" in csvtext and "(sans équipe)" in csvtext and raises(server.costs_export, "2026/11"), "export du mois : lignes avec équipes ; mois invalide refusé")
write_log([R(NOW + 4000, "RH", "llama3.2:3b", out=500, tps=50)])
lines = server.costs_week_lines(NOW + 4100)
ok(lines and lines[0].startswith("Total : 900 jetons produits"), "rapport hebdomadaire : 7 derniers jours = registre (jours 5 à 11) + requête récente, sans les jours plus anciens")

# --- 6. rapport hebdomadaire
base = {"host": "srv", "since": NOW - 7 * 86400, "until": NOW, "usage": {"total": {"count": 1, "errors": 0, "in_tok": 1, "out_tok": 1}, "models": [], "clients": []}}
obj, text, page = report.build(base)
ok("Coûts" not in text, "sans données de coût : le rapport reste identique")
obj, text, page = report.build(dict(base, costs=["Total : 10 jetons produits", "Finance : 5 jetons"]))
ok("Coûts estimés de la semaine" in text and "Finance : 5 jetons" in page and [x["title"] for x in obj["sections"]][3] == "Coûts estimés de la semaine", "section « Coûts estimés de la semaine » dans le texte, le HTML et l'aperçu")

# --- 7. clés : équipe
saved = {}
server.load_publication = lambda: {"keys": [{"id": "1", "name": "RH"}], "enabled": False}
server.save_publication = lambda pub: saved.update(pub)
server.key_update({"id": "1", "team": "  Ressources   humaines "})
ok(saved["keys"][0]["team"] == "Ressources humaines", "équipe d'une clé enregistrée (normalisée)")
server.key_update({"id": "1", "team": ""})
ok("team" not in saved["keys"][0], "équipe vidée : retirée de la clé")
ok(raises(server.key_update, {"id": "1", "team": "x" * 50}), "nom d'équipe trop long refusé")
print("\n%d vérifications réussies." % n)
