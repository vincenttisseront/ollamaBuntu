E = {
"Critique (passe toujours en premier, places réservées)": "Critical (always goes first, reserved slots)",
"Quand le serveur est saturé, les requêtes attendent leur tour : celle d'une clé de priorité haute passe avant une clé de priorité basse (une requête qui attend longtemps gagne un niveau toutes les 2 minutes, aucune ne reste bloquée). Une clé de priorité critique passe toujours en premier, sans vieillissement, et peut utiliser des places que les autres clés n'ont pas le droit de prendre (réglage « places réservées »). La priorité de chaque clé se règle dans Système > Publication de l'API > Plafonds.":
  "When the server is saturated, requests wait their turn: one from a high-priority key goes before one from a low-priority key (a request that waits a long time gains a level every 2 minutes, none stays stuck). A critical-priority key always goes first, without ageing, and can use slots the other keys are not allowed to take (“reserved slots” setting). Each key's priority is set in System > API publication > Limits.",
"Places réservées aux clés critiques (sur le total ci-dessus ; les autres clés n'en prennent jamais plus que le total moins ces places)": "Slots reserved for critical keys (out of the total above; other keys never take more than the total minus these slots)",
"Ramène les demandes qui dépassent ces valeurs au plafond (en-tête de réponse X-OllamaBuntu-Clamped). 0 = sans plafond. Le contexte n'est plafonné que s'il est demandé explicitement. La priorité décide de l'ordre de passage quand le serveur est saturé ; « critique » passe toujours en premier, sans vieillissement.":
  "Brings requests that exceed these values down to the ceiling (X-OllamaBuntu-Clamped response header). 0 = no ceiling. The context is only capped if explicitly requested. The priority decides the order of passage when the server is saturated; “critical” always goes first, without ageing.",
"priorité : 0 (critique), 1 (haute), 2 (normale) ou 3 (basse)": "priority: 0 (critical), 1 (high), 2 (normal) or 3 (low)",
"valeur invalide : places réservées aux clés critiques": "invalid value: slots reserved for critical keys",
"places réservées aux clés critiques : indiquez d'abord un plafond de requêtes simultanées au total": "slots reserved for critical keys: first set a ceiling of simultaneous requests in total",
}
P = [
(r" \(dont (\d+) réservée\(s\) aux clés critiques\)", " ({1} of them reserved for critical keys)"),
(r"places réservées aux clés critiques : (\d+) à (\d+) \(0 = sans limite\)", "slots reserved for critical keys: {1} to {2} (0 = no limit)"),
(r"places réservées aux clés critiques : moins que le total de requêtes simultanées \((\d+)\)", "slots reserved for critical keys: fewer than the total of simultaneous requests ({1})"),
]
