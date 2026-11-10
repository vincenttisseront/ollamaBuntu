E = {
# onglets
"Installés": "Installed", "Ajouter un modèle": "Add a model", "Recommandés": "Recommended", "Personnalisés et préchargement": "Custom and preloading", "Cartes": "Cards",
"Groupes et épinglage": "Groups and pinning", "Paramètres avancés": "Advanced settings", "Vue d'ensemble": "Overview", "Mises à jour": "Updates", "Publication de l'API": "API publication",
"Contrôles": "Checks", "Mises à jour automatiques": "Automatic updates", "Nouveau compte": "New account", "Parc": "Fleet", "Requêtes Ollama": "Ollama requests", "Journaux système": "System logs",
# tableau de bord
"Performances": "Performance", "Dernières requêtes": "Latest requests", "Toutes les requêtes": "All requests", "Période affichée": "Displayed period",
"Charge GPU": "GPU load", "Mémoire vidéo occupée": "Video memory used", "Processeur et mémoire": "CPU and memory", "Requêtes par minute": "Requests per minute",
"Jetons par seconde": "Tokens per second", "Temps avant le premier jeton": "Time to first token", "Requêtes": "Requests", "Vitesse par requête": "Speed per request",
"Débit total": "Total throughput", "Premier jeton": "First token", "Pas encore de données sur cette période": "No data yet for this period",
"Aucun GPU mesurable (NVIDIA ou AMD) : les graphiques GPU restent vides.": "No measurable GPU (NVIDIA or AMD): the GPU charts stay empty.",
# requêtes
"Requêtes vers les modèles": "Requests to the models", "Actualisation automatique": "Automatic refresh", "Dernière heure, par modèle": "Last hour, by model", "Requêtes récentes": "Recent requests",

"Heure": "Time", "Client": "Client", "Instance": "Instance", "Point d'API": "API endpoint", "Statut": "Status", "Durée": "Duration", "1er jeton": "1st token",
"Jetons (entrée / sortie)": "Tokens (in / out)", "Erreurs": "Errors", "Jetons générés": "Generated tokens", "t/s moyen": "Average t/s", "1er jeton moyen": "Average 1st token",
"Durée médiane": "Median duration", "Durée p95": "p95 duration", "interrompue": "interrupted", "Aucune requête enregistrée pour le moment.": "No request recorded yet.",
"Aucune requête dans la dernière heure.": "No request in the last hour.",
# journaux
"Suivi en direct": "Live follow", "Filtrer les lignes...": "Filter lines...", "Filtrer les lignes": "Filter lines", "en direct": "live", "suivi arrêté": "follow stopped",
}
P = [
(r"en direct - (.+)", "live - {1}"),
(r"(Charge GPU|Mémoire vidéo occupée|Processeur et mémoire|Requêtes par minute|Jetons par seconde|Temps avant le premier jeton) : (.+)", "{1}: {2}"),
(r"(Processeur|Mémoire|Requêtes|Vitesse par requête|Débit total|Premier jeton) : (.+)", "{1}: {2}"),
]
