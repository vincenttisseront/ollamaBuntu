# Parc : modèles absents d'un serveur en répartition, modèles de remplacement
E = {
"Modèles absents de ce serveur (il ne reçoit pas leurs requêtes) :": "Models missing on this server (it receives no requests for them):",
"Installez-les (Synchroniser > Modèles) ou choisissez un modèle de remplacement si ses GPU sont différents.": "Install them (Synchronise > Models) or choose a replacement model if its GPUs differ.",
"Modèles de remplacement...": "Replacement models...",
"Si ce serveur ne peut pas faire tourner un modèle (GPU différents), indiquez le modèle qu'il utilisera à la place : une ligne « modèle demandé = modèle de remplacement ». Écrivez « * = modèle » pour remplacer tous les modèles absents. Les réponses viendront alors d'un autre modèle, donc leur qualité et leur style peuvent différer.":
  "If this server cannot run a model (different GPUs), enter the model it will use instead: one line “requested model = replacement model”. Write “* = model” to replace every missing model. Answers will then come from a different model, so quality and style may differ.",
}
Q = "\u201c{1}\u201d"
P = [
(r"Modèles de remplacement de « (.+) »", "Replacement models for " + Q),
(r"Ligne invalide : (.+)", "Invalid line: {1}"),
]
