# Supervision, réglage automatique, limites des clés, règles de routage, retour arrière, sauvegarde de la configuration
E = {
# tableau de bord
"Alerte": "Alert", "Voir le réglage recommandé du contexte et du parallélisme": "See the recommended context and parallelism setting",
# réglage automatique
"Réglage automatique": "Automatic tuning", "Réglage automatique du contexte et du parallélisme": "Automatic context and parallelism tuning",
"Un modèle dont le cache ne tient pas dans la mémoire vidéo bascule en partie sur le processeur : le débit s'effondre. Cette recommandation calcule, pour chaque modèle, le contexte et le nombre de requêtes parallèles qui tiennent dans la mémoire des cartes. Le réglage est commun à tous les modèles et redémarre Ollama.":
  "A model whose cache does not fit in video memory moves partly onto the processor: throughput collapses. This recommendation works out, for each model, the context and the number of parallel requests that fit in the cards' memory. The setting is shared by all models and restarts Ollama.",
"Aucune mémoire vidéo détectée : ce réglage ne s'applique qu'aux serveurs avec GPU.": "No video memory detected: this setting only applies to servers with a GPU.",
"Poids": "Weights", "Contexte maximal": "Maximum context", "Recommandation": "Recommendation", "inconnu": "unknown", "ne tient pas en VRAM": "does not fit in VRAM", "serré": "tight", "tient": "fits",
"Le réglage actuel dépasse la mémoire disponible pour ce modèle.": "The current setting exceeds the memory available for this model.", 
"Appliquer": "Apply", "Réglage appliqué : Ollama redémarre.": "Setting applied: Ollama is restarting.",
# limites des clés
"Limites et consommation": "Limits and usage", "sans limite": "no limit", "tous": "all", "Requêtes simultanées au plus (0 = sans limite)": "Maximum simultaneous requests (0 = no limit)",
"Quota de jetons par jour (0 = sans limite)": "Token quota per day (0 = no limit)", "Quota de jetons par mois (0 = sans limite)": "Token quota per month (0 = no limit)",
"Au-delà du plafond, les requêtes d'un client attendent leur tour (jusqu'à 10 minutes). Au-delà d'un quota, elles sont refusées (erreur 429) jusqu'à la période suivante.":
  "Beyond the cap, a client's requests wait their turn (up to 10 minutes). Beyond a quota, they are refused (error 429) until the next period.",
# alertes
"Alertes": "Alerts",
"Prévient par webhook (Slack, Teams, Mattermost, ntfy...) et par e-mail quand un problème apparaît, puis quand il est résolu. Les alertes actives restent affichées dans le tableau de bord.":
  "Notifies by webhook (Slack, Teams, Mattermost, ntfy...) and by e-mail when a problem appears, then when it is resolved. Active alerts stay displayed on the dashboard.",
"Aucune alerte active.": "No active alert.", "Envoyer les notifications": "Send notifications", "Adresse du webhook (reçoit un message JSON)": "Webhook address (receives a JSON message)",
"Serveur SMTP": "SMTP server", "Port": "Port", "Identifiant SMTP": "SMTP user", "Mot de passe SMTP": "SMTP password", "Expéditeur": "Sender", "Destinataires (un par ligne)": "Recipients (one per line)",
"Événements surveillés": "Monitored events", "Disque plein à partir de (%)": "Disk full from (%)", "GPU chaud à partir de (°C)": "GPU hot from (°C)", "Débit minimal (jetons/s, 0 = désactivé)": "Minimum throughput (tokens/s, 0 = off)",
"Envoyer un message de test": "Send a test message", "Message de test": "Test message", "Aucun mot de passe enregistré": "No password saved",
"Mot de passe enregistré (laisser vide pour le conserver)": "Password saved (leave empty to keep it)",
"Modèle partiellement sur le processeur (débit très réduit)": "Model partly on the processor (very low throughput)", "Service Ollama arrêté": "Ollama service stopped", "Disque presque plein": "Disk almost full",
"GPU trop chaud": "GPU too hot", "Débit de génération trop bas": "Generation throughput too low", "Serveur du parc hors ligne": "Fleet server offline", "Nouvelle version d'OllamaBuntu disponible": "New OllamaBuntu version available",
"Modèle partiellement sur le processeur": "Model partly on the processor", "aucun canal : configurez un webhook ou un e-mail": "no channel: set up a webhook or an e-mail",
"configurez un webhook ou un e-mail": "set up a webhook or an e-mail",
# sauvegarde
"Sauvegarde de la configuration": "Configuration backup",
"Exporte comptes, clés d'API, politique d'usage de l'IA, parc de serveurs, alertes, règles et réglages d'Ollama dans un fichier chiffré par une phrase secrète. Les modèles, les certificats et les réglages de GPU n'en font pas partie.":
  "Exports accounts, API keys, AI usage policy, server fleet, alerts, rules and Ollama settings into a file encrypted with a passphrase. Models, certificates and GPU settings are not included.",
"Phrase secrète (12 caractères au moins)": "Passphrase (at least 12 characters)", "Exporter la configuration": "Export the configuration", "Restaurer": "Restore",
"Fichier de sauvegarde (.obbk)": "Backup file (.obbk)", "Phrase secrète": "Passphrase", "Restaurer la configuration": "Restore the configuration", "Lecture...": "Reading...",
"Fichier exporté : conservez-le avec la phrase secrète, séparément.": "File exported: keep it with the passphrase, separately.",
"Configuration restaurée : la console redémarre, reconnectez-vous.": "Configuration restored: the console is restarting, log in again.", "Restauration": "Restore",
"ce n'est pas une sauvegarde OllamaBuntu": "this is not an OllamaBuntu backup", "phrase secrète incorrecte ou sauvegarde altérée": "wrong passphrase or altered backup",
"phrase secrète trop courte (12 caractères au minimum)": "passphrase too short (12 characters minimum)", "fichier de sauvegarde trop volumineux": "backup file too large",
"fichier de sauvegarde illisible": "unreadable backup file", "sauvegarde vide ou sans manifeste": "empty backup or without manifest", "chiffrement impossible (openssl)": "encryption impossible (openssl)",
"sauvegarde trop volumineuse une fois décompressée": "backup too large once decompressed",
# retour arrière
"Revenir à une version précédente": "Go back to a previous version",
"Avant chaque mise à jour, les fichiers de l'appliance sont sauvegardés. Le retour restaure la console, le routeur et les scripts de la version choisie ; comptes, réglages d'Ollama et modèles sont conservés, ainsi que le programme Ollama installé. L'état actuel est sauvegardé d'abord : le retour est lui-même annulable.":
  "Before each update, the appliance files are backed up. Going back restores the console, the router and the scripts of the chosen version; accounts, Ollama settings and models are kept, as is the installed Ollama program. The current state is backed up first: going back can itself be undone.",
"Sauvegardée le": "Backed up on", "installée": "installed", "Revenir à cette version": "Go back to this version",
"Aucune sauvegarde : la première mise à jour en créera une.": "No backup: the first update will create one.", "Restauration des fichiers de la version précédente.": "Restoring the files of the previous version.",
"sauvegarde inconnue": "unknown backup", "Retour à la version précédente de l'appliance": "Return to the previous appliance version", "Rechargement après restauration de la configuration": "Reload after configuration restore",
# règles de routage et vérification du parc
"Règles de routage": "Routing rules", "Vérifier chaque serveur": "Check each server",
"Imposez ou interdisez un serveur pour un client (clé d'API) et un modèle. Exemple : « la clé Appli RH, modèles gemma*, uniquement sur Srv1 ». Les règles ne s'appliquent qu'aux serveurs en répartition.":
  "Force or forbid a server for a client (API key) and a model. Example: “key HR app, models gemma*, only on Srv1”. Rules only apply to servers in load balancing.",
"Client": "Client", "Modèle (motif, * = tous)": "Model (pattern, * = all)", "Règle": "Rule", "Uniquement sur ce serveur": "Only on this server", "Jamais sur ce serveur": "Never on this server",
"Ajouter la règle": "Add the rule", "Tous les clients": "All clients", "Ce serveur": "This server", "Uniquement sur": "Only on", "Jamais sur": "Never on", "(clé supprimée)": "(deleted key)", "(serveur retiré)": "(removed server)",
"Aucune règle : le routeur choisit selon la charge.": "No rule: the router chooses according to the load.", "Vérification du parc": "Fleet check", "Résultat": "Result", "Détail": "Detail", "Durée": "Duration", "Débit": "Throughput",
"répond": "responds", "échec": "failed", "hors ligne": "offline", "modèle absent, sans modèle de remplacement installé": "model missing, no replacement model installed", "aucun modèle à tester": "no model to test",
"Vérification en cours (chaque serveur génère quelques mots)...": "Checking (each server generates a few words)...",
"clé inconnue dans une règle": "unknown key in a rule", "serveur inconnu ou sans répartition dans une règle": "unknown server, or without load balancing, in a rule", "mode de règle invalide": "invalid rule mode",
"règles invalides (100 au maximum)": "invalid rules (100 maximum)",
# Hugging Face : adaptation à la VRAM
"tient en VRAM": "fits in VRAM", "déborde sur le processeur": "spills onto the processor", "trop gros": "too big",
"Ce serveur n'a pas de GPU : le modèle tournera sur le processeur.": "This server has no GPU: the model will run on the processor.",
"Ce fichier est trop gros pour la mémoire de ce serveur.": "This file is too big for this server's memory.",
"Il ne tiendra pas entièrement en mémoire vidéo : débit nettement réduit.": "It will not fit entirely in video memory: throughput much reduced.",
"Ce modèle est une version sans censure.": "This model is an uncensored version.",
"limites hors bornes": "limits out of range",
}
P = [
# alertes envoyées par le serveur
(r"Disque occupé à (\d+) %", "Disk {1}% full"),
(r"(.+) tourne à (\d+) % sur le processeur : débit fortement réduit", "{1} runs {2}% on the processor: throughput greatly reduced"),
(r"Ollama : service (.+)", "Ollama: service {1}"),
(r"GPU (.+) à (\d+) °C", "GPU {1} at {2} °C"),
(r"Débit moyen de (.+) jetons/s sur les dernières requêtes \(seuil (.+)\)", "Average throughput of {1} tokens/s over the latest requests (threshold {2})"),
(r"Serveur « (.+) » hors ligne", "Server “{1}” offline"),
(r"Version (.+) d'OllamaBuntu disponible", "OllamaBuntu version {1} available"),
(r"(.+) : envoyé", "{1}: sent"), (r"(.+) : échec - (.+)", "{1}: failed - {2}"),
(r"Dernier échec d'envoi : (.+)", "Last sending failure: {1}"),
# réglage automatique
(r"Mémoire vidéo : (.+) \((.+)\) - réglage actuel : contexte (.+), (\d+) en parallèle, cache (.+)", "Video memory: {1} ({2}) - current setting: context {3}, {4} in parallel, {5} cache"),
(r"(\d+) en parallèle, contexte (\d+)", "{1} in parallel, context {2}"),
(r"Appliquer à tous les modèles : (\d+) en parallèle, contexte (\d+) jetons \? Ollama redémarre et les modèles chargés sont déchargés\.", "Apply to all models: {1} in parallel, context {2} tokens? Ollama restarts and loaded models are unloaded."),
(r"(\d+) alertes", "{1} alerts"),
# limites
(r"au plus (\d+) simultanée\(s\)", "at most {1} simultaneous"), (r"(\d+) en cours, (\d+) en attente", "{1} running, {2} waiting"),
(r"jour : (.+) / (.+) jetons", "day: {1} / {2} tokens"), (r"mois : (.+) / (.+) jetons", "month: {1} / {2} tokens"), (r"(.+) jetons au total", "{1} tokens in total"),
(r"(.+) en parallèle", "{1} in parallel"),
(r"quota journalier de (\d+) jetons atteint \(reprise à minuit\) pour « (.+) »", "daily quota of {1} tokens reached (resumes at midnight) for “{2}”"),
(r"quota mensuel de (\d+) jetons atteint \(reprise le mois prochain\) pour « (.+) »", "monthly quota of {1} tokens reached (resumes next month) for “{2}”"),
# sauvegarde et retour
(r"Restaurer la configuration de la version (.+) \((.+)\) \?\nFichiers : (.+)\.\nLa configuration actuelle de ces fichiers sera remplacée, puis Ollama, le routeur et la console redémarrent\.", "Restore the configuration of version {1} ({2})?\nFiles: {3}.\nThe current configuration of these files will be replaced, then Ollama, the router and the console restart."),
(r"Revenir de v(.+) à v(.+) \?\nLes fichiers de l'appliance de cette version sont restaurés ; comptes, réglages d'Ollama et modèles sont conservés\. Les services IA redémarrent\.", "Go back from v{1} to v{2}?\nThe appliance files of this version are restored; accounts, Ollama settings and models are kept. The AI services restart."),
(r"Mémoire vidéo de ce serveur : (.+)", "Video memory of this server: {1}"),
(r"modèle (.+) \(remplacement de (.+)\)", "model {1} (replacing {2})"), (r"modèle (.+)", "model {1}"),
(r"Modèle de référence : (.+)", "Reference model: {1}"),
(r"valeur invalide : (.+)", "invalid value: {1}"), (r"(.+) hors limites \(0 à (\d+)\)", "{1} out of range (0 to {2})"),
(r"motif de modèle invalide : (.+)", "invalid model pattern: {1}"),
(r"contenu inattendu dans la sauvegarde : (.+)", "unexpected content in the backup: {1}"), (r"fichier JSON invalide : (.+)", "invalid JSON file: {1}"),
(r"sauvegarde illisible : (.+)", "unreadable backup: {1}"), (r"fichier trop volumineux : (.+)", "file too large: {1}"),
(r"Aucun mot de passe SMTP", "No SMTP password"),
]
