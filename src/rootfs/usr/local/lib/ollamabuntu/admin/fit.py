#!/usr/bin/env python3
"""OllamaBuntu - ajustement d'un modèle à la mémoire du serveur : place nécessaire, options pour le faire tenir, vitesse estimée.
Fonctions pures (aucun accès disque, réseau ni commande) : testables hors de la console, sans matériel.

Principe. La génération d'un jeton lit une fois tous les poids « actifs » : la vitesse est donc bornée par la bande passante mémoire,
pas par le calcul. Un modèle tient-il en mémoire vidéo ? Sinon, que déborder, et à quel prix ?
- Poids + cache de contexte (K et V, par jeton et par requête parallèle) + réserve du moteur doivent tenir dans la mémoire vidéo.
- Leviers sans perte notable : cache de contexte en q8_0 (presque la moitié de la mémoire), contexte réduit à l'usage réel.
- Modèle « à experts » (MoE) : seule une fraction des experts sert à chaque jeton. On peut garder en mémoire vidéo ce qui sert toujours
  (attention, cache) et mettre les experts en mémoire système : la perte est bien plus faible qu'un débordement par couches.
- Modèle dense : le débordement par couches ralentit en proportion de ce qui sort de la mémoire vidéo.
Les chiffres sont des ESTIMATIONS : la vitesse se calibre sur une mesure réelle quand il y en a une (calibrate)."""
import math
import re

GIB = 1024 ** 3
KV_BYTES = {"f16": 2.0, "q8_0": 34 / 32.0, "q4_0": 18 / 32.0}   # octets par élément du cache (q8_0 : 34 octets pour 32 éléments)
KV_ORDER = ("f16", "q8_0", "q4_0")
RESERVE = 0.9 * GIB          # contexte du pilote + tampons de calcul du moteur
RESERVE_PER_B = 0.015        # + 1,5 % des poids (tampons proportionnels à la taille du modèle)
VRAM_USABLE = 0.96           # part de la mémoire vidéo utilisable (le reste : pilote, affichage, fragmentation)
RAM_USABLE = 0.85            # part de la mémoire disponible utilisable par un modèle débordé
EFF_GPU = 0.65               # rendement habituel de la génération sur GPU (lecture des poids / bande passante théorique)
EFF_RAM = 0.60
MIN_CTX = 2048
KV_FILL = 0.5               # part moyenne du contexte réellement remplie (la lecture du cache croît avec le remplissage)
RAM_GBPS_DEFAULT = 30.0      # sans mesure : double canal DDR4 prudent
SWA_PATTERN = {"gemma2": 2, "gemma3": 6}   # une couche sur N lit tout le contexte, les autres seulement la fenêtre glissante (quand le modèle ne le dit pas)
MOE_ARCH = re.compile(r"(moe|mixtral|deepseek|dbrx|grok|arctic|gpt-?oss|llama4|olmoe|jamba|qwen3next|glm4moe|ernie4_5[-_]moe|hunyuan|bailing|smallthinker|lfm2moe|minimax|phimoe|granitemoe)", re.I)
MOE_NAME = re.compile(r"(?i)(moe|\b\d+x\d+(\.\d+)?b\b|[-_ ]a\d+(\.\d+)?b\b|gpt-oss)")

# Bande passante mémoire théorique des cartes courantes (Go/s). Motif -> débit ; le premier qui correspond l'emporte.
GPU_BW = [
    (r"rtx\s*5090", 1792), (r"rtx\s*5080", 960), (r"rtx\s*5070\s*ti", 896), (r"rtx\s*5070", 672), (r"rtx\s*5060\s*ti", 448), (r"rtx\s*5060", 448),
    (r"rtx\s*4090", 1008), (r"rtx\s*4080", 717), (r"rtx\s*4070\s*ti\s*super", 672), (r"rtx\s*4070\s*ti", 504), (r"rtx\s*4070\s*super", 504), (r"rtx\s*4070", 504),
    (r"rtx\s*4060\s*ti", 288), (r"rtx\s*4060", 272),
    (r"rtx\s*3090", 936), (r"rtx\s*3080\s*ti", 912), (r"rtx\s*3080", 760), (r"rtx\s*3070", 448), (r"rtx\s*3060\s*ti", 448), (r"rtx\s*3060", 360),
    (r"rtx\s*2080\s*ti", 616), (r"rtx\s*2080", 448), (r"rtx\s*2070", 448), (r"rtx\s*2060", 336),
    (r"quadro\s*rtx\s*8000", 672), (r"quadro\s*rtx\s*6000", 672), (r"quadro\s*rtx\s*5000", 448), (r"quadro\s*rtx\s*4000", 416),
    (r"rtx\s*6000\s*ada", 960), (r"rtx\s*a6000", 768), (r"rtx\s*a5000", 768), (r"rtx\s*a4500", 640), (r"rtx\s*a4000", 448), (r"rtx\s*a2000", 288),
    (r"\bl40s?\b", 864), (r"\bl4\b", 300), (r"\bt4\b", 320), (r"\ba10g?\b", 600), (r"\ba40\b", 696), (r"\ba100\b", 1555), (r"\bh100\b", 3350), (r"\bv100\b", 900), (r"\bp40\b", 346), (r"\bp100\b", 732),
    (r"rx\s*9070\s*xt", 640), (r"rx\s*9070", 640), (r"rx\s*7900\s*xtx", 960), (r"rx\s*7900\s*xt", 800), (r"rx\s*7900\s*gre", 576), (r"rx\s*7800\s*xt", 624),
    (r"rx\s*7700\s*xt", 432), (r"rx\s*7700", 432), (r"rx\s*7600", 288), (r"rx\s*6950\s*xt", 576), (r"rx\s*6900\s*xt", 512), (r"rx\s*6800\s*xt", 512), (r"rx\s*6800", 512),
    (r"rx\s*6700\s*xt", 384), (r"rx\s*6600\s*xt", 256), (r"mi300", 5300), (r"mi250", 3277), (r"mi210", 1638), (r"mi100", 1229),
    (r"arc\s*b580", 456), (r"arc\s*a770", 560), (r"arc\s*a750", 512),
]


def gpu_bandwidth(name):
    """Bande passante théorique (Go/s) d'une carte d'après son nom, ou None si elle n'est pas connue."""
    n = str(name or "").lower()
    for rx, gbps in GPU_BW:
        if re.search(rx, n):
            return float(gbps)
    return None


def looks_moe(name="", arch="", tags=()):
    """Un modèle est-il à experts d'après son nom, son architecture, ses étiquettes ? Hypothèse, jamais une certitude (None = on ne sait pas)."""
    if arch and MOE_ARCH.search(str(arch)):
        return True
    text = " ".join([str(name or "")] + [str(t) for t in tags or ()])
    if MOE_NAME.search(text):
        return True
    return False if arch else None


# ------------------------------------------------------------------ forme du modèle
def model_from_show(name, size, info):
    """Forme d'un modèle d'après /api/show (model_info) et la taille du fichier. Retourne None si les poids sont inconnus.
    Clés : name, weights, layers, kv_elems (éléments K+V par jeton, toutes couches), max_ctx, moe, experts, used, expert_bytes, arch, params."""
    info = info or {}
    arch = str(info.get("general.architecture") or "")
    g = lambda k: info.get("%s.%s" % (arch, k))
    layers = g("block_count")
    heads, kv, emb = g("attention.head_count"), g("attention.head_count_kv"), g("embedding_length")
    heads_n = max(heads) if isinstance(heads, list) and heads else heads
    kv = kv if kv is not None else heads
    klen = g("attention.key_length") or (emb // heads_n if isinstance(emb, int) and isinstance(heads_n, int) and heads_n else None)
    vlen = g("attention.value_length") or klen
    kv_total = sum(x for x in kv if isinstance(x, int)) if isinstance(kv, list) else (kv * layers if isinstance(kv, int) and isinstance(layers, int) else None)
    kv_elems = kv_total * (klen + vlen) if kv_total and klen and vlen else None
    experts, used = g("expert_count"), g("expert_used_count")
    params = info.get("general.parameter_count")
    window = g("attention.sliding_window")
    pattern = g("attention.sliding_window_pattern") or SWA_PATTERN.get(arch)
    swa = window if isinstance(window, int) and window > 0 and isinstance(pattern, int) and pattern > 1 else None
    weights = int(size or 0)
    if weights <= 0:
        return None
    moe = bool(isinstance(experts, int) and experts > 1)
    expert_bytes = 0
    if moe and isinstance(layers, int) and isinstance(emb, int):
        eff = g("expert_feed_forward_length") or g("feed_forward_length")
        eff = max(eff) if isinstance(eff, list) and eff else eff
        dense = g("leading_dense_block_count") or 0
        moe_layers = max(1, layers - (dense if isinstance(dense, int) else 0))
        if isinstance(eff, int) and eff > 0 and isinstance(params, (int, float)) and params > 0:
            expert_params = moe_layers * experts * 3 * emb * eff   # porte, montée, descente de chaque expert
            expert_bytes = int(weights * min(0.97, expert_params / float(params)))
        elif isinstance(params, (int, float)) and params > 0 and isinstance(used, int) and used > 0:
            expert_bytes = int(weights * 0.85)   # repli : les experts font l'essentiel des poids d'un modèle à experts
        else:
            expert_bytes = int(weights * 0.85)
    return {"name": name, "weights": weights, "layers": layers if isinstance(layers, int) else None, "kv_elems": kv_elems,
            "max_ctx": g("context_length") if isinstance(g("context_length"), int) else None, "moe": moe,
            "experts": experts if moe else None, "used": used if moe and isinstance(used, int) else None, "expert_bytes": expert_bytes if moe else 0,
            "arch": arch, "params": params if isinstance(params, (int, float)) else None, "swa": swa, "swa_global": (1.0 / pattern) if swa else None,
            "moe_layers": (max(1, layers - (g("leading_dense_block_count") or 0)) if moe and isinstance(layers, int) and isinstance(g("leading_dense_block_count") or 0, int) else None)}


# ------------------------------------------------------------------ calculs
def kv_bytes(model, ctx, kv_type, parallel=1):
    """Cache de contexte (octets) pour `ctx` jetons par requête et `parallel` requêtes. None si la forme du modèle est inconnue."""
    if not model.get("kv_elems"):
        return None
    tokens = ctx
    if model.get("swa"):   # fenêtre glissante : la plupart des couches ne gardent que les derniers jetons de la fenêtre
        g = model["swa_global"]
        tokens = g * ctx + (1 - g) * min(ctx, model["swa"])
    return int(model["kv_elems"] * KV_BYTES[kv_type] * tokens * max(1, parallel))


def reserve(model):
    return int(RESERVE + RESERVE_PER_B * model["weights"])


def resolve_hw(hw, conf=None):
    """Matériel utilisable : {vram, ram_avail, gpu_gbps, ram_gbps, calib}. conf : réglages enregistrés (ram_gbps, gpu_gbps, calibration)."""
    conf = conf or {}
    vram = int(hw.get("vram") or 0)
    gpu_theory = conf.get("gpu_gbps") or max([gpu_bandwidth(n) or 0 for n in hw.get("gpus") or []] or [0]) or None
    calib = conf.get("calib") if isinstance(conf.get("calib"), dict) else None
    return {"vram": vram, "ram_avail": int(hw.get("ram_avail") or 0), "ram_total": int(hw.get("ram_total") or 0), "gpu_theory": gpu_theory,
            "gpu_eff": (calib or {}).get("gpu_gbps") or (gpu_theory * EFF_GPU if gpu_theory else None), "calibrated": bool(calib and calib.get("gpu_gbps")),
            "ram_eff": (conf.get("ram_gbps") or RAM_GBPS_DEFAULT) * EFF_RAM, "ram_measured": bool(conf.get("ram_gbps"))}


def calibrate(measured_tps, weights, active_fraction=1.0):
    """Bande passante effective de la carte (Go/s) d'après un débit MESURÉ d'un modèle entièrement en mémoire vidéo.
    active_fraction : part des poids lue à chaque jeton (1 pour un modèle dense)."""
    if not measured_tps or measured_tps <= 0 or not weights:
        return None
    return round(measured_tps * weights * active_fraction / 1e9, 1)


def tps(gpu_read, cpu_read, hw):
    """Jetons par seconde estimés : temps = octets lus sur la carte / débit carte + octets lus en mémoire système / débit mémoire. None si inconnu."""
    if not hw.get("gpu_eff") and gpu_read:
        return None
    t = (gpu_read / (hw["gpu_eff"] * 1e9) if gpu_read else 0) + (cpu_read / (hw["ram_eff"] * 1e9) if cpu_read else 0)
    return round(1.0 / t, 1) if t > 0 else None


def speed_label(v):
    if v is None:
        return "non estimée"
    return "rapide" if v >= 30 else "confortable" if v >= 12 else "lente" if v >= 4 else "très lente"


def _frac_used(model):
    return (model["used"] / float(model["experts"])) if model.get("moe") and model.get("used") and model.get("experts") else 1.0


def scenario(model, hw, ctx, kv_type, parallel=1, mode="gpu", n_cpu_moe=None, gpu_frac=1.0):
    """Un scénario chiffré : mémoire vidéo et mémoire système nécessaires, entre dans la mémoire ?, débit estimé."""
    kv = kv_bytes(model, ctx, kv_type, parallel)
    if kv is None:
        kv = int(0.5 * GIB * (ctx / 4096.0) * max(1, parallel))   # forme inconnue : ordre de grandeur d'un modèle moyen
    res = reserve(model)
    w = model["weights"]
    eb = model.get("expert_bytes") or 0
    ne = w - eb
    frac = _frac_used(model)
    budget = hw["vram"] * VRAM_USABLE
    kv_read = kv * KV_FILL   # le cache déjà rempli est relu à chaque jeton
    if mode == "gpu":
        vram, ram = w + kv + res, 0
        gread, cread = ne + eb * frac + kv_read, 0
    elif mode == "moe":
        lm = model.get("moe_layers") or model.get("layers") or 1
        n = max(0, min(int(n_cpu_moe or 0), lm))
        cpu_part = eb * (n / float(lm))
        vram, ram = w - cpu_part + kv + res, cpu_part
        gread, cread = ne + (eb - cpu_part) * frac + kv_read, cpu_part * frac   # l'attention et son cache restent sur la carte
    else:   # couches : la fraction gpu_frac des couches (et de leur cache) reste en mémoire vidéo
        g = max(0.0, min(1.0, gpu_frac))
        vram, ram = g * (w + kv) + res, (1 - g) * (w + kv)
        active = ne + eb * frac + kv_read   # octets lus à chaque jeton (poids actifs et cache)
        gread, cread = g * active, (1 - g) * active
    return {"mode": mode, "ctx": ctx, "kv": kv_type, "parallel": parallel, "n_cpu_moe": n_cpu_moe if mode == "moe" else None,
            "gpu_frac": round(gpu_frac, 3) if mode == "layers" else None, "ngl": (int(gpu_frac * model["layers"]) if mode == "layers" and model.get("layers") else None),
            "vram": int(vram), "ram": int(ram), "kv_bytes": kv, "fits_vram": vram <= budget, "fits_ram": ram <= hw["ram_avail"] * RAM_USABLE if ram else True,
            "tps": tps(gread, cread, hw) if (gread or cread) else None, "gpu_read": int(gread), "cpu_read": int(cread), "kv_known": model.get("kv_elems") is not None}


def solve_moe(model, hw, ctx, kv_type, parallel=1):
    """Plus petit nombre de couches dont les experts vont en mémoire système pour que le reste tienne en mémoire vidéo. None si impossible."""
    if not model.get("moe") or not model.get("expert_bytes"):
        return None
    lm = model.get("moe_layers") or model.get("layers")
    if not lm:
        return None
    kv = kv_bytes(model, ctx, kv_type, parallel) or int(0.5 * GIB * (ctx / 4096.0) * max(1, parallel))
    budget = hw["vram"] * VRAM_USABLE
    over = model["weights"] + kv + reserve(model) - budget
    if over <= 0:
        return 0
    n = int(math.ceil(lm * over / float(model["expert_bytes"])))
    return n if n <= lm else None


def solve_layers(model, hw, ctx, kv_type, parallel=1):
    """Part des couches qui tient en mémoire vidéo (0 à 1)."""
    kv = kv_bytes(model, ctx, kv_type, parallel) or int(0.5 * GIB * (ctx / 4096.0) * max(1, parallel))
    budget = hw["vram"] * VRAM_USABLE - reserve(model)
    return max(0.0, min(1.0, budget / float(model["weights"] + kv))) if budget > 0 else 0.0


def ctx_ladder(want, max_ctx):
    """Tailles de contexte à essayer, de la souhaitée à la plus petite utile."""
    top = min(int(want), int(max_ctx)) if max_ctx else int(want)
    if top < MIN_CTX:
        return [max(256, top)]
    out, c = [], top
    while c >= MIN_CTX:
        out.append(c)
        c //= 2
    return out


def plan(model, hw, want_ctx=8192, parallel=1, current=None):
    """Étudie le modèle : verdict, scénarios, meilleur choix.
    current : réglages actuels {ctx, kv, parallel} (facultatif). Retourne un dict prêt à afficher."""
    parallel = max(1, int(parallel or 1))
    want = int(want_ctx or 8192)
    out = {"model": model["name"], "weights": model["weights"], "moe": model.get("moe", False), "experts": model.get("experts"), "used": model.get("used"),
           "expert_bytes": model.get("expert_bytes") or 0, "layers": model.get("layers"), "max_ctx": model.get("max_ctx"),
           "vram": hw["vram"], "ram_avail": hw["ram_avail"], "gpu_theory": hw.get("gpu_theory"), "gpu_eff": hw.get("gpu_eff"), "calibrated": hw.get("calibrated"),
           "kv_known": model.get("kv_elems") is not None, "scenarios": [], "recommended": None, "verdict": "inconnu", "notes": []}
    if hw["vram"] <= 0:
        out["verdict"] = "sans-gpu"
        out["notes"].append("Aucune mémoire vidéo détectée : le modèle tourne sur le processeur.")
        sc = scenario(model, dict(hw, vram=0), want, "f16", parallel, "layers", gpu_frac=0.0)
        sc.update(id="cpu", label="Sur le processeur")
        out["scenarios"] = [sc]
        out["recommended"] = "cpu"
        return out
    sid = 0

    def add(sc, label, why=""):
        nonlocal sid
        sid += 1
        sc.update(id="s%d" % sid, label=label, why=why)
        out["scenarios"].append(sc)
        return sc
    if current:
        c = scenario(model, hw, int(current.get("ctx") or want), current.get("kv") or "f16", int(current.get("parallel") or parallel))
        add(c, "Réglages actuels", "contexte %d, cache %s, %d requête(s) en parallèle" % (c["ctx"], c["kv"], c["parallel"]))
        out["current_fits"] = c["fits_vram"]
    fitting = None
    for ctx in ctx_ladder(want, model.get("max_ctx")):
        for kv in KV_ORDER:
            if kv != "f16" and not model.get("kv_elems"):
                continue
            sc = scenario(model, hw, ctx, kv, parallel)
            if sc["fits_vram"]:
                fitting = add(sc, "Tient en mémoire vidéo", "contexte %d, cache %s" % (ctx, kv))
                break
        if fitting:
            break
    if fitting:
        out["verdict"] = "gpu" if (fitting["ctx"] == min(want, model.get("max_ctx") or want) and fitting["kv"] == "f16") else "ajuste"
        out["recommended"] = fitting["id"]
        if fitting["kv"] != "f16":
            out["notes"].append("Le cache de contexte en %s divise sa mémoire par %.1f ; la perte de qualité est négligeable en q8_0, perceptible en q4_0." %
                                (fitting["kv"], KV_BYTES["f16"] / KV_BYTES[fitting["kv"]]))
        if fitting["ctx"] < min(want, model.get("max_ctx") or want):
            out["notes"].append("Le contexte est réduit à %d jetons : vérifiez que vos demandes ne sont pas plus longues (Journaux > Requêtes : jetons d'entrée)." % fitting["ctx"])
        return out
    # Rien ne tient entièrement en mémoire vidéo : experts en mémoire système, sinon débordement par couches
    ctx = min(want, model.get("max_ctx") or want)
    kv = "q8_0" if model.get("kv_elems") else "f16"
    best = None
    for c in ctx_ladder(ctx, model.get("max_ctx")):
        n = solve_moe(model, hw, c, kv, parallel)
        if n is not None:
            sc = scenario(model, hw, c, kv, parallel, "moe", n_cpu_moe=n)
            if sc["fits_ram"]:
                best = add(sc, "Experts en mémoire système (moteur llama.cpp)",
                           "les experts de %d couche(s) sur %d restent en mémoire système ; attention, cache et le reste en mémoire vidéo" % (n, model.get("moe_layers") or model.get("layers")))
                break
    if best:
        ref = scenario(model, hw, best["ctx"], best["kv"], parallel, "layers", gpu_frac=solve_layers(model, hw, best["ctx"], best["kv"], parallel))
        if ref["fits_ram"]:
            add(ref, "Pour comparaison : débordement par couches (Ollama)", "%d %% des couches en mémoire vidéo" % round(ref["gpu_frac"] * 100))
        out["verdict"] = "moe"
        out["recommended"] = best["id"]
        out["notes"].append("Modèle à experts : seul un petit nombre d'experts sert à chaque jeton, ce qui limite la perte de vitesse. "
                            "Ollama ne sait pas placer les experts en mémoire système : il faut le moteur llama.cpp (Modèles > Moteur MoE).")
        out["notes"].append("La lecture d'un long texte (traitement du prompt) est plus lente que la génération quand les experts sont en mémoire système.")
    else:
        g = solve_layers(model, hw, ctx, kv, parallel)
        sc = scenario(model, hw, ctx, kv, parallel, "layers", gpu_frac=g)
        total_ok = sc["fits_ram"]
        add(sc, "Débordement par couches (Ollama)" if total_ok else "Ne tient pas", "%d %% des couches en mémoire vidéo" % round(g * 100))
        out["verdict"] = "couches" if total_ok else "trop"
        out["recommended"] = sc["id"] if total_ok else None
        if total_ok:
            out["notes"].append("Ce modèle n'est pas à experts : le débordement par couches ralentit d'autant plus que la part en mémoire système est grande. "
                                "Une quantification plus légère (Q4_K_M au lieu de Q5 ou Q6) ou un modèle plus petit vaut souvent mieux.")
        else:
            out["notes"].append("Même avec la mémoire système, le modèle ne tient pas : choisissez une quantification plus légère ou ajoutez de la mémoire.")
    if not out["kv_known"]:
        out["notes"].append("La forme du modèle (couches, têtes) n'est pas connue : le cache de contexte est estimé grossièrement.")
    if not hw.get("gpu_eff"):
        out["notes"].append("Carte non reconnue : vitesse non estimée. Mesurez le débit d'un modèle qui tient en mémoire vidéo pour calibrer.")
    return out


def measured_tps(rows, model, now, span=7 * 86400, norm=lambda x: x):
    """Débit mesuré d'un modèle d'après les requêtes récentes : médiane des jetons/s (n >= 3 requêtes de 30 jetons ou plus). None sinon.
    norm : normalisation des noms (« gemma4:12b » et « gemma4:12b » écrits différemment)."""
    want = norm(model)
    vals = sorted(r["tps"] for r in rows if norm(r.get("model")) == want and now - float(r.get("ts") or 0) <= span and r.get("tps") and (r.get("out_tok") or 0) >= 30 and r.get("status") == 200)
    if len(vals) < 3:
        return None
    return round(vals[len(vals) // 2], 1)


def candidate_from_hf(repo, quant_size, arch="", tags=(), ctx_max=None):
    """Forme sommaire d'un modèle Hugging Face (non installé) : seules la taille et l'hypothèse « à experts » sont connues."""
    moe = looks_moe(repo, arch, tags)
    return {"name": repo, "weights": int(quant_size), "layers": 48, "kv_elems": None, "max_ctx": ctx_max, "moe": bool(moe), "experts": None, "used": None,
            "expert_bytes": int(quant_size * 0.85) if moe else 0, "arch": arch, "params": None, "moe_layers": 48, "guess": True, "moe_certain": False}
