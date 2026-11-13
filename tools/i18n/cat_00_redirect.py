# Redirection de modèles (Modèles > Redirections)
E = {
"Redirections": "Redirects", "Redirection de modèles": "Model redirects",
"Quand une application demande un modèle par son nom, la console peut le faire répondre par un autre : l'application n'a rien à changer. Exemple : toutes les demandes pour « gemma4:12b » servies par « Qwen3 ». Avec un pourcentage inférieur à 100, seule une partie des demandes est redirigée, pour comparer deux modèles en situation réelle. Les droits des clés d'accès s'appliquent au modèle demandé. Une règle ne s'enchaîne pas avec une autre.":
    "When an application asks for a model by name, the console can have another one answer: the application does not need to change. Example: all requests for \"gemma4:12b\" served by \"Qwen3\". With a percentage below 100, only part of the requests is redirected, so you can compare two models in real use. Access-key rights apply to the requested model. A rule is never chained with another one.",
"Ajouter une règle": "Add a rule",
"modèle demandé": "requested model", "modèle servi": "serving model",
"Modèle demandé par les applications": "Model requested by applications", "Modèle qui répond": "Model that answers",
"Part des demandes redirigées, en pourcentage": "Share of requests redirected, in percent", "Règle active": "Rule enabled",
"Retirer": "Remove",
"Non installé sur ce serveur (utile seulement si un serveur du parc le possède).": "Not installed on this server (only useful if a fleet server has it).",
"Quand on demande": "When asked for", "C'est ce modèle qui répond": "This model answers", "Part des demandes": "Share of requests", "Active": "Enabled",
"Aucune redirection : chaque application reçoit le modèle qu'elle demande.": "No redirect: each application gets the model it asks for.",
"Enregistré : appliqué aux prochaines demandes.": "Saved: applies to the next requests.",
"chaque règle a besoin d'un modèle demandé et d'un modèle servi (200 caractères au plus)": "each rule needs a requested model and a serving model (200 characters at most)",
"règles invalides (50 au maximum)": "invalid rules (50 at most)", "règle invalide": "invalid rule",
}
P = [
(r"« (.+) » : le modèle servi est le même que le modèle demandé", "\"{1}\": the serving model is the same as the requested model"),
(r"« (.+) » apparaît deux fois : une seule règle par modèle demandé", "\"{1}\" appears twice: only one rule per requested model"),
(r"pourcentage invalide pour « (.+) »", "invalid percentage for \"{1}\""),
(r"pourcentage de « (.+) » : 1 à 100", "percentage of \"{1}\": 1 to 100"),
(r"« (.+) » est servi par « (.+) », qui est lui-même redirigé : les redirections ne s'enchaînent pas", "\"{1}\" is served by \"{2}\", which is itself redirected: redirects are not chained"),
]
