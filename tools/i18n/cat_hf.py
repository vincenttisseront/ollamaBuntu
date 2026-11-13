# Hugging Face : recherche et téléchargement de modèles GGUF, versions sans censure
E = {
"Ce dépôt contient les poids d'origine (safetensors) : Ollama et llama.cpp ne lisent que le format GGUF, que des tiers publient à part.": "This repository holds the original weights (safetensors): Ollama and llama.cpp only read the GGUF format, which third parties publish separately.",
"Versions GGUF du même modèle (les plus téléchargées) :": "GGUF versions of the same model (most downloaded):",
"Aucune version GGUF trouvée automatiquement : cherchez le nom du modèle dans la recherche Hugging Face de la page Modèles.": "No GGUF version found automatically: search for the model name in the Hugging Face search of the Models page.",
"Hugging Face": "Hugging Face",
"Recherche de modèles au format GGUF sur huggingface.co, puis téléchargement de la quantification choisie. Les modèles « sans censure » (uncensored, abliterated...) sont masqués par défaut.":
  "Search for GGUF models on huggingface.co, then download the chosen quantisation. “Uncensored” models (uncensored, abliterated...) are hidden by default.",
"ex. llama 3.2, qwen coder, mistral": "e.g. llama 3.2, qwen coder, mistral",
"Modèles standard": "Standard models", "Standard et sans censure": "Standard and uncensored", "Sans censure seulement": "Uncensored only",
"Rechercher": "Search", "Recherche en cours...": "Searching...", "Aucun modèle trouvé.": "No model found.", "Choisir": "Choose", "sans censure": "uncensored",
"Lecture des quantifications...": "Reading quantisations...",
"Version sans censure : les garde-fous du modèle d'origine sont retirés. Son usage reste soumis à la politique d'usage de l'IA de votre organisation.":
  "Uncensored version: the safeguards of the original model are removed. Its use remains subject to your organisation's AI usage policy.",
"Plus la quantification est basse (Q2, Q3), plus le fichier est petit et la qualité réduite ; Q4_K_M est un bon compromis.":
  "The lower the quantisation (Q2, Q3), the smaller the file and the lower the quality; Q4_K_M is a good compromise.",
"Aucune quantification GGUF exploitable dans ce dépôt.": "No usable GGUF quantisation in this repository.",
"recherche invalide": "invalid search", "dépôt introuvable sur Hugging Face": "repository not found on Hugging Face",
"nom de dépôt invalide (utilisateur/dépôt)": "invalid repository name (user/repository)",
"dépôt à accès restreint (compte Hugging Face requis) : non téléchargeable ici": "restricted repository (Hugging Face account required): cannot be downloaded here",
}
P = [
(r"(.+) téléchargements", "{1} downloads"),
(r"(\d+) modèle\(s\), les plus téléchargés d'abord\.", "{1} model(s), most downloaded first."),
(r"(.+) téléchargements - (\d+) J'aime - mis à jour le (.*)", "{1} downloads - {2} likes - updated on {3}"),
(r"Télécharger « (.+) » depuis Hugging Face \?( Ce modèle est une version sans censure\.)?", "Download “{1}” from Hugging Face?{2}"),
(r"Hugging Face injoignable : (.+)", "Hugging Face unreachable: {1}"),
(r"Hugging Face a répondu HTTP (\d+)", "Hugging Face answered HTTP {1}"),
]
