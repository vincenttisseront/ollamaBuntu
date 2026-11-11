# Imputation des coûts par clé et par équipe
E = {
"Coûts": "Costs", "Coûts par équipe et par clé": "Costs by team and by key", "Mois": "Month", "Exporter le mois (CSV)": "Export the month (CSV)",
"Jetons, temps de calcul, énergie et coût de chaque clé d'API et de chaque équipe (une équipe regroupe plusieurs clés : renseignez-la à la création de la clé ou dans Plafonds). Le temps de calcul, l'énergie et le coût sont des estimations d'après le débit mesuré et les paramètres ci-dessous : aucun wattmètre n'est lu. Les totaux sont conservés 400 jours, même quand le journal des requêtes est purgé.":
    "Tokens, compute time, energy and cost of each API key and each team (a team groups several keys: set it when creating the key or in Limits). Compute time, energy and cost are estimates based on the measured throughput and the settings below: no power meter is read. Totals are kept for 400 days, even when the request log is purged.",
"Par équipe": "Per team", "Par clé": "Per key",
"Paramètres du calcul": "Calculation settings",
"Énergie = temps de calcul × puissance moyenne en charge. Coût = énergie × prix du kWh + heures de calcul × coût horaire du matériel (amortissement de la machine et de la carte, par exemple). Ces paramètres s'appliquent à tous les mois affichés.":
    "Energy = compute time × average power under load. Cost = energy × price per kWh + compute hours × hourly hardware cost (amortisation of the machine and the card, for example). These settings apply to all months shown.",
"Puissance moyenne en charge (watts)": "Average power under load (watts)", "Prix du kWh": "Price per kWh", "Coût horaire du matériel": "Hourly hardware cost", "Devise": "Currency",
"Équipe (facultatif, pour répartir les coûts)": "Team (optional, to split costs)", "Équipe (pour répartir les coûts)": "Team (to split costs)", "ex. Ressources humaines": "e.g. Human resources",
"Équipe": "Team", "Clé": "Key", "Erreurs": "Errors", "Jetons produits": "Tokens produced", "Temps de calcul": "Compute time", "Énergie estimée": "Estimated energy", "Coût estimé": "Estimated cost",
"Temps de calcul (h)": "Compute time (h)", "Énergie (kWh)": "Energy (kWh)", "Coût": "Cost", "Part": "Share", "Aucune requête ce mois-ci.": "No request this month.",
"(sans équipe)": "(no team)", "Paramètres de coût": "Cost settings",
"puissance moyenne en charge : 1 à 5000 W": "average power under load: 1 to 5000 W", "prix du kWh : 0 à 100": "price per kWh: 0 to 100", "coût horaire du matériel : 0 à 10000": "hourly hardware cost: 0 to 10000",
"devise : 1 à 4 caractères": "currency: 1 to 4 characters", "équipe : 40 caractères au plus, sans < > \"": "team: 40 characters at most, without < > \"", "mois invalide (AAAA-MM)": "invalid month (YYYY-MM)",
"Coûts estimés de la semaine": "Estimated costs for the week",
}
P = [
(r"équipe : (.+)", "team: {1}"),
(r"Les requêtes des (\d+) dernières minutes sont comptées en direct ; elles entrent ensuite dans le registre mensuel\.", "Requests from the last {1} minutes are counted live; they then enter the monthly ledger."),
(r"Les requêtes des (\d+) dernières minutes sont comptées en direct ; elles entrent ensuite dans le registre mensuel\. Registre depuis le (.+)\.", "Requests from the last {1} minutes are counted live; they then enter the monthly ledger. Ledger since {2}."),
]
