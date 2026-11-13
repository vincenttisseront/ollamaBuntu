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
    for g in s.get("gpu_power") or []:
        lvl = str(g.get("level") or "")
        who = g.get("name") or g.get("card") or "carte"
        if lvl == "low":
            out.append({"id": "gpu_power:" + str(g.get("card")), "state": "warn", "fix": "amd_power",
                        "text": "%s est bridée (niveau de puissance « low ») : les fréquences restent basses et le débit s'effondre. « high » fixe les fréquences maximales." % who})
        elif lvl == "auto":
            out.append({"id": "gpu_power:" + str(g.get("card")), "state": "info", "fix": "amd_power",
                        "text": "%s gère ses fréquences automatiquement : elle met un instant à monter en puissance au premier jeton après une pause. « high » les fixe au maximum (plus de bruit et de consommation au repos)." % who})
        elif lvl == "high":
            out.append({"id": "gpu_power:" + str(g.get("card")), "state": "ok", "fix": "", "text": "%s : fréquences maximales fixées." % who})
    rb = s.get("rebar")
    if rb and rb.get("checked"):
        if rb.get("enabled"):
            out.append({"id": "rebar", "state": "ok", "fix": "", "text": "Resizable BAR actif (fenêtre de %s Go sur la carte)." % rb.get("bar_gb")})
        else:
            out.append({"id": "rebar", "state": "info", "fix": "",
                        "text": "Resizable BAR semble désactivé (fenêtre de %s Go pour %s Go de mémoire vidéo). À activer dans le BIOS (« Above 4G Decoding » puis « Resizable BAR ») : "
                                "chargement des modèles et échanges avec la mémoire système plus rapides." % (rb.get("bar_gb"), rb.get("vram_gb"))})
    mm = s.get("memory")
    if mm and mm.get("dimms"):
        if mm["dimms"] == 1:
            out.append({"id": "mem_channels", "state": "warn", "fix": "",
                        "text": "Une seule barrette de mémoire : canal simple, soit environ la moitié du débit d'un double canal. C'est ce débit qui limite un modèle débordé ou ses experts en mémoire système."})
        rated, conf = mm.get("rated"), mm.get("configured")
        if rated and conf and conf < rated * 0.9:
            out.append({"id": "mem_speed", "state": "warn", "fix": "",
                        "text": "La mémoire tourne à %d MT/s alors que ses barrettes sont prévues pour %d MT/s : profil XMP / EXPO désactivé dans le BIOS. Le débit de la mémoire système en dépend directement." % (conf, rated)})
        elif rated and conf:
            out.append({"id": "mem_speed", "state": "ok", "fix": "", "text": "Mémoire à %d MT/s (%d barrette(s))." % (conf, mm["dimms"])})
    for l in s.get("pcie") or []:
        if l.get("width") and l.get("max_width") and l["width"] < l["max_width"]:
            out.append({"id": "pcie:" + str(l.get("card")), "state": "warn", "fix": "",
                        "text": "%s est en PCIe x%d alors que x%d est possible : fente partagée, riser ou câble limitant. Le chargement des modèles et le débordement en pâtissent." % (l.get("name") or l.get("card"), l["width"], l["max_width"])})
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


# ------------------------------------------------------- préchauffage prédictif ---
def hours_add(store, reqs, keep_days=28):
    """Compte les requêtes par modèle, jour et heure locale : {modèle: {'AAAA-MM-JJ': [24 compteurs]}}. Seuls des compteurs sont gardés
    (aucun texte, aucun client). `reqs` : lignes du journal des requêtes ({ts, model, status}). Les jours trop anciens sont retirés."""
    for r in reqs:
        ts, m = r.get("ts"), r.get("model")
        if not ts or not m or (r.get("status") or 200) >= 400 or r.get("cached"):
            continue
        lt = time.localtime(ts)
        day = "%04d-%02d-%02d" % (lt.tm_year, lt.tm_mon, lt.tm_mday)
        store.setdefault(m, {}).setdefault(day, [0] * 24)[lt.tm_hour] += 1
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - keep_days * 86400))
    for m in list(store):
        for day in [d for d in store[m] if d < cutoff]:
            del store[m][day]
        if not store[m]:
            del store[m]
    return store


def predict_clean(d):
    d = d if isinstance(d, dict) else {}
    out = {"enabled": d.get("enabled") is True, "lead": 10, "max_models": 2, "min_days": 3}
    for k, lo, hi, label in (("lead", 2, 30, "avance (minutes)"), ("max_models", 1, 4, "nombre de modèles"), ("min_days", 2, 14, "jours minimum")):
        if k in d:
            try:
                v = int(d[k])
            except (TypeError, ValueError):
                raise ValueError("valeur invalide : %s" % label)
            if not lo <= v <= hi:
                raise ValueError("%s hors limites (%d à %d)" % (label, lo, hi))
            out[k] = v
    return out


def warm_predict(store, lt, loaded=(), cfg=None, window_days=14, min_ratio=0.5, preview=False):
    """Modèles à charger maintenant parce qu'ils sont habituellement demandés dans l'heure qui vient.
    On regarde, pour les jours du même type (semaine ou week-end) des `window_days` derniers jours où le serveur a servi des demandes,
    ceux où le modèle a été utilisé pendant l'heure visée. lt : time.struct_time local. Retourne [{model, hits, days, hour}] (les plus réguliers d'abord)."""
    cfg = predict_clean(cfg or {"enabled": True})
    if lt.tm_min < 60 - cfg["lead"] and not preview:   # aperçu : l'heure suivante, quelle que soit la minute
        return []
    target_ts = time.mktime(lt) + 3600
    tl = time.localtime(target_ts)
    hour, weekend = tl.tm_hour, tl.tm_wday >= 5
    tday = "%04d-%02d-%02d" % (tl.tm_year, tl.tm_mon, tl.tm_mday)
    lo = time.strftime("%Y-%m-%d", time.localtime(target_ts - window_days * 86400))
    kind = lambda day: time.strptime(day, "%Y-%m-%d").tm_wday >= 5
    active = set()
    for days in store.values():
        for day, hrs in days.items():
            if lo <= day < tday and kind(day) == weekend and sum(hrs):
                active.add(day)
    if len(active) < cfg["min_days"]:
        return []
    out = []
    loaded = {str(x) for x in loaded}
    for m, days in store.items():
        if m in loaded:
            continue
        hits = sum(1 for day in active if (days.get(day) or [0] * 24)[hour] > 0)
        if hits >= cfg["min_days"] and hits >= min_ratio * len(active):
            out.append({"model": m, "hits": hits, "days": len(active), "hour": hour})
    out.sort(key=lambda x: (-x["hits"], x["model"]))
    return out[:cfg["max_models"]]


# ------------------------------------------------------------ mesure continue ---
def bench_auto_clean(d):
    d = d if isinstance(d, dict) else {}
    out = {"enabled": d.get("enabled") is True, "at": "03:30", "models": [], "tolerance": 15, "recalibrate": d.get("recalibrate", True) is not False}
    if "at" in d:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(d["at"])):
            raise ValueError("heure invalide (HH:MM)")
        out["at"] = str(d["at"])
    if "tolerance" in d:
        try:
            t = int(d["tolerance"])
        except (TypeError, ValueError):
            raise ValueError("tolérance invalide")
        if not 5 <= t <= 60:
            raise ValueError("tolérance hors limites (5 à 60 %)")
        out["tolerance"] = t
    name = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    out["models"] = [m for m in dict.fromkeys(str(x).strip() for x in (d.get("models") or [])) if name.match(m)][:4]
    return out


def bench_auto_due(cfg, lt, last):
    """True quand l'heure programmée est atteinte (une fois par jour). last : {'AAAA-MM-JJ': True}, nettoyé au passage."""
    if not cfg.get("enabled"):
        return False
    today = "%04d-%02d-%02d" % (lt.tm_year, lt.tm_mon, lt.tm_mday)
    for k in [k for k in last if k != today]:
        last.pop(k)
    if cfg["at"] == "%02d:%02d" % (lt.tm_hour, lt.tm_min) and today not in last:
        last[today] = True
        return True
    return False


def _same_cfg(a, b):
    return all((a.get("cfg") or {}).get(k) == (b.get("cfg") or {}).get(k) for k in ("kv", "fa", "parallel", "ctx"))


def bench_baseline(history, entry, n=5):
    """Débit habituel du modèle : médiane des `n` mesures précédentes faites avec les mêmes réglages (au moins 2), sinon None."""
    xs = [h["tps"] for h in history if h.get("model") == entry["model"] and h.get("tps") and _same_cfg(h, entry)][-n:]
    if len(xs) < 2:
        return None
    xs.sort()
    return xs[len(xs) // 2]


def bench_regression(history, entry, tolerance=15):
    """Baisse de débit par rapport à l'habituel : None ou {baseline, current, pct}."""
    base = bench_baseline(history, entry)
    if not base or not entry.get("tps"):
        return None
    pct = round(100.0 * (entry["tps"] - base) / base, 1)
    return {"baseline": base, "current": entry["tps"], "pct": pct} if pct <= -tolerance else None


def diagnose(entry, prev):
    """Causes probables d'une baisse de débit, d'après ce qui a changé depuis la mesure précédente. Liste de phrases (vide si rien de net)."""
    hints = []
    prev = prev or {}
    vp, pv = entry.get("vram_pct"), prev.get("vram_pct")
    if vp is not None and vp < 100 and (pv is None or vp < pv - 3):
        hints.append("Le modèle est maintenant à %d %% en mémoire vidéo%s : une partie déborde sur le processeur (autre modèle chargé, cache de contexte plus grand, pilote qui réserve plus de mémoire)." %
                     (vp, " (contre %d %%)" % pv if pv is not None else ""))
    sysn, sysp_ = entry.get("sys") or {}, prev.get("sys") or {}
    t = sysn.get("gpu_temp")
    if t is not None and t >= 83:
        hints.append("La carte graphique est à %d °C : bridage thermique probable (poussière, ventilation, boîtier)." % t)
    for key, label in (("kernel", "Le noyau"), ("ollama", "Ollama"), ("driver", "Le pilote graphique")):
        if sysn.get(key) and sysp_.get(key) and sysn[key] != sysp_[key]:
            hints.append("%s a changé depuis la mesure précédente (%s -> %s)." % (label, sysp_[key], sysn[key]))
    if prev and not _same_cfg(entry, prev):
        hints.append("Les réglages d'Ollama ne sont plus les mêmes que lors de la mesure précédente.")
    if entry.get("ram_total") and entry.get("ram_used") and entry["ram_used"] / entry["ram_total"] > 0.92:
        hints.append("La mémoire vive est presque pleine (%d %%) : le système peut pousser des pages vers le disque." % round(100.0 * entry["ram_used"] / entry["ram_total"]))
    if prev.get("ttft_ms") and entry.get("ttft_ms") and entry["ttft_ms"] > 1.5 * prev["ttft_ms"] and not (entry.get("load_ms") or 0) > 1000:
        hints.append("Le délai avant le premier jeton a augmenté de %d %% sans rechargement du modèle." % round(100.0 * entry["ttft_ms"] / prev["ttft_ms"] - 100))
    return hints


# ---------------------------------------------------------- parallélisme adaptatif ---
def concurrency_profile(rows, now, span=86400):
    """Chevauchement des requêtes terminées dans la période : {requests, peak, overlap_pct, solo_ttft, busy_ttft}.
    Une requête « chevauchée » en a croisé une autre. rows : lignes du journal ({ts, ms, ttft_ms, status, cached})."""
    ev = [(r["ts"], r["ts"] + (r.get("ms") or 0) / 1000.0, r.get("ttft_ms")) for r in rows
          if r.get("ts") and r["ts"] >= now - span and (r.get("status") or 200) < 400 and not r.get("cached") and r.get("ms") and r.get("instance") != "-"]
    ev.sort()
    if not ev:
        return {"requests": 0, "peak": 0, "overlap_pct": 0, "solo_ttft": None, "busy_ttft": None}
    points = sorted([(a, 1) for a, _b, _t in ev] + [(b, -1) for _a, b, _t in ev], key=lambda p: (p[0], p[1]))
    cur = peak = 0
    for _t, d in points:
        cur += d
        peak = max(peak, cur)
    overlapped, solo, busy = 0, [], []
    end = 0.0
    for i, (a, b, t) in enumerate(ev):
        nxt = ev[i + 1][0] if i + 1 < len(ev) else None
        crossed = a < end or (nxt is not None and nxt < b)
        end = max(end, b)
        if crossed:
            overlapped += 1
            if t:
                busy.append(t)
        elif t:
            solo.append(t)
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
    return {"requests": len(ev), "peak": peak, "overlap_pct": round(100.0 * overlapped / len(ev)), "solo_ttft": med(solo), "busy_ttft": med(busy)}


def parallel_clean(d):
    d = d if isinstance(d, dict) else {}
    return {"mode": d.get("mode") if d.get("mode") in ("off", "suggest", "auto") else "suggest"}


def parallel_advice(profile, parallel, headroom, slot_bytes, max_par=4, min_requests=20):
    """Nombre de requêtes parallèles conseillé : None (rien à changer) ou {to, text, why}.
    headroom : mémoire vidéo libre (octets) ; slot_bytes : cache de contexte d'une requête de plus (octets, estimé)."""
    par = max(1, int(parallel or 1))
    if profile["requests"] < min_requests:
        return None
    if profile["overlap_pct"] >= 15 and par < min(profile["peak"], max_par):
        if slot_bytes and headroom is not None and headroom < slot_bytes * 1.25:
            return {"to": None, "why": "memory", "text": "%d %% des demandes se chevauchent (jusqu'à %d à la fois) mais la mémoire vidéo libre (%.1f Go) ne permet pas un emplacement de plus (%.1f Go de cache)." %
                    (profile["overlap_pct"], profile["peak"], headroom / 1024 ** 3, slot_bytes / 1024 ** 3)}
        wait = ""
        if profile.get("busy_ttft") and profile.get("solo_ttft") and profile["busy_ttft"] > 1.5 * profile["solo_ttft"]:
            wait = " ; le délai avant le premier jeton est de %d ms quand elles se chevauchent contre %d ms seules" % (profile["busy_ttft"], profile["solo_ttft"])
        return {"to": par + 1, "why": "overlap", "text": "%d %% des demandes se chevauchent (jusqu'à %d à la fois)%s : passer de %d à %d requêtes en parallèle." %
                (profile["overlap_pct"], profile["peak"], wait, par, par + 1)}
    if par > 1 and profile["peak"] <= 1:
        return {"to": par - 1, "why": "unused", "text": "Aucune demande ne s'est chevauchée sur la période alors que %d emplacements sont réservés : en retirer un libère %.1f Go de mémoire vidéo." %
                (par, (slot_bytes or 0) / 1024 ** 3)}
    return None
