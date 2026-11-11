#!/usr/bin/env python3
"""OllamaBuntu - routeur et contrôle d'accès de l'API Ollama.

  - Accès local (127.0.0.1:11434, HTTP) : console, Open WebUI, outils du serveur ;
    sans clé, tous droits.
  - Accès réseau (publication.json) : port et TLS au choix, filtrage par adresse,
    clés d'API (Authorization: Bearer) avec droits et modèles autorisés par clé.
  - Chaque requête est envoyée à l'instance Ollama du modèle demandé : groupe de GPU
    (pools.json) ou instance principale (127.0.0.1:11400). Réponses relayées en flux.
Bibliothèque standard de Python uniquement.
"""
import hashlib
import hmac
import http.client
import http.server
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import limits  # noqa: E402

ETC = os.environ.get("OB_ETC", "/etc/ollamabuntu")
POOLS_FILE = os.path.join(ETC, "pools.json")
PUB_FILE = os.path.join(ETC, "publication.json")
TLS_DIR = os.path.join(ETC, "router-tls")
USAGE_FILE = os.environ.get("OB_ROUTER_USAGE", "/var/lib/ollamabuntu-router/usage.json")
MAIN = os.environ.get("OB_MAIN", "127.0.0.1:11400")
LOCAL = os.environ.get("OB_ROUTER_LISTEN", "127.0.0.1:11434")
# Requêtes qui modifient le magasin de modèles : toujours l'instance principale
MANAGEMENT = ("/api/pull", "/api/push", "/api/delete", "/api/create", "/api/copy", "/api/blobs")
INFERENCE = ("/api/generate", "/api/chat", "/api/embed", "/api/embeddings",
             "/v1/chat/completions", "/v1/completions", "/v1/embeddings", "/v1/responses")
READ_GET = ("/", "/api/tags", "/api/ps", "/api/version", "/v1/models")
FILTERED = ("/api/tags", "/api/ps", "/v1/models")   # listes filtrées selon les modèles autorisés
POLICY_FILE = os.path.join(ETC, "ai-policy.json")
# Fonctions cloud d'Ollama (compte ollama.com, recherche et lecture web, inférence distante)
CLOUD_PATHS = ("/api/web_search", "/api/web_fetch", "/api/experimental/", "/api/me", "/api/signout", "/api/usage", "/api/balance")
HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "te", "trailer", "upgrade", "host"}
MAX_BODY = 512 * 1024 * 1024
_routes = {"mtime": None, "map": {}, "pools": []}
_pub = {"mtime": None, "data": {}, "keys": {}}
_pol = {"mtime": None, "data": {}}
LIMITS_FILE = os.environ.get("OB_ROUTER_LIMITS", os.path.join(os.path.dirname(USAGE_FILE), "limits.json"))
QUEUE_WAIT = int(os.environ.get("OB_QUEUE_WAIT", "600"))   # secondes d'attente d'une requête dont la clé a atteint son plafond
_limiter = limits.Limiter()
_tokens = limits.Tokens()
FLEET_ROUTES = os.path.join(ETC, "fleet-routes.json")
_fleet = {"mtime": None, "data": {"servers": [], "local": {}}}
_local_models = {"t": 0.0, "names": set(), "tags": []}
_rr = {}   # tour de rôle par modèle : deux modèles qui alternent ne doivent pas se fausser l'un l'autre
_inflight = {}   # requêtes en cours par serveur : "local" ou identifiant d'un serveur du parc
_inflight_lock = threading.Lock()
COLD_COST = 1.5   # stratégie « modèle déjà chargé » : charger un modèle vaut 1,5 requête en attente
BALANCE_FILE = os.path.join(ETC, "balance.json")
REQLOG_CONF = os.path.join(ETC, "request-log.json")
_bal = {"mtime": None, "data": {}}
_rqc = {"mtime": None, "data": {}}
_health = limits.Health()
_aff = limits.Affinity()


def inflight_add(key, delta):
    with _inflight_lock:
        _inflight[key] = max(0, _inflight.get(key, 0) + delta)


def hot_json(path, cache):
    """Fichier JSON de réglages, relu à chaud quand il change."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    with _lock:
        if mtime != cache["mtime"]:
            try:
                with open(path, encoding="utf-8") as f:
                    cache["data"] = json.load(f)
            except (OSError, ValueError):
                cache["data"] = {}
            cache["mtime"] = mtime
        return cache["data"] if isinstance(cache["data"], dict) else {}


def balance_strategy():
    return "warm" if hot_json(BALANCE_FILE, _bal).get("strategy") == "warm" else "spread"


def affinity_enabled():
    return hot_json(BALANCE_FILE, _bal).get("affinity", True) is not False


def reqlog_conf():
    d = hot_json(REQLOG_CONF, _rqc)
    try:
        chars = max(40, min(int(d.get("chars", 120)), 300))
    except (TypeError, ValueError):
        chars = 120
    return {"prompt_excerpt": d.get("prompt_excerpt") is True, "chars": chars}


# Extrait de la demande (seulement si l'administrateur l'a activé) : début de la dernière question, secrets masqués
MASKS = (
    (re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), "[jeton]"),
    (re.compile(r"\b(?:sk|pk|obf|obr|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}"), "[clé]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"), "[IBAN]"),
    (re.compile(r"\b(?:\d[ -]?){12,19}\b"), "[numéro]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[e-mail]"),
)


def last_user_text(path, d):
    """Dernière question de la requête, selon le format de l'API (Ollama, compatible OpenAI, Anthropic)."""
    def flat(c):
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in c
                            if not isinstance(p, dict) or p.get("type") in (None, "text", "input_text"))
        return ""
    if path in ("/api/generate", "/v1/completions"):
        return flat(d.get("prompt"))
    if path in ("/api/embed", "/api/embeddings", "/v1/embeddings"):
        return "(embeddings) " + flat(d.get("input") if d.get("input") is not None else d.get("prompt"))
    msgs = d.get("messages") if d.get("messages") is not None else d.get("input")
    if isinstance(msgs, str):
        return msgs
    if isinstance(msgs, list):
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                return flat(m.get("content"))
            if isinstance(m, str):
                return m
    return ""


def prompt_excerpt(path, body, chars):
    try:
        d = json.loads(body)
    except ValueError:
        return ""
    if not isinstance(d, dict):
        return ""
    text = " ".join(last_user_text(path, d)[: chars * 4].split())   # masquage avant la coupe : un secret coupé en deux échapperait aux motifs
    for rx, label in MASKS:
        text = rx.sub(label, text)
    return text if len(text) <= chars else text[: chars - 1].rstrip() + "…"
# Taille du contexte choisie par modèle dans la console (relue à chaud)
CTX_FILE = os.path.join(ETC, "model-context.json")
CTX_PATHS = ("/api/generate", "/api/chat", "/api/embed", "/api/embeddings")
_ctx = {"mtime": None, "data": {}}


def model_context():
    try:
        mtime = os.path.getmtime(CTX_FILE)
    except OSError:
        mtime = None
    with _lock:
        if mtime != _ctx["mtime"]:
            try:
                with open(CTX_FILE, encoding="utf-8") as f:
                    _ctx["data"] = {norm(k): int(v) for k, v in json.load(f).get("models", {}).items() if int(v) > 0}
            except (OSError, ValueError, AttributeError, TypeError):
                _ctx["data"] = {}
            _ctx["mtime"] = mtime
        return _ctx["data"]


def with_context(path, body):
    """API native d'Ollama : taille du contexte du modèle ajoutée si la requête n'en précise pas (options.num_ctx)."""
    if path not in CTX_PATHS or not body:
        return body
    ctx = model_context()
    if not ctx:
        return body
    try:
        d = json.loads(body)
    except ValueError:
        return body
    if not isinstance(d, dict) or not ctx.get(norm(str(d.get("model") or ""))):
        return body
    opts = d.get("options") if isinstance(d.get("options"), dict) else {}
    if "num_ctx" in opts:
        return body   # la requête choisit elle-même
    d["options"] = dict(opts, num_ctx=ctx[norm(str(d["model"]))])
    return json.dumps(d).encode()
# Journal des requêtes vers les modèles : métadonnées seulement (jamais les prompts ni les réponses)
REQ_LOG = os.environ.get("OB_ROUTER_REQLOG", "/var/lib/ollamabuntu-router/requests.jsonl")
REQ_LOG_MAX = 5 * 1024 * 1024
_req_lock = threading.Lock()


def request_metrics(tail, elapsed, ttft):
    """Compteurs de fin de réponse : Ollama (eval_count/eval_duration) ou API compatible OpenAI (usage)."""
    text = tail.decode("utf-8", "replace")
    cands = [l[5:].strip() if l.startswith("data:") else l.strip() for l in text.splitlines()]
    cands = [c for c in cands if c.startswith("{")] or [text.strip()]
    for c in reversed(cands):
        try:
            d = json.loads(c)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if "eval_count" in d or "prompt_eval_count" in d:
            out, dur = d.get("eval_count"), d.get("eval_duration")
            return {"in_tok": d.get("prompt_eval_count"), "out_tok": out,
                    "tps": round(out / (dur / 1e9), 1) if out and dur else None,
                    "load_ms": round(d.get("load_duration", 0) / 1e6) if d.get("load_duration") else None}
        u = d.get("usage")
        if isinstance(u, dict):
            out = u.get("completion_tokens") or u.get("output_tokens")
            gen = max(elapsed - (ttft or 0), 0.001)
            return {"in_tok": u.get("prompt_tokens") or u.get("input_tokens"), "out_tok": out,
                    "tps": round(out / gen, 1) if out else None, "load_ms": None}
    return {}


def log_request(entry):
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _req_lock:
        try:
            if os.path.exists(REQ_LOG) and os.path.getsize(REQ_LOG) > REQ_LOG_MAX:
                os.replace(REQ_LOG, REQ_LOG + ".1")
            fd = os.open(REQ_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)   # lisible du seul compte du routeur et de root
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
        except OSError:
            pass
_lock = threading.Lock()
_usage = {}
_usage_dirty = threading.Event()


def policy():
    """Politique d'usage de l'IA (ai-policy.json), relue dès qu'elle change. Absente : cloud interdit."""
    try:
        mtime = os.path.getmtime(POLICY_FILE)
    except OSError:
        mtime = None
    with _lock:
        if mtime != _pol["mtime"]:
            try:
                with open(POLICY_FILE, encoding="utf-8") as f:
                    _pol["data"] = json.load(f)
            except (OSError, ValueError):
                _pol["data"] = {}
            _pol["mtime"] = mtime
        return _pol["data"]


def fleet():
    """Serveurs du parc utilisables pour la répartition (écrit par la console principale)."""
    try:
        mtime = os.path.getmtime(FLEET_ROUTES)
    except OSError:
        mtime = None
    with _lock:
        if mtime != _fleet["mtime"]:
            try:
                with open(FLEET_ROUTES, encoding="utf-8") as f:
                    _fleet["data"] = json.load(f)
            except (OSError, ValueError):
                _fleet["data"] = {"servers": [], "local": {}}
            _fleet["mtime"] = mtime
        return _fleet["data"]


def local_models():
    """Modèles installés sur ce serveur (cache de 10 s)."""
    if time.time() - _local_models["t"] > 10:
        try:
            c = http.client.HTTPConnection(*split(MAIN), timeout=5)
            c.request("GET", "/api/tags")
            tags = json.loads(c.getresponse().read() or b"{}").get("models", [])
            c.close()
        except (OSError, ValueError):
            tags = _local_models["tags"]
        exclude = {norm(x) for x in os.environ.get("OB_ROUTER_LOCAL_EXCLUDE", "").split(",") if x}   # essais
        tags = [m for m in tags if norm(m.get("name") or m.get("model")) not in exclude]
        _local_models.update(t=time.time(), tags=tags, names={norm(m.get("name") or m.get("model")) for m in tags})
    return _local_models


def is_cloud_model(name):
    tag = norm(name).rsplit(":", 1)[-1]
    return tag == "cloud" or tag.endswith("-cloud")


def uses_vision(body):
    """Images ou vidéos dans la requête (formats Ollama, OpenAI et Anthropic)."""
    try:
        d = json.loads(body or b"{}")
    except ValueError:
        return False
    if not isinstance(d, dict):
        return False
    if d.get("images"):
        return True
    for m in d.get("messages") or d.get("input") or []:
        if not isinstance(m, dict):
            continue
        if m.get("images") or m.get("videos"):
            return True
        c = m.get("content")
        if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") in ("image_url", "input_image", "image", "video_url", "input_video") for x in c):
            return True
    return False


def uses_tools(body):
    try:
        d = json.loads(body or b"{}")
    except ValueError:
        return False
    return isinstance(d, dict) and bool(d.get("tools") or d.get("functions"))


def publication():
    """Configuration d'accès réseau, relue dès que publication.json change."""
    try:
        mtime = os.path.getmtime(PUB_FILE)
    except OSError:
        mtime = None
    with _lock:
        if mtime != _pub["mtime"]:
            try:
                with open(PUB_FILE, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            nets = []
            for c in data.get("allow") or []:
                try:
                    nets.append(ipaddress.ip_network(c, strict=False))
                except ValueError:
                    pass
            data["_nets"] = nets
            _pub.update(mtime=mtime, data=data,
                        keys={k["hash"]: k for k in data.get("keys", []) if k.get("hash") and k.get("enabled", True)})
        return _pub["data"], _pub["keys"]


def key_expired(key, today=None):
    """Clé valable jusqu'à la fin du jour d'expiration (AAAA-MM-JJ, heure locale du serveur) ; vide = sans échéance."""
    exp = str(key.get("expires") or "")
    return bool(exp) and (today or time.strftime("%Y-%m-%d")) > exp


def retry_status(status, kind, last):
    """Une réponse d'erreur justifie-t-elle d'essayer le serveur suivant ? Un serveur distant : jeton refusé (401), requête trop grosse (413), saturé ou en panne (429, 502-504),
    toujours ; une erreur interne d'Ollama (500) et les mêmes pannes sur ce serveur : seulement s'il reste un autre candidat (sinon le client voit la vraie erreur)."""
    if kind == "remote" and status in (401, 413, 429, 502, 503, 504):
        return True
    return (not last) and status in (429, 500, 502, 503, 504)


def norm(name):
    """Forme canonique d'un nom de modèle : « llama3.1 » == « llama3.1:latest » ==
    « registry.ollama.ai/library/llama3.1:latest »."""
    n = str(name or "").strip()
    for p in ("registry.ollama.ai/library/", "ollama.com/library/", "library/"):
        if n.startswith(p):
            n = n[len(p):]
    if ":" not in n.split("/")[-1]:
        n += ":latest"
    return n.lower()


def routes():
    """Table modèle -> instance, relue dès que pools.json change."""
    try:
        mtime = os.path.getmtime(POOLS_FILE)
    except OSError:
        mtime = None
    with _lock:
        if mtime != _routes["mtime"]:
            table, pools = {}, []
            try:
                with open(POOLS_FILE, encoding="utf-8") as f:
                    pools = json.load(f).get("pools", [])
            except (OSError, ValueError):
                pools = []
            for p in pools:
                for m in p.get("models", []):
                    table[norm(m)] = "127.0.0.1:%d" % int(p["port"])
            _routes.update(mtime=mtime, map=table, pools=pools)
        return _routes["map"], _routes["pools"]


def split(addr):
    host, _, port = addr.rpartition(":")
    return host, int(port)


class Router(http.server.BaseHTTPRequestHandler):
    server_version = "OllamaBuntu-router"
    sys_version = ""
    protocol_version = "HTTP/1.0"   # réponses délimitées par la fermeture : le flux passe tel quel
    timeout = 3600

    def log_message(self, fmt, *args):
        pass

    def read_body(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            parts, total = [], 0
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                parts.append(self.rfile.read(size))
                self.rfile.readline()
                total += size
                if total > MAX_BODY:
                    raise ValueError("requête trop volumineuse")
            return b"".join(parts)
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("requête trop volumineuse")
        return self.rfile.read(n) if n else b""

    def target_for(self, method, path, body):
        if path.startswith(MANAGEMENT) or not body:
            return MAIN
        try:
            data = json.loads(body)
        except ValueError:
            return MAIN
        model = data.get("model") or data.get("name") if isinstance(data, dict) else None
        if not model:
            return MAIN
        table, _ = routes()
        return table.get(norm(model), MAIN)

    def release_inflight(self):
        key = getattr(self, "_inflight_key", None)
        if key:
            self._inflight_key = None
            inflight_add(key, -1)

    def json_reply(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    @staticmethod
    def candidates(model, fl, kid=None, session=None):
        """Serveurs capables de répondre : le modèle déjà en mémoire d'abord, puis le moins chargé.
        Une conversation (session) retourne au serveur qui l'a déjà traitée tant qu'il n'est pas nettement plus occupé que les autres."""
        out = []
        loc = fl.get("local") or {}
        if model in local_models()["names"]:
            out.append(("local", model in {norm(x) for x in loc.get("loaded", [])}, float(loc.get("load") or 0), None))
        for s in fl.get("servers", []):
            if not s.get("online"):
                continue
            have = {norm(m.get("name") or m.get("model")) for m in s.get("models", [])}
            use = model if model in have else None
            if use is None:   # correspondance choisie par l'administrateur : modèle demandé -> modèle de remplacement de ce serveur
                mp = {norm(k): norm(v) for k, v in (s.get("model_map") or {}).items() if k != "*"}
                sub = mp.get(model) or norm((s.get("model_map") or {}).get("*") or "")
                if sub and sub in have:
                    use = sub
            if use:
                out.append(("remote", use in {norm(x) for x in s.get("loaded", [])}, float(s.get("load") or 0), dict(s, use_model=use)))
        t_now = time.time()
        sound = [c for c in out if c[0] == "local" or not _health.tripped(c[3]["id"], t_now)]
        out = sound or out   # un serveur qui vient d'échouer plusieurs fois est écarté un moment, sauf s'il n'y a pas d'autre choix
        matched = False
        rules = fl.get("rules") or []
        if rules:
            out, matched = limits.apply_rules(out, rules, kid, model)
        if matched and not out:
            return []
        with _inflight_lock:
            strategy = balance_strategy()
            turn = _rr.get(model, 0)
            _rr[model] = turn + 1
            size = max(len(out), 1)

            def score(i, c):
                busy = _inflight.get("local" if c[0] == "local" else c[3]["id"], 0)   # requêtes en cours, mesurées par ce routeur
                rank = (i + turn) % size   # à égalité, les serveurs se relaient
                if strategy == "warm":   # modèle déjà en mémoire d'abord, sauf si ce serveur est déjà occupé
                    return (busy + (0 if c[1] else COLD_COST) + c[2] / 400.0, rank)
                return (busy, rank)
            ordered = [c for _, c in sorted(((score(i, c), c) for i, c in enumerate(out)), key=lambda t: t[0])]
            if session and len(ordered) > 1 and affinity_enabled():
                sid = lambda c: "local" if c[0] == "local" else c[3]["id"]
                by_id = {sid(c): c for c in ordered}
                new_ids, _hit = _aff.order(session, [sid(c) for c in ordered], {i: _inflight.get(i, 0) for i in by_id})
                ordered = [by_id[i] for i in new_ids]
            if ordered and any(c[0] == "remote" for c in ordered):   # choix et réservation d'un seul geste : deux requêtes simultanées ne visent pas le même serveur
                first = ordered[0]
                k = "local" if first[0] == "local" else first[3]["id"]
                _inflight[k] = _inflight.get(k, 0) + 1
        return ordered

    def balanced(self, method, path, body, cands, model):
        """Envoie la requête au premier serveur capable ; en cas d'échec avant le premier octet envoyé au client (connexion refusée, erreur 5xx,
        réponse vide ou coupée), la même requête est rejouée sur le serveur suivant. Les échecs sont mémorisés (disjoncteur) et journalisés."""
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() not in ("content-length", "authorization", "x-api-key")}
        headers["Content-Length"] = str(len(body))
        table, _ = routes()
        for idx, (kind, _loaded, _load, srv) in enumerate(cands):
            ikey = "local" if kind == "local" else srv["id"]
            name = "local" if kind == "local" else srv["name"]
            last = idx == len(cands) - 1
            if idx:
                inflight_add(ikey, 1)   # le premier choix est déjà réservé par candidates()
            conn = None
            try:
                if kind == "local":
                    target = table.get(norm(model), MAIN)
                    conn = http.client.HTTPConnection(*split(target), timeout=3600)
                    conn.request(method, self.path, body=body, headers=headers)
                    label = target
                else:
                    u = urllib.parse.urlsplit(srv["url"])
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE   # certificat autosigné : empreinte épinglée vérifiée ci-dessous
                    conn = http.client.HTTPSConnection(u.hostname, u.port or 443, context=ctx, timeout=3600)
                    conn.connect()
                    h = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest().upper()
                    if ":".join(h[i:i + 2] for i in range(0, 64, 2)) != srv["fingerprint"]:
                        print("répartition : certificat inattendu pour %s, serveur écarté" % srv["name"], flush=True)
                        conn.close()
                        inflight_add(ikey, -1)
                        continue
                    rbody = body
                    if srv.get("use_model") and srv["use_model"] != norm(model):   # le serveur reçoit son modèle de remplacement
                        try:
                            d = json.loads(body)
                            d["model"] = srv["use_model"]
                            rbody = json.dumps(d).encode()
                        except (ValueError, TypeError, AttributeError):
                            rbody = body
                    conn.request(method, "/api/fleet/ollama" + self.path, body=rbody,
                                 headers=dict(headers, **{"Content-Length": str(len(rbody))}, Authorization="Bearer " + srv["token"], **{"X-OB": "1"}))
                    label = "serveur:" + srv["name"]
                resp = conn.getresponse()
            except (OSError, ssl.SSLError, http.client.HTTPException) as e:
                print("répartition : %s indisponible (%s), serveur suivant" % (name, e), flush=True)
                self.note_failure(ikey, name, "injoignable")
                inflight_add(ikey, -1)
                if conn is not None:
                    conn.close()
                continue
            if retry_status(resp.status, kind, last):
                print("répartition : %s a répondu %d, serveur suivant" % (name, resp.status), flush=True)
                self.note_failure(ikey, name, str(resp.status))
                conn.close()
                inflight_add(ikey, -1)
                continue
            first, ttft0 = None, None
            if self.req_meta is not None and not last and self.command != "HEAD" and resp.status < 400:
                try:   # on attend le premier octet avant de répondre au client : tant qu'il n'a rien reçu, on peut encore changer de serveur
                    first = resp.read1(65536)
                except (OSError, http.client.HTTPException) as e:
                    first = b""
                    print("répartition : réponse de %s coupée (%s), serveur suivant" % (name, e), flush=True)
                if not first:
                    self.note_failure(ikey, name, "réponse vide ou coupée")
                    conn.close()
                    inflight_add(ikey, -1)
                    continue
                ttft0 = time.time() - self.t0
            if resp.status < 500:
                _health.ok(ikey)
            self._inflight_key = ikey
            return self.stream_back(resp, conn, label, first, ttft0)
        if self.req_meta is not None:
            log_request(dict(self.req_meta, ts=round(self.t0, 3), instance="-", status=503, aborted=False, ms=round((time.time() - self.t0) * 1000), ttft_ms=None,
                             retried=list(self._retried)))
        return self.json_reply(503, {"error": "aucun serveur disponible pour le modèle « %s » (ce serveur et le parc)" % model})

    def note_failure(self, ikey, name, why):
        """Mémorise un échec : serveur écarté un moment après plusieurs échecs, et trace dans le journal de la requête."""
        _health.fail(ikey)
        self._retried.append("%s : %s" % (name, why))

    def stream_back(self, resp, conn, label, first=None, ttft0=None):
        """Relais en flux de la réponse ; pour les requêtes vers les modèles, mesure et journalisation.
        first : premier morceau déjà lu par balanced() (pour pouvoir changer de serveur tant que le client n'a rien reçu)."""
        ttft, tail, aborted = ttft0, b"", False
        try:
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("X-OllamaBuntu-Instance", label)
            if getattr(self, "_clamped", None):
                self.send_header("X-OllamaBuntu-Clamped", ",".join(self._clamped))
            self.end_headers()
            if self.command != "HEAD":
                while True:
                    if first is not None:
                        chunk, first = first, None
                    else:
                        chunk = resp.read1(65536)
                    if not chunk:
                        break
                    if ttft is None:
                        ttft = time.time() - self.t0
                    if self.req_meta is not None:
                        tail = (tail + chunk)[-65536:]   # fin de la réponse seulement : compteurs d'Ollama
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            aborted = True   # client parti : la fermeture interrompt aussi la génération en amont
        finally:
            conn.close()
            self.release_inflight()
            if self.req_meta is not None:
                elapsed = time.time() - getattr(self, "t0", time.time())
                met = request_metrics(tail, elapsed, ttft)
                log_request(dict(self.req_meta, ts=round(self.t0, 3), instance=label, status=resp.status, aborted=aborted,
                                 ms=round(elapsed * 1000), ttft_ms=round(ttft * 1000) if ttft is not None else None,
                                 **({"retried": list(self._retried)} if getattr(self, "_retried", None) else {}), **met))
                if getattr(self, "_kid", None):
                    _tokens.add(self._kid, (met.get("in_tok") or 0) + (met.get("out_tok") or 0))

    def merged_models(self, path, allowed, fl):
        """Liste unifiée : modèles de ce serveur et des serveurs du parc en ligne (filtrée selon la clé)."""
        tags = list(local_models()["tags"])
        seen = {norm(m.get("name") or m.get("model")) for m in tags}
        for s in fl.get("servers", []):
            if not s.get("online"):
                continue
            for m in s.get("models", []):
                n = norm(m.get("name") or m.get("model"))
                if n not in seen:
                    seen.add(n)
                    tags.append(m)
        if allowed is not None:
            tags = [m for m in tags if norm(m.get("name") or m.get("model")) in allowed]
        if path == "/v1/models":
            return self.json_reply(200, {"object": "list", "data": [{"id": m.get("name"), "object": "model", "created": 0, "owned_by": "ollamabuntu"} for m in tags]})
        return self.json_reply(200, {"models": tags})

    @staticmethod
    def model_of(path, body):
        if path.startswith("/v1/models/"):
            return urllib.parse.unquote(path[len("/v1/models/"):])
        if not body:
            return None
        try:
            data = json.loads(body)
        except ValueError:
            return None
        if isinstance(data, dict):
            m = data.get("model") or data.get("name") or (data.get("source") if path == "/api/copy" else None)
            return str(m) if m else None
        return None

    def filtered_list(self, path, allowed):
        try:
            c = http.client.HTTPConnection(*split(MAIN), timeout=30)
            c.request("GET", path)
            data = json.loads(c.getresponse().read() or b"{}")
            c.close()
        except (OSError, ValueError) as e:
            return self.json_reply(502, {"error": "instance Ollama injoignable : %s" % e})
        if path == "/v1/models":
            data["data"] = [m for m in data.get("data", []) if norm(m.get("id")) in allowed]
        else:
            data["models"] = [m for m in data.get("models", []) if norm(m.get("name") or m.get("model")) in allowed]
        self.json_reply(200, data)

    def merged_ps(self, allowed=None):
        """/api/ps : modèles chargés sur toutes les instances."""
        _, pools = routes()
        models = []
        for addr in [MAIN] + ["127.0.0.1:%d" % int(p["port"]) for p in pools]:
            try:
                c = http.client.HTTPConnection(*split(addr), timeout=5)
                c.request("GET", "/api/ps")
                r = c.getresponse()
                if r.status == 200:
                    models += [m for m in json.loads(r.read() or b"{}").get("models", [])
                               if allowed is None or norm(m.get("name") or m.get("model")) in allowed]
                c.close()
            except (OSError, ValueError):
                continue
        self.json_reply(200, {"models": models})

    def category(self, method, path):
        if path in INFERENCE:
            return "inference"
        if path == "/api/show" or (method in ("GET", "HEAD") and (path in READ_GET or path.startswith("/v1/models/"))):
            return "read"
        return "manage"   # gestion du magasin et tout point d'API inconnu

    def rights(self):
        """None = accès local sans restriction ; sinon (nom, droits, modèles autorisés, id de clé)."""
        try:
            peer = ipaddress.ip_address(self.client_address[0].split("%")[0])
        except ValueError:
            peer = None
        if peer is not None and (peer.is_loopback or (peer.version == 6 and peer.ipv4_mapped and peer.ipv4_mapped.is_loopback)):
            return None
        pub, keys = publication()
        if not self.server.public or not pub.get("enabled"):
            raise PermissionError(403, "accès réseau désactivé")
        if pub["_nets"]:
            p4 = peer.ipv4_mapped if peer is not None and peer.version == 6 and peer.ipv4_mapped else peer
            if p4 is None or not any(p4 in n for n in pub["_nets"] if n.version == p4.version):
                raise PermissionError(403, "adresse %s non autorisée" % self.client_address[0])
        if not pub.get("auth", True):
            a = pub.get("anonymous") or {}
            return ("anonyme", set(a.get("perms") or []), {norm(m) for m in a.get("models") or []}, None, set(a.get("deny") or []))
        auth = self.headers.get("Authorization") or ""
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else (self.headers.get("X-API-Key") or "").strip()
        if not token:
            raise PermissionError(401, "clé d'API requise (en-tête Authorization: Bearer <clé>)")
        digest = hashlib.sha256(token.encode()).hexdigest()
        key = next((k for h, k in keys.items() if hmac.compare_digest(h, digest)), None)
        if not key:
            raise PermissionError(401, "clé d'API invalide ou révoquée")
        if key_expired(key):
            raise PermissionError(401, "clé d'API expirée (le %s)" % key.get("expires"))
        self._key = key
        return (key.get("name", "?"), set(key.get("perms") or []), {norm(m) for m in key.get("models") or []}, key.get("id"), set(key.get("deny") or []))

    def note_usage(self, kid):
        if kid:
            with _lock:
                u = _usage.setdefault(kid, {"count": 0})
                u["count"] += 1
                u["last"] = int(time.time())   # horodatage (secondes), comme le reste de la console
            _usage_dirty.set()

    def deny(self, code, message):
        raw = json.dumps({"error": message}, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if code == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="OllamaBuntu"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)
        print("accès refusé %s %s %s : %s" % (self.client_address[0], self.command, self.path[:80], message), flush=True)

    def relay(self):
        self._key, self._slot, self._kid = None, None, None
        try:
            self._relay()
        finally:
            if self._slot:
                _limiter.release(self._slot)
                self._slot = None

    def _relay(self):
        self.t0, self.req_meta, self._inflight_key, self._retried = time.time(), None, None, []
        method = self.command
        path = urllib.parse.urlsplit(self.path).path
        try:
            body = self.read_body() if method in ("POST", "PUT", "PATCH", "DELETE") else None
        except ValueError as e:
            return self.json_reply(413, {"error": str(e)})
        # Politique d'usage de l'IA : s'applique à tous les clients, accès local compris
        if not policy().get("cloud", False):
            if path.startswith(CLOUD_PATHS):
                return self.deny(403, "fonctions cloud d'Ollama désactivées (politique d'usage de l'IA de l'appliance)")
            model = self.model_of(path, body)
            if model and is_cloud_model(model):
                return self.deny(403, "modèle cloud « %s » interdit : il s'exécute chez Ollama, hors de ce serveur (politique d'usage de l'IA)" % model)
        try:
            r = self.rights()
        except PermissionError as e:
            return self.deny(*e.args)
        allowed = None
        if path in INFERENCE:   # requêtes mesurées : utilisation des modèles
            self.req_meta = {"client": "local" if r is None else r[0], "ip": self.client_address[0], "path": path,
                             "model": self.model_of(path, body) if body else None}
            conf = reqlog_conf()
            if conf["prompt_excerpt"] and body:   # désactivé par défaut : réglage de la console (Journaux > Requêtes)
                excerpt = prompt_excerpt(path, body, conf["chars"])
                if excerpt:
                    self.req_meta["prompt"] = excerpt
        if r is not None:
            who, perms, models, kid, deny = r
            if "audio" in deny and path.startswith("/v1/audio"):
                return self.deny(403, "audio (synthèse, transcription) non autorisé pour « %s »" % who)
            if "vision" in deny and body and uses_vision(body):
                return self.deny(403, "images et vidéos en entrée non autorisées pour « %s »" % who)
            if "tools" in deny and body and uses_tools(body):
                return self.deny(403, "outils (appels de fonctions) non autorisés pour « %s »" % who)
            cat = self.category(method, path)
            if cat not in perms:
                return self.deny(403, "droit « %s » non accordé à « %s »" % ({"inference": "utilisation des modèles", "read": "consultation", "manage": "gestion des modèles"}[cat], who))
            if models:
                allowed = models
                model = self.model_of(path, body)
                if model is not None and norm(model) not in models:
                    return self.deny(403, "modèle « %s » non autorisé pour « %s »" % (model, who))
            self.note_usage(kid)
            key = self._key or {}
            if path in INFERENCE and kid:
                why = _tokens.exceeded(kid, key.get("quota_day"), key.get("quota_month"))
                if why:
                    return self.deny(429, "%s pour « %s »" % (why, who))
                if not _limiter.acquire(kid, key.get("max_concurrent"), QUEUE_WAIT):
                    return self.deny(429, "trop de requêtes simultanées pour « %s » (plafond %s) : file d'attente pleine" % (who, key.get("max_concurrent")))
                if key.get("max_concurrent"):
                    self._slot = kid
        self._kid = kid if r is not None else None
        body = with_context(path, body)
        self._clamped = []
        if r is not None and self._key and (self._key.get("max_ctx") or self._key.get("max_output")) and path in INFERENCE:
            body, self._clamped = limits.apply_caps(path, body, self._key.get("max_ctx"), self._key.get("max_output"))
        fl = fleet()
        if fl.get("servers") and method == "GET" and path in ("/api/tags", "/v1/models"):
            return self.merged_models(path, allowed, fl)
        if method == "GET" and path == "/api/ps":
            return self.merged_ps(allowed)
        if allowed is not None and method == "GET" and path in FILTERED:
            return self.filtered_list(path, allowed)
        if fl.get("servers") and body and not path.startswith(MANAGEMENT) and self.category(method, path) in ("inference", "read"):
            model = self.model_of(path, body)
            if model:
                cands = self.candidates(norm(model), fl, getattr(self, "_kid", None), limits.session_key(self.headers, body, getattr(self, "_kid", None), norm(model)))
                if not cands and fl.get("rules"):
                    return self.json_reply(503, {"error": "aucun serveur autorisé par les règles de routage pour « %s »" % model})
                if any(c[0] == "remote" for c in cands):
                    return self.balanced(method, path, body, cands, model)
        target = self.target_for(method, path, body)
        if self.req_meta is not None:   # requête en cours sur ce serveur, comptée dès l'envoi
            inflight_add("local", 1)
            self._inflight_key = "local"
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() not in ("content-length", "authorization", "x-api-key")}
        if body is not None:
            headers["Content-Length"] = str(len(body))
        try:
            conn = http.client.HTTPConnection(*split(target), timeout=3600)
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except OSError as e:
            self.release_inflight()
            return self.json_reply(502, {"error": "instance Ollama %s injoignable : %s" % (target, e)})
        return self.stream_back(resp, conn, target)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = relay


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    public = False

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if isinstance(e, (ssl.SSLError, ConnectionError, socket.timeout, TimeoutError)):
            # HTTP en clair sur le port HTTPS, TLS trop ancien, client parti : une ligne suffit
            print("connexion rejetée %s : %s" % (client_address[0], getattr(e, "reason", None) or type(e).__name__), flush=True)
            return
        super().handle_error(request, client_address)


def split_listen(addr):
    host, _, port = addr.replace("http://", "").rpartition(":")
    return (host or "127.0.0.1").strip("[]"), int(port)


def make_server(host, port, public, tls):
    Server.address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
    httpd = Server((host, port), Router)
    httpd.public = public
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(os.path.join(TLS_DIR, "cert.pem"), os.path.join(TLS_DIR, "key.pem"))
        # poignée de main dans le fil de la requête : un client lent ne bloque pas les autres
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True, do_handshake_on_connect=False)
    return httpd


def usage_writer():
    while True:
        _usage_dirty.wait()
        time.sleep(10)
        _usage_dirty.clear()
        with _lock:
            snap = json.dumps(_usage)
        try:
            os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
            tmp = USAGE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(snap)
            os.replace(tmp, USAGE_FILE)
        except OSError:
            pass


def limits_writer():
    """État de la file d'attente (rapide) et jetons consommés (persistés) pour la console."""
    last = 0.0
    while True:
        _limiter.dirty.wait(timeout=5)
        _limiter.dirty.clear()
        if _tokens.dirty.is_set() or time.time() - last > 5:
            _tokens.dirty.clear()
        limits.write_json(LIMITS_FILE, {"t": int(time.time()), "queue": _limiter.snapshot(), "tokens": _tokens.snapshot()})
        last = time.time()
        time.sleep(2)


def main():
    try:
        with open(USAGE_FILE, encoding="utf-8") as f:
            _usage.update(json.load(f))
    except (OSError, ValueError):
        pass
    try:
        with open(LIMITS_FILE, encoding="utf-8") as f:
            _tokens.load(json.load(f).get("tokens"))
    except (OSError, ValueError):
        pass
    pub, _ = publication()
    lhost, lport = split_listen(LOCAL)
    servers = []
    if pub.get("enabled"):
        port, tls = int(pub.get("port") or 11443), bool(pub.get("tls", True))
        if port == lport and not tls:   # même port : un seul écouteur, le local reste reconnu par son adresse
            servers.append(make_server("0.0.0.0", port, True, False))
        else:
            servers.append(make_server(lhost, lport, False, False))
            servers.append(make_server("0.0.0.0", port, True, tls))
    else:
        servers.append(make_server(lhost, lport, False, False))
    for srv in servers:
        h, p = srv.server_address[:2]
        print("OllamaBuntu : routeur Ollama sur %s:%d (%s%s)" % (h, p, "réseau" if srv.public else "local",
              ", TLS" if isinstance(srv.socket, ssl.SSLSocket) else ""), flush=True)
    threading.Thread(target=usage_writer, daemon=True).start()
    threading.Thread(target=limits_writer, daemon=True).start()
    for srv in servers[1:]:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    servers[0].serve_forever()


if __name__ == "__main__":
    sys.exit(main())
