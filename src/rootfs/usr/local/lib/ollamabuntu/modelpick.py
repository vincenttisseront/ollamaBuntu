"""Choix d'un modèle de remplacement sur un serveur qui n'a pas le modèle demandé (répartition de charge « modèle différent »).
Module partagé par le routeur (choix à chaque requête) et la console (carte « Répartition de charge » : ce que chaque serveur répondrait)."""


def norm(name):
    n = str(name or "").strip()
    for p in ("registry.ollama.ai/library/", "ollama.com/library/", "library/"):
        if n.startswith(p):
            n = n[len(p):]
    if ":" not in n.split("/")[-1]:
        n += ":latest"
    return n.lower()


def is_cloud(name):
    tag = norm(name).rsplit(":", 1)[-1]
    return tag == "cloud" or tag.endswith("-cloud")


def _family(m):
    d = m.get("details") or {}
    return str(d.get("family") or (m.get("name") or m.get("model") or "").split(":")[0].split("-")[0]).lower()


def _is_embed(m):
    n = norm(m.get("name") or m.get("model") or "")
    return "embed" in n or _family(m) in ("bert", "nomic-bert", "xlm-roberta")


def auto_substitute(models, model, want, loaded):
    """Modèle de ce serveur qui remplace `model` quand il ne l'a pas : même nature (conversation / embeddings), même famille si possible,
    déjà en mémoire de préférence, puis le plus proche en taille. `want` : fiche du modèle demandé sur cette console (ou None)."""
    emb = _is_embed(want) if want else ("embed" in model)
    fam = _family(want) if want else None
    size = float((want or {}).get("size") or 0)
    best = None
    for m in models:
        n = norm(m.get("name") or m.get("model") or "")
        if not n or is_cloud(n) or _is_embed(m) != emb:
            continue
        gap = abs(float(m.get("size") or 0) - size) / (size or 1) if size else 0
        key = (0 if fam and _family(m) == fam else 1, 0 if n in loaded else 1, gap, n)
        if best is None or key < best[0]:
            best = (key, n)
    return best[1] if best else None
