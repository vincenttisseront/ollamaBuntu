Q = "\u201c{1}\u201d"
E = {
"Synchroniser tout le parc...": "Synchronise the whole fleet...", "Synchroniser...": "Synchronise...", "Synchroniser": "Synchronise",
"Activer la répartition de charge": "Enable load balancing", "Désactiver la répartition": "Disable load balancing", "Désactiver la répartition de charge": "Disable load balancing",
"Activer": "Enable", "répartition": "load balancing", "Dernière synchronisation": "Last synchronisation", "Synchronisation terminée": "Synchronisation complete",
"Modèles personnalisés": "Custom models", "Politique d'usage de l'IA": "AI usage policy", "Clés d'API": "API keys", "rien à faire": "nothing to do", "modèles déjà présents": "models already present",
"Téléchargement des modèles synchronisés depuis la console principale": "Downloading models synchronised from the main console",
"aucun serveur en ligne à synchroniser": "no online server to synchronise", "choisissez au moins un élément à synchroniser": "choose at least one item to synchronise",
"le serveur n'a pas fourni de jeton de routage (version trop ancienne ?)": "the server did not provide a routing token (version too old?)",
"requête non autorisée par la répartition de charge": "request not allowed by load balancing", "jeton de gestion centralisée invalide ou révoqué": "invalid or revoked centralised management token",
">>> Accès Internet d'Ollama désactivé par la politique d'usage de l'IA : téléchargement impossible sur ce serveur.": ">>> Ollama's Internet access is disabled by the AI usage policy: download impossible on this server.",
}
P = [
(r"(\d+) serveur\(s\) - (\d+) en ligne - répartition de charge sur (\d+) serveur\(s\) - (\d+) GPU mesuré\(s\), charge moyenne (\d+) %", "{1} server(s) - {2} online - load balancing on {3} server(s) - {4} GPU(s) measured, average load {5}%"),
(r"(\d+) serveur\(s\) - (\d+) en ligne - répartition de charge sur (\d+) serveur\(s\) - (\d+) GPU mesuré\(s\)", "{1} server(s) - {2} online - load balancing on {3} server(s) - {4} GPU(s) measured"),
(r"Synchroniser tout le parc", "Synchronise the whole fleet"), (r"Synchroniser « (.+) »", "Synchronise " + Q),
(r"Copier depuis cette console vers (tous les serveurs en ligne|« .+ ») :", "Copy from this console to {1}:"), (r"tous les serveurs en ligne", "all online servers"),
(r"Les requêtes reçues par cette console pour un modèle présent sur « (.+) » pourront y être envoyées, selon la charge de chaque serveur\..*",
 "Requests received by this console for a model present on " + Q + " may be sent there, depending on each server's load. " + Q + " issues a token limited to using models for this; its own AI usage policy still applies."),
(r"Les requêtes ne seront plus envoyées à « (.+) » ; son jeton de routage est révoqué\.", "Requests will no longer be sent to " + Q + "; its routing token is revoked."),
(r"(.+) : échec - (.+)", "{1}: failed - {2}"), (r"(.+) : politique appliquée(.*)", "{1}: policy applied{2}"), (r"(.+) : rien à faire", "{1}: nothing to do"),
(r"(\d+) clé\(s\) d'API", "{1} API key(s)"), (r"(\d+) modèle\(s\) en téléchargement", "{1} model(s) downloading"),
(r"(\d+) modèle\(s\) personnalisé\(s\) créé\(s\)(.*)", "{1} custom model(s) created{2}"), (r", (\d+) en attente de leur modèle de base", ", {1} waiting for their base model"),
(r"Dernière synchronisation reçue de « (.+) » : (.+)", "Last synchronisation received from " + Q + ": {2}"),
(r"dernier contact : (.+) - répartition de charge autorisée", "last contact: {1} - load balancing allowed"),
(r"aucun serveur disponible pour le modèle « (.+) » \(ce serveur et le parc\)", "no server available for model " + Q + " (this server and the fleet)"),
(r"Ollama injoignable sur ce serveur : (.+)", "Ollama unreachable on this server: {1}"), (r">>> Téléchargement de (.+)", ">>> Downloading {1}"), (r">>> Échec : (.+)", ">>> Failed: {1}"),
]
