# Moteur llama.cpp : cache d'invites, mémoire verrouillée, décodage spéculatif
E = {
"Modèle verrouillé en mémoire": "Model locked in memory",
"Décodage spéculatif : motifs répétés": "Speculative decoding: repeated patterns",
"Réutilisation du cache d'invites (jetons, 0 = désactivée)": "Prompt cache reuse (tokens, 0 = disabled)",
"Mémoire du cache d'invites (Mo, vide = réglage de llama-server)": "Prompt cache memory (MB, empty = llama-server setting)",
"Verrouiller le modèle en mémoire": "Lock the model in memory",
"Verrouiller le modèle en mémoire (évite qu'il soit déplacé sur le disque ; demande assez de mémoire libre)":
  "Lock the model in memory (keeps it from being swapped out to disk; needs enough free memory)",
"Décodage spéculatif": "Speculative decoding",
"Désactivé": "Disabled",
"Avec un modèle brouillon": "With a draft model",
"Par motifs répétés (sans second modèle)": "By repeated patterns (no second model)",
"Modèle brouillon": "Draft model",
"Choisir un modèle": "Choose a model",
"Modèle brouillon (petit, de la même famille)": "Draft model (small, same family)",
"Jetons proposés à chaque étape (1 à 64)": "Tokens proposed at each step (1 to 64)",
"Réutilisation du cache : quand une invite ne diffère d'une précédente que par un passage au milieu, llama-server réutilise ce qu'il a déjà calculé après ce passage. Décodage spéculatif : un petit modèle propose plusieurs jetons que le grand modèle vérifie d'un coup ; la réponse est la même, souvent plus vite (surtout en code et en reformulation). Le brouillon doit partager le vocabulaire du modèle principal et occupe de la mémoire vidéo en plus ; le taux d'acceptation mesuré s'affiche dans la liste des moteurs.":
  "Cache reuse: when a prompt differs from a previous one only by a passage in the middle, llama-server reuses what it already computed after that passage. Speculative decoding: a small model proposes several tokens that the large model checks in one go; the answer is the same, often faster (especially for code and rewording). The draft must share the main model's vocabulary and takes extra video memory; the measured acceptance rate is shown in the engine list.",
"réutilisation du cache : 0 (désactivée) à 8192 jetons": "cache reuse: 0 (disabled) to 8192 tokens",
"jetons proposés par le brouillon : 1 à 64": "tokens proposed by the draft: 1 to 64",
"couches du brouillon sur la carte : 0 à 999": "draft layers on the card: 0 to 999",
"mémoire du cache d'invites : 0 (désactivée) à 262144 Mo, vide = réglage de llama-server": "prompt cache memory: 0 (disabled) to 262144 MB, empty = llama-server setting",
"décodage spéculatif : désactivé, modèle brouillon ou motifs répétés": "speculative decoding: disabled, draft model or repeated patterns",
"nom du modèle brouillon invalide": "invalid draft model name",
"décodage spéculatif : choisissez le modèle brouillon": "speculative decoding: choose the draft model",
"le modèle brouillon doit être plus petit que le modèle principal, pas le même": "the draft model must be smaller than the main model, not the same one",
"modèle brouillon : fichier illisible": "draft model: unreadable file",
"réutilisation du cache inconnue de cette version de llama-server": "cache reuse unknown to this llama-server version",
"mémoire du cache d'invites inconnue de cette version de llama-server": "prompt cache memory unknown to this llama-server version",
"verrouillage en mémoire inconnu de cette version de llama-server": "memory locking unknown to this llama-server version",
"modèle brouillon introuvable : décodage spéculatif ignoré": "draft model not found: speculative decoding ignored",
"décodage spéculatif avec un modèle brouillon inconnu de cette version de llama-server : mettez-la à jour":
  "speculative decoding with a draft model unknown to this llama-server version: update it",
"décodage spéculatif par motifs répétés inconnu de cette version de llama-server : mettez-la à jour": "speculative decoding by repeated patterns unknown to this llama-server version: update it",
}
P = [
(r'Réutilisation du cache d\'invites : (\d+) jetons', "Prompt cache reuse: {1} tokens"),
(r'Décodage spéculatif : brouillon (.+) \((.+)\)', "Speculative decoding: draft {1} ({2})"),
(r'Brouillon : (\d+) % acceptés \((\d+) sur (\d+) jetons\)', "Draft: {1} % accepted ({2} of {3} tokens)"),
(r'le modèle brouillon \((.+)\) doit être bien plus petit que le modèle principal \((.+)\) : sinon il ralentit au lieu d\'accélérer', "the draft model ({1}) must be much smaller than the main model ({2}): otherwise it slows things down instead of speeding them up"),
(r'modèle brouillon : (.+)', "draft model: {1}"),
]
