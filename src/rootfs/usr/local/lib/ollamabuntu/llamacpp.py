#!/usr/bin/env python3
"""OllamaBuntu - moteur llama.cpp pour les modèles à experts (MoE) trop gros pour la mémoire vidéo.
Fonctions pures (aucun accès réseau ni processus) partagées par le démon `llama-engine.py` et par la console :
- retrouver le fichier GGUF d'un modèle installé dans Ollama (manifeste -> blob) ;
- valider un moteur et construire la ligne de commande de llama-server, d'après ce que CETTE version sait faire (--help) ;
- traduire les requêtes Ollama (/api/chat, /api/generate) vers l'API compatible OpenAI de llama-server, et ses réponses (JSON ou flux SSE) vers Ollama ;
- choisir le bon fichier parmi les versions publiées de llama.cpp.
Pourquoi un moteur à part : Ollama ne sait pas laisser les experts d'un modèle MoE en mémoire système tout en gardant l'attention et le cache
sur la carte (option --n-cpu-moe de llama.cpp). Les modèles restent installés dans Ollama : on réutilise leurs fichiers, sans les dupliquer."""
import json
import os
import re
import shlex
import time

ENGINE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")
KV_TYPES = ("f16", "q8_0", "q4_0")
MODEL_MEDIA = "application/vnd.ollama.image.model"
DENY_EXTRA = {"-m", "--model", "--host", "--port", "--api-key", "--api-key-file", "--ssl-key-file", "--ssl-cert-file", "--path", "--log-file", "--model-url", "-mu",
              "-hf", "--hf-repo", "-hff", "--hf-file", "-hft", "--hf-token", "--lora", "--lora-scaled", "--control-vector", "--webui-config", "--webui-config-file",
              "--api-prefix", "--slot-save-path", "--media-path", "--tools", "--mmproj", "-mm"}
EXTRA_TOKEN = re.compile(r"^[-A-Za-z0-9_.,:/=+*|\\()\[\]^]{1,120}$")   # ni $ ni ; ni & ni redirection : jamais passé à un interpréteur, mais on ne laisse rien passer
PORT_RANGE = (11600, 11699)           # démons moteurs (compatibles Ollama)
BACKEND_RANGE = (11700, 11799)        # llama-server lui-même (jamais joignable depuis le réseau)
DEFAULTS = {"ctx": 8192, "parallel": 1, "ngl": 999, "n_cpu_moe": None, "kv": "q8_0", "flash": True, "threads": 0, "idle_min": 15,
            "start_timeout": 300, "unload_ollama": True, "extra": "",
            # accélération : réutilisation des débuts d'invite déjà calculés, mémoire verrouillée, décodage spéculatif
            "cache_reuse": 0, "cache_ram": None, "mlock": False, "spec": "", "draft_model": "", "draft_max": 16, "draft_ngl": 999}
SPEC_MODES = ("", "draft", "ngram")   # « draft » : petit modèle brouillon ; « ngram » : motifs déjà vus dans la conversation, sans second modèle


# ------------------------------------------------------------------ modèles installés dans Ollama
def parse_model_name(name):
    """(hôte, espace, modèle, étiquette) comme le fait Ollama pour ranger ses manifestes."""
    n, tag = str(name), "latest"
    if ":" in n.split("/")[-1]:
        n, tag = n.rsplit(":", 1)
    parts = n.split("/")
    if len(parts) == 1:
        return "registry.ollama.ai", "library", parts[0], tag
    if len(parts) == 2:
        return "registry.ollama.ai", parts[0], parts[1], tag
    return parts[0], "/".join(parts[1:-1]), parts[-1], tag


def manifest_candidates(models_dir, name):
    """Chemins où Ollama peut avoir rangé le manifeste de ce modèle (deux dispositions selon la version)."""
    host, ns, model, tag = parse_model_name(name)
    hosts = [host] + (["ollama.com"] if host == "registry.ollama.ai" else [])
    return [os.path.join(models_dir, sub, h, ns, model, tag) for sub in ("manifests-v2", "manifests") for h in hosts]


def blob_of(manifest, models_dir):
    """Chemin du fichier GGUF d'un manifeste Ollama, ou None (poids absents, empreinte invalide)."""
    for layer in (manifest or {}).get("layers") or []:
        if layer.get("mediaType") == MODEL_MEDIA:
            digest = str(layer.get("digest") or "")
            if re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                return os.path.join(models_dir, "blobs", digest.replace(":", "-"))
    return None


def find_gguf(models_dir, name, read=None):
    """Fichier GGUF du modèle `name` installé. read(path) -> texte ou None (par défaut : lecture du disque). Retourne (chemin, erreur)."""
    def default_read(p):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None
    read = read or default_read
    for p in manifest_candidates(models_dir, name):
        raw = read(p)
        if raw is None:
            continue
        try:
            blob = blob_of(json.loads(raw), models_dir)
        except ValueError:
            continue
        if blob:
            return blob, None
        return None, "le manifeste de « %s » ne contient pas de fichier de modèle" % name
    return None, "modèle « %s » non installé dans Ollama" % name


# ------------------------------------------------------------------ réglages d'un moteur
def extra_clean(text):
    """Options supplémentaires de llama-server : mots simples, jamais celles qui ouvrent le réseau, des fichiers ou un autre modèle."""
    text = str(text or "").strip()
    if not text:
        return ""
    if len(text) > 300:
        raise ValueError("options supplémentaires : 300 caractères au plus")
    try:
        toks = shlex.split(text)
    except ValueError:
        raise ValueError("options supplémentaires : guillemets non fermés")
    for t in toks:
        if not EXTRA_TOKEN.match(t):
            raise ValueError("options supplémentaires : caractères non autorisés dans « %s »" % t[:30])
        flag = t.split("=", 1)[0]
        if flag in DENY_EXTRA or flag.startswith(("--ssl", "--hf", "--model", "--lora")):
            raise ValueError("option « %s » interdite : la console la gère elle-même ou elle ouvre l'accès au réseau ou aux fichiers" % flag)
    return " ".join(toks)


def config_clean(data, cur=None):
    """Valide un moteur (ValueError si invalide). Champs : id, model, port, backend_port, ctx, parallel, ngl, n_cpu_moe, kv, flash, threads, idle_min,
    start_timeout, unload_ollama, extra, cache_reuse, cache_ram, mlock, spec, draft_model, draft_max, draft_ngl. Les champs absents gardent leur valeur actuelle (ou celle par défaut)."""
    out = dict(DEFAULTS, **(cur or {}))
    data = data if isinstance(data, dict) else {}
    if "id" in data or "id" not in out:
        i = str(data.get("id") or "").strip()
        if not ENGINE_ID_RE.match(i):
            raise ValueError("identifiant du moteur : 1 à 24 caractères (lettres minuscules, chiffres, tiret)")
        out["id"] = i
    if "model" in data or "model" not in out:
        m = str(data.get("model") or "").strip()
        if not MODEL_NAME_RE.match(m):
            raise ValueError("nom de modèle invalide")
        out["model"] = m
    for k, lo, hi, label in (("ctx", 512, 1048576, "contexte : 512 à 1 048 576 jetons"), ("parallel", 1, 8, "requêtes parallèles : 1 à 8"),
                             ("ngl", 0, 999, "couches sur la carte : 0 à 999"), ("threads", 0, 256, "fils de calcul : 0 (automatique) à 256"),
                             ("idle_min", 0, 1440, "arrêt après inactivité : 0 (jamais) à 1440 minutes"), ("start_timeout", 30, 1800, "délai de démarrage : 30 à 1800 secondes")):
        if k in data:
            try:
                v = int(str(data[k]).strip())
            except (TypeError, ValueError):
                raise ValueError(label)
            if not lo <= v <= hi:
                raise ValueError(label)
            out[k] = v
    if "n_cpu_moe" in data:
        v = data["n_cpu_moe"]
        if v in (None, "", "null"):
            out["n_cpu_moe"] = None
        else:
            try:
                v = int(str(v).strip())
            except (TypeError, ValueError):
                raise ValueError("couches dont les experts vont en mémoire système : 0 à 512")
            if not 0 <= v <= 512:
                raise ValueError("couches dont les experts vont en mémoire système : 0 à 512")
            out["n_cpu_moe"] = v
    if "kv" in data:
        if data["kv"] not in KV_TYPES:
            raise ValueError("cache de contexte : f16, q8_0 ou q4_0")
        out["kv"] = data["kv"]
    for k in ("flash", "unload_ollama", "mlock"):
        if k in data:
            out[k] = bool(data[k])
    for k, lo, hi, label in (("cache_reuse", 0, 8192, "réutilisation du cache : 0 (désactivée) à 8192 jetons"), ("draft_max", 1, 64, "jetons proposés par le brouillon : 1 à 64"),
                             ("draft_ngl", 0, 999, "couches du brouillon sur la carte : 0 à 999")):
        if k in data:
            try:
                v = int(str(data[k]).strip())
            except (TypeError, ValueError):
                raise ValueError(label)
            if not lo <= v <= hi:
                raise ValueError(label)
            out[k] = v
    if "cache_ram" in data:
        v = data["cache_ram"]
        if v in (None, "", "null"):
            out["cache_ram"] = None
        else:
            try:
                v = int(str(v).strip())
            except (TypeError, ValueError):
                raise ValueError("mémoire du cache d'invites : 0 (désactivée) à 262144 Mo, vide = réglage de llama-server")
            if not 0 <= v <= 262144:
                raise ValueError("mémoire du cache d'invites : 0 (désactivée) à 262144 Mo, vide = réglage de llama-server")
            out["cache_ram"] = v
    if "spec" in data:
        if (data["spec"] or "") not in SPEC_MODES:
            raise ValueError("décodage spéculatif : désactivé, modèle brouillon ou motifs répétés")
        out["spec"] = data["spec"] or ""
    if "draft_model" in data:
        m = str(data["draft_model"] or "").strip()
        if m and not MODEL_NAME_RE.match(m):
            raise ValueError("nom du modèle brouillon invalide")
        out["draft_model"] = m
    if out["spec"] == "draft":
        if not out["draft_model"]:
            raise ValueError("décodage spéculatif : choisissez le modèle brouillon")
        if out["draft_model"] == out["model"]:
            raise ValueError("le modèle brouillon doit être plus petit que le modèle principal, pas le même")
    if "extra" in data:
        out["extra"] = extra_clean(data["extra"])
    if out["kv"] in ("q8_0", "q4_0") and not out["flash"]:
        raise ValueError("un cache de contexte quantifié exige la flash attention")
    for k, rng in (("port", PORT_RANGE), ("backend_port", BACKEND_RANGE)):
        if k in data:
            try:
                v = int(data[k])
            except (TypeError, ValueError):
                raise ValueError("port invalide")
            if not rng[0] <= v <= rng[1]:
                raise ValueError("port : %d à %d" % rng)
            out[k] = v
    return out


def free_ports(engines):
    """(port du démon, port de llama-server) libres pour un nouveau moteur."""
    used = {int(e.get("port") or 0) for e in engines} | {int(e.get("backend_port") or 0) for e in engines}
    pick = lambda rng: next(p for p in range(rng[0], rng[1] + 1) if p not in used)
    return pick(PORT_RANGE), pick(BACKEND_RANGE)


# ------------------------------------------------------------------ ce que cette version de llama-server sait faire
def detect_caps(help_text):
    """Options reconnues par ce llama-server d'après son --help. Les options changent d'une version à l'autre : on ne suppose rien."""
    t = help_text or ""
    return {"n_cpu_moe": "--n-cpu-moe" in t, "override_tensor": "--override-tensor" in t, "flash": "--flash-attn" in t,
            "flash_value": bool(re.search(r"--flash-attn\s*[\[{(]", t)), "cache_type": "--cache-type-k" in t, "jinja": "--jinja" in t,
            "parallel": "--parallel" in t, "threads": "--threads" in t, "no_webui": "--no-webui" in t, "ngl": "--n-gpu-layers" in t,
            "ctx": "--ctx-size" in t, "cache_reuse": "--cache-reuse" in t, "cache_ram": "--cache-ram" in t, "mlock": "--mlock" in t,
            "spec_type": "--spec-type" in t, "draft_model": "--model-draft" in t or bool(re.search(r"(^|\s)-md[,\s]", t)),
            "draft_max": "--draft-max" in t or "--draft-n" in t, "draft_ngl": "--n-gpu-layers-draft" in t or "--gpu-layers-draft" in t or bool(re.search(r"(^|\s)-ngld[,\s]", t))}


def moe_override(n):
    """Expression de --override-tensor qui garde en mémoire système les experts des n premières couches (pour une version sans --n-cpu-moe)."""
    layers = "|".join(str(i) for i in range(int(n)))
    return r"blk\.(%s)\.ffn_(up|down|gate)_exps\.=CPU" % layers


def build_args(cfg, caps, binary, gguf, backend_port=None, draft_gguf=None):
    """Ligne de commande de llama-server. Retourne (arguments, avertissements) : une option que cette version ne connaît pas est retirée et signalée."""
    warn, a = [], [binary, "-m", gguf, "--host", "127.0.0.1", "--port", str(backend_port or cfg["backend_port"])]
    par = max(1, int(cfg["parallel"]))
    a += ["-c", str(int(cfg["ctx"]) * par)]   # -c est le contexte TOTAL, partagé entre les requêtes parallèles
    if caps.get("parallel", True):
        a += ["-np", str(par)]
    elif par > 1:
        warn.append("cette version de llama-server ne sait pas traiter des requêtes en parallèle")
    if caps.get("ngl", True):
        a += ["-ngl", str(int(cfg["ngl"]))]
    if cfg.get("threads"):
        a += ["-t", str(int(cfg["threads"]))]
    n = cfg.get("n_cpu_moe")
    if n:
        if caps.get("n_cpu_moe"):
            a += ["--n-cpu-moe", str(int(n))]
        elif caps.get("override_tensor"):
            a += ["--override-tensor", moe_override(n)]
            warn.append("--n-cpu-moe inconnue de cette version : remplacée par --override-tensor")
        else:
            warn.append("cette version de llama-server ne sait pas placer les experts en mémoire système : le moteur ne servira à rien, mettez-la à jour")
    if cfg.get("flash"):
        if caps.get("flash_value"):
            a += ["--flash-attn", "on"]
        elif caps.get("flash"):
            a += ["--flash-attn"]
        else:
            warn.append("flash attention inconnue de cette version")
    if cfg.get("kv") != "f16":
        if caps.get("cache_type", True):
            a += ["--cache-type-k", cfg["kv"], "--cache-type-v", cfg["kv"]]
        else:
            warn.append("cache de contexte quantifié inconnu de cette version")
    if cfg.get("cache_reuse"):
        if caps.get("cache_reuse"):
            a += ["--cache-reuse", str(int(cfg["cache_reuse"]))]
        else:
            warn.append("réutilisation du cache inconnue de cette version de llama-server")
    if cfg.get("cache_ram") is not None:
        if caps.get("cache_ram"):
            a += ["--cache-ram", str(int(cfg["cache_ram"]))]
        else:
            warn.append("mémoire du cache d'invites inconnue de cette version de llama-server")
    if cfg.get("mlock"):
        if caps.get("mlock"):
            a += ["--mlock"]
        else:
            warn.append("verrouillage en mémoire inconnu de cette version de llama-server")
    spec = cfg.get("spec") or ""
    if spec == "draft":
        if not draft_gguf:
            warn.append("modèle brouillon introuvable : décodage spéculatif ignoré")
        elif not caps.get("draft_model"):
            warn.append("décodage spéculatif avec un modèle brouillon inconnu de cette version de llama-server : mettez-la à jour")
        else:
            a += ["--model-draft", draft_gguf]
            if caps.get("draft_max", True):
                a += ["--draft-max", str(int(cfg.get("draft_max") or 16))]
            if caps.get("draft_ngl", True):
                a += ["--n-gpu-layers-draft", str(int(cfg.get("draft_ngl", 999)))]
    elif spec == "ngram":
        if caps.get("spec_type"):
            a += ["--spec-type", "ngram-simple"]
            if caps.get("draft_max", True):
                a += ["--draft-max", str(int(cfg.get("draft_max") or 16))]
        else:
            warn.append("décodage spéculatif par motifs répétés inconnu de cette version de llama-server : mettez-la à jour")
    if caps.get("jinja"):
        a += ["--jinja"]   # gabarit de conversation du modèle (nécessaire aux outils et au raisonnement)
    if caps.get("no_webui"):
        a += ["--no-webui"]
    if cfg.get("extra"):
        a += shlex.split(cfg["extra"])
    return a, warn


# ------------------------------------------------------------------ traduction Ollama -> OpenAI (llama-server)
SAMPLING = ("temperature", "top_p", "top_k", "min_p", "seed", "repeat_penalty", "presence_penalty", "frequency_penalty", "mirostat", "mirostat_tau",
            "mirostat_eta", "typical_p", "repeat_last_n")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def sampling(options):
    """Paramètres d'échantillonnage d'Ollama -> champs de llama-server ; contexte et placement sont ceux du moteur, pas de la requête."""
    out, o = {}, options if isinstance(options, dict) else {}
    for k in SAMPLING:
        if _num(o.get(k)):
            out[k] = o[k]
    if _num(o.get("num_predict")) and o["num_predict"] > 0:
        out["max_tokens"] = int(o["num_predict"])
    stop = o.get("stop")
    if isinstance(stop, str):
        stop = [stop]
    if isinstance(stop, list) and all(isinstance(x, str) for x in stop) and stop:
        out["stop"] = stop[:16]
    return out


def to_openai_messages(messages):
    """Messages Ollama -> messages OpenAI. ValueError si la demande demande ce que le moteur ne sait pas faire (images)."""
    if not isinstance(messages, list) or not messages:
        raise ValueError("« messages » est obligatoire")
    out, pending, seq = [], [], 0
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant", "tool"):
            raise ValueError("message invalide (rôle : system, user, assistant ou tool)")
        if m.get("images"):
            raise ValueError("les images ne sont pas prises en charge par le moteur llama.cpp (modèle servi sans projecteur multimodal)")
        content = m.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ValueError("le contenu d'un message doit être du texte")
        msg = {"role": m["role"], "content": content}
        if m["role"] == "assistant" and isinstance(m.get("tool_calls"), list) and m["tool_calls"]:
            calls = []
            for c in m["tool_calls"]:
                fn = (c or {}).get("function") or {}
                seq += 1
                cid = "call_%d" % seq
                pending.append(cid)
                args = fn.get("arguments", {})
                calls.append({"id": cid, "type": "function", "function": {"name": str(fn.get("name") or ""), "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}})
            msg["tool_calls"] = calls
        if m["role"] == "tool":
            msg["tool_call_id"] = pending.pop(0) if pending else "call_0"
        out.append(msg)
    return out


def _response_format(fmt):
    if fmt == "json":
        return {"type": "json_object"}
    if isinstance(fmt, dict):
        return {"type": "json_schema", "json_schema": {"name": "sortie", "schema": fmt}}
    if fmt in (None, ""):
        return None
    raise ValueError("format : « json » ou un schéma JSON")


def _common(body, stream):
    out = sampling(body.get("options"))
    out["cache_prompt"] = True   # le début de l'invite déjà calculé (consigne système, historique) n'est pas recalculé à la demande suivante
    out["stream"] = bool(stream)
    if stream:
        out["stream_options"] = {"include_usage": True}
    rf = _response_format(body.get("format"))
    if rf:
        out["response_format"] = rf
    if body.get("think") is not None and isinstance(body["think"], bool):
        out["chat_template_kwargs"] = {"enable_thinking": body["think"]}
    return out


def chat_to_openai(body):
    """/api/chat d'Ollama -> corps de /v1/chat/completions. Le flux est actif par défaut, comme chez Ollama."""
    stream = body.get("stream") is not False
    out = _common(body, stream)
    out["messages"] = to_openai_messages(body.get("messages"))
    if isinstance(body.get("tools"), list) and body["tools"]:
        out["tools"] = body["tools"]
    return out, stream


def generate_to_openai(body):
    """/api/generate d'Ollama -> conversation d'un message (le modèle applique son gabarit). Pas de mode brut, de suffixe ni de contexte."""
    for k, label in (("raw", "mode brut"), ("suffix", "suffixe"), ("context", "contexte précédent"), ("template", "gabarit")):
        if body.get(k):
            raise ValueError("« %s » n'est pas pris en charge par le moteur llama.cpp (%s)" % (k, label))
    if body.get("images"):
        raise ValueError("les images ne sont pas prises en charge par le moteur llama.cpp")
    prompt = body.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("« prompt » est obligatoire")
    msgs = []
    if isinstance(body.get("system"), str) and body["system"]:
        msgs.append({"role": "system", "content": body["system"]})
    msgs.append({"role": "user", "content": prompt})
    stream = body.get("stream") is not False
    out = _common(body, stream)
    out["messages"] = msgs
    return out, stream


# ------------------------------------------------------------------ traduction OpenAI -> Ollama
def spec_counts(timings):
    """(jetons proposés par le brouillon, jetons acceptés) d'après les durées d'une réponse de llama-server ; (0, 0) si la version ne les donne pas."""
    t = timings if isinstance(timings, dict) else {}
    n, ok = t.get("draft_n"), t.get("draft_n_accepted")
    if isinstance(n, int) and isinstance(ok, int) and not isinstance(n, bool) and n > 0 and 0 <= ok <= n:
        return n, ok
    return 0, 0


def iso_now(t=None):
    t = time.time() if t is None else t
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%09dZ" % int((t % 1) * 1e9)


def _tool_calls_out(calls):
    out = []
    for c in calls or []:
        fn = (c or {}).get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                args = {}
        out.append({"function": {"name": str(fn.get("name") or ""), "arguments": args if isinstance(args, dict) else {}}})
    return out


def _durations(t0, t_first, t_end, timings, load_s):
    """(total, chargement, évaluation du prompt, génération) en nanosecondes : mesures de llama-server si présentes, sinon l'horloge."""
    ns = lambda s: int(max(0.0, s) * 1e9)
    if isinstance(timings, dict) and _num(timings.get("predicted_ms")):
        return (ns(t_end - t0), ns(load_s), ns(float(timings.get("prompt_ms") or 0) / 1000.0), ns(float(timings["predicted_ms"]) / 1000.0))
    first = t_first if t_first is not None else t0 + load_s   # premier jeton inconnu : tout le temps après le chargement compte comme génération
    return (ns(t_end - t0), ns(load_s), ns(first - t0 - load_s), ns(t_end - first))


def _done_reason(r):
    return "length" if r == "length" else "stop"


def final_chunk(kind, model, usage, timings, t0, t_first, t_end, load_s, finish, extra_count=0):
    """Dernier objet d'une réponse Ollama : décomptes et durées."""
    usage = usage if isinstance(usage, dict) else {}
    timings = timings if isinstance(timings, dict) else {}
    p = usage.get("prompt_tokens", timings.get("prompt_n", 0)) or 0
    c = usage.get("completion_tokens", timings.get("predicted_n", extra_count)) or 0
    total, load, pe, ev = _durations(t0, t_first, t_end, timings, load_s)
    o = {"model": model, "created_at": iso_now(t_end)}
    o["message" if kind == "chat" else "response"] = {"role": "assistant", "content": ""} if kind == "chat" else ""
    o.update(done=True, done_reason=_done_reason(finish), total_duration=total, load_duration=load, prompt_eval_count=int(p), prompt_eval_duration=pe,
             eval_count=int(c), eval_duration=ev)
    return o


def response_to_ollama(kind, model, resp, t0, t_end, load_s=0.0):
    """Réponse JSON complète de llama-server -> réponse Ollama (flux désactivé)."""
    ch = ((resp or {}).get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    text = msg.get("content") or ""
    out = final_chunk(kind, model, resp.get("usage"), resp.get("timings"), t0, None, t_end, load_s, ch.get("finish_reason"))
    if kind == "chat":
        m = {"role": "assistant", "content": text}
        if msg.get("reasoning_content"):
            m["thinking"] = msg["reasoning_content"]
        if msg.get("tool_calls"):
            m["tool_calls"] = _tool_calls_out(msg["tool_calls"])
        out["message"] = m
    else:
        out["response"] = text
        if msg.get("reasoning_content"):
            out["thinking"] = msg["reasoning_content"]
    return out


class StreamTranslator:
    """Flux SSE de llama-server -> lignes JSON d'Ollama (une par morceau, la dernière porte les décomptes)."""

    def __init__(self, kind, model, t0=None, load_s=0.0, clock=time.time):
        self.kind, self.model, self.clock = kind, model, clock
        self.t0 = clock() if t0 is None else t0
        self.load_s = load_s
        self.t_first = None
        self.finish = None
        self.usage = None
        self.timings = None
        self.pieces = 0
        self.calls = {}     # indice -> {name, arguments} : les appels d'outils arrivent par fragments
        self.done = False

    def _line(self, obj):
        return (json.dumps(obj, ensure_ascii=False) + "\n").encode()

    def _piece(self, content, thinking=""):
        o = {"model": self.model, "created_at": iso_now(self.clock()), "done": False}
        if self.kind == "chat":
            m = {"role": "assistant", "content": content}
            if thinking:
                m["thinking"] = thinking
            o["message"] = m
        else:
            o["response"] = content
            if thinking:
                o["thinking"] = thinking
        return o

    def feed(self, raw):
        """Une ligne du flux SSE (octets) -> lignes JSON d'Ollama à renvoyer (liste d'octets, éventuellement vide)."""
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            return []
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            return []
        try:
            d = json.loads(payload)
        except ValueError:
            return []
        out = []
        if isinstance(d.get("usage"), dict):
            self.usage = d["usage"]
        if isinstance(d.get("timings"), dict):
            self.timings = d["timings"]
        for ch in d.get("choices") or []:
            delta = ch.get("delta") or {}
            text, think = delta.get("content") or "", delta.get("reasoning_content") or ""
            if text or think:
                if self.t_first is None:
                    self.t_first = self.clock()
                self.pieces += 1
                out.append(self._line(self._piece(text, think)))
            for tc in delta.get("tool_calls") or []:
                slot = self.calls.setdefault(int(tc.get("index") or 0), {"name": "", "arguments": ""})
                fn = tc.get("function") or {}
                slot["name"] += fn.get("name") or ""
                slot["arguments"] += fn.get("arguments") or ""
            if ch.get("finish_reason"):
                self.finish = ch["finish_reason"]
        return out

    def close(self):
        """Fin du flux : appels d'outils éventuels puis objet final (une seule fois)."""
        if self.done:
            return []
        self.done = True
        out = []
        t_end = self.clock()
        if self.calls and self.kind == "chat":
            calls = [{"function": {"name": c["name"], "arguments": c["arguments"]}} for _, c in sorted(self.calls.items())]
            o = self._piece("")
            o["message"]["tool_calls"] = _tool_calls_out(calls)
            out.append(self._line(o))
        out.append(self._line(final_chunk(self.kind, self.model, self.usage, self.timings, self.t0, self.t_first, t_end, self.load_s, self.finish, self.pieces)))
        return out


# ------------------------------------------------------------------ choix du fichier à installer (versions publiées de llama.cpp)
def pick_asset(assets, backend="vulkan", arch="x64"):
    """Fichier .zip ou .tar.gz d'une release llama.cpp pour Ubuntu, d'après le moteur de calcul demandé (vulkan, rocm, cuda, cpu).
    assets : liste {name, size, digest, browser_download_url}. Retourne l'élément choisi ou None. Les noms varient : correspondance par mots."""
    words = {"vulkan": ("vulkan",), "rocm": ("rocm", "hip"), "cuda": ("cuda",), "cpu": ()}
    others = {"vulkan", "rocm", "hip", "cuda", "opencl", "sycl", "openvino", "musa", "kleidiai", "s390x", "riscv", "arm64", "aarch64", "android", "macos", "xcframework", "win", "windows", "cudart"}
    want = words.get(backend)
    if want is None:
        return None
    best = None
    for a in assets or []:
        name = str(a.get("name") or "").lower()
        if not re.search(r"\.(zip|tar\.gz|tgz)$", name) or "ubuntu" not in name or arch not in name or "llama-" not in name or name.startswith("cudart"):
            continue   # « cudart-… » : bibliothèques d'exécution CUDA seules, sans llama-server
        toks = set(re.split(r"[^a-z0-9]+", name))
        if want:
            if not any(w in toks for w in want):
                continue
            score = 0
        else:
            if toks & others:
                continue
            score = 0
        if "bin" not in toks:
            score += 1
        if best is None or (score, name) < (best[0], best[1]):
            best = (score, name, a)
    return best[2] if best else None


def pick_release(releases, backend="vulkan", arch="x64"):
    """Première version publiée (la plus récente d'abord) qui a un fichier Ubuntu pour ce moteur de calcul ET sa somme SHA-256.
    On ne se fie pas à « la dernière version » de GitHub : llama.cpp marque ses versions de compilation comme « pré-versions », et une version
    sans binaires (v1.0.0 : un simple fichier texte) a déjà été désignée « dernière ». Retourne (version, fichier, None), ou (None, None, raison)
    avec raison « nofile » (aucun fichier pour ce moteur) ou « nosum:<étiquette> » (fichier trouvé mais somme SHA-256 non publiée)."""
    nosum = None
    for rel in releases or []:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        asset = pick_asset(rel.get("assets"), backend, arch)
        if asset is None:
            continue
        if digest_sha256(asset) is None:
            nosum = nosum or str(rel.get("tag_name") or "")
            continue
        return rel, asset, None
    return None, None, ("nosum:" + nosum) if nosum else "nofile"


def digest_sha256(asset):
    """Somme SHA-256 publiée avec le fichier (« sha256:... »), ou None."""
    d = str((asset or {}).get("digest") or "")
    m = re.fullmatch(r"sha256:([0-9a-f]{64})", d.lower())
    return m.group(1) if m else None


def server_in_listing(names):
    """Chemin de llama-server dans la liste des fichiers d'une archive (le plus court qui se termine par /llama-server), ou None."""
    cands = [n for n in names if n.split("/")[-1] == "llama-server" and not n.endswith("/")]
    return min(cands, key=lambda n: (n.count("/"), len(n))) if cands else None
