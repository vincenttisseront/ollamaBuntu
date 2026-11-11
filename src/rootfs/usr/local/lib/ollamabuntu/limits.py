#!/usr/bin/env python3
"""OllamaBuntu - limites du routeur : requêtes simultanées par clé (file d'attente), quotas de jetons, règles de routage.
Bibliothèque standard de Python uniquement ; testable sans réseau."""
import fnmatch
import json
import os
import threading
import time


class Limiter:
    """Au plus `cap` requêtes en cours par clé ; les suivantes attendent leur tour (au plus `wait` secondes)."""

    def __init__(self):
        self._cv = threading.Condition()
        self._running = {}
        self._waiting = {}
        self.dirty = threading.Event()

    def acquire(self, kid, cap, wait):
        cap = int(cap or 0)
        if not kid or cap <= 0:
            return True
        deadline = time.time() + wait
        with self._cv:
            self._waiting[kid] = self._waiting.get(kid, 0) + 1
            self.dirty.set()
            try:
                while self._running.get(kid, 0) >= cap:
                    left = deadline - time.time()
                    if left <= 0:
                        return False
                    self._cv.wait(left)
                self._running[kid] = self._running.get(kid, 0) + 1
                return True
            finally:
                self._waiting[kid] -= 1
                self.dirty.set()

    def release(self, kid):
        with self._cv:
            if self._running.get(kid, 0) > 0:
                self._running[kid] -= 1
            self._cv.notify_all()
        self.dirty.set()

    def snapshot(self):
        with self._cv:
            keys = set(self._running) | set(self._waiting)
            return {k: {"running": self._running.get(k, 0), "waiting": self._waiting.get(k, 0)} for k in keys
                    if self._running.get(k, 0) or self._waiting.get(k, 0)}


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
