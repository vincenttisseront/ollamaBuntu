#!/usr/bin/env python3
"""OllamaBuntu - caches du routeur : réponses exactes (génération déterministe), embeddings, et suivi des débuts d'invite.

  - Cache de réponses : seulement les requêtes dont la température est explicitement 0 (la même demande redonne la même réponse).
    Gardé en mémoire vive uniquement (rien sur le disque : un redémarrage le vide), borné en taille et en durée.
  - Cache d'embeddings : un vecteur par (modèle, texte, options). Une demande n'est servie du cache que si TOUS ses textes y sont.
  - Débuts d'invite : seules des empreintes sont gardées (jamais le texte) pour compter combien de débuts distincts circulent.
Fonctions pures et classes sans accès réseau ni disque : testables hors du routeur. Bibliothèque standard uniquement."""
import array
import collections
import hashlib
import json
import threading
import time

RESPONSE_PATHS = ("/api/chat", "/api/generate", "/v1/chat/completions", "/v1/completions")
EMBED_PATHS = ("/api/embed", "/api/embeddings", "/v1/embeddings")
DEFAULTS = {"responses": False, "embeddings": False, "ttl": 3600, "max_mb": 64, "max_entry_kb": 512, "purged": 0}
SKIP_HEADER = "x-ollamabuntu-cache"   # « skip » : cette demande ignore le cache (lecture et écriture)


def clean_config(d):
    """Réglages validés (levée de ValueError avec un message lisible)."""
    d = d if isinstance(d, dict) else {}
    out = dict(DEFAULTS)
    for k in ("responses", "embeddings"):
        if k in d:
            out[k] = d[k] is True
    for key, label, lo, hi in (("ttl", "durée de conservation (secondes)", 60, 7 * 86400), ("max_mb", "taille maximale (Mo)", 4, 1024),
                               ("max_entry_kb", "taille maximale d'une réponse (Ko)", 16, 8192)):
        if key in d:
            try:
                v = int(d[key])
            except (TypeError, ValueError):
                raise ValueError("valeur invalide : %s" % label)
            if not lo <= v <= hi:
                raise ValueError("%s hors limites (%d à %d)" % (label, lo, hi))
            out[key] = v
    try:
        out["purged"] = max(0, int(d.get("purged") or 0))
    except (TypeError, ValueError):
        out["purged"] = 0
    return out


def _canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _loads(body):
    try:
        d = json.loads(body)
    except (ValueError, TypeError):
        return None
    return d if isinstance(d, dict) else None


# ---------------------------------------------------------------------------- réponses ---
def temperature(path, d):
    """Température demandée explicitement, ou None (absente : le modèle tire au hasard, donc pas de cache)."""
    t = d.get("temperature") if path.startswith("/v1/") else (d.get("options") or {}).get("temperature") if isinstance(d.get("options"), dict) else None
    return t if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def response_key(path, body):
    """(clé, None) pour une demande dont la réponse peut être rejouée ; (None, raison) sinon."""
    if path not in RESPONSE_PATHS:
        return None, "chemin non concerné"
    d = _loads(body)
    if d is None:
        return None, "corps illisible"
    t = temperature(path, d)
    if t is None:
        return None, "température non fixée"
    if t != 0:
        return None, "température non nulle"
    n = d.get("n")
    if isinstance(n, int) and n > 1:
        return None, "plusieurs réponses demandées"
    body_key = {k: v for k, v in d.items() if k not in ("keep_alive", "user")}
    return hashlib.sha256((path + "\x00" + _canon(body_key)).encode("utf-8", "replace")).hexdigest(), None


def complete(path, raw, content_type=""):
    """La réponse est-elle entière et sans erreur ? (une réponse tronquée ou en erreur n'est jamais gardée)."""
    if not raw:
        return False
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return False
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if path.startswith("/v1/"):
        if "text/event-stream" in content_type or lines[0].startswith("data:"):
            return lines[-1] == "data: [DONE]" and not any(l.startswith("data:") and '"error"' in l[:40] for l in lines)
        d = _loads(text)
        return bool(d) and "error" not in d and bool(d.get("choices"))
    last = _loads(lines[-1])
    if not last or "error" in last:
        return False
    return last.get("done") is True and not any('"error"' in l[:12] for l in lines[:-1])


class Lru:
    """Cache borné en octets et en durée, éviction du moins récemment utilisé. Sûr entre threads."""

    def __init__(self, max_bytes=64 << 20, ttl=3600):
        self.max_bytes, self.ttl = int(max_bytes), int(ttl)
        self.d = collections.OrderedDict()
        self.size = 0
        self.lock = threading.Lock()
        self.hits = self.misses = self.stores = self.evicted = 0

    def configure(self, max_bytes, ttl):
        with self.lock:
            self.max_bytes, self.ttl = int(max_bytes), int(ttl)
            self._shrink()

    def get(self, key, now=None):
        now = time.time() if now is None else now
        with self.lock:
            e = self.d.get(key)
            if e is None:
                self.misses += 1
                return None
            if e[0] < now:
                self.d.pop(key)
                self.size -= e[1]
                self.misses += 1
                return None
            self.d.move_to_end(key)
            self.hits += 1
            return e[2]

    def get_all(self, keys, now=None):
        """Valeurs de toutes les clés, ou None si l'une manque (un seul succès ou échec compté pour la demande entière)."""
        now = time.time() if now is None else now
        with self.lock:
            out = []
            for k in keys:
                e = self.d.get(k)
                if e is None or e[0] < now:
                    if e is not None:
                        self.d.pop(k)
                        self.size -= e[1]
                    self.misses += 1
                    return None
                out.append(e[2])
            for k in keys:
                self.d.move_to_end(k)
            self.hits += 1
            return out

    def put(self, key, value, size, now=None):
        now = time.time() if now is None else now
        size = int(size) + 96
        if size > self.max_bytes // 2:
            return False   # une seule entrée ne doit pas vider le cache
        with self.lock:
            old = self.d.pop(key, None)
            if old:
                self.size -= old[1]
            self.d[key] = (now + self.ttl, size, value)
            self.size += size
            self.stores += 1
            self._shrink()
        return True

    def _shrink(self):
        while self.size > self.max_bytes and self.d:
            _, e = self.d.popitem(last=False)
            self.size -= e[1]
            self.evicted += 1

    def clear(self):
        with self.lock:
            self.d.clear()
            self.size = 0

    def snapshot(self):
        with self.lock:
            return {"entries": len(self.d), "bytes": self.size, "hits": self.hits, "misses": self.misses, "stores": self.stores, "evicted": self.evicted}


# --------------------------------------------------------------------------- embeddings ---
def embed_inputs(path, body):
    """(modèle, [textes], clé des options) d'une demande d'embeddings que le cache sait traiter, sinon None."""
    d = _loads(body)
    if d is None or path not in EMBED_PATHS:
        return None
    model = d.get("model")
    if not isinstance(model, str) or not model:
        return None
    if path == "/api/embeddings":
        texts = d.get("prompt")
        texts = [texts] if isinstance(texts, str) else None
    else:
        texts = d.get("input")
        texts = [texts] if isinstance(texts, str) else texts if isinstance(texts, list) and texts and all(isinstance(x, str) for x in texts) else None
    if not texts or len(texts) > 512:
        return None
    if path == "/v1/embeddings" and d.get("encoding_format") not in (None, "float"):
        return None
    opts = {k: d.get(k) for k in ("truncate", "dimensions", "options") if d.get(k) is not None}
    return model, texts, _canon(opts)


def embed_key(model, text, optkey):
    return hashlib.sha256((model + "\x00" + optkey + "\x00" + text).encode("utf-8", "replace")).hexdigest()


def pack(vec):
    return array.array("f", vec).tobytes()


def unpack(raw):
    a = array.array("f")
    a.frombytes(raw)
    return [float("%.8g" % x) for x in a]


def embed_vectors(path, raw):
    """Vecteurs d'une réponse d'embeddings, dans l'ordre des textes ; None si la réponse est inattendue."""
    d = _loads(raw)
    if not d or "error" in d:
        return None
    try:
        if path == "/api/embed":
            vs = d["embeddings"]
        elif path == "/api/embeddings":
            vs = [d["embedding"]]
        else:
            vs = [x["embedding"] for x in sorted(d["data"], key=lambda x: x.get("index", 0))]
    except (KeyError, TypeError, AttributeError):
        return None
    if not isinstance(vs, list) or not all(isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v) for v in vs):
        return None
    return vs


def embed_response(path, model, vectors):
    """Réponse complète construite avec les vecteurs mémorisés (mêmes champs que celle d'Ollama, durées à zéro)."""
    if path == "/api/embed":
        return {"model": model, "embeddings": vectors, "total_duration": 0, "load_duration": 0, "prompt_eval_count": 0}
    if path == "/api/embeddings":
        return {"embedding": vectors[0]}
    return {"object": "list", "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)], "model": model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}


# ------------------------------------------------------------------------ débuts d'invite ---
MIN_PREFIX = 200   # un début plus court ne vaut pas la peine d'être gardé au chaud


def _flat(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
    return ""


def prefix_hash(path, body):
    """Empreinte du début de l'invite (consigne système, sinon début du texte), ou None s'il est trop court pour être utile."""
    d = _loads(body)
    if d is None:
        return None
    text = ""
    if isinstance(d.get("messages"), list):
        text = next((_flat(m.get("content")) for m in d["messages"] if isinstance(m, dict) and m.get("role") in ("system", "developer")), "")
        if not text:
            text = next((_flat(m.get("content")) for m in d["messages"] if isinstance(m, dict)), "")
    elif isinstance(d.get("system"), str) and d["system"]:
        text = d["system"]
    elif isinstance(d.get("prompt"), str):
        text = d["prompt"]
    if len(text) < MIN_PREFIX:
        return None
    return hashlib.sha1((str(d.get("model", "")) + "\x00" + text[:MIN_PREFIX * 5]).encode("utf-8", "replace")).hexdigest()[:16]


class Prefixes:
    """Compte les débuts d'invite vus pendant la dernière heure : quelles invites circulent et combien de fois chacune revient."""

    def __init__(self, window=3600, size=500):
        self.window, self.size = window, size
        self.seen = collections.OrderedDict()   # empreinte -> [modèle, première vue, dernière vue, nombre]
        self.lock = threading.Lock()

    def note(self, model, h, now=None):
        if not h:
            return
        now = time.time() if now is None else now
        with self.lock:
            e = self.seen.get(h)
            if e is None:
                self.seen[h] = [str(model), now, now, 1]
                while len(self.seen) > self.size:
                    self.seen.popitem(last=False)
            else:
                e[2], e[3] = now, e[3] + 1
                self.seen.move_to_end(h)

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            live = [e for e in self.seen.values() if e[2] >= now - self.window]
        by_model = {}
        for m, _a, _b, n in live:
            by_model.setdefault(m, []).append(n)
        return {"distinct": len(live), "requests": sum(e[3] for e in live), "reused": sum(e[3] - 1 for e in live),
                "models": [{"model": m, "distinct": len(ns), "requests": sum(ns), "frequent": sum(1 for n in ns if n >= 3)} for m, ns in sorted(by_model.items())]}
