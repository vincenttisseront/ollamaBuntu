#!/usr/bin/env python3
"""OllamaBuntu - performances : mesure de débit, profils de réglages, contrôles système, préchauffage, garde-fou de débit.
Fonctions pures (aucun accès disque, réseau ni commande) : testables hors de la console."""
import re
import time

BENCH_PROMPT = ("Explique en une dizaine de phrases, pour un lecteur non spécialiste, comment fonctionne une pompe à chaleur, "
                "puis donne trois conseils pour réduire sa consommation d'énergie.")
BENCH_TOKENS = 128
KV_TYPES = ("f16", "q8_0", "q4_0")

# Réglages d'Ollama par profil. Seules ces clés sont modifiées ; le reste de la configuration est conservé.
PROFILES = {
    "latence": {
        "label": "Latence minimale",
        "help": "Réponses les plus rapides pour peu d'utilisateurs : modèle gardé en mémoire, une seule requête par modèle, cache en pleine précision.",
        "env": {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "f16", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_KEEP_ALIVE": "24h"},
    },
    "equilibre": {
        "label": "Équilibré",
        "help": "Bon compromis débit / mémoire : cache réduit de moitié, deux requêtes en parallèle, modèles déchargés après 30 minutes.",
        "env": {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_NUM_PARALLEL": "2", "OLLAMA_KEEP_ALIVE": "30m", "OLLAMA_MAX_LOADED_MODELS": "2"},
    },
    "econome": {
        "label": "Économe en mémoire",
        "help": "Libère le plus de RAM et de mémoire vidéo : cache divisé par quatre, un seul modèle chargé, déchargement rapide, contexte de 4 096 jetons.",
        "env": {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q4_0", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_KEEP_ALIVE": "2m", "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_CONTEXT_LENGTH": "4096"},
    },
}


def _val(env, k):
    return str(env.get(k) or "").strip()


def normalize_env(changes, env):
    """Cohérence des réglages : un cache quantifié exige la flash attention (sinon Ollama l'ignore sans prévenir).
    Retourne les changements complétés ; lève ValueError si le type de cache est inconnu."""
    out = dict(changes)
    kv = out.get("OLLAMA_KV_CACHE_TYPE")
    if kv is not None:
        if kv not in KV_TYPES and kv != "":
            raise ValueError("type de cache inconnu (%s)" % ", ".join(KV_TYPES))
        if kv in ("q8_0", "q4_0") and _val(dict(env, **out), "OLLAMA_FLASH_ATTENTION") != "1":
            out["OLLAMA_FLASH_ATTENTION"] = "1"
    if out.get("OLLAMA_FLASH_ATTENTION") == "0" and _val(dict(env, **out), "OLLAMA_KV_CACHE_TYPE") in ("q8_0", "q4_0"):
        raise ValueError("la flash attention est nécessaire au cache quantifié : repassez d'abord le cache en f16")
    return out


def profile_diff(name, env):
    """Changements qu'appliquerait un profil : [{key, from, to}] (clés déjà à la bonne valeur omises)."""
    p = PROFILES.get(name)
    if not p:
        raise ValueError("profil inconnu")
    return [{"key": k, "from": _val(env, k), "to": v} for k, v in p["env"].items() if _val(env, k) != v]


def detect_profile(env):
    for name, p in PROFILES.items():
        if all(_val(env, k) == v for k, v in p["env"].items()):
            return name
    return ""


# ---------------------------------------------------------------- mesure de débit ---
def bench_result(model, gen, ps_entry=None, mem=None, env=None, now=None):
    """Résultat d'une génération « stream: false » d'Ollama : jetons/s, délai avant le 1er jeton, part en mémoire vidéo.
    gen : réponse de /api/generate ; ps_entry : ligne du modèle dans /api/ps ; mem : {used, total} (RAM, octets)."""
    ev, evd = int(gen.get("eval_count") or 0), int(gen.get("eval_duration") or 0)
    pe, ped = int(gen.get("prompt_eval_count") or 0), int(gen.get("prompt_eval_duration") or 0)
    load = int(gen.get("load_duration") or 0)
    if not ev or not evd:
        raise ValueError("Ollama n'a renvoyé aucune mesure de génération")
    size, vram = int((ps_entry or {}).get("size") or 0), int((ps_entry or {}).get("size_vram") or 0)
    env = env or {}
    return {"t": int(now if now is not None else time.time()), "model": model, "tps": round(ev * 1e9 / evd, 1),
            "prompt_tps": round(pe * 1e9 / ped, 1) if pe and ped else None,
            "ttft_ms": round((load + ped) / 1e6), "load_ms": round(load / 1e6), "tokens": ev,
            "vram_pct": round(100.0 * vram / size) if size else None, "size": size or None,
            "ram_used": (mem or {}).get("used"), "ram_total": (mem or {}).get("total"),
            "cfg": {"kv": _val(env, "OLLAMA_KV_CACHE_TYPE") or "f16", "fa": _val(env, "OLLAMA_FLASH_ATTENTION") == "1",
                    "parallel": _val(env, "OLLAMA_NUM_PARALLEL") or "auto", "ctx": _val(env, "OLLAMA_CONTEXT_LENGTH") or "auto"}}


def bench_median(runs):
    """Série de mesures successives : médiane du débit et du délai (la 1re, qui charge le modèle, pèse peu sur le résultat)."""
    if not runs:
        raise ValueError("aucune mesure")
    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        return xs[len(xs) // 2] if xs else None
    best = dict(runs[-1])
    best.update(tps=med([r["tps"] for r in runs]), ttft_ms=med([r["ttft_ms"] for r in runs]), runs=len(runs))
    best["load_ms"] = max(r.get("load_ms") or 0 for r in runs)
    return best


def bench_compare(history, entry):
    """Écart avec la mesure précédente du même modèle : {tps_pct, ttft_pct, previous} ou None."""
    prev = next((h for h in reversed(history) if h.get("model") == entry["model"]), None)
    if not prev or not prev.get("tps"):
        return None
    pct = lambda a, b: round(100.0 * (a - b) / b, 1) if a is not None and b else None
    return {"tps_pct": pct(entry["tps"], prev["tps"]), "ttft_pct": pct(entry.get("ttft_ms"), prev.get("ttft_ms")), "previous": prev.get("t")}


# ----------------------------------------------------------- contrôles système ---
def sys_checks(s):
    """s : swappiness (int|None), governors [str] (un par cœur, vide si inconnu), mem_total, swap_total (octets), zram (bool),
    webui {deployed, limit_mb, rss_mb}, thp (str). Retourne [{id, state: ok|warn|info, text, fix}] ; fix : identifiant d'action ou ""."""
    out = []
    sw = s.get("swappiness")
    if sw is not None:
        if sw > 20:
            out.append({"id": "swappiness", "state": "warn", "fix": "swappiness",
                        "text": "vm.swappiness vaut %d : le système pousse des pages vers le disque trop tôt, ce qui ralentit Ollama. 10 est recommandé." % sw})
        else:
            out.append({"id": "swappiness", "state": "ok", "fix": "", "text": "vm.swappiness = %d." % sw})
    govs = sorted(set(g for g in s.get("governors") or [] if g))
    if govs:
        if govs == ["performance"]:
            out.append({"id": "governor", "state": "ok", "fix": "", "text": "Fréquence du processeur : performance."})
        else:
            out.append({"id": "governor", "state": "warn", "fix": "governor",
                        "text": "Fréquence du processeur en mode « %s » : la montée en charge ajoute de la latence aux premiers jetons. « performance » est recommandé sur un serveur." % ", ".join(govs)})
    mem, swap = int(s.get("mem_total") or 0), int(s.get("swap_total") or 0)
    if mem and mem <= 16 * 1024 ** 3 and not s.get("zram"):
        out.append({"id": "zram", "state": "info", "fix": "",
                    "text": "Mémoire vive limitée (%d Go) et pas de zram : un swap compressé en mémoire (paquet zram-tools) absorbe les pointes sans solliciter le disque." % round(mem / 1024 ** 3)})
    elif s.get("zram"):
        out.append({"id": "zram", "state": "ok", "fix": "", "text": "Swap compressé (zram) actif."})
    if mem and swap > mem and not s.get("zram"):
        out.append({"id": "swap_big", "state": "info", "fix": "", "text": "Le swap (%d Go) dépasse la mémoire vive : un modèle qui y déborde deviendrait inutilisable (quelques jetons/s)." % round(swap / 1024 ** 3)})
    w = s.get("webui") or {}
    if w.get("deployed"):
        if not w.get("limit_mb") and mem >= 4 * 1024 ** 3:
            out.append({"id": "webui_mem", "state": "warn" if (w.get("rss_mb") or 0) > 3072 else "info", "fix": "webui_mem",
                        "text": "Open WebUI n'a pas de plafond de mémoire%s. Un plafond de 2 Go protège les modèles d'un emballement." % (" (il utilise %d Mo)" % w["rss_mb"] if w.get("rss_mb") else "")})
        elif w.get("limit_mb"):
            out.append({"id": "webui_mem", "state": "ok", "fix": "", "text": "Open WebUI plafonné à %d Mo." % w["limit_mb"]})
    return out


def parse_limit(value):
    """« 2g » / « 1536m » → mégaoctets ; ValueError si hors de 512 Mo à 64 Go."""
    m = re.fullmatch(r"(\d{1,4})([mg])", str(value or "").strip().lower())
    if not m:
        raise ValueError("plafond invalide (ex. 2g ou 1536m)")
    mb = int(m.group(1)) * (1024 if m.group(2) == "g" else 1)
    if not 512 <= mb <= 65536:
        raise ValueError("plafond hors limites (512 Mo à 64 Go)")
    return mb


# ------------------------------------------------------------------ préchauffage ---
def warmup_clean(cfg):
    """Réglage de préchauffage validé : {boot: [modèles], times: [{at: 'HH:MM', models: [...], days: [0-6]}]} (lundi = 0)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    name = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    clean = lambda ms: [m for m in dict.fromkeys(str(x).strip() for x in (ms or [])) if name.match(m)][:6]
    times = []
    for t in (cfg.get("times") or [])[:8]:
        at = str((t or {}).get("at", ""))
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
            raise ValueError("heure invalide (HH:MM)")
        days = sorted({int(d) for d in (t.get("days") or range(7)) if str(d).isdigit() and 0 <= int(d) <= 6}) or list(range(7))
        if clean(t.get("models")):
            times.append({"at": at, "models": clean(t.get("models")), "days": days})
    return {"boot": clean(cfg.get("boot")), "times": times}


def warmup_due(cfg, lt, last):
    """Modèles à charger maintenant. lt : time.struct_time local ; last : {'HH:MM@AAAA-MM-JJ': True} des créneaux déjà joués (mis à jour)."""
    due, today = [], "%04d-%02d-%02d" % (lt.tm_year, lt.tm_mon, lt.tm_mday)
    now = "%02d:%02d" % (lt.tm_hour, lt.tm_min)
    for t in cfg.get("times") or []:
        key = "%s@%s" % (t["at"], today)
        if t["at"] == now and lt.tm_wday in t.get("days", range(7)) and key not in last:
            last[key] = True
            due += [m for m in t["models"] if m not in due]
    for k in [k for k in last if not k.endswith(today)]:
        last.pop(k)
    return due


# --------------------------------------------------------- garde-fou de débit ---
def baseline_tps(samples, now, recent=600, span=86400):
    """Débit habituel : médiane des échantillons de la journée précédant les `recent` dernières secondes (>= 5 mesures)."""
    xs = sorted(s["tps"] for s in samples if s.get("tps") and now - span <= s.get("t", 0) < now - recent)
    return xs[len(xs) // 2] if len(xs) >= 5 else None


def next_fix(env, ctx_min=4096):
    """Réglage le moins coûteux à resserrer pour gagner en débit, ou None. Un seul pas à la fois."""
    if _val(env, "OLLAMA_FLASH_ATTENTION") != "1":
        return {"changes": {"OLLAMA_FLASH_ATTENTION": "1"}, "text": "activer la flash attention"}
    kv = _val(env, "OLLAMA_KV_CACHE_TYPE") or "f16"
    if kv == "f16":
        return {"changes": {"OLLAMA_KV_CACHE_TYPE": "q8_0"}, "text": "passer le cache en q8_0 (moitié moins de mémoire, qualité quasi identique)"}
    p = _val(env, "OLLAMA_NUM_PARALLEL")
    par = int(p) if p.isdigit() else 1
    if par > 1:
        return {"changes": {"OLLAMA_NUM_PARALLEL": str(par - 1)}, "text": "réduire le parallélisme à %d" % (par - 1)}
    ctx = _val(env, "OLLAMA_CONTEXT_LENGTH")
    if ctx.isdigit() and int(ctx) // 2 >= ctx_min:
        return {"changes": {"OLLAMA_CONTEXT_LENGTH": str(int(ctx) // 2)}, "text": "réduire le contexte par défaut à %d jetons" % (int(ctx) // 2)}
    if kv == "q8_0":
        return {"changes": {"OLLAMA_KV_CACHE_TYPE": "q4_0"}, "text": "passer le cache en q4_0 (mémoire divisée par quatre, légère perte de qualité sur les longs contextes)"}
    return None


def perf_guard(samples, now, offload, env, drop_pct=50, min_requests=3):
    """Chute de débit : le débit récent est inférieur à `drop_pct` % de l'habituel, ou un modèle déborde sur le processeur.
    Retourne None ou {kind: offload|slow, baseline, current, ratio, fix: {changes, text}|None, text}."""
    recent = [s for s in samples if s.get("tps") and s.get("t", 0) >= now - 600]
    reqs = sum(s.get("req") or 0 for s in recent)
    cur = round(sum(s["tps"] for s in recent) / len(recent), 1) if recent else None
    base = baseline_tps(samples, now)
    drop = bool(cur and base and reqs >= min_requests and cur < base * drop_pct / 100.0)
    if not offload and not drop:
        return None
    fix = next_fix(env)
    kind = "offload" if offload else "slow"
    what = ("%s déborde sur le processeur" % offload[0]["name"]) if offload else "débit de %s jetons/s au lieu de %s d'habitude" % (cur, base)
    return {"kind": kind, "baseline": base, "current": cur, "ratio": round(cur / base, 2) if cur and base else None, "fix": fix,
            "text": "%s%s" % (what[0].upper() + what[1:], " — suggestion : " + fix["text"] if fix else " — aucun réglage simple à resserrer ; essayez un modèle plus petit")}
