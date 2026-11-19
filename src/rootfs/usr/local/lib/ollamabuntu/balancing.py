"""Répartition de charge : puissance mesurée de chaque serveur, estimation de la durée d'une requête, files d'attente centrales.
Module pur (aucun réseau) : le routeur y puise, les tests le vérifient seul."""
import json
import os
import threading
import time

import limits

WAIT = object()   # « aucun serveur libre pour l'instant » : la requête attend dans la file centrale du routeur
STALE = 6 * 3600   # une mesure plus vieille que six heures n'est plus fiable (modèle déchargé, serveur changé)


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


class Perf:
    """Moyennes mobiles par (serveur, modèle servi) : délai avant le premier jeton et secondes par jeton produit ;
    longueur moyenne des réponses par modèle. Alimenté par chaque réponse réussie."""
    ALPHA = 0.3

    def __init__(self):
        self._lock = threading.Lock()
        self._s = {}      # (serveur, modèle) -> {"ttft", "spt", "n", "t"}
        self._len = {}    # modèle -> longueur moyenne des réponses, en jetons

    def update(self, sid, model, ttft, dur, out_tok, now=None):
        now = time.time() if now is None else now
        if not sid or not model or dur is None or dur <= 0:
            return
        ttft = _clip(float(ttft if ttft is not None else dur), 0.0, 120.0)
        out_tok = int(out_tok or 0)
        a = self.ALPHA
        with self._lock:
            s = self._s.setdefault((sid, model), {"ttft": None, "spt": None, "n": 0, "t": now})
            s["ttft"] = ttft if s["ttft"] is None else s["ttft"] + a * (ttft - s["ttft"])
            if out_tok >= 8 and dur > ttft:   # trop peu de jetons : la vitesse ne veut rien dire
                spt = _clip((dur - ttft) / out_tok, 0.0005, 5.0)
                s["spt"] = spt if s["spt"] is None else s["spt"] + a * (spt - s["spt"])
            s["n"] += 1
            s["t"] = now
            if out_tok > 0:
                self._len[model] = float(out_tok) if model not in self._len else self._len[model] + a * (out_tok - self._len[model])

    def predict(self, sid, model, now=None):
        """Durée attendue d'une requête seule sur ce serveur (secondes), ou None si on ne l'a pas encore mesurée."""
        now = time.time() if now is None else now
        with self._lock:
            s = self._s.get((sid, model))
            if not s or s["spt"] is None or now - s["t"] > STALE:
                return None
            return s["ttft"] + self._len.get(model, 100.0) * s["spt"]

    def ttft(self, sid, model, now=None):
        """Délai moyen avant la première réponse de ce serveur pour ce modèle (secondes), ou None."""
        now = time.time() if now is None else now
        with self._lock:
            s = self._s.get((sid, model))
            return s["ttft"] if s and s["ttft"] is not None and now - s["t"] <= STALE else None

    def services(self, pairs, now=None):
        """pairs : [(serveur, modèle servi)]. Durée attendue de chacun ; un serveur jamais mesuré prend la médiane des mesurés
        (ni favorisé ni écarté : il apprend vite), ou 1 s si personne n'est encore mesuré (le classement revient alors à « le moins occupé »)."""
        known = [self.predict(sid, model, now) for sid, model in pairs]
        vals = sorted(v for v in known if v is not None)
        default = vals[len(vals) // 2] if vals else 1.0
        return [default if v is None else v for v in known], bool(vals)

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            return {"%s|%s" % k: {"ttft": round(v["ttft"], 2), "spt": round(v["spt"], 4) if v["spt"] else None, "n": v["n"]}
                    for k, v in self._s.items() if now - v["t"] <= STALE}


def cost(service, busy, par, cold=0.0, load=0.0):
    """Durée attendue avant la fin d'une nouvelle requête sur ce serveur : sa propre durée, plus la file devant elle (requêtes en cours
    réparties sur les places du serveur), plus le coût d'un chargement de modèle (`cold`, en requêtes) et la charge mesurée (`load`, 0 à 100)."""
    return service * (1.0 + busy / float(max(par, 1)) + cold + load / 400.0)


def queue_delay(service, busy, par):
    """Attente avant que la requête commence, sur ce serveur."""
    return service * busy / float(max(par, 1))


def eff_prio(prio, t, now):
    """Priorité effective d'une requête qui attend : la critique (0) ne vieillit pas ; les autres gagnent un niveau toutes les 2 minutes."""
    if prio == 0:
        return 0
    return max(1, prio - int((now - t) // limits.AGING))


class Waiters:
    """Requêtes qui attendent une place sur un serveur du parc (file centrale). À manipuler sous le verrou du routeur."""

    def __init__(self):
        self._seq = 0
        self.items = {}

    def ticket(self, prio, model, now=None):
        self._seq += 1
        return {"seq": self._seq, "prio": limits.priority_of(prio), "t": time.time() if now is None else now, "model": model, "ids": set(), "queued": False}

    def register(self, tk, ids):
        tk["ids"] = set(ids)
        tk["queued"] = True
        self.items[tk["seq"]] = tk

    def drop(self, tk):
        self.items.pop(tk["seq"], None)
        tk["queued"] = False

    def must_yield(self, tk, free_ids, now):
        """Une requête mieux classée (priorité, puis ancienneté) attend-elle l'une des places libres ? Alors celle-ci lui laisse la place."""
        mine = (eff_prio(tk["prio"], tk["t"], now), tk["seq"])
        free = set(free_ids)
        for w in self.items.values():
            if w is tk or not (w["ids"] & free):
                continue
            if (eff_prio(w["prio"], w["t"], now), w["seq"]) < mine:
                return True
        return False

    def waiting(self, now=None):
        now = time.time() if now is None else now
        return sorted(({"model": w["model"], "prio": w["prio"], "waited": round(now - w["t"], 1)} for w in self.items.values()),
                      key=lambda x: (eff_prio(x["prio"], now - x["waited"], now), -x["waited"]))


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


class Popularity:
    """Requêtes par modèle et par heure de la journée, lissées sur plusieurs jours : de quoi charger à l'avance les modèles
    que les clients demandent d'ordinaire à cette heure."""
    ALPHA = 0.3

    def __init__(self, path=None):
        self.path = path
        self._lock = threading.Lock()
        d = load_json(path) if path else {}
        self._avg = d.get("avg") if isinstance(d.get("avg"), dict) else {}   # modèle -> [24 moyennes]
        self._cur = {}      # modèle -> requêtes de l'heure en cours
        self._hour = d.get("hour")
        self._dirty = False

    def hit(self, model, now=None):
        now = time.time() if now is None else now
        h = time.localtime(now).tm_hour
        with self._lock:
            self._roll(h)
            self._cur[model] = self._cur.get(model, 0) + 1

    def _roll(self, h):
        """Au changement d'heure, le compte de l'heure écoulée entre dans la moyenne (sous le verrou)."""
        if self._hour is None:
            self._hour = h
        if h == self._hour:
            return
        for m in set(self._avg) | set(self._cur):
            row = self._avg.setdefault(m, [0.0] * 24)
            row[self._hour] = row[self._hour] + self.ALPHA * (self._cur.get(m, 0) - row[self._hour])
        self._cur, self._hour, self._dirty = {}, h, True

    def expected(self, now=None, minimum=3.0):
        """Modèles attendus dans l'heure qui vient (moyenne de la même heure les jours précédents, ou rythme de l'heure en cours), du plus demandé au moins demandé."""
        now = time.time() if now is None else now
        h = time.localtime(now).tm_hour
        with self._lock:
            self._roll(h)
            scores = {}
            for m, row in self._avg.items():
                scores[m] = max(scores.get(m, 0.0), row[h])
            for m, c in self._cur.items():
                scores[m] = max(scores.get(m, 0.0), float(c))
            return [m for m, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v >= minimum]

    def save(self):
        if not self.path:
            return
        with self._lock:
            if not self._dirty:
                return
            data = {"avg": {m: [round(x, 2) for x in row] for m, row in self._avg.items()}, "hour": self._hour}
            self._dirty = False
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass
