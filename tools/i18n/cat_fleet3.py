# Parc : modèles absents d'un serveur en répartition, modèles de remplacement
E = {
"Modèles absents de ce serveur (il ne reçoit pas leurs requêtes) :": "Models missing on this server (it receives no requests for them):",
"Installez-les (Synchroniser > Modèles) ou choisissez un modèle de remplacement si ses GPU sont différents.": "Install them (Synchronise > Models) or choose a replacement model if its GPUs differ.",
"Modèles de remplacement...": "Replacement models...",
"Si ce serveur ne peut pas faire tourner un modèle (GPU différents), choisissez le modèle qu'il utilisera à la place. « Tous les modèles absents du serveur » remplace en une fois tous ceux qu'il n'a pas. Les réponses viendront alors d'un autre modèle, donc leur qualité et leur style peuvent différer.":
  "If this server cannot run a model (different GPUs), choose the model it will use instead. “All models missing on the server” replaces every model it does not have in one go. Answers will then come from a different model, so quality and style may differ.",
"Tous les modèles absents du serveur": "All models missing on the server",
"Modèle demandé": "Requested model", "Modèle de remplacement": "Replacement model",
"Ajouter une association": "Add a pairing",
"Aucun modèle détecté sur ce serveur : installez-en d'abord (Synchroniser > Modèles).": "No model detected on this server: install some first (Synchronise > Models).",
"Aucun modèle de ce serveur ne convient automatiquement : choisissez-le vous-même.": "No model on this server fits automatically: choose one yourself.",
"Tous les modèles de cette console sont présents sur ce serveur : aucun remplacement nécessaire.": "All models of this console are present on this server: no replacement needed.",
}
Q = "\u201c{1}\u201d"
P = [
(r"Modèles de remplacement de « (.+) »", "Replacement models for " + Q),
(r"Ligne invalide : (.+)", "Invalid line: {1}"),
(r"Proposition automatique pour (\d+) modèle\(s\) absent\(s\) de ce serveur : choisissez, modifiez ou retirez avant d'enregistrer\.", "Automatic proposal for {1} model(s) missing on this server: choose, edit or remove before saving."),
(r"Un modèle ne peut pas se remplacer lui-même : (.+)", "A model cannot replace itself: {1}"),
(r"(.+) \(introuvable\)", "{1} (not found)"),
]
