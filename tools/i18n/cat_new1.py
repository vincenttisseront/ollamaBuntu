Q = "\u201c{1}\u201d"
E = {
"Modèles personnalisés": "Custom models",
"Variante d'un modèle installé avec son propre prompt système et ses paramètres (par exemple un assistant RH qui répond toujours en français, avec une température basse). Les poids ne sont pas dupliqués ; la variante s'utilise par son nom, comme tout modèle.":
  "A variant of an installed model with its own system prompt and settings (for example an HR assistant that always answers in French, with a low temperature). Weights are not duplicated; the variant is used by its name, like any model.",
"Température": "Temperature", "Pénalité de répétition": "Repetition penalty", "Créer ou mettre à jour": "Create or update", "Préchargement": "Preloading",
"Modèles gardés en mémoire en permanence et rechargés automatiquement après un redémarrage : pas d'attente au premier appel.": "Models kept in memory permanently and reloaded automatically after a restart: no wait on the first call.",
"Enregistrer le préchargement": "Save preloading", "Charge": "Load", "Gestion centralisée": "Centralised management",
"Autorisez une console OllamaBuntu principale à superviser ce serveur (état, charge, alertes) et à y lancer des actions de maintenance (redémarrer Ollama, rechercher et installer les correctifs de sécurité). Elle n'a accès ni aux comptes, ni aux réglages, ni aux conversations.":
  "Allow a main OllamaBuntu console to monitor this server (status, load, alerts) and run maintenance actions on it (restart Ollama, check for and install security fixes). It has no access to accounts, settings or conversations.",
"Nom de la console principale": "Main console name", "Autoriser une console principale": "Authorise a main console",
"Criticité des correctifs de sécurité (avis Ubuntu) :": "Severity of security fixes (Ubuntu notices):", "Paquet": "Package", "Dépôt": "Repository", "Criticité": "Severity",
"non déterminée": "undetermined", "critique": "critical", "haute": "high", "moyenne": "medium", "basse": "low", "négligeable": "negligible",
"sécurité": "security", "correctif": "bug fix", "rétroportage": "backport", "autre": "other",
"Ce que l'IA peut faire et atteindre. Ollama génère du texte et des embeddings, et analyse les images ou vidéos fournies (modèles de vision) ; il ne génère ni images ni vidéos. Ces règles sont aussi appliquées par le routeur, quel que soit le client.":
  "What the AI can do and reach. Ollama generates text and embeddings, and analyses the images or videos it is given (vision models); it generates neither images nor videos. These rules are also enforced by the router, whatever the client.",
"Fonctions cloud d'Ollama : modèles « :cloud » exécutés chez Ollama et recherche web via ollama.com (les données quittent le serveur)":
  "Ollama cloud features: \u201c:cloud\u201d models run at Ollama and web search via ollama.com (data leaves the server)",
"Ollama peut accéder à Internet (sinon : seuls les téléchargements de modèles lancés depuis cette console, le temps du téléchargement)":
  "Ollama can access the Internet (otherwise: only model downloads started from this console, for the duration of the download)",
"Recherche sur Internet": "Internet search", "Génération d'images (moteur externe à configurer : ComfyUI, Automatic1111, API)": "Image generation (external engine to configure: ComfyUI, Automatic1111, API)",
"Exécution du code des réponses": "Execution of code in answers", "Interpréteur de code (le modèle lance lui-même du code)": "Code interpreter (the model runs code itself)",
"Connexions à des API externes compatibles OpenAI": "Connections to external OpenAI-compatible APIs", "Connexions directes des utilisateurs à leurs propres API": "Users' direct connections to their own APIs",
"Partage de conversations vers la communauté Open WebUI": "Sharing conversations to the Open WebUI community",
"Verrouiller : les administrateurs d'Open WebUI ne peuvent pas modifier ces réglages": "Lock: Open WebUI administrators cannot change these settings",
"Usages de l'IA": "AI usage", "Appliquer": "Apply", "Serveurs": "Servers", "Ajouter un serveur": "Add a server", "Vérifier et ajouter": "Check and add",
"Sur le serveur à ajouter : Système > Gestion centralisée > « Autoriser une console principale », puis copiez le jeton affiché. Ce serveur pourra alors être supervisé d'ici (état, charge, alertes) et recevoir des actions de maintenance ; ses comptes, réglages et conversations restent inaccessibles.":
  "On the server to add: System > Centralised management > \u201cAuthorise a main console\u201d, then copy the token shown. That server can then be monitored from here (status, load, alerts) and receive maintenance actions; its accounts, settings and conversations remain inaccessible.",
"Jeton": "Token", "ex. GPU-Paris-01": "e.g. GPU-Paris-01", "ex. assistant-rh": "e.g. hr-assistant",
"ex. Tu es l'assistant RH de l'entreprise. Réponds en français, de façon concise et factuelle.": "e.g. You are the company's HR assistant. Answer in English, concisely and factually.",
"oui (console + SSH)": "yes (console + SSH)",
}
P = [
(r"Requires Internet access from the server \(registry\.ollama\.ai\)\. Hugging Face : hf\.co/<utilisateur>/<dépôt>:<quantification> \(dépôts GGUF\), ex\. (.+)", "Requires Internet access from the server (registry.ollama.ai). Hugging Face: hf.co/<user>/<repository>:<quantisation> (GGUF repositories), e.g. {1}"),
(r"Hugging Face : hf\.co/<utilisateur>/<dépôt>:<quantification> \(dépôts GGUF\), ex\. (.+)", "Hugging Face: hf.co/<user>/<repository>:<quantisation> (GGUF repositories), e.g. {1}"),
(r"(\d+) paquet\(s\) en attente :", "{1} package(s) pending:"),
(r"(\d+) (sécurité|correctif|rétroportage|autre)", "{1} {2}"),
(r"(\d+) (non déterminée|critique|haute|moyenne|basse|négligeable)", "{1} {2}"),
(r"Dernière recherche : (.+) - criticité : (.+)", "Last check: {1} - severity: {2}"),
(r"nouveau → (.+)", "new → {1}"),
(r"à revoir : (.+)", "to review: {1}"),
]
