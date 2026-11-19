E = {
"Accepter un modèle différent pour répartir la charge : un serveur qui n'a pas le modèle demandé répond avec son modèle le plus proche (même nature, même famille, déjà en mémoire, taille voisine), même sans modèle de remplacement réglé. Les requêtes avec images restent sur les serveurs qui ont exactement le modèle. Les réponses peuvent donc varier d'un serveur à l'autre.":
  "Accept a different model to spread the load: a server that does not have the requested model answers with its closest model (same kind, same family, already in memory, similar size), even without a replacement model set. Requests with images stay on servers that have exactly the requested model. Answers may therefore vary from one server to another.",
}
P = []
P += [
(r"^(\d+) / (\d+) \(\+(\d+) en remplacement\)$", "{1} / {2} (+{3} as replacement)"),
(r"^oui, avec un modèle différent \((.*)\)$", "yes, with a different model ({1})"),
]
