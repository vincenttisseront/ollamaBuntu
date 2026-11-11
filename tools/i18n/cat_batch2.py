# Second lot : thème, cloche d'alertes, parc sur le tableau de bord, statistiques, filtres et export CSV, palette Ctrl+K,
# température et puissance des GPU, échéance des clés, export Prometheus
E = {
# en-tête
"Aller à... (Ctrl+K)": "Go to... (Ctrl+K)", "Alertes actives": "Active alerts", "Aucune alerte": "No alert", "Configurer les alertes": "Configure alerts",
"Thème : automatique": "Theme: automatic", "Thème : clair": "Theme: light", "Thème : sombre": "Theme: dark",
"critique": "critical", "attention": "warning", "info": "info",
# tableau de bord
"Parc de serveurs": "Server fleet", "Gérer les serveurs": "Manage servers", "Aucun modèle en mémoire": "No model in memory",
"Température GPU": "GPU temperature", "Puissance GPU": "GPU power",
# journal des requêtes
"Recherche": "Search", "Modèle, client, demande...": "Model, client, request...", "Rechercher dans les requêtes": "Search the requests", "Statut": "Status",
"Toutes": "All", "Réussies": "Succeeded", "En erreur ou interrompues": "Failed or interrupted", "Exporter en CSV": "Export as CSV",
# statistiques
"Statistiques": "Statistics", "Utilisation des modèles": "Model usage", "24 h": "24 h", "7 jours": "7 days",
"Calculé d'après le journal des requêtes conservé sur ce serveur (métadonnées seulement). Une période plus longue que la conservation réglée dans l'onglet Requêtes est tronquée.":
  "Computed from the request log kept on this server (metadata only). A period longer than the retention set in the Requests tab is truncated.",
"Requêtes": "Requests", "Taux d'erreur": "Error rate", "Jetons en entrée": "Input tokens", "Jetons générés": "Generated tokens", "Durée moyenne": "Average duration",
"Requêtes dans le temps": "Requests over time", "rouge : en erreur": "red: failed", "Par client": "By client",
"Aucune requête sur cette période.": "No request in this period.",
# échéance des clés
"Expire le (vide = jamais)": "Expires on (empty = never)", "Échéance": "Expiry", "expirée": "expired", "expire aujourd'hui": "expires today", "Date d'expiration": "Expiry date",
"La clé reste valable jusqu'à la fin de ce jour. Laissez vide pour qu'elle n'expire jamais.": "The key stays valid until the end of that day. Leave empty so that it never expires.",
"Clé d'API expirée ou bientôt expirée": "API key expired or about to expire",
"date d'expiration invalide (format AAAA-MM-JJ)": "invalid expiry date (format YYYY-MM-DD)",
# Prometheus
"Export Prometheus": "Prometheus export",
"Expose l'état du serveur (GPU, mémoire, requêtes, jetons, file d'attente, parc) au format Prometheus. L'accès se fait avec un jeton dédié en lecture seule, distinct des clés d'API et des comptes ; seule son empreinte est conservée.":
  "Exposes the server state (GPU, memory, requests, tokens, queue, fleet) in Prometheus format. Access uses a dedicated read-only token, separate from API keys and accounts; only its fingerprint is kept.",
"Générer un jeton": "Generate a token", "Révoquer le jeton": "Revoke the token", "Remplacer le jeton": "Replace the token", "Export désactivé : aucun jeton.": "Export disabled: no token.",
"Remplacer le jeton ? L'ancien cessera de fonctionner immédiatement.": "Replace the token? The old one stops working immediately.", "Remplacer": "Replace",
"Jeton Prometheus créé": "Prometheus token created",
"Copiez-le maintenant : il ne sera plus jamais affiché (seule son empreinte est conservée).": "Copy it now: it will never be shown again (only its fingerprint is kept).",
"Copier": "Copy", "Copié.": "Copied.", "Sélectionné : Ctrl+C pour copier.": "Selected: Ctrl+C to copy.",
"Révoquer le jeton Prometheus ? Les collectes en cours échoueront.": "Revoke the Prometheus token? Ongoing scrapes will fail.",
"export Prometheus désactivé": "Prometheus export disabled", "jeton invalide": "invalid token", "action inconnue": "unknown action",
# palette
"Aller à un écran, un onglet, une action...": "Go to a screen, a tab, an action...", "Rechercher une commande": "Search for a command",
"↑ ↓ pour choisir, Entrée pour valider, Échap pour fermer.": "↑ ↓ to choose, Enter to confirm, Esc to close.",
"Écran": "Screen", "Onglet": "Tab", "Compte": "Account", "Action": "Action", "Mon compte": "My account", "Changer de thème": "Change theme", "Changer de langue": "Change language",
"Actualiser le tableau de bord": "Refresh the dashboard", "Aucun résultat.": "No result.",
}
P = [
(r"(\d+) alerte\(s\) active\(s\)", "{1} active alert(s)"),
(r"GPU (\d+(?:[.,]\d+)?) % - (.+) / (.+)", "GPU {1}% - {2} / {3}"), (r"GPU (\d+(?:[.,]\d+)?) %", "GPU {1}%"),
(r"Processeur (\d+(?:[.,]\d+)?) %", "Processor {1}%"), (r"En mémoire : (.+)", "In memory: {1}"),
(r"(\d+) résultat\(s\) sur (\d+)", "{1} result(s) out of {2}"),
(r"(\d+) - (.+) jetons", "{1} - {2} tokens"),
(r"Requêtes par tranche : (\d+) au total", "Requests per slice: {1} in total"),
(r"(.+) : (\d+) requête\(s\), (\d+) en erreur", "{1}: {2} request(s), {3} failed"), (r"(.+) : (\d+) requête\(s\)", "{1}: {2} request(s)"),
(r"expire dans (\d+) j", "expires in {1} d"), (r"expire le (\d{4}-\d{2}-\d{2})", "expires on {1}"),
(r"Échéance de la clé « (.+) »", "Expiry of key “{1}”"),
(r"Jeton créé le (.+)", "Token created on {1}"),
(r"Clé d'API « (.+) » expirée", "API key “{1}” expired"), (r"Clé d'API « (.+) » expire aujourd'hui", "API key “{1}” expires today"),
(r"Clé d'API « (.+) » expire dans (\d+) jour\(s\)", "API key “{1}” expires in {2} day(s)"),
]
