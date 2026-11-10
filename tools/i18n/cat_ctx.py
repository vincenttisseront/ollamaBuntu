E = {
"Taille du contexte": "Context size", "Par défaut pour tous les modèles": "Default for all models", "Valeur par défaut d'Ollama": "Ollama default",
"S'applique aussi à l'API compatible OpenAI. Appliquer redémarre Ollama.": "Also applies to the OpenAI-compatible API. Applying restarts Ollama.",
"Par modèle": "Per model", "Maximum du modèle": "Model maximum", "Contexte appliqué": "Applied context", "Mémoire du contexte": "Context memory", "Défaut du serveur": "Server default",
"Contexte : réglage du modèle": "Context: model setting", "Taille du contexte de la conversation": "Conversation context size", "la valeur par défaut d'Ollama": "the Ollama default",
"Application (redémarrage d'Ollama)...": "Applying (restarting Ollama)...", "taille de contexte invalide": "invalid context size",
"Nombre de jetons qu'un modèle garde en tête pour une conversation : questions, réponses et documents fournis. Plus il est grand, plus le modèle se souvient, mais plus il occupe de mémoire vidéo ; au-delà de la mémoire de la carte, il déborde sur celle du serveur et ralentit fortement.":
  "Number of tokens a model keeps in mind for a conversation: questions, answers and documents provided. The larger it is, the more the model remembers, but the more video memory it uses; beyond the card's memory, it spills over into the server's memory and slows down sharply.",
"La valeur d'un modèle s'applique à toutes les requêtes de l'API d'Ollama (console, Open WebUI, applications), sauf si la requête précise sa propre taille. La mémoire est estimée pour une requête à la fois.":
  "A model's value applies to all Ollama API requests (console, Open WebUI, applications), unless the request specifies its own size. Memory is estimated for one request at a time.",
}
P = [
(r"(\d+) K jetons", "{1} K tokens"), (r"([\d\u202f\u00a0 ]+) jetons", "{1} tokens"), (r"(.+) jetons \(maximum\)", "{1} tokens (maximum)"),
(r"Défaut du serveur \((.+)\)", "Server default ({1})"), (r"Contexte de (.+)", "Context of {1}"),
(r"≈ (.+) \((\d+) requêtes parallèles\)", "≈ {1} ({2} parallel requests)"),
(r"Appliquer (.+) à tous les modèles \? Ollama redémarre : les requêtes en cours sont interrompues\.", "Apply {1} to all models? Ollama restarts: requests in progress are interrupted."),
(r"au-delà du maximum du modèle \((\d+) jetons\)", "beyond the model maximum ({1} tokens)"),
(r"taille de contexte hors limites \((\d+) à (\d+) jetons\)", "context size out of range ({1} to {2} tokens)"),
]
