#!/usr/bin/env python3
"""OllamaBuntu - limites du routeur : requêtes simultanées par clé (file d'attente), quotas de jetons, règles de routage.
Bibliothèque standard de Python uniquement ; testable sans réseau."""
import fnmatch
import hashlib
import json
import os
import threading
import time


PRIORITIES = (1, 2, 3)   # 1 haute, 2 normale, 3 basse
AGING = 120              # une requête qui attend gagne un niveau de priorité toutes les 120 s : aucune ne reste bloquée indéfiniment


def priority_of(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 2
    return v if v in PRIORITIES else 2


class Limiter:
    """File d'attente des requêtes d'inférence.
    - Au plus `cap` requêtes en cours par clé ; au plus `total` en même temps pour tout le serveur (protège la mémoire de la carte graphique).
    - Quand il faut attendre, la requête de plus haute priorité passe d'abord, à priorité égale la plus ancienne (avec vieillissement).
    - Une requête dont la clé a atteint son plafond ne bloque pas les autres.
    Chaque requête attend au plus `wait` secondes."""

    def __init__(self):
        self._cv = threading.Condition()
        self._running = {}
        self._waiting = {}
        self._tickets = []
        self._seq = 0
        self._total = 0
        self._waits = []   # (instant, secondes d'attente, priorité) des requêtes admises après avoir attendu
        self.dirty = threading.Event()

    @staticmethod
    def gated(kid, cap, total):
        """La requête passe-t-elle par la file ? Non si ni plafond de clé ni plafond global ne s'applique."""
        return bool(kid) and (int(cap or 0) > 0 or int(total or 0) > 0)

    def _eff(self, t, now):
        return max(1, t["prio"] - int((now - t["t"]) // AGING))

    def _rank(self, t, now):
        return (self._eff(t, now), t["seq"])

    def _blocked(self, t):
        return t["cap"] > 0 and self._running.get(t["kid"], 0) >= t["cap"]

    def _my_turn(self, me, total, now):
        if self._blocked(me):
            return False
        if total > 0 and self._total >= total:
            return False
        mine = self._rank(me, now)
        return not any(w is not me and not self._blocked(w) and self._rank(w, now) < mine for w in self._tickets)

    def acquire_ex(self, kid, cap, wait, prio=2, total=0, info=None, max_queue=0, now=None):
        """Retourne (admis, raison). raison : None | « timeout » (attente trop longue) | « full » (file pleine)."""
        cap, total = int(cap or 0), int(total or 0)
        if not self.gated(kid, cap, total):
            return True, None
        clock = now if callable(now) else time.time
        t0 = clock()
        deadline = t0 + wait
        with self._cv:
            if max_queue and len(self._tickets) >= int(max_queue) and not self._can_go_now(kid, cap, total, t0):
                return False, "full"
            self._seq += 1
            me = {"kid": kid, "cap": cap, "prio": priority_of(prio), "seq": self._seq, "t": t0, "info": dict(info or {})}
            self._tickets.append(me)
            self._waiting[kid] = self._waiting.get(kid, 0) + 1
            self.dirty.set()
            try:
                while not self._my_turn(me, total, clock()):
                    left = deadline - clock()
                    if left <= 0:
                        return False, "timeout"
                    self._cv.wait(min(left, 2))
                self._running[kid] = self._running.get(kid, 0) + 1
                self._total += 1
                waited = clock() - t0
                if waited >= 0.05:
                    self._waits.append((clock(), waited, me["prio"]))
                    del self._waits[:-300]
                return True, None
            finally:
                self._tickets.remove(me)
                self._waiting[kid] -= 1
                self._cv.notify_all()   # le suivant de la file peut maintenant passer
                self.dirty.set()

    def _can_go_now(self, kid, cap, total, now):
        if cap > 0 and self._running.get(kid, 0) >= cap:
            return False
        return not (total > 0 and self._total >= total) and not self._tickets

    def acquire(self, kid, cap, wait, **kw):
        return self.acquire_ex(kid, cap, wait, **kw)[0]

    def release(self, kid):
        with self._cv:
            if self._running.get(kid, 0) > 0:
                self._running[kid] -= 1
                if self._total > 0:
                    self._total -= 1
            self._cv.notify_all()
        self.dirty.set()

    def snapshot(self):
        with self._cv:
            keys = set(self._running) | set(self._waiting)
            return {k: {"running": self._running.get(k, 0), "waiting": self._waiting.get(k, 0)} for k in keys
                    if self._running.get(k, 0) or self._waiting.get(k, 0)}

    def waiting_list(self, now=None):
        """File d'attente dans l'ordre de passage : [{kid, who, model, prio, eff, waited}]."""
        now = now or time.time()
        with self._cv:
            ts = sorted(self._tickets, key=lambda t: self._rank(t, now))
            return [{"kid": t["kid"], "who": t["info"].get("who"), "model": t["info"].get("model"), "prio": t["prio"], "eff": self._eff(t, now),
                     "waited": round(now - t["t"], 1)} for t in ts]

    def total_running(self):
        with self._cv:
            return self._total

    def wait_stats(self, since=3600, now=None):
        """Attente des requêtes admises dans la dernière heure : nombre, moyenne et maximum (secondes), par priorité."""
        now = now or time.time()
        with self._cv:
            rows = [w for w in self._waits if now - w[0] <= since]
        out = {"n": len(rows), "avg": round(sum(w[1] for w in rows) / len(rows), 1) if rows else 0, "max": round(max([w[1] for w in rows] or [0]), 1), "by_prio": {}}
        for p in PRIORITIES:
            xs = [w[1] for w in rows if w[2] == p]
            if xs:
                out["by_prio"][str(p)] = {"n": len(xs), "avg": round(sum(xs) / len(xs), 1)}
        return out


class Tokens:
    """Jetons consommés par clé, par jour et par mois (heure locale du serveur)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.data = {}
        self.dirty = threading.Event()

    @staticmethod
    def _stamp(now=None):
        t = time.localtime(now or time.time())
        return time.strftime("%Y-%m-%d", t), time.strftime("%Y-%m", t)

    def _slot(self, kid, now=None):
        day, month = self._stamp(now)
        u = self.data.setdefault(kid, {"d": day, "day": 0, "m": month, "month": 0, "total": 0, "req": 0})
        if u["d"] != day:
            u["d"], u["day"] = day, 0
        if u["m"] != month:
            u["m"], u["month"] = month, 0
        return u

    def add(self, kid, n, now=None):
        if not kid or not n:
            return
        with self._lock:
            u = self._slot(kid, now)
            u["day"] += int(n)
            u["month"] += int(n)
            u["total"] += int(n)
            u["req"] += 1
        self.dirty.set()

    def exceeded(self, kid, quota_day, quota_month, now=None):
        """Message de refus si un quota est atteint, sinon None."""
        if not kid:
            return None
        with self._lock:
            u = self._slot(kid, now)
            if quota_day and u["day"] >= int(quota_day):
                return "quota journalier de %d jetons atteint (reprise à minuit)" % int(quota_day)
            if quota_month and u["month"] >= int(quota_month):
                return "quota mensuel de %d jetons atteint (reprise le mois prochain)" % int(quota_month)
        return None

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self.data))

    def load(self, data):
        if isinstance(data, dict):
            with self._lock:
                self.data.update({k: v for k, v in data.items() if isinstance(v, dict)})


def write_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except OSError:
        pass


def apply_rules(cands, rules, kid, model):
    """Règles de routage. cands : [(« local »|« remote », ..., serveur)] ; identifiant « local » ou celui du serveur distant.
    Règle : {"key": id|"*", "model": motif|"*", "server": "local"|id, "mode": "only"|"never"}.
    Retourne (candidats filtrés, True si au moins une règle s'applique)."""
    hits = [r for r in rules or [] if r.get("key") in ("*", kid) and fnmatch.fnmatch(model, str(r.get("model") or "*").lower())]
    if not hits:
        return cands, False
    only = {r["server"] for r in hits if r.get("mode") == "only"}
    never = {r["server"] for r in hits if r.get("mode") == "never"}

    def sid(c):
        return "local" if c[0] == "local" else c[3]["id"]
    return [c for c in cands if sid(c) not in never and (not only or sid(c) in only)], True


# ----------------------------------------------------------- affinité de session ---
SESSION_HEADER = "x-ollamabuntu-session"


def _flat(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in c if not isinstance(p, dict) or p.get("type") in (None, "text", "input_text"))
    return ""


def session_key(headers, body, kid="", model=""):
    """Identifiant stable d'une conversation, pour renvoyer ses requêtes vers le même serveur (le cache du début de prompt y est déjà chaud).
    Ordre : en-tête X-OllamaBuntu-Session, champ « user » (compatible OpenAI), sinon empreinte du message système et de la 1re question.
    Retourne None s'il n'y a rien de stable (requête isolée)."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    raw = str(h.get(SESSION_HEADER) or "").strip()[:128]
    d = None
    if not raw and body:
        try:
            d = json.loads(body)
        except (ValueError, TypeError):
            d = None
        if isinstance(d, dict):
            raw = str(d.get("user") or "").strip()[:128]
            if not raw and isinstance(d.get("messages"), list):
                system = next((_flat(m.get("content")) for m in d["messages"] if isinstance(m, dict) and m.get("role") == "system"), "")
                first = next((_flat(m.get("content")) for m in d["messages"] if isinstance(m, dict) and m.get("role") == "user"), "")
                if first or system:
                    raw = "h:" + hashlib.sha1((system[:300] + "\x00" + first[:300]).encode("utf-8", "replace")).hexdigest()[:16]
    return "%s|%s|%s" % (kid or "", model, raw) if raw else None


class Affinity:
    """Mémorise quel serveur a traité une conversation. Un serveur déjà bien plus occupé que les autres est abandonné (priorité à la charge)."""

    def __init__(self, ttl=900, slack=2, size=2000):
        self.ttl, self.slack, self.size = ttl, slack, size
        self._lock = threading.Lock()
        self._map = {}

    def order(self, skey, ordered_ids, busy, now=None):
        """ordered_ids : serveurs dans l'ordre normal de la répartition ; busy : {id: requêtes en cours}.
        Retourne la nouvelle liste (le serveur de la conversation en tête s'il est candidat et pas surchargé) et l'identifiant retenu."""
        now = time.time() if now is None else now
        if not skey or not ordered_ids:
            return list(ordered_ids), False
        with self._lock:
            sid, ts = self._map.get(skey, (None, 0))
            if sid in ordered_ids and now - ts <= self.ttl and busy.get(sid, 0) <= min(busy.get(i, 0) for i in ordered_ids) + self.slack:
                out, hit = [sid] + [i for i in ordered_ids if i != sid], True
            else:
                out, hit = list(ordered_ids), False
            self._map[skey] = (out[0], now)
            if len(self._map) > self.size:
                for k in sorted(self._map, key=lambda k: self._map[k][1])[:self.size // 4]:
                    self._map.pop(k, None)
        return out, hit


# ---------------------------------------------------- plafonds de contexte et de sortie ---
def apply_caps(path, body, max_ctx=0, max_output=0):
    """Plafonne la taille de contexte (options.num_ctx, API native) et la longueur de sortie (num_predict, max_tokens, max_completion_tokens).
    Une valeur absente ou illimitée reçoit le plafond de sortie ; le contexte n'est jamais ajouté (changer num_ctx recharge le modèle).
    Retourne (corps, [paramètres ramenés au plafond])."""
    if not body or not (max_ctx or max_output):
        return body, []
    try:
        d = json.loads(body)
    except (ValueError, TypeError):
        return body, []
    if not isinstance(d, dict):
        return body, []
    clamped = []
    native = path in ("/api/chat", "/api/generate")
    openai = path in ("/v1/chat/completions", "/v1/completions")
    if native:
        opts = d.get("options") if isinstance(d.get("options"), dict) else {}
        if max_ctx and isinstance(opts.get("num_ctx"), (int, float)) and opts["num_ctx"] > max_ctx:
            opts["num_ctx"] = int(max_ctx)
            clamped.append("num_ctx")
        if max_output:
            cur = opts.get("num_predict")
            if not isinstance(cur, (int, float)) or cur < 0 or cur > max_output:   # absent, -1 (illimité), -2 (jusqu'au remplissage du contexte) ou trop grand
                opts["num_predict"] = int(max_output)
                clamped.append("num_predict")
        d["options"] = opts
    elif openai and max_output:
        present = [k for k in ("max_tokens", "max_completion_tokens") if k in d]
        for k in present:
            if not isinstance(d[k], (int, float)) or d[k] <= 0 or d[k] > max_output:
                d[k] = int(max_output)
                clamped.append(k)
        if not present:
            d["max_tokens"] = int(max_output)
            clamped.append("max_tokens")
    else:
        return body, []
    return (json.dumps(d).encode() if clamped else body), clamped


class Health:
    """Mémoire des échecs récents par serveur : un serveur qui échoue plusieurs fois de suite est écarté un court moment (disjoncteur)."""

    def __init__(self, limit=3, window=60, cool=30):
        self.limit, self.window, self.cool = limit, window, cool
        self._lock = threading.Lock()
        self._fails = {}

    def fail(self, sid, now=None):
        now = time.time() if now is None else now
        with self._lock:
            xs = [t for t in self._fails.get(sid, []) if now - t < self.window]
            self._fails[sid] = xs + [now]

    def ok(self, sid):
        with self._lock:
            self._fails.pop(sid, None)

    def tripped(self, sid, now=None):
        now = time.time() if now is None else now
        with self._lock:
            xs = [t for t in self._fails.get(sid, []) if now - t < self.window]
            return len(xs) >= self.limit and now - xs[-1] < self.cool

