#!/usr/bin/env python3
"""OllamaBuntu - journal d'audit des actions d'administration : qui a fait quoi, depuis où, avec quel résultat.
Fonctions pures. Aucune valeur secrète n'est jamais consignée (mots de passe, jetons, clés, phrases secrètes)."""
import csv
import io
import time

SECRET_WORDS = ("password", "passwd", "pass", "token", "secret", "key", "hash", "cookie", "authorization", "new", "current", "totp", "otp", "pin", "phrase", "salt", "private", "b64")
# Pas de journal pour ce qui n'est pas une action d'administration (conversations de test, relais d'inférence)
SKIP_PREFIXES = ("/api/privacy/test", "/api/rag/search", "/api/chat", "/api/fleet/ollama/", "/api/fleet/action", "/api/login")
LABELS = {
    "/api/logout": "Déconnexion", "/api/password": "Changement de son mot de passe",
    "/api/users": "Gestion des comptes", "/api/users/create": "Création d'un compte", "/api/users/delete": "Suppression d'un compte", "/api/users/reset": "Réinitialisation d'un mot de passe",
    "/api/models/pull": "Téléchargement d'un modèle", "/api/models/delete": "Suppression d'un modèle", "/api/models/custom": "Création d'un modèle personnalisé",
    "/api/models/context": "Taille de contexte d'un modèle", "/api/ollama-env": "Réglages d'Ollama",
    "/api/keys/create": "Création d'une clé d'API", "/api/keys/update": "Modification d'une clé d'API", "/api/keys/delete": "Suppression d'une clé d'API", "/api/keys/regenerate": "Renouvellement d'une clé d'API",
    "/api/publication": "Publication de l'API", "/api/alerts": "Réglage des alertes", "/api/alerts/test": "Test d'envoi des alertes",
    "/api/fleet/balance/strategy": "Répartition de charge", "/api/fleet/balance/test": "Test de répartition", "/api/queue/config": "File d'attente", "/api/redirects/config": "Redirection de modèles", "/api/fit/config": "Réglages de l'ajustement", "/api/fit/measure-ram": "Mesure du débit mémoire", "/api/fit/calibrate": "Calibrage de la carte", "/api/fit/apply": "Réglages appliqués d'après l'ajustement", "/api/llama/install": "Installation du moteur llama.cpp", "/api/llama/save": "Moteur MoE (réglages)", "/api/llama/action": "Moteur MoE (démarrage, arrêt)", "/api/llama/delete": "Moteur MoE supprimé", "/api/power/config": "Réveil et veille du parc (réglages)", "/api/power/server": "Réveil et veille d'un serveur", "/api/power/wake": "Réveil d'un serveur", "/api/power/sleep": "Mise en veille d'un serveur", "/api/power/member": "Mise en veille à distance (autorisation)", "/api/power/wol": "Réveil réseau d'une carte", "/api/costs/config": "Paramètres de coût", "/api/privacy/config": "Confidentialité des demandes", "/api/rag/upload": "Dépôt d'un document", "/api/rag/delete": "Suppression d'un document", "/api/rag/reindex": "Réindexation des documents", "/api/rag/config": "Réglages des documents", "/api/sso/config": "Configuration du SSO", "/api/sso/test": "Essai du SSO", "/sso/oidc/callback": "Connexion SSO (OpenID Connect)", "/api/login": "Connexion",
    "/api/prom/token": "Jeton Prometheus", "/api/gpu/guard/config": "Réparation automatique du GPU", "/api/gpu/guard/repair": "Réparation du GPU",
    "/api/perf/profile": "Profil de performance", "/api/perf/fix": "Réglage système de performance", "/api/perf/guard": "Garde-fou de débit",
    "/api/perf/apply-suggestion": "Réglage suggéré appliqué", "/api/perf/warmup": "Préchauffage des modèles", "/api/perf/warmup/run": "Préchauffage immédiat",
    "/api/bench/run": "Mesure de débit", "/api/lab/compare": "Comparaison de modèles", "/api/mu/config": "Mises à jour planifiées des modèles", "/api/mu/run": "Mise à jour de modèles", "/api/mu/rollback": "Retour à l'ancienne version d'un modèle", "/api/lab/suite": "Jeu de tests enregistré", "/api/lab/suite/delete": "Jeu de tests supprimé", "/api/lab/run": "Exécution d'un jeu de tests", "/api/bench/clear": "Effacement de l'historique de mesures",
    "/api/report/config": "Rapport hebdomadaire", "/api/report/send": "Envoi du rapport hebdomadaire", "/api/audit/clear": "Effacement du journal d'audit",
    "/api/requests/clear": "Effacement du journal des requêtes", "/api/backup/create": "Sauvegarde de la configuration", "/api/backup/restore": "Restauration de la configuration",
}
DETAIL_KEYS = 8


def _secret(k):
    k = str(k).lower()
    return any(w in k for w in SECRET_WORDS)


def _short(v, n=60):
    s = str(v).replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def describe(path, data):
    """(libellé, détail) d'une action : seuls les champs simples et non secrets sont repris."""
    label = LABELS.get(path) or path.replace("/api/", "", 1).replace("/", " › ")
    parts = []
    def add(prefix, d):
        for k, v in d.items():
            if len(parts) >= DETAIL_KEYS or _secret(k):
                continue
            if isinstance(v, bool) or isinstance(v, (int, float)):
                parts.append("%s%s=%s" % (prefix, k, v))
            elif isinstance(v, str) and v:
                parts.append("%s%s=%s" % (prefix, k, _short(v)))
            elif isinstance(v, list):
                parts.append("%s%s=%d élément(s)" % (prefix, k, len(v)))
            elif isinstance(v, dict) and not prefix:
                add(k + ".", v)
    if isinstance(data, dict):
        add("", data)
    return label, ", ".join(parts)[:240]


def entry(user, role, ip, path, data, status, now=None):
    label, detail = describe(path, data)
    return {"ts": int(now if now is not None else time.time()), "user": _short(user, 40), "role": _short(role or "", 20), "ip": _short(ip, 45), "path": path,
            "label": label, "detail": detail, "status": int(status), "ok": 200 <= int(status) < 400}


def skipped(path):
    return path.startswith(SKIP_PREFIXES)


def search(entries, q="", user="", status=""):
    """Du plus récent au plus ancien ; q cherche dans l'action, le détail et l'utilisateur ; status : ok | error."""
    q = (q or "").strip().lower()
    out = []
    for e in reversed(entries):
        if user and e.get("user") != user:
            continue
        if status == "ok" and not e.get("ok"):
            continue
        if status == "error" and e.get("ok"):
            continue
        if q and q not in (" ".join(str(e.get(k, "")) for k in ("label", "detail", "user", "path", "ip"))).lower():
            continue
        out.append(e)
    return out


_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def to_csv(entries):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["date", "utilisateur", "rôle", "adresse", "action", "détail", "chemin", "résultat"])
    for e in sorted(entries, key=lambda e: e.get("ts") or 0):
        row = [time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(e.get("ts") or 0)), e.get("user", ""), e.get("role", ""), e.get("ip", ""),
               e.get("label", ""), e.get("detail", ""), e.get("path", ""), "ok" if e.get("ok") else "refusé (%s)" % e.get("status")]
        w.writerow(["'" + c if isinstance(c, str) and c.startswith(_FORMULA) else c for c in row])
    return out.getvalue()
