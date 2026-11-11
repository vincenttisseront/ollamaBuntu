# File d'attente avec priorités et protection de la carte graphique
PRIO = {"haute": "high", "normale": "normal", "basse": "low"}
E = {
"File d'attente": "Queue", "Ce qui attend": "What is waiting", "Protection de la carte graphique": "Graphics card protection",
"normale": "normal", "Normale": "Normal", "Haute (passe en premier)": "High (goes first)", "Basse (traitements de fond)": "Low (background jobs)", "Haute": "High", "Basse": "Low",
"Priorité dans la file d'attente": "Queue priority", "Priorité": "Priority", "N°": "No.", "Attend depuis": "Waiting for",
"En cours :": "Running:", "En attente :": "Waiting:",
"priorité haute": "high priority", "priorité basse": "low priority", "(monte à haute)": "(rising to high)", "(monte à normale)": "(rising to normal)",
"Dernière heure : aucune requête n'a eu à attendre.": "Last hour: no request had to wait.",
"Rien n'attend : le serveur absorbe toutes les requêtes.": "Nothing is waiting: the server absorbs all requests.",
"Aucune donnée du routeur pour le moment.": "No data from the router at the moment.",
"Quand le serveur est saturé, les requêtes attendent leur tour : celle d'une clé de priorité haute passe avant une clé de priorité basse (une requête qui attend longtemps gagne un niveau toutes les 2 minutes, aucune ne reste bloquée). La priorité de chaque clé se règle dans Système > Publication de l'API > Plafonds.":
    "When the server is saturated, requests wait their turn: a request from a high-priority key goes before a low-priority key (a request that waits a long time rises one level every 2 minutes, none stays blocked). Each key's priority is set in System > API publication > Limits.",
"Chaque requête en cours occupe de la mémoire (contexte, cache). Au-delà de ce que la carte peut tenir, Ollama décharge des modèles ou échoue. Limitez ici le nombre de requêtes traitées en même temps ; les suivantes attendent dans la file. 0 = sans limite.":
    "Each running request uses memory (context, cache). Beyond what the card can hold, Ollama unloads models or fails. Limit here the number of requests processed at the same time; the following ones wait in the queue. 0 = no limit.",
"Requêtes simultanées au total": "Simultaneous requests in total",
"Taille maximale de la file (au-delà : refus immédiat, erreur 429)": "Maximum queue size (beyond: immediate refusal, error 429)",
"Ramène les demandes qui dépassent ces valeurs au plafond (en-tête de réponse X-OllamaBuntu-Clamped). 0 = sans plafond. Le contexte n'est plafonné que s'il est demandé explicitement. La priorité décide de l'ordre de passage quand le serveur est saturé.":
    "Brings requests that exceed these values back to the limit (response header X-OllamaBuntu-Clamped). 0 = no limit. The context is only capped when it is requested explicitly. The priority decides the order of passage when the server is saturated.",
"priorité invalide": "invalid priority", "priorité : 1 (haute), 2 (normale) ou 3 (basse)": "priority: 1 (high), 2 (normal) or 3 (low)",
"valeur invalide : requêtes simultanées au total": "invalid value: simultaneous requests in total", "valeur invalide : taille de la file": "invalid value: queue size",
}
P = [
(r"requêtes simultanées au total : (\d+) à (\d+) \(0 = sans limite\)", "simultaneous requests in total: {1} to {2} (0 = no limit)"),
(r"taille de la file : (\d+) à (\d+) \(0 = sans limite\)", "queue size: {1} to {2} (0 = no limit)"),
(r"Ollama traite déjà (\d+) requête\(s\) en parallèle par modèle ; un plafond de (\d+) à (\d+) est un point de départ raisonnable pour une carte de 24 Go\.",
 "Ollama already processes {1} request(s) in parallel per model; a limit of {2} to {3} is a reasonable starting point for a 24 GB card."),
(r"Dernière heure : (\d+) requête\(s\) ont attendu, (.+) en moyenne, (.+) au plus\.", "Last hour: {1} request(s) had to wait, {2} on average, {3} at most."),
]
for fr, en in PRIO.items():
    P.append((r"priorité %s : (.+) en moyenne" % fr, "%s priority: {1} on average" % en))
