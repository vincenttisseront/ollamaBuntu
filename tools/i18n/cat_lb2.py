Q = "\u201c{1}\u201d"
E = {
"Demande": "Request", "Serveur": "Server", "Ce serveur": "This server", "Enregistrer un extrait de la demande": "Record an excerpt of the request",
"Longueur": "Length", "Conservation": "Retention", "1 jour": "1 day", "Effacer l'historique": "Clear the history", "Historique effacé.": "History cleared.", "Effacer": "Clear",
"Toutes les requêtes passant par l'API (console, Open WebUI, applications, parc). Par défaut, seules des métadonnées sont enregistrées ; un extrait de la demande peut être ajouté ci-dessous.":
  "All requests going through the API (console, Open WebUI, applications, fleet). By default only metadata is recorded; an excerpt of the request can be added below.",
"Désactivé par défaut. Quand il est activé, le début de la dernière question de chaque requête est conservé sur ce serveur, visible des administrateurs seulement, avec masquage des clés, jetons, IBAN, numéros de carte et adresses e-mail. La conservation s'applique à tout l'historique des requêtes.":
  "Disabled by default. When enabled, the beginning of the last question of each request is kept on this server, visible to administrators only, with keys, tokens, IBANs, card numbers and e-mail addresses masked. Retention applies to the whole request history.",
"Le contenu des demandes n'est pas enregistré.": "The content of requests is not recorded.", "Activer l'extrait de la demande": "Enable the request excerpt",
"Enregistrer le début de la dernière question de chaque requête ? Il sera conservé sur ce serveur et visible des administrateurs de cette console ; les clés, jetons, IBAN, numéros de carte et adresses e-mail sont masqués.":
  "Record the beginning of the last question of each request? It will be kept on this server and visible to this console's administrators; keys, tokens, IBANs, card numbers and e-mail addresses are masked.",
"Effacer tout l'historique des requêtes ? Cette action est définitive.": "Clear the whole request history? This cannot be undone.",
"Tester la répartition": "Test the balancing", "Stratégie": "Strategy",
"Quand plusieurs serveurs ont le même modèle, cette console envoie chaque requête à l'un d'eux. Un serveur n'est utilisé que si la répartition y est activée, s'il est en ligne et s'il a le modèle demandé.":
  "When several servers have the same model, this console sends each request to one of them. A server is used only if balancing is enabled on it, it is online and it has the requested model.",
"Répartir : le serveur le moins occupé, à tour de rôle": "Spread: the least busy server, taking turns", "Privilégier le modèle déjà chargé en mémoire": "Prefer the model already loaded in memory",
"Chaque requête va au serveur qui en traite le moins à cet instant ; à égalité, les serveurs se relaient. Un modèle est chargé sur chaque serveur à sa première utilisation, ce qui prend du temps pour un gros modèle. Une conversation peut changer de serveur d'une réponse à l'autre.":
  "Each request goes to the server handling the fewest at that moment; on a tie, servers take turns. A model is loaded on each server on first use, which takes time for a large model. A conversation can change server from one answer to the next.",
"Chaque requête va de préférence au serveur qui a déjà le modèle en mémoire, tant qu'il n'est pas occupé par plusieurs requêtes. Les autres serveurs ne servent qu'en cas de forte demande ou de panne : avec un seul utilisateur, tout reste sur le même serveur.":
  "Each request preferably goes to the server that already has the model in memory, as long as it is not busy with several requests. Other servers are only used under heavy demand or failure: with a single user, everything stays on the same server.",
"La répartition n'est pas activée pour ce serveur : utilisez « Activer la répartition de charge » sur sa carte (onglet Parc).": "Load balancing is not enabled for this server: use \u201cEnable load balancing\u201d on its card (Fleet tab).",
"Le serveur est hors ligne.": "The server is offline.", "Ce serveur n'annonce pas ses modèles : mettez-le à jour avec la dernière ISO.": "This server does not announce its models: update it with the latest ISO.",
"Aucun modèle en commun avec ce serveur : installez les mêmes modèles (Parc > Synchroniser > Modèles).": "No model in common with this server: install the same models (Fleet > Synchronise > Models).",
"Aucun serveur dans le parc : ajoutez-en un (onglet « Ajouter un serveur »).": "No server in the fleet: add one (\u201cAdd a server\u201d tab).",
"État par serveur": "Status by server", "Répartition": "Balancing", "Modèles en commun": "Shared models", "Requêtes servies (24 h)": "Requests served (24 h)", "Dernière requête": "Last request",
"Présent sur": "Present on", "Répartissable": "Can be balanced", "oui": "yes", "non (un seul serveur)": "no (single server)", "activée": "enabled", "désactivée": "disabled",
"Aucun modèle n'est présent sur plusieurs serveurs : le test est impossible.": "No model is present on several servers: the test is impossible.",
"Modèle à tester": "Model to test", "Lancer le test": "Run the test", "Test en cours...": "Test running...", "Résultat du test": "Test result",
"Envoie 4 petites requêtes en même temps au modèle choisi, pour voir quels serveurs répondent. Le modèle sera chargé sur chaque serveur concerné, ce qui peut prendre du temps pour un gros modèle.":
  "Sends 4 small requests at the same time to the chosen model, to see which servers answer. The model will be loaded on each server involved, which can take time for a large model.",
"Activer aussi la répartition de charge (le serveur délivre un jeton limité à l'utilisation des modèles)": "Also enable load balancing (the server issues a token limited to using models)",
"Serveur ajouté, répartition de charge activée.": "Server added, load balancing enabled.", "stratégie inconnue": "unknown strategy",
"longueur de l'extrait": "excerpt length", "durée de conservation": "retention period",
}
P = [
(r"(\d+) caractères", "{1} characters"), (r"(\d+) jours", "{1} days"),
(r"La répartition est active : (\d+) serveur\(s\) peuvent recevoir des requêtes\.", "Load balancing is active: {1} server(s) can receive requests."),
(r"(\d+) requêtes envoyées en même temps, (\d+) réussie\(s\)\.", "{1} requests sent at once, {2} succeeded."), (r"(\d+) requête\(s\)", "{1} request(s)"),
(r"Serveur ajouté, mais la répartition n'a pas pu être activée : (.+)", "Server added, but load balancing could not be enabled: {1}"),
(r"(.+) hors limites \((\d+) à (\d+)\)", "{1} out of range ({2} to {3})"), (r"valeur invalide : (.+)", "invalid value: {1}"),
]
E.update({"Répartition de charge": "Load balancing"})
