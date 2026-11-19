E = {
"Modèle différent pour répartir la charge": "Different model to spread the load",
"Jamais : seuls les serveurs qui ont exactement le modèle demandé répondent": "Never: only servers that have exactly the requested model answer",
"En cas de débordement : un serveur qui n'a pas le modèle répond avec son modèle le plus proche seulement si l'attente sur les autres dépasse le délai ci-dessous":
  "On overflow: a server without the model answers with its closest model only if the wait on the others exceeds the delay below",
"Toujours : un serveur sans le modèle répond avec son modèle le plus proche (même nature, même famille, déjà en mémoire, taille voisine)":
  "Always: a server without the model answers with its closest model (same kind, same family, already in memory, similar size)",
"Délai de débordement (secondes)": "Overflow delay (seconds)",
"Les requêtes avec images restent sur les serveurs qui ont exactement le modèle. Avec un remplacement, les réponses peuvent varier d'un serveur à l'autre. Chaque clé d'API peut avoir son propre réglage (Plafonds).":
  "Requests with images stay on servers that have exactly the requested model. With a replacement, answers may vary from one server to another. Each API key can have its own setting (Limits).",
"Charger à l'avance les modèles que les clients demandent d'ordinaire à cette heure, sur les serveurs du parc qui n'ont rien en mémoire et ne servent personne (les nuits et week-ends sont lissés sur plusieurs jours).":
  "Preload the models clients usually ask for at this time of day, on fleet servers that have nothing in memory and are serving nobody (the pattern is smoothed over several days).",
"« Places » : nombre de requêtes que le routeur envoie en même temps à un serveur (0 = sans limite, Ollama gère sa file). Au-delà, les requêtes attendent dans une file centrale et partent vers le premier serveur qui se libère, par ordre de priorité.":
  "“Slots”: number of requests the router sends to a server at the same time (0 = no limit, Ollama manages its own queue). Beyond that, requests wait in a central queue and go to the first server that frees up, in priority order.",
"Places": "Slots",
"Modèle différent pour cette clé": "Different model for this key",
"Selon le réglage de la répartition": "Follow the load-balancing setting",
"Jamais (exactement le modèle demandé)": "Never (exactly the requested model)",
"En cas de débordement": "On overflow",
"Toujours": "Always",
"Doubler les requêtes lentes : si le serveur choisi tarde à répondre, la même requête part aussi sur un autre serveur et la première réponse gagne (clés critiques)":
  "Duplicate slow requests: if the chosen server is slow to answer, the same request is also sent to another server and the first answer wins (critical keys)",
"Doubler les requêtes lentes": "Duplicate slow requests",
"Doubler les requêtes lentes sur un second serveur": "Duplicate slow requests on a second server",
"Modèle différent pour cette clé": "Different model for this key",
"jamais": "never",
"au débordement": "on overflow",
"toujours": "always",
"requêtes doublées si lentes": "requests duplicated when slow",
"tous les serveurs du parc sont occupés pour « %s » depuis %d s : réessayez": "all fleet servers are busy for “%s” for %d s: try again",
"attente invalide": "invalid wait",
"attente : 1 à 600 secondes": "wait: 1 to 600 seconds",
"places invalides": "invalid slots",
"places : 0 (sans limite) à 64": "slots: 0 (no limit) to 64",
"mode de remplacement inconnu": "unknown replacement mode",
"remplacement de modèle : strict, overflow ou always": "model replacement: strict, overflow or always",
}
P = [
(r"^modèle différent : (.*)$", "different model: {1}"),
(r"^tous les serveurs du parc sont occupés pour « (.*) » depuis (\d+) s : réessayez$", "all fleet servers are busy for “{1}” for {2} s: try again"),
]
