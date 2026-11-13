#!/usr/bin/env python3
"""OllamaBuntu - console d'administration web (HTTPS).

Bibliothèque standard de Python 3 uniquement : rien à installer.

  server.py                      lance le serveur (HTTPS 443 + redirection depuis 80)
  server.py --set-password USER  crée/met à jour un administrateur (mot de passe lu sur stdin)
  server.py --regen-cert         régénère le certificat auto-signé (nom + IP actuels)
  server.py --render-firewall    affiche les règles du pare-feu (nftables) d'après la configuration
  server.py --firewall-reset     rétablit l'administration (SSH, console) depuis tous les réseaux
"""
import base64
import glob
import grp
import calendar
import collections
import hashlib
import ipaddress
import hmac
import http.client
import http.cookies
import http.server
import json
import os
import pwd
import re
import secrets
import shlex
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # modules partagés avec le routeur
import privacy  # noqa: E402  détection et masquage des données sensibles, termes interdits
import rag  # noqa: E402  base de documents : extraction, découpage, vecteurs, recherche
import power  # noqa: E402  réveil (Wake-on-LAN) et mise en veille des serveurs du parc
import fit  # noqa: E402  ajustement d'un modèle à la mémoire : place, options, vitesse estimée
import llamacpp  # noqa: E402  moteur llama.cpp : fichier du modèle, ligne de commande, traduction Ollama / OpenAI
import updater  # noqa: E402  mise à jour depuis Internet (GitHub)
import monitor  # noqa: E402  débordement CPU/GPU, alertes, réglages recommandés
import backup  # noqa: E402  sauvegarde chiffrée de la configuration
import usage  # noqa: E402  statistiques d'usage, export CSV du journal des requêtes
import prom  # noqa: E402  exposition Prometheus
import hw  # noqa: E402  disponibilité des GPU pour Ollama, santé du matériel
import perf  # noqa: E402  mesure de débit, profils, préchauffage, garde-fou de débit
import audit  # noqa: E402  journal d'audit des actions d'administration
import report  # noqa: E402  rapport hebdomadaire
import modelupdate  # noqa: E402  mise à jour des modèles avec retour arrière
import evals  # noqa: E402  laboratoire : comparateur de modèles, tests de non-régression
import costs  # noqa: E402  imputation des coûts par clé et par équipe
import sso  # noqa: E402  connexion unique : OpenID Connect, LDAP / Active Directory

VERSION = "@@OB_VERSION@@"
ETC = os.environ.get("OB_ETC", "/etc/ollamabuntu")
SHARE = os.environ.get("OB_SHARE", "/usr/share/ollamabuntu")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
USERS_FILE = os.path.join(ETC, "users.json")
LEGACY_CRED = os.path.join(ETC, "admin.json")
BUILD_INFO = os.path.join(ETC, "build-info.json")
TLS_DIR = os.path.join(ETC, "tls")
CERT_FILE = os.path.join(TLS_DIR, "cert.pem")
KEY_FILE = os.path.join(TLS_DIR, "key.pem")
OLLAMA_ENV = os.path.join(ETC, "ollama.env")
JOBS_DIR = os.environ.get("OB_JOBS", "/var/lib/ollamabuntu/jobs")
MODELS_DIR = os.environ.get("OB_MODELS", "/usr/share/ollama/.ollama/models")
OLLAMA_LIB = os.environ.get("OB_OLLAMA_LIB", "/usr/local/lib/ollama")   # ROCm : lib/ollama/rocm_v7_2 (versionné)
OLLAMA_ADDR = os.environ.get("OB_OLLAMA", "127.0.0.1:11434")
HTTPS_PORT = int(os.environ.get("OB_HTTPS_PORT", "443"))
HTTP_PORT = int(os.environ.get("OB_HTTP_PORT", "80"))
# Points d'injection pour les tests (faux /sys, faux journal, faux paquets installés)
PCI_ROOT = os.environ.get("OB_PCI_ROOT", "/sys/bus/pci/devices")
SYS_ROOT = os.environ.get("OB_SYS_ROOT", "")
OLLAMA_LOG_FILE = os.environ.get("OB_OLLAMA_LOG", "")
FAKE_INSTALLED = os.environ.get("OB_INSTALLED")

SESSION_TTL = 8 * 3600
PBKDF2_ITERATIONS = 310_000
MAX_BODY = 2 * 1024 * 1024
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,199}$")
USER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
ROLES = ("admin", "utilisateur")
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/i18n/en.json": ("i18n/en.json", "application/json; charset=utf-8"),
}

LOG_SOURCES = {
    "ollama": ["journalctl", "--no-pager", "-o", "short-iso", "-n", "300", "-u", "ollama"],
    "admin": ["journalctl", "--no-pager", "-o", "short-iso", "-n", "300", "-u", "ollamabuntu-admin"],
    "kernel": ["journalctl", "--no-pager", "-o", "short-iso", "-n", "300", "-k", "-b"],
    "system": ["journalctl", "--no-pager", "-o", "short-iso", "-n", "300", "-p", "warning"],
    "install": "/var/log/ollamabuntu-install.log",
    "setup": "/var/log/ollamabuntu-setup.log",
}

# Paramètres avancés d'Ollama modifiables depuis l'interface (vide = valeur par défaut)
ENV_KEYS = [
    ("OLLAMA_KEEP_ALIVE", "Durée de maintien d'un modèle en mémoire (ex. 5m, 1h, -1 = toujours)"),
    ("OLLAMA_NUM_PARALLEL", "Requêtes traitées en parallèle par modèle"),
    ("OLLAMA_MAX_LOADED_MODELS", "Nombre maximal de modèles chargés simultanément"),
    ("OLLAMA_CONTEXT_LENGTH", "Taille de contexte par défaut (jetons)"),
    ("OLLAMA_FLASH_ATTENTION", "Flash attention : 1 = activée"),
    ("OLLAMA_KV_CACHE_TYPE", "Précision du cache de contexte : f16 (défaut), q8_0 (moitié moins de mémoire) ou q4_0 (quart) ; exige la flash attention"),
    ("OLLAMA_IGPU_ENABLE", "GPU intégrés (Intel, APU AMD) : 1 = autorisés"),
    ("OLLAMA_VULKAN", "Moteur Vulkan : 0 = désactivé"),
    ("HSA_OVERRIDE_GFX_VERSION", "AMD ROCm : forcer une cible GFX (ex. 10.3.0)"),
    ("CUDA_VISIBLE_DEVICES", "NVIDIA : GPU utilisés (ex. 0,1)"),
    ("GGML_VK_VISIBLE_DEVICES", "Vulkan : GPU utilisés (ex. 1)"),
    ("OLLAMA_SCHED_SPREAD", "Répartir chaque modèle sur tous les GPU : 1 = oui (sinon un seul GPU quand le modèle y tient)"),
]
ENV_VALUE_RE = re.compile(r"^[A-Za-z0-9.,:_+-]{0,64}$")

JOBS = {
    "update-os": ("Mise à jour du système", """\
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
set -e
apt-get update
apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade
apt-get -y autoremove
if [ -f /var/run/reboot-required ]; then echo ">>> Redémarrage nécessaire pour terminer la mise à jour."; fi
echo ">>> Mise à jour terminée."
"""),
    "install-nvidia": ("Installation du pilote NVIDIA", """\
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
set -e
apt-get update
command -v ubuntu-drivers >/dev/null || apt-get install -y ubuntu-drivers-common
echo ">>> Pilotes recommandés :"; ubuntu-drivers list --gpgpu || true
ubuntu-drivers install --gpgpu
# Utilitaires (nvidia-smi) de la même branche que le pilote installé,
# quelle que soit sa variante : 595, 595-server, 595-open, 595-server-open...
lib=$(dpkg-query -W -f='${db:Status-Abbrev} ${Package}\\n' 'libnvidia-compute-*' 2>/dev/null | awk '$1=="ii" {print $2}' | sort -V | tail -n1)
if [ -z "$lib" ]; then echo ">>> ERREUR : aucun pilote NVIDIA n'a été installé."; exit 1; fi
apt-get install -y "nvidia-utils-${lib#libnvidia-compute-}"
echo ">>> Pilote installé : ${lib#libnvidia-compute-}"
echo ">>> Redémarrez le serveur pour le charger (bouton dans Système ou ci-dessous)."
"""),
    "install-vulkan": ("Activation de l'accélération Vulkan (Intel / AMD)", """\
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
set -e
apt-get update
apt-get install -y mesa-vulkan-drivers libvulkan1 vulkan-tools
# permet à Ollama de lire la mémoire GPU disponible via Vulkan (documentation Ollama)
setcap cap_perfmon+ep /usr/local/bin/ollama || true
systemctl restart ollama
sleep 8
echo ">>> GPU vus par Vulkan :"; vulkaninfo --summary 2>/dev/null | grep -E "deviceName|deviceType" || true
echo ">>> Vulkan activé. L'onglet GPU indique si Ollama utilise la carte."
"""),
    "install-rocm": ("Installation du support AMD ROCm pour Ollama", """\
set -e
v=$(curl -fsS http://127.0.0.1:11434/api/version | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')
echo ">>> Ollama $v : téléchargement du module ROCm correspondant"
base="https://github.com/ollama/ollama/releases/download/v$v"
tmp=$(mktemp -d /var/tmp/ollama-rocm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
curl -fsSL --retry 3 -o "$tmp/sha256sum.txt" "$base/sha256sum.txt"
f=""; for n in ollama-linux-amd64-rocm.tar.zst ollama-linux-amd64-rocm.tgz; do grep -qE "[ /]$n\\$" "$tmp/sha256sum.txt" && { f=$n; break; }; done
[ -n "$f" ] || { echo ">>> ERREUR : pas de module ROCm pour Ollama $v"; exit 1; }
curl -fL --retry 3 --progress-bar -o "$tmp/$f" "$base/$f"
sum=$(grep -E "[ /]$f\\$" "$tmp/sha256sum.txt" | cut -d' ' -f1)
echo "$sum  $tmp/$f" | sha256sum -c -
case $f in *.zst) zstd -dc "$tmp/$f" | tar -xf - -C /usr/local --no-same-owner ;; *) tar -xzf "$tmp/$f" -C /usr/local --no-same-owner ;; esac
systemctl restart ollama
echo ">>> Module ROCm installé. L'onglet GPU indique si Ollama utilise la carte."
echo ">>> Les GPU AMD sont réglés automatiquement à chaque démarrage d'Ollama (détail par carte dans l'onglet GPU)."
"""),
}

JOBS.update({
    "install-smart": ("Installation de smartmontools (santé des disques)", "export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a\nset -e\napt-get install -y smartmontools\necho \">>> smartmontools installé : la santé des disques apparaît dans Système > Matériel.\"\n"),
    "apt-refresh": ("Recherche des mises à jour", "set -e\napt-get update\necho \">>> Listes des paquets actualisées.\"\n"),
    "update-security": ("Installation des mises à jour de sécurité", """\
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
set -e
apt-get update
pkgs=$(apt-get -s -o Debug::NoLocking=1 dist-upgrade | awk '/^Inst / && /-security/ {print $2}')
if [ -z "$pkgs" ]; then echo ">>> Aucune mise à jour de sécurité en attente."; exit 0; fi
echo ">>> $(echo $pkgs | wc -w) paquet(s) de sécurité : $pkgs"
apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install --only-upgrade $pkgs
if [ -f /var/run/reboot-required ]; then echo ">>> Redémarrage nécessaire pour terminer."; fi
echo ">>> Mises à jour de sécurité installées."
"""),
    "install-security": ("Installation des paquets de sécurité (pare-feu, mises à jour automatiques)", """\
set -e
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nftables unattended-upgrades
if [ ! -f /etc/ollamabuntu/.autoupdates-configured ]; then
  python3 /usr/local/lib/ollamabuntu/admin/server.py --init-autoupdates && touch /etc/ollamabuntu/.autoupdates-configured
  systemctl daemon-reload; systemctl restart apt-daily-upgrade.timer || true
fi
[ -f /etc/ollamabuntu/firewall.nft ] || python3 /usr/local/lib/ollamabuntu/admin/server.py --render-firewall > /etc/ollamabuntu/firewall.nft
systemctl enable --now ollamabuntu-firewall.service
echo ">>> Paquets de sécurité installés : le pare-feu et les mises à jour automatiques sont actifs."
"""),
    "webui-apply": ("Application de la politique d'usage de l'IA à Open WebUI", "exec /usr/local/lib/ollamabuntu/open-webui.sh apply\n"),
    "fleet-pull": ("Téléchargement des modèles synchronisés depuis la console principale", """\
if ! python3 -c 'import json,sys; sys.exit(0 if json.load(open("/etc/ollamabuntu/ai-policy.json")).get("ollama_internet", True) else 1)' 2>/dev/null \\
   && [ -f /etc/ollamabuntu/ai-policy.json ]; then
  echo ">>> Accès Internet d'Ollama désactivé par la politique d'usage de l'IA : téléchargement impossible sur ce serveur."
  exit 1
fi
rc=0
while read -r m; do
  [ -n "$m" ] || continue
  echo ">>> Téléchargement de $m"
  OLLAMA_HOST=127.0.0.1:11434 /usr/local/bin/ollama pull "$m" || { echo ">>> Échec : $m"; rc=1; }
done < /var/lib/ollamabuntu/fleet-pull.txt
exit $rc
"""),
    "appliance-update": ("Mise à jour de l'appliance depuis un CD/ISO ou une clé USB", "exec /usr/local/sbin/ollamabuntu-update --yes\n"),
    "appliance-update-online": ("Mise à jour de l'appliance depuis Internet (GitHub)", "exec /usr/bin/python3 /usr/local/lib/ollamabuntu/admin/updater.py apply --yes\n"),
    "config-reload": ("Rechargement après restauration de la configuration", "systemctl restart ollama.service ollamabuntu-router.service ollamabuntu-firewall.service || true\nexec systemctl restart ollamabuntu-admin.service\n"),
    "appliance-rollback": ("Retour à la version précédente de l'appliance", "exit 1\n"),
    "webui-install": ("Déploiement d'Open WebUI", "exec /bin/bash /usr/local/lib/ollamabuntu/open-webui.sh install\n"),
    "webui-update": ("Mise à jour d'Open WebUI", "exec /bin/bash /usr/local/lib/ollamabuntu/open-webui.sh update\n"),
    "webui-remove": ("Suppression du conteneur Open WebUI", "exec /bin/bash /usr/local/lib/ollamabuntu/open-webui.sh remove\n"),
    "webui-purge": ("Suppression d'Open WebUI et de ses données", "exec /bin/bash /usr/local/lib/ollamabuntu/open-webui.sh purge\n"),
})

_sessions = {}
_failures = {}
_lock = threading.Lock()
_users_lock = threading.Lock()
_cpu_prev = [None]


# ------------------------------------------------------------------ outils ---
def read_text(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def run(cmd, timeout=10, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def tail(path, size=65536):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            n = f.tell()
            f.seek(max(0, n - size))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def atomic_write(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def sysp(path):
    return SYS_ROOT + path


def boot_id():
    return read_text("/proc/sys/kernel/random/boot_id")


def uptime():
    try:
        return float(read_text("/proc/uptime", "0").split()[0])
    except (ValueError, IndexError):
        return 0.0


def ollama_version():
    try:
        return ollama_json("GET", "/api/version", timeout=3)[1].get("version")
    except OSError:
        return None


# ------------------------------------------------------- comptes et rôles ---
def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return {"algo": "pbkdf2_sha256", "iterations": PBKDF2_ITERATIONS,
            "salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(dk).decode()}


def verify_password(password, record):
    try:
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["hash"])
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(record["iterations"]))
        return hmac.compare_digest(dk, expected)
    except (KeyError, ValueError, TypeError):
        return False


def save_users(users):
    atomic_write(USERS_FILE, json.dumps({"users": users}, indent=1))


def load_users():
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f).get("users", {})
    except FileNotFoundError:
        pass
    except ValueError:
        return {}
    try:  # migration depuis l'ancien fichier à compte unique
        with open(LEGACY_CRED, encoding="utf-8") as f:
            old = json.load(f)
        name = old.pop("user")
        old.pop("updated", None)
        users = {name: {"role": "admin", "linux": True, "created": int(time.time()),
                        "updated": int(time.time()), "rev": secrets.token_hex(8), **old}}
        save_users(users)
        return users
    except (OSError, ValueError, KeyError):
        return {}


def password_problem(user, password):
    if len(password) < 8:
        return "Mot de passe trop court (8 caractères minimum)."
    if password == user:
        return "Le mot de passe doit être différent de l'identifiant."
    if any(ord(c) < 32 for c in password):
        return "Caractères de contrôle interdits dans le mot de passe."
    return None


def group_exists(name):
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def sys_user(name):
    try:
        return pwd.getpwnam(name)
    except KeyError:
        return None


def linux_cmd(cmd, stdin=None):
    r = subprocess.run(cmd, input=stdin, text=True, capture_output=True, timeout=30)
    if r.returncode != 0:
        raise ValueError("%s : %s" % (cmd[0], (r.stderr or r.stdout).strip()[:200]))


def linux_create(user, password, role):
    if sys_user(user):
        raise ValueError("Un compte Linux « %s » existe déjà sur ce serveur." % user)
    groups = [g for g in (("sudo", "adm", "ollama") if role == "admin" else ()) if group_exists(g)]
    cmd = ["useradd", "-m", "-s", "/bin/bash", "-c", "OllamaBuntu (%s)" % role]
    if groups:
        cmd += ["-G", ",".join(groups)]
    linux_cmd(cmd + [user])
    linux_cmd(["chpasswd"], "%s:%s\n" % (user, password))


def linux_set_role(user, role):
    if role == "admin":
        groups = [g for g in ("sudo", "adm", "ollama") if group_exists(g)]
        if groups:
            linux_cmd(["usermod", "-aG", ",".join(groups), user])
    else:
        for g in ("sudo", "adm"):
            subprocess.run(["gpasswd", "-d", user, g], capture_output=True, timeout=30)


def linux_delete(user):
    p = sys_user(user)
    if p and 1000 <= p.pw_uid < 60000:   # jamais un compte système ; le dossier personnel est conservé
        subprocess.run(["userdel", user], capture_output=True, timeout=30)


def public_users():
    return [{"user": u, "role": r.get("role", "utilisateur"), "linux": bool(r.get("linux")), "sso": r.get("sso") or "", "display": r.get("display") or "",
             "created": r.get("created"), "updated": r.get("updated")}
            for u, r in sorted(load_users().items())]


def set_admin_cli(user, password):
    """Utilisé par l'assistant console : crée ou met à jour l'administrateur principal."""
    with _users_lock:
        users = load_users()
        rec = users.get(user, {"created": int(time.time())})
        rec.update(hash_password(password))
        rec.update({"role": "admin", "linux": True, "updated": int(time.time()), "rev": secrets.token_hex(8)})
        users[user] = rec
        save_users(users)


# ------------------------------------------------ ajustement des modèles et moteur llama.cpp (modèles MoE) ---
FIT_FILE = os.path.join(ETC, "fit.json")             # débit mémoire mesuré, calibrage de la carte (aucun secret)
ENGINES_FILE = os.path.join(ETC, "engines.json")     # moteurs llama.cpp : lu par le routeur ET par chaque démon (une seule source)
LLAMA_GLOBAL = os.path.join(ETC, "llama.json")       # binaire installé
LLAMA_ROOT = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "llama")
LLAMA_REPO = os.environ.get("OB_LLAMA_REPO", "ggml-org/llama.cpp")
LLAMA_MAX_DOWNLOAD = 600 << 20
LLAMA_MAX_UNPACKED = 2 << 30
_fit_info = {}
_llama_inst = {"state": "idle", "log": [], "error": "", "t": 0}
_llama_lock = threading.Lock()
_engine_lock = threading.Lock()
FIT_LABELS = {"gpu": "Tient en mémoire vidéo", "ajuste": "Tient avec un réglage", "moe": "Experts en mémoire système", "couches": "Déborde (ralenti)", "trop": "Trop gros",
              "sans-gpu": "Sur le processeur", "inconnu": "Inconnu"}


def fit_hw():
    """Matériel : mémoire vidéo totale, mémoire système disponible, noms des cartes."""
    gpus = gpu_inventory()
    mem = meminfo()
    return {"vram": int(sum(parse_size(u.get("total")) for u in gpus)), "gpus": [str(u.get("description") or u.get("name") or "") for u in gpus],
            "ram_total": mem.get("MemTotal", 0), "ram_avail": mem.get("MemAvailable", 0)}


def fit_conf():
    d = load_json_file(FIT_FILE, {})
    out = {}
    for k in ("ram_gbps", "gpu_gbps"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out[k] = float(v)
    c = d.get("calib")
    if isinstance(c, dict) and isinstance(c.get("gpu_gbps"), (int, float)) and c["gpu_gbps"] > 0:
        out["calib"] = {"gpu_gbps": float(c["gpu_gbps"]), "model": str(c.get("model") or ""), "tps": c.get("tps"), "t": c.get("t")}
    return out


def fit_conf_save(**changes):
    d = fit_conf()
    d.update(changes)
    d = {k: v for k, v in d.items() if v is not None}
    atomic_write(FIT_FILE, json.dumps(d), 0o644)
    return d


def fit_show(name, digest):
    key = (name, digest)
    if key not in _fit_info:
        try:
            info = ollama_json("POST", "/api/show", {"model": name}, timeout=20)[1].get("model_info") or {}
        except (OSError, ValueError):
            info = {}
        if not info:
            return {}
        _fit_info[key] = info
    return _fit_info[key]


def fit_settings():
    """Réglages actuels d'Ollama : contexte par défaut, parallélisme, cache de contexte."""
    env = read_env()
    num = lambda k: int(env[k]) if str(env.get(k, "")).isdigit() else None
    return {"ctx": num("OLLAMA_CONTEXT_LENGTH"), "parallel": num("OLLAMA_NUM_PARALLEL") or 1, "kv": env.get("OLLAMA_KV_CACHE_TYPE") or "f16"}


def fit_one(m, hwr, st, ctx_conf, rows, now):
    """Étude d'un modèle installé (ligne de /api/tags). Retourne (forme, étude)."""
    shape = fit.model_from_show(m["name"], m.get("size"), fit_show(m["name"], m.get("digest")))
    if shape is None:
        return None, None
    want = ctx_conf.get(m["name"]) or ctx_conf.get(short_name(m["name"])) or st["ctx"]
    cur = {"ctx": want, "kv": st["kv"], "parallel": st["parallel"]} if want else None
    return shape, fit.plan(shape, hwr, want_ctx=want or min(shape.get("max_ctx") or 8192, 8192), parallel=st["parallel"], current=cur)


def fit_row(shape, plan, engines, rows, now):
    rec = next((s for s in plan["scenarios"] if s["id"] == plan["recommended"]), None)
    moe = next((s for s in plan["scenarios"] if s["mode"] == "moe"), None)
    return {"name": shape["name"], "weights": shape["weights"], "moe": shape["moe"], "experts": shape.get("experts"), "used": shape.get("used"), "layers": shape.get("layers"),
            "max_ctx": shape.get("max_ctx"), "verdict": plan["verdict"], "label": FIT_LABELS.get(plan["verdict"], plan["verdict"]), "known_shape": plan["kv_known"],
            "ctx": rec["ctx"] if rec else None, "kv": rec["kv"] if rec else None, "tps": rec["tps"] if rec else None, "tps_label": fit.speed_label(rec["tps"] if rec else None),
            "n_cpu_moe": moe["n_cpu_moe"] if moe else None, "measured": fit.measured_tps(rows, shape["name"], now, norm=short_name),
            "engine": any(short_name(e.get("model", "")) == short_name(shape["name"]) for e in engines)}


def fit_view(model=None):
    """Chaque modèle installé face à la mémoire du serveur ; le détail complet d'un modèle si `model` est donné."""
    hw_ = fit_hw()
    conf = fit_conf()
    hwr = fit.resolve_hw(hw_, conf)
    st = fit_settings()
    ctx_conf = load_json_file(CONTEXT_FILE, {}).get("models", {})
    now = time.time()
    rows_log = read_requests(20000)
    engines = engines_load()[0]
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    models, detail = [], None
    for m in sorted(tags, key=lambda t: t.get("name", "")):
        if str(m.get("name", "")).endswith("-cloud") or hidden_model(m.get("name", "")):
            continue
        shape, plan = fit_one(m, hwr, st, ctx_conf, rows_log, now)
        if shape is None:
            continue
        row = fit_row(shape, plan, engines, rows_log, now)
        models.append(row)
        if model and m["name"] == model:
            detail = dict(plan, row=row)
    return {"hw": {"vram": hw_["vram"], "gpus": hw_["gpus"], "ram_total": hw_["ram_total"], "ram_avail": hw_["ram_avail"], "gpu_theory": hwr["gpu_theory"], "gpu_eff": hwr["gpu_eff"],
                   "calibrated": hwr["calibrated"], "ram_measured": hwr["ram_measured"], "ram_eff": hwr["ram_eff"]}, "conf": conf, "settings": st, "models": models, "detail": detail}


def fit_hf(repo):
    """Quantifications d'un modèle Hugging Face face à la mémoire du serveur (forme sommaire : seule la taille est connue)."""
    f = hf_files(repo)
    hwr = fit.resolve_hw(fit_hw(), fit_conf())
    moe = fit.looks_moe(repo, f.get("arch") or "", f.get("tags") or [])
    st = fit_settings()
    for q in f["quants"]:
        cand = fit.candidate_from_hf(repo, q["size"], f.get("arch") or "", f.get("tags") or [], f.get("ctx"))
        p = fit.plan(cand, hwr, 8192, st["parallel"])
        rec = next((s for s in p["scenarios"] if s["id"] == p["recommended"]), None)
        q.update(verdict=p["verdict"], label=FIT_LABELS.get(p["verdict"], p["verdict"]), tps=rec["tps"] if rec else None, tps_label=fit.speed_label(rec["tps"] if rec else None),
                 n_cpu_moe=next((s["n_cpu_moe"] for s in p["scenarios"] if s["mode"] == "moe"), None))
    f.update(moe=moe, vram=hwr["vram"], ram_avail=hwr["ram_avail"], gpu_eff=hwr["gpu_eff"])
    return f


def fit_save_conf(data):
    out = {}
    for k, hi in (("ram_gbps", 2000.0), ("gpu_gbps", 10000.0)):
        if k in data:
            v = data[k]
            if v in (None, ""):
                out[k] = None
                continue
            try:
                v = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                raise ValueError("débit invalide")
            if not 1 <= v <= hi:
                raise ValueError("débit : 1 à %d Go/s" % hi)
            out[k] = round(v, 1)
    if data.get("clear_calibration"):
        out["calib"] = None
    return fit_conf_save(**out)


def fit_measure_ram(seconds=1.5, mb=48):
    """Débit de la mémoire système (Go/s) : copies de blocs sur plusieurs fils (ctypes libère le verrou de l'interpréteur). Mesure prudente
    (une copie lit et écrit : le débit de lecture seule d'une génération peut être plus haut). Dure ~2 s à pleine charge de la mémoire."""
    import ctypes
    n = max(1, min(os.cpu_count() or 2, 8))
    size = mb << 20
    done = [0] * n

    def work(i):
        src, dst = ctypes.create_string_buffer(size), ctypes.create_string_buffer(size)
        end, total = time.time() + seconds, 0
        while time.time() < end:
            ctypes.memmove(dst, src, size)
            total += size
        done[i] = total
    t0 = time.time()
    ths = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    gbps = round(sum(done) / max(time.time() - t0, 0.001) / 1e9, 1)
    fit_conf_save(ram_gbps=gbps)
    return gbps


def fit_calibrate(model):
    """Calibre la bande passante effective de la carte d'après le débit MESURÉ d'un modèle qui tient en mémoire vidéo."""
    hwr = fit.resolve_hw(fit_hw(), {k: v for k, v in fit_conf().items() if k != "calib"})
    try:
        m = next(t for t in ollama_json("GET", "/api/tags", timeout=10)[1].get("models", []) if t.get("name") == model)
    except (StopIteration, OSError, ValueError):
        raise ValueError("modèle introuvable")
    shape = fit.model_from_show(m["name"], m.get("size"), fit_show(m["name"], m.get("digest")))
    if shape is None:
        raise ValueError("forme du modèle inconnue")
    plan = fit.plan(shape, hwr, 8192, fit_settings()["parallel"])
    if plan["verdict"] not in ("gpu", "ajuste"):
        raise ValueError("ce modèle déborde de la mémoire vidéo : son débit ne mesure pas la carte")
    tps = fit.measured_tps(read_requests(20000), model, time.time(), norm=short_name)
    if tps is None:
        raise ValueError("pas assez de requêtes récentes de ce modèle (3 au moins, de 30 jetons ou plus) : utilisez-le puis réessayez, ou lancez une mesure dans Performance")
    sc = next((x for x in plan["scenarios"] if x["id"] == plan["recommended"]), None)
    if sc is None or sc["mode"] != "gpu" or sc["cpu_read"]:
        raise ValueError("ce modèle déborde de la mémoire vidéo : son débit ne mesure pas la carte")
    gbps = fit.calibrate(tps, sc["gpu_read"])   # octets lus par jeton : poids actifs et cache déjà rempli, comme dans l'estimation
    fit_conf_save(calib={"gpu_gbps": gbps, "model": model, "tps": tps, "t": int(time.time())})
    return {"gpu_gbps": gbps, "tps": tps}


def fit_apply(data):
    """Applique un scénario « tient en mémoire vidéo » : contexte du modèle et, si besoin, précision du cache (réglage global d'Ollama)."""
    model = str(data.get("model") or "")
    if not MODEL_RE.match(model):
        raise ValueError("nom de modèle invalide")
    ctx, kv = data.get("ctx"), data.get("kv") or "f16"
    if kv not in perf.KV_TYPES:
        raise ValueError("type de cache inconnu")
    set_model_context(model, ctx)
    cur = fit_settings()["kv"]
    if kv != cur:
        update_env(perf.normalize_env({"OLLAMA_KV_CACHE_TYPE": "" if kv == "f16" else kv}, read_env()))
    return {"ctx": check_ctx(ctx), "kv": kv}


# --- moteur llama.cpp
def engines_load():
    d = load_json_file(ENGINES_FILE, {})
    return [e for e in d.get("engines", []) if isinstance(e, dict)], d.get("exclusive") is not False


def engines_store(engines, exclusive=True):
    atomic_write(ENGINES_FILE, json.dumps({"exclusive": exclusive, "engines": engines}, ensure_ascii=False, indent=1), 0o644)


def llama_binary():
    g = load_json_file(LLAMA_GLOBAL, {})
    b = str(g.get("binary") or "")
    ok = bool(b) and os.path.isfile(b) and os.access(b, os.X_OK)
    return {"installed": ok, "path": b if ok else "", "tag": g.get("tag"), "backend": g.get("backend"), "asset": g.get("asset"), "sha256": g.get("sha256"), "installed_at": g.get("installed"), "repo": g.get("repo")}


def vulkan_ready():
    icd = sorted(os.path.basename(p) for d in ("/usr/share/vulkan/icd.d", "/etc/vulkan/icd.d") for p in glob.glob(os.path.join(d, "*.json")))
    loader = any(os.path.exists(p) for p in glob.glob("/usr/lib/*/libvulkan.so.1") + glob.glob("/usr/lib64/libvulkan.so.1") + glob.glob("/lib/*/libvulkan.so.1"))
    return {"loader": loader, "icd": icd}


def engine_unit(eid):
    return "ollamabuntu-llama@%s.service" % eid


def engine_status(e):
    try:
        st, d = ollama_json("GET", "/engine/status", timeout=3, addr="127.0.0.1:%d" % int(e["port"]))
        if st == 200 and isinstance(d, dict):
            d["service"] = "active"
            return d
    except (OSError, ValueError):
        pass
    svc = run(["systemctl", "is-active", engine_unit(e["id"])], timeout=5).strip() or "inactive"
    return {"state": "service arrêté" if svc != "activating" else "démarrage du service", "service": svc, "error": "", "tail": [], "inflight": 0, "requests": 0}


def engine_suggest(model):
    """Réglages proposés pour un moteur MoE d'après le calcul d'ajustement : couches d'experts en mémoire système, contexte, cache."""
    hwr = fit.resolve_hw(fit_hw(), fit_conf())
    st = fit_settings()
    try:
        m = next(t for t in ollama_json("GET", "/api/tags", timeout=10)[1].get("models", []) if t.get("name") == model)
    except (StopIteration, OSError, ValueError):
        return {}
    shape = fit.model_from_show(m["name"], m.get("size"), fit_show(m["name"], m.get("digest")))
    if shape is None or not shape.get("moe"):
        return {"moe": False}
    p = fit.plan(shape, hwr, st["ctx"] or 8192, 1)
    moe = next((s for s in p["scenarios"] if s["mode"] == "moe"), None)
    if moe is None:   # le modèle tient déjà : aucun expert à déplacer
        return {"moe": True, "n_cpu_moe": 0, "ctx": min(8192, shape.get("max_ctx") or 8192), "kv": "q8_0", "cpu_bytes": 0, "fits": True}
    return {"moe": True, "n_cpu_moe": moe["n_cpu_moe"], "ctx": moe["ctx"], "kv": moe["kv"], "cpu_bytes": moe["ram"], "tps": moe["tps"], "fits": False}


def engine_cpu_bytes(model, n_cpu_moe, ctx, kv, parallel):
    """Octets d'experts laissés en mémoire système pour ces réglages (affichés dans /api/ps ; 0 si inconnus)."""
    if not n_cpu_moe:
        return 0
    try:
        m = next(t for t in ollama_json("GET", "/api/tags", timeout=10)[1].get("models", []) if t.get("name") == model)
    except (StopIteration, OSError, ValueError):
        return 0
    shape = fit.model_from_show(m["name"], m.get("size"), fit_show(m["name"], m.get("digest")))
    if shape is None or not shape.get("moe"):
        return 0
    return int(fit.scenario(shape, fit.resolve_hw(fit_hw(), fit_conf()), int(ctx), kv, int(parallel), "moe", n_cpu_moe=int(n_cpu_moe))["ram"])


def engine_slug(model, taken):
    base = re.sub(r"[^a-z0-9]+", "-", short_name(model).lower()).strip("-")[:20] or "moteur"
    i, cand = 1, base
    while cand in taken:
        i += 1
        cand = "%s-%d" % (base[:20 - len(str(i)) - 1], i)
    return cand


def engine_save(data):
    """Crée ou modifie un moteur. Le modèle doit être installé dans Ollama (son fichier est lu sur place, jamais copié)."""
    with _engine_lock:
        engines, exclusive = engines_load()
        cur = next((e for e in engines if e.get("id") == data.get("id")), None) if data.get("id") else None
        model = str(data.get("model") or (cur or {}).get("model") or "")
        if not MODEL_RE.match(model):
            raise ValueError("nom de modèle invalide")
        _, err = llamacpp.find_gguf(MODELS_DIR, model)
        if err:
            raise ValueError(err)
        if any(e.get("model") == model and e is not cur and e.get("id") != (cur or {}).get("id") for e in engines):
            raise ValueError("ce modèle a déjà un moteur")
        d = dict(data)
        d.setdefault("model", model)
        if cur is None:
            d["id"] = engine_slug(model, {e.get("id") for e in engines})
            sug = engine_suggest(model)
            for k in ("n_cpu_moe", "ctx", "kv"):
                if k not in d or d[k] in (None, "") and k != "n_cpu_moe":
                    if sug.get(k) is not None:
                        d[k] = sug[k]
            d["port"], d["backend_port"] = llamacpp.free_ports(engines)
        cfg = llamacpp.config_clean(d, cur)
        cfg["cpu_bytes"] = engine_cpu_bytes(model, cfg.get("n_cpu_moe"), cfg["ctx"], cfg["kv"], cfg["parallel"])
        new = [cfg if e.get("id") == cfg["id"] else e for e in engines] if cur is not None else engines + [cfg]
        engines_store(new, exclusive)
    unit = engine_unit(cfg["id"])
    run(["systemctl", "enable", "--now", unit], timeout=30)
    if cur is not None:
        run(["systemctl", "restart", unit], timeout=30)   # le démon relit ses réglages au démarrage ; llama-server redémarre à la demande
    return cfg


def engine_delete(eid):
    with _engine_lock:
        engines, exclusive = engines_load()
        if not any(e.get("id") == eid for e in engines):
            raise ValueError("moteur introuvable")
        engines_store([e for e in engines if e.get("id") != eid], exclusive)
    run(["systemctl", "disable", "--now", engine_unit(eid)], timeout=60)


def engine_action(eid, act):
    e = next((x for x in engines_load()[0] if x.get("id") == eid), None)
    if e is None:
        raise ValueError("moteur introuvable")
    if act not in ("start", "stop", "restart"):
        raise ValueError("action inconnue")
    if act in ("start", "restart") and not llama_binary()["installed"]:
        raise ValueError("le moteur llama.cpp n'est pas installé")
    if run(["systemctl", "is-active", engine_unit(eid)], timeout=5).strip() != "active":
        run(["systemctl", "start", engine_unit(eid)], timeout=30)
        time.sleep(1)

    def go():
        try:
            ollama_json("POST", "/engine/" + act, {}, timeout=600 if act != "stop" else 60, addr="127.0.0.1:%d" % int(e["port"]))
        except (OSError, ValueError):
            pass
    if act == "stop":
        go()
    else:
        threading.Thread(target=go, daemon=True).start()   # le chargement d'un gros modèle dure : l'écran suit l'état
    return True


def engine_logs(eid):
    if not any(x.get("id") == eid for x in engines_load()[0]):
        raise ValueError("moteur introuvable")
    return {"text": run(["journalctl", "--no-pager", "-o", "short-iso", "-n", "200", "-u", engine_unit(eid)], timeout=15)}


def llama_view():
    engines, exclusive = engines_load()
    hw_ = fit_hw()
    out = []
    for e in engines:
        out.append(dict(e, status=engine_status(e)))
    cands = []
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    fv = fit_view() if tags else {"models": []}
    for r in fv["models"]:
        if r["moe"] and not r["engine"]:
            cands.append({"name": r["name"], "verdict": r["verdict"], "label": r["label"], "n_cpu_moe": r["n_cpu_moe"], "weights": r["weights"], "tps": r["tps"]})
    return {"binary": llama_binary(), "install": dict(_llama_inst, log=list(_llama_inst["log"])[-60:]), "engines": out, "exclusive": exclusive, "candidates": cands,
            "all_models": sorted(t["name"] for t in tags if not str(t.get("name", "")).endswith("-cloud") and not hidden_model(t.get("name", ""))),
            "vulkan": vulkan_ready(), "gpus": hw_["gpus"], "repo": LLAMA_REPO}


def _llama_log(msg):
    with _llama_lock:
        _llama_inst["log"].append(msg)
        del _llama_inst["log"][:-200]


def _llama_extract(archive, name, dest):
    """Extrait l'archive de llama.cpp : pas de chemin absolu ou remontant, liens relatifs internes seulement, taille bornée."""
    import tarfile
    import zipfile
    root = os.path.realpath(dest)
    os.makedirs(root, mode=0o755, exist_ok=True)
    total, listing = 0, []

    def target_ok(path):
        return os.path.realpath(path).startswith(root + os.sep) or os.path.realpath(path) == root
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for i in zf.infolist():
                n = i.filename
                if n.startswith("/") or ".." in n.split("/") or "\\" in n:
                    raise ValueError("archive refusée : chemin suspect (%s)" % re.sub(r"[^\w./-]", "?", n)[:60])
                total += i.file_size
                if total > LLAMA_MAX_UNPACKED:
                    raise ValueError("archive refusée : taille anormale")
                out = os.path.join(root, n)
                if i.is_dir() or n.endswith("/"):
                    os.makedirs(out, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if ((i.external_attr >> 16) & 0o170000) == 0o120000:   # lien symbolique (bibliothèques versionnées)
                    link = zf.read(i).decode()
                    if link.startswith("/") or not target_ok(os.path.join(os.path.dirname(out), link)):
                        raise ValueError("archive refusée : lien suspect (%s)" % re.sub(r"[^\w./-]", "?", n)[:60])
                    os.symlink(link, out)
                else:
                    with zf.open(i) as src, open(out, "wb") as f:
                        shutil.copyfileobj(src, f)
                    os.chmod(out, 0o755 if (i.external_attr >> 16) & 0o111 else 0o644)
                listing.append(n)
    else:
        with tarfile.open(archive) as tf:
            for m in tf:
                n = m.name
                if n.startswith("/") or ".." in n.split("/"):
                    raise ValueError("archive refusée : chemin suspect (%s)" % re.sub(r"[^\w./-]", "?", n)[:60])
                total += max(m.size, 0)
                if total > LLAMA_MAX_UNPACKED:
                    raise ValueError("archive refusée : taille anormale")
                out = os.path.join(root, n)
                if m.isdir():
                    os.makedirs(out, exist_ok=True)
                elif m.issym():
                    if m.linkname.startswith("/") or not target_ok(os.path.join(os.path.dirname(out), m.linkname)):
                        raise ValueError("archive refusée : lien suspect")
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    os.symlink(m.linkname, out)
                elif m.isreg():
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with tf.extractfile(m) as src, open(out, "wb") as f:
                        shutil.copyfileobj(src, f)
                    os.chmod(out, 0o755 if m.mode & 0o111 else 0o644)
                else:
                    raise ValueError("archive refusée : type de fichier inattendu")
                if not m.isdir():
                    listing.append(n)
    return listing


def _llama_install(backend):
    try:
        _llama_log("Recherche de la dernière version de %s..." % LLAMA_REPO)
        with updater._open("%s/repos/%s/releases/latest" % (updater.API, LLAMA_REPO), timeout=30) as r:
            rel = json.loads(updater._read_limited(r, 5 << 20))
        tag = str(rel.get("tag_name") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", tag):
            raise ValueError("version illisible dans la réponse de GitHub")
        asset = llamacpp.pick_asset(rel.get("assets"), backend)
        if asset is None:
            raise ValueError("aucun fichier Ubuntu « %s » dans la version %s : essayez un autre moteur de calcul" % (backend, tag))
        sha = llamacpp.digest_sha256(asset)
        if not sha:
            raise ValueError("GitHub ne publie pas la somme SHA-256 de ce fichier : installation refusée (elle ne pourrait pas être vérifiée)")
        name = str(asset["name"])
        _llama_log("Version %s, fichier %s (%d Mo)" % (tag, name, int(asset.get("size") or 0) >> 20))
        os.makedirs(LLAMA_ROOT, mode=0o755, exist_ok=True)
        part = os.path.join(LLAMA_ROOT, "download.part.%s" % ("zip" if name.lower().endswith(".zip") else "tgz"))
        got = updater._download(str(asset.get("browser_download_url") or ""), part, LLAMA_MAX_DOWNLOAD, name)
        if got != sha:
            os.remove(part)
            raise ValueError("somme SHA-256 incorrecte : téléchargement refusé")
        _llama_log("Somme SHA-256 vérifiée (%s...)" % sha[:12])
        dest = os.path.join(LLAMA_ROOT, tag + "-" + backend)
        tmp = dest + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        listing = _llama_extract(part, name, tmp)
        os.remove(part)
        rel_server = llamacpp.server_in_listing(listing)
        if not rel_server:
            raise ValueError("llama-server est absent de l'archive")
        binary = os.path.join(tmp, rel_server)
        os.chmod(binary, 0o755)
        env = dict(os.environ, LD_LIBRARY_PATH=os.path.dirname(binary) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""))
        r = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=30, env=env, cwd=os.path.dirname(binary))
        text = (r.stdout or "") + (r.stderr or "")
        if r.returncode not in (0, 1) or "--ctx-size" not in text:
            raise ValueError("llama-server ne démarre pas sur ce serveur : %s" % (text.strip().splitlines() or ["aucun message"])[-1][:200])
        caps = llamacpp.detect_caps(text)
        _llama_log("llama-server démarre (--n-cpu-moe : %s)." % ("oui" if caps["n_cpu_moe"] else "non, repli sur --override-tensor" if caps["override_tensor"] else "NON : à mettre à jour"))
        shutil.rmtree(dest, ignore_errors=True)
        os.rename(tmp, dest)
        final = os.path.join(dest, rel_server)
        atomic_write(LLAMA_GLOBAL, json.dumps({"binary": final, "tag": tag, "backend": backend, "asset": name, "sha256": sha, "installed": int(time.time()), "repo": LLAMA_REPO}), 0o644)
        for old in sorted(glob.glob(os.path.join(LLAMA_ROOT, "*-" + backend)), key=os.path.getmtime)[:-2]:   # on garde la version précédente
            shutil.rmtree(old, ignore_errors=True)
        for e in engines_load()[0]:   # les moteurs en marche reprennent le nouveau binaire à leur prochain démarrage
            try:
                ollama_json("POST", "/engine/stop", {}, timeout=60, addr="127.0.0.1:%d" % int(e["port"]))
            except (OSError, ValueError):
                pass
        if backend == "vulkan" and not vulkan_ready()["icd"]:
            _llama_log("Attention : aucun pilote Vulkan détecté. Installez-le (GPU > Activer Vulkan) avant de démarrer un moteur.")
        _llama_log("Installation terminée.")
        with _llama_lock:
            _llama_inst.update(state="done", error="", t=time.time())
    except (ValueError, OSError, updater.UpdateError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        msg = str(e) or e.__class__.__name__
        sys.stderr.write("installation de llama.cpp : %s\n" % msg)
        _llama_log("Échec : " + msg)
        with _llama_lock:
            _llama_inst.update(state="error", error=msg, t=time.time())


def llama_install(backend):
    if backend not in ("vulkan", "rocm", "cpu"):
        raise ValueError("moteur de calcul : vulkan, rocm ou cpu")
    with _llama_lock:
        if _llama_inst["state"] == "running":
            raise ValueError("une installation est déjà en cours")
        _llama_inst.update(state="running", log=[], error="", t=time.time())
    threading.Thread(target=_llama_install, args=(backend,), daemon=True).start()


# ------------------------------------------------ base de documents (RAG) ---
RAG_CONF = os.path.join(ETC, "rag.json")   # lu à chaud par le routeur (aucun secret)
RAG_DIR = os.environ.get("OB_RAG", os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "rag"))
EMBED_MODEL_RE = re.compile(r"embed|bge-|nomic|minilm|e5-", re.I)
MAX_UPLOAD_BODY = rag.MAX_UPLOAD * 4 // 3 + 4096   # base64 : un tiers de plus
_rag_store = {"s": None, "dir": None}
_rag_jobs = {}
_rag_lock = threading.Lock()
_rag_index_lock = threading.Lock()      # une indexation à la fois : le modèle d'embeddings sert aussi les conversations


def rag_store():
    if _rag_store["dir"] != RAG_DIR:
        _rag_store.update(s=rag.Store(RAG_DIR), dir=RAG_DIR)
    return _rag_store["s"]


def rag_config():
    try:
        return rag.config_clean(load_json_file(RAG_CONF, {}))
    except ValueError:
        return dict(rag.DEFAULTS)


def rag_save(data):
    cfg = rag.config_clean(data, rag_config())
    atomic_write(RAG_CONF, json.dumps(cfg), 0o644)
    return cfg


def rag_plain(name):
    s = short_name(name)
    return s[:-7] if s.endswith(":latest") else s


def rag_embed_models():
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        return []
    return sorted({rag_plain(m.get("name", "")) for m in tags if EMBED_MODEL_RE.search(m.get("name", ""))})


def rag_view():
    cfg, store = rag_config(), rag_store()
    docs = store.docs()
    with _rag_lock:
        jobs = [dict(j) for j in _rag_jobs.values()]
    models = rag_embed_models()
    stale = sum(1 for d in docs if d.get("model") != cfg["embed_model"])
    return {"settings": cfg, "docs": docs, "jobs": sorted(jobs, key=lambda j: -j["started"]), "collections": store.collections(), "chunks": sum(d.get("chunks", 0) for d in docs),
            "max_chunks": rag.MAX_CHUNKS, "embed_models": models, "model_ok": rag_plain(cfg["embed_model"]) in models, "stale": stale,
            "pdf": bool(shutil.which("pdftotext")), "max_upload": rag.MAX_UPLOAD}


def rag_job(jid, **kw):
    with _rag_lock:
        if jid in _rag_jobs:
            _rag_jobs[jid].update(kw)


def rag_embed_chunks(jid, model, texts):
    """Vecteurs des extraits, avec progression."""
    doc_prefix = rag.prefixes(model)[0]
    out = []
    for i in range(0, len(texts), 16):
        out.extend(rag.embed(main_addr(), model, [doc_prefix + t for t in texts[i:i + 16]], timeout=600))
        rag_job(jid, done=len(out))
    return out


def rag_index(jid, name, data, collection, sha, cfg):
    store = rag_store()
    try:
        with _rag_index_lock:
            rag_job(jid, state="extract")
            chunks = rag.chunk(rag.extract(name, data), cfg["chunk_chars"], cfg["overlap"])
            if not chunks:
                raise ValueError("aucun texte trouvé dans ce fichier")
            if len(chunks) > rag.MAX_DOC_CHUNKS:
                raise ValueError("document trop long : %d extraits (au plus %d) ; découpez-le ou augmentez la taille des extraits" % (len(chunks), rag.MAX_DOC_CHUNKS))
            if store.chunk_count() + len(chunks) > rag.MAX_CHUNKS:
                raise ValueError("la base atteindrait plus de %d extraits ; supprimez des documents" % rag.MAX_CHUNKS)
            rag_job(jid, state="embed", total=len(chunks), done=0)
            vecs = rag_embed_chunks(jid, cfg["embed_model"], [c["t"] for c in chunks])
            meta = {"id": jid, "name": name, "collection": collection, "model": cfg["embed_model"], "dim": len(vecs[0]), "chunks": len(chunks), "size": len(data),
                    "sha": sha, "added": int(time.time())}
            store.save(meta, chunks, vecs)
        with _rag_lock:
            _rag_jobs.pop(jid, None)
    except (ValueError, OSError, MemoryError) as e:
        sys.stderr.write("documents : indexation de « %s » impossible : %s\n" % (name, e))
        rag_job(jid, state="error", error=str(e)[:300])


def rag_reindex_doc(jid, did, cfg):
    store = rag_store()
    try:
        with _rag_index_lock:
            c = store._load(did)
            if not c:
                raise ValueError("document introuvable ou illisible")
            rag_job(jid, state="embed", total=len(c["chunks"]), done=0)
            vecs = rag_embed_chunks(jid, cfg["embed_model"], [x["t"] for x in c["chunks"]])
            store.save(dict(c["meta"], model=cfg["embed_model"], dim=len(vecs[0])), c["chunks"], vecs)
        with _rag_lock:
            _rag_jobs.pop(jid, None)
    except (ValueError, OSError, MemoryError) as e:
        sys.stderr.write("documents : réindexation impossible : %s\n" % e)
        rag_job(jid, state="error", error=str(e)[:300])


def rag_start(jid, name, collection, target, *args):
    with _rag_lock:
        if sum(1 for j in _rag_jobs.values() if j["state"] in ("queued", "extract", "embed")) >= 20:
            raise ValueError("trop de dépôts en cours d'indexation : attendez qu'ils se terminent")
        _rag_jobs[jid] = {"id": jid, "name": name, "collection": collection, "state": "queued", "done": 0, "total": 0, "error": "", "started": time.time()}
    threading.Thread(target=target, args=args, daemon=True).start()
    return jid


def rag_upload(data):
    name = os.path.basename(str(data.get("name") or "").replace("\\", "/")).strip()
    if not rag.NAME_RE.match(name):
        raise ValueError("nom de fichier invalide")
    collection = rag.collection_clean(data.get("collection") or "Général")
    try:
        raw = base64.b64decode(str(data.get("content_b64") or ""), validate=True)
    except (ValueError, TypeError):
        raise ValueError("contenu du fichier illisible")
    if not raw:
        raise ValueError("fichier vide")
    if len(raw) > rag.MAX_UPLOAD:
        raise ValueError("fichier trop volumineux (25 Mo au plus)")
    sha = hashlib.sha256(raw).hexdigest()
    store = rag_store()
    if any(d.get("sha") == sha and d["collection"] == collection for d in store.docs()):
        raise ValueError("ce document est déjà dans la base « %s »" % collection)
    ext = os.path.splitext(name.lower())[1]
    if ext not in rag.TEXT_EXT | {".html", ".htm", ".docx", ".odt", ".pdf"}:
        raise ValueError("format non pris en charge (%s) : texte, Markdown, CSV, JSON, HTML, Word (.docx), OpenDocument (.odt) ou PDF" % (ext or "sans extension"))
    if ext == ".pdf" and not shutil.which("pdftotext"):
        raise ValueError("PDF : le programme pdftotext n'est pas installé sur ce serveur (apt install poppler-utils) ; convertissez le fichier en texte ou en Word")
    cfg = rag_config()
    jid = store.new_id()
    rag_start(jid, name, collection, rag_index, jid, name, raw, collection, sha, cfg)
    return jid


def rag_delete(did):
    did = str(did or "")
    with _rag_lock:
        j = _rag_jobs.get(did)
        if j and j["state"] == "error":
            del _rag_jobs[did]
            return
        if j:
            raise ValueError("indexation en cours : attendez la fin avant de supprimer")
    rag_store().delete(did)


def rag_reindex(did=None):
    cfg, store = rag_config(), rag_store()
    todo = [d for d in store.docs() if (d["id"] == did if did else d.get("model") != cfg["embed_model"])]
    if did and not todo:
        raise ValueError("document introuvable")
    ids = []
    for d in todo:
        ids.append(rag_start(d["id"], d["name"], d["collection"], rag_reindex_doc, d["id"], d["id"], cfg))
    return ids


def rag_search(data, allowed=None):
    """Recherche pour la console : extraits les plus proches de la question + consigne système prête à l'emploi."""
    question = " ".join(str(data.get("question") or "").split())[:2000]
    if not question:
        raise ValueError("question vide")
    cfg, store = rag_config(), rag_store()
    colls = rag.collections_clean(data.get("collection") if data.get("collection") is not None else [])
    try:
        k = max(1, min(int(data.get("k") or cfg["top_k"]), 12))
    except (TypeError, ValueError):
        k = cfg["top_k"]
    q = rag.embed(main_addr(), cfg["embed_model"], [rag.prefixes(cfg["embed_model"])[1] + question], timeout=120)[0]
    hits, stale = store.search(q, colls, k, cfg["min_score"], cfg["embed_model"], allowed)
    return {"system": rag.build_system(hits), "sources": rag.citations(hits), "stale": stale, "model": cfg["embed_model"]}


# ------------------------------------------------ réveil et mise en veille des serveurs du parc ---
POWER_FILE = os.path.join(ETC, "power.json")                # réglages généraux (console principale)
POWER_MEMBER = os.path.join(ETC, "power-member.json")       # côté serveur géré : la console principale peut-elle le mettre en veille ?
POWER_LOG = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "power-log.json")
_power_lock = threading.Lock()
_power_mem = {}      # id du serveur -> {idle_since, woke_at, wake_sent, slept_at} : en mémoire (après un redémarrage de la console, le suivi repart de zéro)
_power_run = {"busy_since": None, "last": 0}
POWER_SUSPEND = ["systemctl", "--no-block", "--check-inhibitors=no"]


def power_config():
    try:
        return power.config_clean(load_json_file(POWER_FILE, {}))
    except ValueError:
        return dict(power.DEFAULTS)


def power_save(data):
    cfg = power.config_clean(data, power_config())
    atomic_write(POWER_FILE, json.dumps(cfg), 0o644)
    return cfg


def power_member_allow():
    a = load_json_file(POWER_MEMBER, {}).get("allow", "")
    return a if a in power.MODES else ""


def power_member_save(data):
    cfg = power.member_clean(data)
    atomic_write(POWER_MEMBER, json.dumps(cfg), 0o600)
    return cfg


def power_log(limit=60):
    d = load_json_file(POWER_LOG, [])
    return [e for e in d if isinstance(e, dict)][-limit:]


def power_event(kind, name, why, ok=True, detail=""):
    ev = power.event_line(time.time(), kind, name, why, ok, detail)
    with _power_lock:
        log = power_log(100)
        log.append(ev)
        try:
            atomic_write(POWER_LOG, json.dumps(log[-100:], ensure_ascii=False), 0o600)
        except OSError:
            pass
    return ev


def power_nics():
    """Cartes réseau filaires de CE serveur : adresse MAC (à saisir sur la console principale) et état du réveil réseau."""
    have = bool(shutil.which("ethtool"))
    nics = power.list_nics("/sys/class/net", (lambda i: run(["ethtool", i], timeout=5)) if have else None)
    return nics, have


def power_wol_set(iface, enable):
    """Active (ou désactive) le réveil réseau d'une carte, maintenant et à chaque démarrage (unité systemd ollamabuntu-wol@<carte>)."""
    nics, have = power_nics()
    if not have:
        raise ValueError("ethtool n'est pas installé sur ce serveur (apt install ethtool)")
    if iface not in {n["iface"] for n in nics}:
        raise ValueError("carte réseau inconnue")
    if enable and not next(n for n in nics if n["iface"] == iface)["supported"]:
        raise ValueError("cette carte ne prend pas en charge le réveil par paquet magique")
    r = subprocess.run(["systemctl", "enable" if enable else "disable", "--now", "ollamabuntu-wol@%s.service" % iface], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError("systemctl : %s" % (r.stderr or r.stdout).strip()[:200])
    if not enable:
        run(["ethtool", "-s", iface, "wol", "d"], timeout=10)


def power_member_sleep(mode):
    """Côté serveur géré : exécute la demande de mise en veille de la console principale, si l'administrateur local l'a autorisée."""
    if not power.allowed(power_member_allow(), mode):
        raise ValueError("ce serveur n'autorise pas sa mise en veille à distance (Système > Gestion centralisée > Mise en veille à distance)")
    if any(not j["done"] for j in list_jobs()):
        raise ValueError("une tâche est en cours sur ce serveur : mise en veille refusée")
    if mode == "suspend" and run(["systemctl", "can-suspend"], timeout=10).strip() != "yes":
        raise ValueError("ce serveur ne prend pas en charge la mise en veille (suspend)")

    def go():
        time.sleep(3)   # laisse partir la réponse
        sys.stderr.write("mise en veille (%s) demandée par la console principale\n" % mode)
        try:
            subprocess.run(POWER_SUSPEND + [mode], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            sys.stderr.write("mise en veille : %s\n" % e)
    threading.Thread(target=go, daemon=True).start()


def fleet_set_power(sid, data):
    with _fleet_lock:
        servers = load_fleet()
        for x in servers:
            if x["id"] == sid:
                x["power"] = power.server_clean(data, x.get("power"))
                break
        else:
            raise ValueError("serveur inconnu")
        save_fleet(servers)
    write_fleet_routes()
    return x["power"]


def power_server_state(s, now):
    st = _fleet_state.get(s["id"]) or {}
    m = _power_mem.get(s["id"]) or {}
    return power.state_of(st.get("state") == "en ligne", m.get("wake_sent"), m.get("slept_at"), now, power_config()["wake_timeout_s"])


def power_wake(sid, why="demandé par un administrateur"):
    s = fleet_server(sid)
    p = power.server_clean(s.get("power"))
    if not p["mac"]:
        raise ValueError("adresse MAC du serveur non renseignée")
    try:
        power.send_wol(p["mac"], p["broadcast"])
    except OSError as e:
        power_event("wake", s["name"], why, False, str(e))
        raise ValueError("envoi du paquet impossible : %s" % e)
    now = time.time()
    _power_mem.setdefault(s["id"], {}).update(wake_sent=now, idle_since=None)
    power_event("wake", s["name"], why)
    return {"sent": now}


def power_sleep(sid, why="demandé par un administrateur", mode=None):
    s = fleet_server(sid)
    p = power.server_clean(s.get("power"))
    mode = mode or p["sleep"] or "suspend"
    if mode not in ("suspend", "poweroff"):
        raise ValueError("mode inconnu")
    if not p["mac"]:
        raise ValueError("adresse MAC du serveur non renseignée : sans elle il ne pourrait pas être réveillé")
    try:
        code, data, _ = fleet_request(s["url"], "/api/fleet/action", s["token"], s["fingerprint"], "POST", {"action": "power-sleep", "data": {"mode": mode}}, timeout=30)
    except FleetError:
        raise ValueError("certificat du serveur changé : approuvez-le d'abord")
    except (OSError, ssl.SSLError) as e:
        raise ValueError("serveur injoignable : %s" % e)
    if code != 200:
        msg = data.get("error") or "refusé par le serveur (%d)" % code
        power_event("sleep", s["name"], why, False, msg)
        raise ValueError(msg)
    m = _power_mem.setdefault(s["id"], {})
    m.update(slept_at=time.time(), idle_since=None, woke_at=None)
    power_event("sleep", s["name"], why, True, mode)
    return {"mode": mode}


def power_inputs(now, cfg):
    """Photographie du parc pour power.decide : état de chaque serveur, demandes en attente, signaux du routeur, saturation."""
    lim = load_json_file(ROUTER_LIMITS, {})
    fresh = now - int(lim.get("t") or 0) < 30
    waiting = [{"model": short_name(w.get("model") or ""), "waited": w.get("waited", 0)} for w in (lim.get("waiting") or [])] if fresh else []
    hints = {short_name(k): float(v) for k, v in (lim.get("wake") or {}).items()} if fresh and isinstance(lim.get("wake"), dict) else {}
    servers = load_fleet()
    reqs = read_requests(4000) if any((s.get("power") or {}).get("sleep") for s in servers) else []
    last_req = {}
    for r in reqs:
        inst = str(r.get("instance") or "")
        if inst.startswith("serveur:"):
            last_req[inst[8:]] = max(last_req.get(inst[8:], 0), r.get("ts", 0))
    out, loads = [], []
    for s in servers:
        st = _fleet_state.get(s["id"]) or {}
        d = st.get("data") or {}
        p = power.server_clean(s.get("power"))
        m = _power_mem.setdefault(s["id"], {})
        state = power.state_of(st.get("state") == "en ligne", m.get("wake_sent"), m.get("slept_at"), now, cfg["wake_timeout_s"])
        load = avg_load(d.get("gpu_live"), (d.get("cpu") or {}).get("usage")) if state == "awake" else None
        if state == "awake":
            if m.get("wake_sent") and not m.get("woke_at"):
                m["woke_at"] = now
                power_event("wake-ok", s["name"], "le serveur répond de nouveau (%d s après le paquet)" % (now - m["wake_sent"]))
            m.pop("slept_at", None)
            power.track_idle(m, power.is_idle(load, d.get("jobs"), last_req.get(s["name"]), now), now)
            if s.get("route_token"):
                loads.append(load)
        else:
            m["idle_since"] = None
            if state == "offline" and m.get("wake_sent") and not m.get("failed") and now - m["wake_sent"] >= cfg["wake_timeout_s"]:
                m["failed"] = True
                power_event("wake-failed", s["name"], "aucune réponse %d s après le paquet" % cfg["wake_timeout_s"], False)
        if state != "offline" or not m.get("wake_sent"):
            m.pop("failed", None)
        out.append({"id": s["id"], "name": s["name"], "state": state, "power": p, "idle_since": m.get("idle_since"), "woke_at": m.get("woke_at"),
                    "wake_sent": m.get("wake_sent"),
                    "models": sorted(power.requestable([short_name(t.get("name") or t.get("model") or "") for t in d.get("model_tags", [])], s.get("model_map")))})
    last = (list(_metrics["samples"]) or [{}])[-1]
    loads.append(avg_load(gpu_metrics(), last.get("cpu")))   # ce serveur compte aussi parmi ceux qui travaillent
    return out, waiting, hints, loads


def power_tick(now=None):
    """Un passage : décide puis exécute (réveil par paquet, mise en veille à distance). Retourne les actions menées."""
    now = now or time.time()
    cfg = power_config()
    servers, waiting, hints, loads = power_inputs(now, cfg)
    _power_run["busy_since"] = power.track_busy(_power_run["busy_since"], power.saturated(loads, cfg["wake_busy_pct"]), now)
    done = []
    for a in power.decide(now, cfg, servers, waiting, hints, _power_run["busy_since"]):
        try:
            if a["action"] == "wake":
                power_wake(a["id"], a["why"])
            else:
                power_sleep(a["id"], a["why"], a.get("mode"))
            done.append(a)
        except ValueError as e:
            sys.stderr.write("réveil/veille (%s) : %s\n" % (a["name"], e))
    _power_run["last"] = now
    return done


def power_worker():
    time.sleep(10)
    while True:
        try:
            power_tick()
        except Exception as e:
            sys.stderr.write("réveil/veille : %s\n" % e)
        time.sleep(int(os.environ.get("OB_POWER_INTERVAL", "15")))


def power_view():
    now, cfg = time.time(), power_config()
    servers = []
    for s in load_fleet():
        st = _fleet_state.get(s["id"]) or {}
        d = st.get("data") or {}
        m = _power_mem.get(s["id"]) or {}
        servers.append({"id": s["id"], "name": s["name"], "state": power_server_state(s, now), "fleet_state": st.get("state", "en attente"), "power": power.server_clean(s.get("power")),
                        "idle_min": int((now - m["idle_since"]) // 60) if m.get("idle_since") else None, "wake_sent": m.get("wake_sent"), "failed": bool(m.get("failed")),
                        "nics": d.get("nics") or [], "allow": d.get("power_allow", ""), "tools": d.get("power_tools")})
    return {"settings": cfg, "servers": servers, "log": list(reversed(power_log())), "active": now - _power_run["last"] < 60, "limits": {k: list(v[:2]) for k, v in power.LIMITS.items()}}


# ------------------------------------------------ confidentialité : données sensibles et termes interdits ---
PRIVACY_FILE = os.path.join(ETC, "privacy.json")   # lu à chaud par le routeur (aucun secret)


def privacy_config():
    try:
        return privacy.config_clean(load_json_file(PRIVACY_FILE, {}))
    except ValueError:
        return privacy.default_config()


def privacy_save(data):
    cfg = privacy.config_clean(data, privacy_config())
    atomic_write(PRIVACY_FILE, json.dumps(cfg, ensure_ascii=False), 0o644)
    return cfg


def privacy_view():
    reqs, now = read_requests(20000), time.time()
    keys = [{"id": k["id"], "name": k["name"], "words": k.get("words") or []} for k in load_publication().get("keys", [])]
    return {"config": privacy_config(), "day": privacy.stats(reqs, now, 86400, short_name), "week": privacy.stats(reqs, now, 7 * 86400, short_name), "keys": keys,
            "limits": {"words": privacy.MAX_WORDS, "key_words": privacy.MAX_KEY_WORDS}, "categories": list(privacy.CATEGORIES)}


def privacy_test(data):
    """Essai sur un texte saisi dans la console : rien n'est enregistré ni consigné ; les réglages enregistrés sont appliqués."""
    text = str(data.get("text") or "")[:5000]
    cfg = privacy_config()
    masked, found = privacy.mask_text(text, privacy.active_cats(cfg))
    wrx = privacy.words_regex(cfg["words"] + privacy.words_clean(data.get("words") or [], privacy.MAX_KEY_WORDS))
    hits = []
    if wrx is not None:
        for m in wrx.finditer(privacy.fold(text)):
            w = text[m.start():m.end()]
            if w not in hits:
                hits.append(w)
    return {"masked": masked, "categories": sorted(found), "hits": hits, "action": cfg["words_action"], "anonymize": cfg["anonymize"]}


# ------------------------------------------------ connexion unique (SSO) : OpenID Connect, LDAP / Active Directory ---
SSO_FILE = os.path.join(ETC, "sso.json")   # contient le secret client et le mot de passe du compte de service : 0600
_sso_pending = {}    # state -> {nonce, verifier, exp} : connexions OIDC commencées (10 minutes, usage unique)
_sso_cache = {}      # découverte et clés publiques du fournisseur
_sso_lock = threading.Lock()
SSO_ERRORS = ("state", "idp", "denied", "config", "user")   # codes affichés sur la page de connexion (jamais de texte venu du fournisseur)


def sso_config():
    try:
        return sso.config_clean(load_json_file(SSO_FILE, {}))
    except ValueError:
        return json.loads(json.dumps(sso.DEFAULTS))


def sso_save(data):
    cfg = sso.config_clean(data, sso_config())
    atomic_write(SSO_FILE, json.dumps(cfg, ensure_ascii=False), 0o600)
    with _sso_lock:
        _sso_cache.clear()
    return cfg


def sso_view():
    cfg = sso_config()
    v = sso.public_view(cfg)
    v["oidc"]["redirect_uri"] = (cfg["oidc"]["redirect_base"] + "/sso/oidc/callback") if cfg["oidc"]["redirect_base"] else ""
    v["users"] = sum(1 for r in load_users().values() if r.get("sso"))
    return v


def sso_providers():
    """Ce que la page de connexion doit proposer (public : aucun secret, aucun détail de configuration)."""
    cfg = sso_config()
    return {"oidc": cfg["oidc"]["name"] if cfg["oidc"]["enabled"] else None, "ldap": bool(cfg["ldap"]["enabled"])}


def sso_upsert(kind, raw, role, sub=None, display=None):
    """Crée ou met à jour le compte local d'un utilisateur SSO (nom préfixé, aucun mot de passe). Le rôle suit les groupes à chaque connexion."""
    name = sso.account_name(kind, raw)
    if not name:
        raise ValueError("identifiant SSO inutilisable")
    with _users_lock:
        users = load_users()
        rec = users.get(name)
        now = int(time.time())
        if rec:
            if rec.get("sso") != kind or (sub and rec.get("sub") and rec["sub"] != sub):
                raise ValueError("ce nom est déjà associé à une autre identité")   # un fournisseur qui réattribue un identifiant ne reprend pas le compte
            if rec.get("role") != role or rec.get("display") != display:
                rec.update(role=role, display=display, updated=now)
                save_users(users)
        else:
            rec = {"role": role, "linux": False, "sso": kind, "created": now, "updated": now, "rev": secrets.token_hex(8), "display": display}
            if sub:
                rec["sub"] = sub
            users[name] = rec
            save_users(users)
    return name, rec


def sso_ldap_login(username, password):
    """Connexion par l'annuaire. Retourne (compte, rôle, enregistrement). AuthFailed : refus ; ValueError : annuaire mal réglé ou injoignable ; PermissionError : aucun groupe autorisé."""
    cfg = sso_config()
    if not cfg["ldap"]["enabled"]:
        raise sso.AuthFailed("annuaire désactivé")
    info = sso.ldap_login(cfg["ldap"], username, password)
    role = sso.role_for(info["groups"], cfg["roles"], cfg["default_role"])
    if not role:
        raise PermissionError(info["login"])
    name, rec = sso_upsert("ldap", info["login"], role, sub=info["dn"].lower(), display=info["name"])
    return name, role, rec


def sso_disco(oc):
    with _sso_lock:
        hit = _sso_cache.get("disco")
        if hit and time.time() - hit[0] < 600:
            return hit[1]
    doc = sso.discovery(oc)
    with _sso_lock:
        _sso_cache["disco"] = (time.time(), doc)
    return doc


def sso_jwks(oc, disco, refresh=False):
    with _sso_lock:
        hit = _sso_cache.get("jwks")
        if hit and not refresh and time.time() - hit[0] < 3600:
            return hit[1]
        if hit and refresh and time.time() - hit[0] < 60:   # pas plus d'un rechargement par minute
            return hit[1]
    doc = sso.fetch_json(disco["jwks_uri"], ca_pem=oc.get("ca_pem", ""))
    with _sso_lock:
        _sso_cache["jwks"] = (time.time(), doc)
    return doc


def sso_oidc_begin():
    """Début d'une connexion OIDC : (adresse d'autorisation, state)."""
    cfg = sso_config()
    oc = cfg["oidc"]
    if not oc["enabled"]:
        raise ValueError("config")
    disco = sso_disco(oc)
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = sso.pkce_pair()
    now = time.time()
    with _sso_lock:
        for k in [k for k, v in _sso_pending.items() if v["exp"] < now]:
            del _sso_pending[k]
        if len(_sso_pending) >= 500:
            raise ValueError("trop de connexions en cours")
        _sso_pending[state] = {"nonce": nonce, "verifier": verifier, "exp": now + 600}
    return sso.auth_url(disco["authorization_endpoint"], oc["client_id"], oc["redirect_base"] + "/sso/oidc/callback", oc["scopes"], state, nonce, challenge), state


def sso_oidc_finish(code, state):
    """Fin d'une connexion OIDC. Retourne (compte, rôle, enregistrement). ValueError(code) avec un code de SSO_ERRORS."""
    with _sso_lock:
        pend = _sso_pending.pop(state, None)
    if not pend or pend["exp"] < time.time():
        raise ValueError("state")
    cfg = sso_config()
    oc = cfg["oidc"]
    if not oc["enabled"]:
        raise ValueError("config")
    try:
        disco = sso_disco(oc)
        tok = sso.token_request(oc, disco, code, oc["redirect_base"] + "/sso/oidc/callback", pend["verifier"])
        idt = tok.get("id_token")
        if not idt:
            raise ValueError("pas de jeton d'identité")
        try:
            claims = sso.verify_id_token(idt, sso_jwks(oc, disco), oc["issuer"], oc["client_id"], pend["nonce"])
        except ValueError as e:
            if "clé de signature inconnue" not in str(e):
                raise
            claims = sso.verify_id_token(idt, sso_jwks(oc, disco, refresh=True), oc["issuer"], oc["client_id"], pend["nonce"])
        groups = sso.claim_values(claims, oc["groups_claim"])
        if not groups and disco.get("userinfo_endpoint") and tok.get("access_token"):
            ui = sso.fetch_json(disco["userinfo_endpoint"], headers={"Authorization": "Bearer " + str(tok["access_token"])}, ca_pem=oc.get("ca_pem", ""))
            if ui.get("sub") == claims["sub"]:
                groups = sso.claim_values(ui, oc["groups_claim"])
                for k in ("preferred_username", "email", "name"):
                    claims.setdefault(k, ui.get(k))
    except ValueError as e:
        sys.stderr.write("SSO OIDC : %s\n" % e)
        raise ValueError("idp")
    role = sso.role_for(groups, cfg["roles"], cfg["default_role"])
    if not role:
        raise ValueError("denied")
    raw = claims.get("preferred_username") or claims.get("email") or claims["sub"]
    try:
        name, rec = sso_upsert("sso", raw, role, sub=claims["sub"], display=str(claims.get("name") or raw)[:80])
    except ValueError:
        raise ValueError("user")
    return name, role, rec


def sso_test(data):
    """Essai de la configuration enregistrée. OIDC : découverte + clés. LDAP : connexion et compte de service, puis, si un identifiant est fourni, une vraie connexion (sans créer de compte)."""
    cfg = sso_config()
    kind = data.get("kind")
    if kind == "oidc":
        oc = cfg["oidc"]
        if not oc["issuer"]:
            raise ValueError("renseignez et enregistrez d'abord l'émetteur")
        with _sso_lock:
            _sso_cache.clear()
        disco = sso.discovery(oc)
        keys = sso.fetch_json(disco["jwks_uri"], ca_pem=oc.get("ca_pem", "")).get("keys") or []
        rsa = [k for k in keys if isinstance(k, dict) and k.get("kty") == "RSA"]
        if not rsa:
            raise ValueError("le fournisseur ne publie aucune clé RSA (seul RS256/384/512 est pris en charge)")
        algs = disco.get("id_token_signing_alg_values_supported")
        if algs and not any(a in algs for a in ("RS256", "RS384", "RS512")):
            raise ValueError("le fournisseur ne signe pas en RS256 (algorithmes annoncés : %s)" % ", ".join(str(a) for a in algs[:6]))
        return {"ok": True, "issuer": disco["issuer"], "keys": len(rsa), "groups_claim_advertised": "groups" in (disco.get("claims_supported") or [])}
    if kind == "ldap":
        lc = cfg["ldap"]
        if not lc["host"] or not lc["base_dn"]:
            raise ValueError("renseignez et enregistrez d'abord le serveur et la base de recherche")
        user, pw = str(data.get("user") or ""), str(data.get("password") or "")
        if not user:
            c = sso.ldap_connect(lc)
            try:
                code, diag = c.bind(lc["bind_dn"], lc["bind_password"]) if lc["bind_dn"] else c.bind("", "")
                if code != 0:
                    raise ValueError("le compte de service est refusé (code %d) : %s" % (code, diag[:100]))
            finally:
                c.close()
            return {"ok": True, "bound": lc["bind_dn"] or "(anonyme)"}
        try:
            info = sso.ldap_login(lc, user, pw)
        except sso.AuthFailed:
            raise ValueError("identifiant introuvable (ou ambigu), ou mot de passe incorrect")
        return {"ok": True, "dn": info["dn"], "name": info["name"], "groups": info["groups"][:30], "role": sso.role_for(info["groups"], cfg["roles"], cfg["default_role"])}
    raise ValueError("type d'essai inconnu")


# ------------------------------------------------------------- certificat ---
def local_ips():
    res = []
    try:
        for itf in json.loads(run(["ip", "-j", "addr", "show"]) or "[]"):
            if itf.get("ifname") == "lo":
                continue
            for a in itf.get("addr_info", []):
                if a.get("scope") == "global" and a.get("local"):
                    res.append({"iface": itf.get("ifname"), "family": a.get("family"),
                                "addr": "%s/%s" % (a["local"], a.get("prefixlen", ""))})
    except ValueError:
        pass
    return res


def regen_cert():
    os.makedirs(TLS_DIR, mode=0o700, exist_ok=True)
    host = socket.gethostname()
    names = {"DNS:" + host, "DNS:localhost", "IP:127.0.0.1"}
    for line in read_text("/etc/hosts").splitlines():
        parts = line.split()
        if parts and parts[0] == "127.0.1.1":
            names.update("DNS:" + p for p in parts[1:] if re.fullmatch(r"[A-Za-z0-9.-]+", p))
    for ip in local_ips():
        names.add("IP:" + ip["addr"].split("/")[0])
    key_tmp, cert_tmp = KEY_FILE + ".new", CERT_FILE + ".new"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                    "-days", "3650", "-keyout", key_tmp, "-out", cert_tmp,
                    "-subj", "/CN=%s/O=OllamaBuntu" % host,
                    "-addext", "subjectAltName=" + ",".join(sorted(names)),
                    "-addext", "extendedKeyUsage=serverAuth"],
                   check=True, capture_output=True)
    os.chmod(key_tmp, 0o600)
    os.replace(key_tmp, KEY_FILE)
    os.replace(cert_tmp, CERT_FILE)


# --------------------------------------------------------------- sessions ---
def new_session(user, role, stamp):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        for k in [k for k, v in _sessions.items() if v["exp"] < now]:
            del _sessions[k]
        _sessions[token] = {"user": user, "role": role, "stamp": stamp, "exp": now + SESSION_TTL}
    return token


def session_get(token):
    """Session valide -> (utilisateur, rôle). Un compte supprimé ou dont le mot de passe
    a changé invalide aussitôt ses autres sessions."""
    if not token:
        return None
    with _lock:
        s = _sessions.get(token)
        if not s or s["exp"] < time.time():
            _sessions.pop(token, None)
            return None
    rec = load_users().get(s["user"])
    if not rec or rec.get("rev") != s["stamp"]:
        with _lock:
            _sessions.pop(token, None)
        return None
    return s["user"], rec.get("role", "utilisateur")


def session_restamp(token, stamp):
    with _lock:
        if token in _sessions:
            _sessions[token]["stamp"] = stamp


def too_many_failures(ip):
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(ip, []) if now - t < 300]
        _failures[ip] = recent
        return len(recent) >= 5


def record_failure(ip):
    with _lock:
        _failures.setdefault(ip, []).append(time.time())


# ----------------------------------------------------------------- Ollama ---
def ollama_conn(timeout, addr=None):
    """Instance principale par défaut (gestion des modèles) ; addr=OLLAMA_ADDR pour passer par le routeur."""
    host, port = (addr or main_addr()).rsplit(":", 1)
    return http.client.HTTPConnection(host, int(port), timeout=timeout)


def hidden_model(name):
    """Variantes techniques non listées : copies « -gpuN » (épinglage) et copies de sécurité des mises à jour (ob-prev/...)."""
    return bool(re.search(r"-gpu\d+$", str(name))) or modelupdate.is_prev(name)


def ollama_json(method, path, body=None, timeout=15, addr=None):
    conn = ollama_conn(timeout, addr)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=payload,
                     headers={"Content-Type": "application/json"} if payload else {})
        resp = conn.getresponse()
        raw = resp.read()
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            data = {"error": raw.decode(errors="replace")[:500]}
        return resp.status, data
    finally:
        conn.close()


def read_env():
    env = {}
    for line in read_text(OLLAMA_ENV).splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"')
    return env


def update_env(changes, restart=True):
    env = read_env()
    env.update(changes)
    lines = ["# Variables d'environnement d'Ollama (gérées par l'administration web OllamaBuntu)"]
    lines += ["%s=%s" % (k, v) for k, v in env.items() if v != ""]
    atomic_write(OLLAMA_ENV, "\n".join(lines) + "\n", 0o644)
    if restart:
        pools = load_pools()
        if pools:   # réglages repris par chaque groupe ; adresse publique portée par le routeur
            with _pools_lock:
                apply_pools(pools)
        else:
            run(["systemctl", "restart", "ollama.service"], timeout=60)


def ollama_exposed():
    return bool(load_publication().get("enabled"))


# ------------------------------------------------------------------- GPU ----
VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel", "0x1a03": "ASPEED", "0x102b": "Matrox",
           "0x15ad": "VMware", "0x1234": "QEMU", "0x1b36": "QEMU", "0x1af4": "Virtio",
           "0x1414": "Microsoft Hyper-V", "0x1013": "Cirrus Logic", "0x19e5": "Huawei"}
# Contrôleurs d'affichage de BMC (iDRAC/iLO...) et cartes graphiques virtuelles
DISPLAY_ONLY = {"0x1a03", "0x102b", "0x15ad", "0x1234", "0x1b36", "0x1af4", "0x1414", "0x1013", "0x19e5"}
LOGFMT = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')


def logfmt(line):
    return {k: (v[1:-1].replace('\\"', '"') if v.startswith('"') else v) for k, v in LOGFMT.findall(line)}


def parse_discovery(text):
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if "discovering available GPUs" in l]
    used, dropped = [], []
    for line in lines[starts[-1] if starts else 0:]:
        if 'msg="inference compute"' in line:
            used.append(logfmt(line))
        elif "dropping integrated GPU" in line:
            dropped.append(logfmt(line))
    return used, dropped


_LOG_CACHE = {}
LOG_CACHE_TTL = 20


def ollama_log_text(unit="ollama.service"):
    """Lecture du journal d'Ollama, mémorisée 20 s : un affichage de l'écran GPU la demande plusieurs fois et chaque lecture
    peut durer plusieurs secondes sur un gros journal."""
    if OLLAMA_LOG_DIR or (OLLAMA_LOG_FILE and unit == "ollama.service"):
        return _ollama_log_text(unit)
    now = time.monotonic()
    hit = _LOG_CACHE.get(unit)
    if hit and now - hit[0] < LOG_CACHE_TTL:
        return hit[1]
    text = _ollama_log_text(unit)
    _LOG_CACHE[unit] = (time.monotonic(), text)
    return text


def _ollama_log_text(unit="ollama.service"):
    if OLLAMA_LOG_DIR:
        return read_text(os.path.join(OLLAMA_LOG_DIR, unit + ".log"))
    if OLLAMA_LOG_FILE and unit == "ollama.service":
        return read_text(OLLAMA_LOG_FILE)
    # Seules les lignes utiles sont demandées : sur un Ollama qui tourne depuis longtemps, la phrase de démarrage (« discovering available GPUs »)
    # sort vite des 5000 dernières lignes du journal (une ligne par requête) et le GPU passerait à tort pour « non utilisé ».
    out = run(["journalctl", "-u", unit, "-b", "-g", JOURNAL_GREP, "-n", "20000", "--no-pager", "-o", "cat"], timeout=8)
    if out and "discovering available GPUs" in out:
        return out
    return run(["journalctl", "-u", unit, "-b", "-n", "5000", "--no-pager", "-o", "cat"], timeout=15)   # journalctl sans -g, ou démarrage sans détection


JOURNAL_GREP = r"discovering available GPUs|inference compute|dropping integrated GPU|rocm|amdgpu|\bhip\b|kfd|gfx[0-9]|hsa"


def ollama_service_info(unit="ollama.service"):
    """Identité de l'instance en cours (PID + instant de démarrage), nombre de redémarrages automatiques, état."""
    out = run(["systemctl", "show", unit, "-p", "MainPID", "-p", "ActiveEnterTimestampMonotonic", "-p", "ActiveEnterTimestamp", "-p", "NRestarts", "-p", "ActiveState"], 5) or ""
    d = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    pid, mono = d.get("MainPID", "0"), d.get("ActiveEnterTimestampMonotonic", "0")
    try:
        restarts = int(d.get("NRestarts", "0"))
    except ValueError:
        restarts = 0
    return {"id": ("%s:%s" % (pid, mono)) if pid not in ("", "0") and mono not in ("", "0") else "", "state": d.get("ActiveState", ""),
            "since": d.get("ActiveEnterTimestamp", ""), "restarts": restarts}


def ollama_discovery(unit="ollama.service"):
    """Dernière détection de matériel faite par une instance Ollama (journal du démarrage en cours).
    Le journal peut perdre la phrase de démarrage (rotation, journal en mémoire plein de lignes de requêtes) : le dernier résultat
    est donc mémorisé avec l'identité de l'instance et réutilisé tant que c'est la même instance qui tourne."""
    used, dropped = parse_discovery(ollama_log_text(unit))
    if OLLAMA_LOG_DIR or OLLAMA_LOG_FILE:
        return used, dropped
    path = os.path.join(STATE_DIR, "gpu-discovery-%s.json" % re.sub(r"[^A-Za-z0-9_.-]", "_", unit))
    sid = ollama_service_info(unit)["id"]
    if used:
        if sid:
            try:
                atomic_write(path, json.dumps({"id": sid, "used": used, "dropped": dropped}))
            except OSError:
                pass
        return used, dropped
    if sid:
        saved = load_json_file(path, {})
        if isinstance(saved, dict) and saved.get("id") == sid and saved.get("used"):
            return saved["used"], saved.get("dropped") or []
    return used, dropped


ROCM_HINT_RE = re.compile(r"(?i)(rocm|amdgpu|\bhip\b|kfd|gfx\d|hsa)")
ROCM_PROBLEM_RE = re.compile(r"(?i)(level=(warn|error)|unsupported|not supported|skipping|failed|unable|denied|permission|no compatible)")


def rocm_hint(text):
    """Dernier message d'Ollama sur ROCm signalant un problème, dans la dernière détection de matériel."""
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if "discovering available GPUs" in l]
    for line in reversed(lines[starts[-1] if starts else 0:]):
        if ROCM_HINT_RE.search(line) and ROCM_PROBLEM_RE.search(line):
            d = logfmt(line)
            words = " ".join("%s=%s" % (k, d[k]) for k in ("error", "gpu", "gpu_type", "reason") if d.get(k))
            return ((d.get("msg") or line.strip()) + (" (" + words + ")" if words else ""))[:220]
    return None


GPU_AUTO = os.environ.get("OB_GPU_AUTO", "/usr/local/lib/ollamabuntu/gpu-auto.py")


def amd_auto_report():
    """Réglage automatique des GPU AMD : cibles ROCm installées, état de chaque carte (gpu-auto.py)."""
    try:
        return json.loads(run([sys.executable, GPU_AUTO, "--report"], timeout=10) or "{}")
    except ValueError:
        return {}


def kfd_access():
    """Le compte ollama peut-il ouvrir /dev/kfd (accès des GPU AMD par ROCm) ? None : périphérique absent."""
    path = os.environ.get("OB_DEV_KFD", "/dev/kfd")
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_mode & 0o006 == 0o006:
        return True
    try:
        if pwd.getpwnam("ollama").pw_gid == st.st_gid or "ollama" in grp.getgrgid(st.st_gid).gr_mem:
            return True
    except KeyError:
        pass
    return False


# ------------------------------------------------ groupes de GPU et épinglage ---
# Un groupe = une instance Ollama limitée à ses cartes (ollama-pool@<id>.service),
# l'instance principale ne voyant plus que les cartes restantes ; le routeur
# (ollamabuntu-router.service, port public 11434) envoie chaque requête à l'instance
# du modèle demandé. Un épinglage = une variante « modèle:tag-gpuN » (paramètre main_gpu).
POOLS_FILE = os.path.join(ETC, "pools.json")
POOLS_DIR = os.path.join(ETC, "pools")
MAIN_OVERRIDE = os.path.join(ETC, "ollama-main.env")
PINS_FILE = os.path.join(ETC, "placements.json")
INVENTORY_FILE = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "gpu-inventory.json")
MAIN_INTERNAL = os.environ.get("OB_OLLAMA_MAIN", "127.0.0.1:11400")
POOL_BASE_PORT = int(os.environ.get("OB_POOL_PORT", "11500"))
OLLAMA_LOG_DIR = os.environ.get("OB_OLLAMA_LOG_DIR", "")
VIS_KEYS = ("CUDA_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "GGML_VK_VISIBLE_DEVICES")
POOL_NAME_RE = re.compile(r"^[^\x00-\x1f<>\"'&]{1,40}$")
_pools_lock = threading.Lock()


def load_json_file(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_pools():
    return load_json_file(POOLS_FILE, {}).get("pools", [])


def load_pins():
    return load_json_file(PINS_FILE, {}).get("pins", {})


def read_env_file(path):
    env = {}
    for line in read_text(path).splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"')
    return env


def main_addr():
    """Instance principale d'Ollama (port interne) ; le routeur porte 127.0.0.1:11434."""
    return MAIN_INTERNAL


def instances():
    """Instances Ollama actives : (unité systemd, adresse, groupe ou None)."""
    out = [("ollama.service", main_addr(), None)]
    for p in load_pools():
        out.append(("ollama-pool@%s.service" % p["id"], "127.0.0.1:%d" % int(p["port"]), p))
    return out


def gpu_inventory():
    """Cartes de calcul détectées par les instances Ollama, indexées par adresse PCI.
    Repart des détections actuelles : une carte retirée du serveur disparaît, sauf si elle est
    réservée à un groupe (instance peut-être arrêtée), auquel cas elle est marquée absente.
    Le numéro Vulkan n'est relevé que sur une détection sans restriction, puis conservé."""
    old = load_json_file(INVENTORY_FILE, {})
    main_restricted = any(k in read_env_file(MAIN_OVERRIDE) or k in read_env() for k in VIS_KEYS)
    inv = {}
    for unit, addr, pool in instances():
        used, _ = ollama_discovery(unit)
        for u in used:
            if u.get("library", "").lower() == "cpu":
                continue
            key = norm_pci(u.get("pci_id")) or u.get("id")
            if not key:
                continue
            e = {"key": key, "library": u.get("library"), "id": u.get("id"), "pci_id": u.get("pci_id"),
                 "description": u.get("description") or u.get("name"), "total": u.get("total"),
                 "ordinal": old.get(key, {}).get("ordinal")}
            if pool is None and not main_restricted:
                m = re.search(r"(\d+)$", u.get("name", ""))
                e["ordinal"] = int(m.group(1)) if m else None
            inv[key] = e
    for p in load_pools():
        for k in p["gpus"]:
            if k not in inv and k in old:
                inv[k] = dict(old[k], missing=True)
    stored = {k: {x: y for x, y in v.items() if x != "missing"} for k, v in inv.items()}
    if json.dumps(stored, sort_keys=True) != json.dumps(old, sort_keys=True):
        try:
            atomic_write(INVENTORY_FILE, json.dumps(stored, indent=1), 0o644)
        except OSError:
            pass
    return sorted(inv.values(), key=lambda g: (g.get("library") or "", g.get("ordinal") if g.get("ordinal") is not None else 99, g["key"]))


def visibility(gpus):
    """Variables qui limitent une instance aux cartes données (« -1 » = aucune carte de ce type)."""
    cuda = [g["id"] for g in gpus if g.get("library") == "CUDA" and g.get("id")]
    rocm = [g["id"] for g in gpus if g.get("library") == "ROCm" and g.get("id")]
    vk = [str(g["ordinal"]) for g in gpus if g.get("library") == "Vulkan" and g.get("ordinal") is not None]
    return {"CUDA_VISIBLE_DEVICES": ",".join(cuda) or "-1", "ROCR_VISIBLE_DEVICES": ",".join(rocm) or "-1",
            "GGML_VK_VISIBLE_DEVICES": ",".join(vk) or "-1"}


def env_text(title, env):
    return "# %s (généré par la console OllamaBuntu)\n" % title + "".join("%s=%s\n" % (k, v) for k, v in env.items())


def apply_pools(pools):
    """Écrit la configuration de chaque instance et (re)démarre les services concernés."""
    inv = {g["key"]: g for g in gpu_inventory()}
    previous = {p["id"] for p in load_pools()}
    base = {k: v for k, v in read_env().items() if k not in VIS_KEYS + ("OLLAMA_HOST", "OLLAMA_MODELS")}
    os.makedirs(POOLS_DIR, exist_ok=True)
    reserved = set()
    for p in pools:
        env = dict(base, OLLAMA_HOST="127.0.0.1:%d" % p["port"], OLLAMA_MODELS=MODELS_DIR, OLLAMA_NOPRUNE="1")
        env.update(visibility([inv[k] for k in p["gpus"] if k in inv]))
        atomic_write(os.path.join(POOLS_DIR, p["id"] + ".env"), env_text("Groupe de GPU « %s »" % p["name"], env), 0o644)
        reserved |= set(p["gpus"])
    main_env = {"OLLAMA_HOST": MAIN_INTERNAL}
    if pools:
        main_env.update(visibility([g for k, g in inv.items() if k not in reserved]))
    atomic_write(MAIN_OVERRIDE, env_text("Instance principale : port interne" + (" et cartes non réservées à un groupe" if pools else ""), main_env), 0o644)
    atomic_write(POOLS_FILE, json.dumps({"pools": pools}, ensure_ascii=False, indent=1), 0o644)
    current = {p["id"] for p in pools}
    for pid in previous - current:
        run(["systemctl", "disable", "--now", "ollama-pool@%s.service" % pid], timeout=60)
        try:
            os.remove(os.path.join(POOLS_DIR, pid + ".env"))
        except OSError:
            pass
    run(["systemctl", "restart", "ollama.service"], timeout=90)
    for pid in sorted(current):
        run(["systemctl", "enable", "ollama-pool@%s.service" % pid], timeout=30)
        run(["systemctl", "restart", "ollama-pool@%s.service" % pid], timeout=90)
    # le routeur relit pools.json à chaud : pas de redémarrage, pas de conversation coupée


def validate_pool(data, pools, editing=None):
    name = str(data.get("name", "")).strip()
    if not POOL_NAME_RE.match(name):
        raise ValueError("nom de groupe invalide (1 à 40 caractères)")
    inv = {g["key"]: g for g in gpu_inventory()}
    gpus = [str(k) for k in data.get("gpus") or []]
    models = sorted({short_name(str(m).strip()) for m in data.get("models") or [] if str(m).strip()}, key=str.lower)
    if not gpus:
        raise ValueError("choisissez au moins un GPU")
    for k in gpus:
        g = inv.get(k)
        if not g:
            raise ValueError("GPU inconnu : %s" % k)
        if g.get("library") == "Vulkan" and g.get("ordinal") is None:
            raise ValueError("%s : numéro Vulkan inconnu (redémarrez Ollama sans groupe ni restriction de GPU, puis réessayez)" % g["description"])
    for m in models:
        if not MODEL_RE.match(m):
            raise ValueError("nom de modèle invalide : %s" % m)
    for p in pools:
        if p["id"] == editing:
            continue
        if set(gpus) & set(p["gpus"]):
            raise ValueError("un GPU choisi appartient déjà au groupe « %s »" % p["name"])
        if {m.lower() for m in models} & {m.lower() for m in p["models"]}:
            raise ValueError("un modèle choisi est déjà affecté au groupe « %s »" % p["name"])
        if p["name"].lower() == name.lower():
            raise ValueError("un groupe porte déjà ce nom")
    return name, gpus, models


def pool_create(data):
    with _pools_lock:
        pools = load_pools()
        if len(pools) >= 16:
            raise ValueError("16 groupes au maximum")
        name, gpus, models = validate_pool(data, pools)
        used_ids = {p["id"] for p in pools}
        used_ports = {int(p["port"]) for p in pools}
        pid = next("g%d" % i for i in range(1, 100) if "g%d" % i not in used_ids)
        port = next(POOL_BASE_PORT + i for i in range(100) if POOL_BASE_PORT + i not in used_ports)
        pools.append({"id": pid, "name": name, "port": port, "gpus": gpus, "models": models})
        apply_pools(pools)
        return pid


def pool_update(data):
    with _pools_lock:
        pools = load_pools()
        p = next((x for x in pools if x["id"] == data.get("id")), None)
        if not p:
            raise ValueError("groupe introuvable")
        p["name"], p["gpus"], p["models"] = validate_pool(data, pools, editing=p["id"])
        apply_pools(pools)


def pool_delete(pid):
    with _pools_lock:
        pools = load_pools()
        if not any(p["id"] == pid for p in pools):
            raise ValueError("groupe introuvable")
        apply_pools([p for p in pools if p["id"] != pid])


# ------------------------------------------------- publication de l'API Ollama ---
# Le routeur (ollamabuntu-router.service) porte l'adresse publique d'Ollama : accès local
# 127.0.0.1:11434 sans restriction, accès réseau selon publication.json (port, TLS,
# filtrage IP, clés d'API avec droits et modèles autorisés). Ollama écoute en interne
# sur 127.0.0.1:11400. Les clés ne sont conservées que sous forme d'empreinte SHA-256.
PUB_FILE = os.path.join(ETC, "publication.json")
ROUTER_TLS = os.path.join(ETC, "router-tls")
ROUTER_USAGE = os.environ.get("OB_ROUTER_USAGE", "/var/lib/ollamabuntu-router/usage.json")
PERMS = ("inference", "read", "manage")
PUB_DEFAULT = {"enabled": False, "port": 11443, "tls": True, "auth": True, "allow": [],
               "anonymous": {"perms": ["inference", "read"], "models": []}, "keys": []}
KEY_NAME_RE = re.compile(r"^[^\x00-\x1f<>\"'&]{1,40}$")
_pub_lock = threading.Lock()


def load_publication():
    d = dict(PUB_DEFAULT)
    d.update(load_json_file(PUB_FILE, {}))
    return d


def ollama_group_id():
    try:
        import grp
        return grp.getgrnam("ollama").gr_gid
    except (ImportError, KeyError):
        return None


def save_publication(d):
    atomic_write(PUB_FILE, json.dumps(d, ensure_ascii=False, indent=1), 0o640)
    gid = ollama_group_id()
    if gid is not None and os.geteuid() == 0:
        os.chown(PUB_FILE, 0, gid)   # lisible par le routeur (utilisateur ollama), pas par les autres


def ensure_router_tls():
    """Copie du certificat de la console, lisible par le routeur (qui ne tourne pas en root)."""
    gid = ollama_group_id()
    os.makedirs(ROUTER_TLS, mode=0o750, exist_ok=True)
    for src, name, mode in ((CERT_FILE, "cert.pem", 0o644), (KEY_FILE, "key.pem", 0o640)):
        dst = os.path.join(ROUTER_TLS, name)
        with open(src, "rb") as f:
            data = f.read()
        tmp = dst + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        if gid is not None and os.geteuid() == 0:
            os.chown(tmp, 0, gid)
        os.replace(tmp, dst)
    if gid is not None and os.geteuid() == 0:
        os.chown(ROUTER_TLS, 0, gid)


def server_addresses():
    out = run(["hostname", "-I"], timeout=5).split()
    return [a for a in out if ":" not in a] or ["adresse-du-serveur"]


def publication_view():
    pub = load_publication()
    usage_by_key = load_json_file(ROUTER_USAGE, {})
    keys = [{k: v for k, v in key.items() if k != "hash"} | {"usage": usage_by_key.get(key.get("id"), {}), "days_left": expiry_days(key.get("expires"))}
            for key in pub.get("keys", [])]
    scheme = "https" if pub["tls"] else "http"
    urls = ["%s://%s:%d" % (scheme, a, pub["port"]) for a in server_addresses()]
    return {**{k: v for k, v in pub.items() if k != "keys"}, "keys": keys, "urls": urls,
            "router": unit_state("ollamabuntu-router.service")}


def validate_models(models):
    out = []
    for m in models or []:
        m = str(m).strip()
        if not MODEL_RE.match(m):
            raise ValueError("nom de modèle invalide : %s" % m[:60])
        out.append(short_name(m))
    if len(out) > 200:
        raise ValueError("200 modèles au maximum")
    return sorted(set(out), key=str.lower)


def validate_perms(perms, allow_empty=False):
    p = [x for x in PERMS if x in (perms or [])]
    if not p and not allow_empty:
        raise ValueError("accordez au moins un droit")
    return p


def set_publication(data):
    with _pub_lock:
        pub = load_publication()
        old = (pub["enabled"], pub["port"], pub["tls"])
        if "enabled" in data:
            pub["enabled"] = bool(data["enabled"])
        if "tls" in data:
            pub["tls"] = bool(data["tls"])
        if "auth" in data:
            pub["auth"] = bool(data["auth"])
        if "port" in data:
            try:
                port = int(data["port"])
            except (TypeError, ValueError):
                raise ValueError("port invalide")
            reserved = {11400, HTTPS_PORT, 3000, int(os.environ.get("OB_WEBUI_TLS_PORT", "8443"))} | \
                       {int(p["port"]) for p in load_pools()} | set(range(POOL_BASE_PORT, POOL_BASE_PORT + 100))
            if not 1024 <= port <= 65535 or port in reserved:
                raise ValueError("port %s indisponible (1024-65535, hors ports de la console, d'Open WebUI et des instances Ollama)" % data["port"])
            pub["port"] = port
        if pub["tls"] and pub["port"] == 11434:
            raise ValueError("le port 11434 est l'accès local en HTTP : choisissez un autre port pour HTTPS (par ex. 11443)")
        if "allow" in data:
            nets = []
            for c in data.get("allow") or []:
                c = str(c).strip()
                if not c:
                    continue
                try:
                    nets.append(str(ipaddress.ip_network(c, strict=False)))
                except ValueError:
                    raise ValueError("réseau invalide : %s (format attendu : 10.0.0.0/8 ou 192.168.1.20)" % c[:60])
            if len(nets) > 50:
                raise ValueError("50 réseaux au maximum")
            pub["allow"] = nets
        if "anonymous" in data:
            a = data.get("anonymous") or {}
            pub["anonymous"] = {"perms": validate_perms(a.get("perms"), allow_empty=True), "models": validate_models(a.get("models"))}
        if pub["enabled"] and pub["tls"]:
            ensure_router_tls()
        save_publication(pub)
        if (pub["enabled"], pub["port"], pub["tls"]) != old:   # écoute modifiée : redémarrage du routeur
            run(["systemctl", "restart", "ollamabuntu-router.service"], timeout=60)
    apply_firewall(force=True)   # ouverture / fermeture du port publié, réseaux autorisés


def key_create(data):
    name = str(data.get("name", "")).strip()
    if not KEY_NAME_RE.match(name):
        raise ValueError("nom de clé invalide (1 à 40 caractères)")
    with _pub_lock:
        pub = load_publication()
        if any(k["name"].lower() == name.lower() for k in pub["keys"]):
            raise ValueError("une clé porte déjà ce nom")
        if len(pub["keys"]) >= 100:
            raise ValueError("100 clés au maximum")
        token = "ob_" + secrets.token_urlsafe(32)
        key = {"id": secrets.token_hex(4), "name": name, "hash": hashlib.sha256(token.encode()).hexdigest(),
               "prefix": token[:9], "perms": validate_perms(data.get("perms")), "models": validate_models(data.get("models")),
               "deny": [x for x in KEY_RESTRICTIONS if x in (data.get("deny") or [])],
               "enabled": True, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        key.update(validate_limits(data))
        if data.get("team"):
            key["team"] = costs.team_clean(data["team"])
        if data.get("words"):
            key["words"] = privacy.words_clean(data["words"], privacy.MAX_KEY_WORDS)
        if data.get("collections"):
            key["collections"] = rag.collections_clean(data["collections"])
        key["expires"] = validate_expiry(data.get("expires"))
        pub["keys"].append(key)
        save_publication(pub)   # le routeur relit le fichier : aucune interruption
    return token, {k: v for k, v in key.items() if k != "hash"}


def validate_expiry(v):
    """Date d'expiration d'une clé (AAAA-MM-JJ, valable jusqu'à la fin de ce jour) ; vide = sans échéance."""
    v = str(v or "").strip()
    if not v:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ValueError("date d'expiration invalide (format AAAA-MM-JJ)")
    try:
        time.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ValueError("date d'expiration invalide (format AAAA-MM-JJ)")
    return v


def expiry_days(v, today=None):
    """Jours restants avant l'expiration (0 = dernier jour, négatif = expirée) ; None sans échéance."""
    if not v:
        return None
    t = time.strptime(today or time.strftime("%Y-%m-%d"), "%Y-%m-%d")
    e = time.strptime(v, "%Y-%m-%d")
    return (calendar.timegm(e) - calendar.timegm(t)) // 86400


LIMIT_FIELDS = {"max_concurrent": 64, "quota_day": 10 ** 12, "quota_month": 10 ** 13, "max_ctx": 2_000_000, "max_output": 1_000_000}


def validate_limits(data, current=None):
    """Plafond de requêtes simultanées et quotas de jetons d'une clé (0 = sans limite)."""
    out = {}
    for k, hi in LIMIT_FIELDS.items():
        if k not in data and current is not None:
            continue
        try:
            v = int(data.get(k) or 0)
        except (TypeError, ValueError):
            raise ValueError("valeur invalide : %s" % k)
        if not 0 <= v <= hi:
            raise ValueError("%s hors limites (0 à %d)" % (k, hi))
        out[k] = v
    if "priority" in data:
        try:
            pr = int(data["priority"])
        except (TypeError, ValueError):
            raise ValueError("priorité invalide")
        if pr not in (1, 2, 3):
            raise ValueError("priorité : 1 (haute), 2 (normale) ou 3 (basse)")
        out["priority"] = pr
    return out


def key_update(data):
    with _pub_lock:
        pub = load_publication()
        key = next((k for k in pub["keys"] if k["id"] == data.get("id")), None)
        if not key:
            raise ValueError("clé introuvable")
        if "name" in data:
            name = str(data["name"]).strip()
            if not KEY_NAME_RE.match(name) or any(k is not key and k["name"].lower() == name.lower() for k in pub["keys"]):
                raise ValueError("nom de clé invalide ou déjà utilisé")
            key["name"] = name
        if "perms" in data:
            key["perms"] = validate_perms(data["perms"])
        if "models" in data:
            key["models"] = validate_models(data["models"])
        if "enabled" in data:
            key["enabled"] = bool(data["enabled"])
        if "deny" in data:
            key["deny"] = [x for x in KEY_RESTRICTIONS if x in (data.get("deny") or [])]
        if any(k in data for k in LIMIT_FIELDS) or "priority" in data:
            key.update(validate_limits(data, key))
        if "expires" in data:
            key["expires"] = validate_expiry(data.get("expires"))
        if "collections" in data:
            colls = rag.collections_clean(data["collections"])
            if colls:
                key["collections"] = colls
            else:
                key.pop("collections", None)
        if "words" in data:
            words = privacy.words_clean(data["words"], privacy.MAX_KEY_WORDS)
            if words:
                key["words"] = words
            else:
                key.pop("words", None)
        if "team" in data:
            team = costs.team_clean(data["team"])
            if team:
                key["team"] = team
            else:
                key.pop("team", None)
        save_publication(pub)


def key_delete(kid):
    with _pub_lock:
        pub = load_publication()
        keys = [k for k in pub["keys"] if k["id"] != kid]
        if len(keys) == len(pub["keys"]):
            raise ValueError("clé introuvable")
        pub["keys"] = keys
        save_publication(pub)


# ------------------------------------------- sécurité : pare-feu et mises à jour ---
# Pare-feu nftables : table « inet ollamabuntu » dédiée (les tables de Docker ne sont pas
# touchées), politique de refus en entrée, ouvertures calculées d'après l'état de
# l'appliance (console, Open WebUI déployé, publication de l'API) ; resynchronisé
# périodiquement et à chaque changement. Chargé au démarrage par ollamabuntu-firewall.service.
FW_FILE = os.path.join(ETC, "firewall.json")
FW_RULES = os.environ.get("OB_FW_RULES", os.path.join(ETC, "firewall.nft"))
NFT = os.environ.get("OB_NFT", "/usr/sbin/nft")
SSH_PORT = int(os.environ.get("OB_SSH_PORT", "22"))
FW_DEFAULT = {"enabled": True, "admin_allow": [], "log_drops": True}
_fw_lock = threading.Lock()


def load_firewall():
    d = dict(FW_DEFAULT)
    d.update(load_json_file(FW_FILE, {}))
    return d


def split_nets(nets):
    v4, v6 = [], []
    for c in nets or []:
        n = ipaddress.ip_network(c, strict=False)
        (v4 if n.version == 4 else v6).append(str(n))
    return v4, v6


def webui_deployed():
    return os.path.exists(os.path.join(ETC, "open-webui.env"))


def firewall_ports(cfg=None):
    """Ouvertures en entrée : port, rôle, origines autorisées (vide = toutes)."""
    cfg = cfg or load_firewall()
    admin = cfg.get("admin_allow") or []
    out = [{"port": SSH_PORT, "service": "SSH (administration, débit limité par adresse)", "sources": admin},
           {"port": HTTPS_PORT, "service": "Console d'administration (HTTPS)", "sources": admin}]
    if HTTP_PORT:
        out.append({"port": HTTP_PORT, "service": "Console : redirection HTTP vers HTTPS", "sources": admin})
    if webui_deployed():
        out.append({"port": WEBUI_TLS_PORT, "service": "Open WebUI (HTTPS)", "sources": []})
    pub = load_publication()
    if pub.get("enabled"):
        out.append({"port": int(pub["port"]), "service": "API Ollama publiée (%s%s)" % ("HTTPS" if pub["tls"] else "HTTP", ", clé d'API" if pub["auth"] else ", sans clé"),
                    "sources": pub.get("allow") or []})
    return out


def render_firewall(cfg=None):
    cfg = cfg or load_firewall()
    ports = firewall_ports(cfg)
    lines = ["# OllamaBuntu - pare-feu (généré par la console : ne pas modifier à la main)",
             "table inet ollamabuntu", "delete table inet ollamabuntu", "", "table inet ollamabuntu {",
             "\tcounter refus {}",
             "\tset ssh_rl4 { type ipv4_addr; flags dynamic, timeout; timeout 2m; }",
             "\tset ssh_rl6 { type ipv6_addr; flags dynamic, timeout; timeout 2m; }"]
    sets, named = [], {}   # un ensemble nftables par liste d'origines distincte (partagé entre ports)
    for p in ports:
        v4, v6 = split_nets(p["sources"])
        for fam, typ, nets in (("4", "ipv4_addr", v4), ("6", "ipv6_addr", v6)):
            name = None
            if nets:
                key = (fam, tuple(sorted(nets)))
                if key not in named:
                    named[key] = "src%d_%s" % (len(named), fam)
                    sets.append("\tset %s { type %s; flags interval; auto-merge; elements = { %s } }" % (named[key], typ, ", ".join(sorted(nets))))
                name = named[key]
            p["set" + fam] = name
    lines += sets
    lines += ["", "\tchain input {", "\t\ttype filter hook input priority filter; policy drop;",
              "\t\tct state established,related accept", "\t\tct state invalid drop", "\t\tiif \"lo\" accept",
              "\t\ticmp type { destination-unreachable, time-exceeded, parameter-problem } accept",
              "\t\ticmp type echo-request limit rate 10/second accept",
              "\t\ticmpv6 type { destination-unreachable, packet-too-big, time-exceeded, parameter-problem, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept",
              "\t\ticmpv6 type echo-request limit rate 10/second accept",
              "\t\tudp sport 67 udp dport 68 accept\t# client DHCPv4",
              "\t\tudp sport 547 udp dport 546 accept\t# client DHCPv6",
              "\t\ttcp dport %d ct state new add @ssh_rl4 { ip saddr limit rate over 10/minute burst 20 packets } counter name refus drop" % SSH_PORT,
              "\t\ttcp dport %d ct state new add @ssh_rl6 { ip6 saddr limit rate over 10/minute burst 20 packets } counter name refus drop" % SSH_PORT]
    for p in ports:
        comment = p["service"].replace('"', "'")
        if not p["sources"]:
            lines.append("\t\ttcp dport %d accept\t# %s" % (p["port"], comment))
        else:
            if p["set4"]:
                lines.append("\t\tip saddr @%s tcp dport %d accept\t# %s" % (p["set4"], p["port"], comment))
            if p["set6"]:
                lines.append("\t\tip6 saddr @%s tcp dport %d accept\t# %s" % (p["set6"], p["port"], comment))
    if cfg.get("log_drops", True):
        lines.append("\t\tlimit rate 6/minute log prefix \"ollamabuntu pare-feu refus : \" level info")
    lines += ["\t\tcounter name refus", "\t}"] + ollama_egress_rules() + ["}", ""]
    return "\n".join(lines)


def apply_firewall(force=False):
    """Écrit et charge les règles ; vérification préalable (nft -c) : en cas d'erreur, rien n'est changé."""
    with _fw_lock:
        cfg = load_firewall()
        if not os.path.exists(NFT):
            return False, "nftables absent : pare-feu inactif"
        if not cfg.get("enabled", True):
            run([NFT, "delete", "table", "inet", "ollamabuntu"], timeout=15)
            return True, "pare-feu désactivé"
        text = render_firewall(cfg)
        loaded = subprocess.run([NFT, "list", "table", "inet", "ollamabuntu"], capture_output=True, timeout=15).returncode == 0
        if not force and loaded and read_text(FW_RULES) == text:
            return True, "à jour"
        tmp = FW_RULES + ".new"
        atomic_write(tmp, text, 0o644)
        chk = subprocess.run([NFT, "-c", "-f", tmp], capture_output=True, text=True, timeout=30)
        if chk.returncode != 0:
            os.remove(tmp)
            err = " ".join(l.replace(tmp, "firewall.nft") for l in chk.stderr.strip().splitlines() if "Error" in l or "error" in l) or chk.stderr.strip()
            return False, "règles refusées par nftables, aucune modification : %s" % err[:300]
        r = subprocess.run([NFT, "-f", tmp], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, "chargement impossible : %s" % r.stderr.strip()[:300]
        os.replace(tmp, FW_RULES)
        return True, "règles chargées"


_online_check_lock = threading.Lock()


def online_update_worker():
    """Vérification automatique quotidienne des versions publiées (désactivée par défaut)."""
    time.sleep(300)
    while True:
        try:
            cfg = updater.load_config()
            last = updater.load_json(updater.STATE_FILE, {}).get("checked_at") or 0
            if cfg["auto_check"] and cfg["repo"] and time.time() - last > 86400:
                with _online_check_lock:
                    updater.check()
        except updater.UpdateError as e:
            sys.stderr.write("mise à jour en ligne : %s\n" % e)
        except Exception as e:   # la boucle ne doit jamais s'arrêter
            sys.stderr.write("mise à jour en ligne : %s\n" % e)
        time.sleep(3600)


def firewall_worker():
    """Resynchronise le pare-feu sur l'état de l'appliance (Open WebUI déployé ou retiré...)."""
    while True:
        try:
            ok, msg = apply_firewall()
            if not ok:
                sys.stderr.write("pare-feu : %s\n" % msg)
        except Exception as e:
            sys.stderr.write("pare-feu : %s\n" % e)
        time.sleep(20)


def firewall_status():
    cfg = load_firewall()
    active = os.path.exists(NFT) and subprocess.run([NFT, "list", "table", "inet", "ollamabuntu"], capture_output=True, timeout=15).returncode == 0
    drops = None
    if active:
        m = re.search(r"packets (\d+) bytes", run([NFT, "list", "counter", "inet", "ollamabuntu", "refus"], timeout=10))
        drops = int(m.group(1)) if m else None
    return {"enabled": cfg["enabled"], "active": active, "available": os.path.exists(NFT), "admin_allow": cfg["admin_allow"],
            "log_drops": cfg["log_drops"], "ports": [{k: v for k, v in p.items() if not k.startswith("set")} for p in firewall_ports(cfg)],
            "drops": drops}


def set_firewall(data, client_ip):
    with _fw_lock:
        cfg = load_firewall()
        if "enabled" in data:
            cfg["enabled"] = bool(data["enabled"])
        if "log_drops" in data:
            cfg["log_drops"] = bool(data["log_drops"])
        if "admin_allow" in data:
            nets = []
            for c in data.get("admin_allow") or []:
                c = str(c).strip()
                if not c:
                    continue
                try:
                    nets.append(str(ipaddress.ip_network(c, strict=False)))
                except ValueError:
                    raise ValueError("réseau invalide : %s (format attendu : 10.0.0.0/8 ou 192.168.1.20)" % c[:60])
            if len(nets) > 50:
                raise ValueError("50 réseaux au maximum")
            if nets:
                try:
                    me = ipaddress.ip_address(client_ip)
                    me = me.ipv4_mapped or me if me.version == 6 else me
                except ValueError:
                    me = None
                if me is not None and not me.is_loopback and not any(me in ipaddress.ip_network(n) for n in nets):
                    raise ValueError("votre adresse %s ne serait plus autorisée : ajoutez-la (ou son réseau) pour ne pas perdre l'accès" % client_ip)
            cfg["admin_allow"] = nets
        atomic_write(FW_FILE, json.dumps(cfg, indent=1), 0o644)
    ok, msg = apply_firewall(force=True)
    if not ok:
        raise ValueError(msg)


# Mises à jour de sécurité automatiques (unattended-upgrades) : activation, heure,
# redémarrage automatique facultatif. Fichiers propres à l'appliance, créés une seule
# fois à l'installation (les réglages de l'administrateur survivent aux mises à jour).
UU_PERIODIC = os.environ.get("OB_UU_PERIODIC", "/etc/apt/apt.conf.d/20auto-upgrades")
UU_CONF = os.environ.get("OB_UU_CONF", "/etc/apt/apt.conf.d/52ollamabuntu-unattended")
UU_TIMER = os.environ.get("OB_UU_TIMER", "/etc/systemd/system/apt-daily-upgrade.timer.d/ollamabuntu.conf")
UU_LOG = os.environ.get("OB_UU_LOG", "/var/log/unattended-upgrades/unattended-upgrades.log")
UU_BIN = os.environ.get("OB_UU_BIN", "/usr/bin/unattended-upgrade")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def uu_files(enabled, at, reboot, reboot_at):
    periodic = ('// OllamaBuntu : mises à jour automatiques (géré par la console)\n'
                'APT::Periodic::Update-Package-Lists "%d";\nAPT::Periodic::Unattended-Upgrade "%d";\n'
                'APT::Periodic::AutocleanInterval "7";\n' % (int(enabled), int(enabled)))
    conf = ('// OllamaBuntu : options des mises à jour de sécurité automatiques (géré par la console)\n'
            '// Origines : celles de 50unattended-upgrades (correctifs de sécurité Ubuntu).\n'
            'Unattended-Upgrade::Automatic-Reboot "%s";\nUnattended-Upgrade::Automatic-Reboot-Time "%s";\n'
            'Unattended-Upgrade::Automatic-Reboot-WithUsers "true";\n'
            'Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";\nUnattended-Upgrade::Remove-Unused-Dependencies "true";\n'
            'Unattended-Upgrade::SyslogEnable "true";\n' % ("true" if reboot else "false", reboot_at))
    timer = ('# OllamaBuntu : heure des mises à jour automatiques (géré par la console)\n'
             '[Timer]\nOnCalendar=\nOnCalendar=*-*-* %s\nRandomizedDelaySec=10m\nPersistent=true\n' % at)
    return periodic, conf, timer


def autoupdates_status():
    periodic, conf, timer = read_text(UU_PERIODIC), read_text(UU_CONF), read_text(UU_TIMER)
    m = re.search(r"OnCalendar=\*-\*-\* (\d\d:\d\d)", timer)
    rt = re.search(r'Automatic-Reboot-Time "([0-9:]+)"', conf)
    nxt = run(["systemctl", "show", "apt-daily-upgrade.timer", "-p", "NextElapseUSecRealtime", "--value"], timeout=5).strip()
    log = [l for l in read_text(UU_LOG).splitlines() if l.strip()][-12:]
    return {"installed": os.path.exists(UU_BIN), "enabled": bool(re.search(r'Unattended-Upgrade\s+"1"', periodic)),
            "time": m.group(1) if m else "06:00", "reboot": 'Automatic-Reboot "true"' in conf,
            "reboot_time": rt.group(1) if rt else "04:00", "next": nxt if nxt and nxt != "n/a" else None, "log": log}


def set_autoupdates(data):
    cur = autoupdates_status()
    enabled = bool(data.get("enabled", cur["enabled"]))
    at, reboot_at = str(data.get("time", cur["time"])), str(data.get("reboot_time", cur["reboot_time"]))
    if not TIME_RE.match(at) or not TIME_RE.match(reboot_at):
        raise ValueError("heure invalide (format HH:MM)")
    if enabled and not cur["installed"]:
        raise ValueError("unattended-upgrades n'est pas installé sur ce serveur")
    periodic, conf, timer = uu_files(enabled, at, bool(data.get("reboot", cur["reboot"])), reboot_at)
    atomic_write(UU_PERIODIC, periodic, 0o644)
    atomic_write(UU_CONF, conf, 0o644)
    os.makedirs(os.path.dirname(UU_TIMER), exist_ok=True)
    atomic_write(UU_TIMER, timer, 0o644)
    run(["systemctl", "daemon-reload"], timeout=30)
    run(["systemctl", "restart", "apt-daily-upgrade.timer"], timeout=30)


SYSCTL_HARDENING = [
    ("net.ipv4.conf.all.accept_redirects", "0"), ("net.ipv6.conf.all.accept_redirects", "0"),
    ("net.ipv4.conf.all.send_redirects", "0"), ("net.ipv4.conf.all.accept_source_route", "0"),
    ("net.ipv4.conf.all.rp_filter", "1"), ("net.ipv4.tcp_syncookies", "1"), ("net.ipv4.conf.all.log_martians", "1"),
    ("kernel.kptr_restrict", "2"), ("kernel.dmesg_restrict", "1"), ("kernel.unprivileged_bpf_disabled", "1"),
    ("net.core.bpf_jit_harden", "2"), ("fs.suid_dumpable", "0"), ("kernel.yama.ptrace_scope", "1")]


def hardening_audit():
    """Contrôles lus sur le système réel (pas sur la configuration souhaitée)."""
    out = []
    add = lambda label, ok, detail="": out.append({"label": label, "ok": bool(ok), "detail": detail})
    fw = firewall_status()
    add("Pare-feu : refus par défaut en entrée", fw["active"],
        "%d ports ouverts : %s" % (len(fw["ports"]), ", ".join(str(p["port"]) for p in fw["ports"])) if fw["active"] else
        ("nftables absent" if not fw["available"] else "inactif"))
    au = autoupdates_status()
    add("Mises à jour de sécurité automatiques", au["installed"] and au["enabled"],
        ("chaque jour vers %s%s" % (au["time"], ", redémarrage automatique à %s si nécessaire" % au["reboot_time"] if au["reboot"] else ", sans redémarrage automatique"))
        if au["enabled"] else ("unattended-upgrades absent" if not au["installed"] else "désactivées"))
    sshd = run(["sshd", "-T"], timeout=10).lower()
    if sshd:
        opts = dict(l.split(" ", 1) for l in sshd.splitlines() if " " in l)
        bad = [k for k, v in (("permitrootlogin", "no"), ("maxauthtries", "4"), ("x11forwarding", "no"), ("permitemptypasswords", "no")) if opts.get(k) != v]
        add("SSH : root interdit, tentatives limitées, X11 désactivé", not bad, "à revoir : " + ", ".join(bad) if bad else "PermitRootLogin no, MaxAuthTries 4")
    else:
        add("SSH : configuration durcie", os.path.exists("/etc/ssh/sshd_config.d/50-ollamabuntu.conf"), "lecture de sshd -T impossible")
    bad = []
    for key, want in SYSCTL_HARDENING:
        val = read_text("/proc/sys/" + key.replace(".", "/"), None)
        if val is not None and val.strip() != want:
            bad.append("%s=%s" % (key, val.strip()))
    add("Noyau : paramètres réseau et mémoire durcis", not bad, "à revoir : " + ", ".join(bad) if bad else "%d paramètres conformes" % len(SYSCTL_HARDENING))
    add("AppArmor actif", read_text(sysp("/sys/module/apparmor/parameters/enabled")).strip() == "Y")
    add("Ctrl+Alt+Suppr désactivé sur la console", os.path.realpath("/etc/systemd/system/ctrl-alt-del.target") == "/dev/null")
    pub = load_publication()
    if pub.get("enabled"):
        add("API Ollama publiée : clé d'API exigée", pub.get("auth"), "" if pub.get("auth") else "toute machine autorisée du réseau peut l'utiliser sans clé")
        add("API Ollama publiée : HTTPS", pub.get("tls"), "" if pub.get("tls") else "clés et échanges transmis en clair")
    add("Aucun redémarrage en attente pour appliquer des correctifs", not os.path.exists(sysp("/var/run/reboot-required")),
        "redémarrez le serveur pour activer les derniers correctifs (noyau...)")
    return out


# ------------------------------------------------------ politique d'usage de l'IA ---
# Ce que l'IA peut faire : fonctions cloud d'Ollama (inférence distante, recherche web
# via ollama.com), accès Internet du service Ollama, fonctions d'Open WebUI. Appliquée
# par les réglages officiels (OLLAMA_NO_CLOUD, variables d'Open WebUI) et, quel que soit
# le client, par le routeur (ai-policy.json) et le pare-feu (sortie du compte ollama).
POLICY_FILE = os.path.join(ETC, "ai-policy.json")
WEBUI_POLICY_ENV = os.path.join(ETC, "open-webui-policy.env")
WEBUI_FEATURES = [
    ("web_search", "ENABLE_WEB_SEARCH", "Recherche sur Internet"),
    ("image_generation", "ENABLE_IMAGE_GENERATION", "Génération d'images (moteur externe à configurer : ComfyUI, Automatic1111, API)"),
    ("code_execution", "ENABLE_CODE_EXECUTION", "Exécution du code des réponses"),
    ("code_interpreter", "ENABLE_CODE_INTERPRETER", "Interpréteur de code (le modèle lance lui-même du code)"),
    ("external_apis", "ENABLE_OPENAI_API", "Connexions à des API externes compatibles OpenAI"),
    ("direct_connections", "ENABLE_DIRECT_CONNECTIONS", "Connexions directes des utilisateurs à leurs propres API"),
    ("community_sharing", "ENABLE_COMMUNITY_SHARING", "Partage de conversations vers la communauté Open WebUI"),
]
KEY_RESTRICTIONS = ("vision", "audio", "tools")
_egress = {"pulls": 0}
_egress_lock = threading.Lock()


def load_policy():
    d = {"cloud": False, "ollama_internet": True, "webui": {k: False for k, _, _ in WEBUI_FEATURES}, "webui_locked": False}
    stored = load_json_file(POLICY_FILE, {})
    d.update({k: v for k, v in stored.items() if k != "webui"})
    d["webui"].update(stored.get("webui", {}))
    d["cloud"] = not read_env().get("OLLAMA_NO_CLOUD")   # état réel du service
    return d


def webui_policy_env(pol):
    lines = ["# Politique d'usage de l'IA (console OllamaBuntu) : fonctions d'Open WebUI"]
    lines += ["%s=%s" % (env, "true" if pol["webui"].get(k) else "false") for k, env, _ in WEBUI_FEATURES]
    if pol.get("webui_locked"):
        lines.append("ENABLE_PERSISTENT_CONFIG=false   # réglages imposés à chaque démarrage")
    return "\n".join(lines) + "\n"


def policy_view():
    pol = load_policy()
    return dict(pol, webui_features=[{"key": k, "label": label} for k, _, label in WEBUI_FEATURES],
                webui_deployed=webui_deployed(), egress_window=_egress["pulls"] > 0)


def set_policy(data):
    old = load_policy()
    pol = load_policy()
    for k in ("cloud", "ollama_internet", "webui_locked"):
        if k in data:
            pol[k] = bool(data[k])
    for k, v in (data.get("webui") or {}).items():
        if k in pol["webui"]:
            pol["webui"][k] = bool(v)
    atomic_write(POLICY_FILE, json.dumps({k: v for k, v in pol.items()}, indent=1), 0o644)   # lu par le routeur
    atomic_write(WEBUI_POLICY_ENV, webui_policy_env(pol), 0o600)
    if pol["cloud"] != old["cloud"]:
        update_env({"OLLAMA_NO_CLOUD": "" if pol["cloud"] else "1"})
    if pol["ollama_internet"] != old["ollama_internet"]:
        apply_firewall(force=True)
    if webui_deployed() and (pol["webui"] != old["webui"] or pol["webui_locked"] != old["webui_locked"]):
        return start_job("webui-apply")   # recréation du conteneur avec les nouvelles variables
    return None


class egress_window:
    """Ouvre l'accès Internet du compte ollama le temps d'un téléchargement lancé depuis la console."""
    def __enter__(self):
        with _egress_lock:
            _egress["pulls"] += 1
        if not load_policy()["ollama_internet"]:
            apply_firewall(force=True)

    def __exit__(self, *exc):
        with _egress_lock:
            _egress["pulls"] -= 1
        if not load_policy()["ollama_internet"]:
            apply_firewall(force=True)
        return False


def ollama_egress_rules():
    """Sortie du compte ollama vers Internet refusée (réseaux locaux et privés autorisés)."""
    if load_policy()["ollama_internet"] or _egress["pulls"] > 0:
        return []
    try:
        import pwd
        uid = pwd.getpwnam("ollama").pw_uid
    except (ImportError, KeyError):
        return []
    return ["\tchain output {", "\t\ttype filter hook output priority filter; policy accept;",
            "\t\tmeta skuid %d oif != \"lo\" ip daddr != { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 } ct state new counter name refus drop\t# Ollama : pas d'accès Internet" % uid,
            "\t\tmeta skuid %d oif != \"lo\" ip6 daddr != { fc00::/7, fe80::/10 } ct state new counter name refus drop" % uid,
            "\t}"]



# ------------------------------------------------- gestion avancée des modèles ---
# Modèles personnalisés : variante d'un modèle installé avec prompt système et paramètres
# (API /api/create, poids partagés). Préchargement : modèles gardés en mémoire en
# permanence (keep_alive -1), rechargés automatiquement après un redémarrage.
CUSTOM_FILE = os.path.join(ETC, "custom-models.json")
PRELOAD_FILE = os.path.join(ETC, "preload.json")
CUSTOM_PARAMS = {"temperature": (float, 0.0, 2.0), "top_p": (float, 0.0, 1.0), "num_ctx": (int, 256, 262144), "repeat_penalty": (float, 0.5, 2.0)}
_preload = {"state": {}}


def load_custom():
    return load_json_file(CUSTOM_FILE, {}).get("models", {})


def custom_create(data):
    name, base = str(data.get("name", "")).strip(), str(data.get("base", "")).strip()
    if not MODEL_RE.match(name) or name.startswith(("hf.co/", "huggingface.co/")):
        raise ValueError("nom de modèle invalide (lettres, chiffres, « . _ - : », ex. assistant-rh)")
    if not MODEL_RE.match(base):
        raise ValueError("modèle de base invalide")
    system = str(data.get("system", "")).replace("\r\n", "\n")
    if len(system) > 20000:
        raise ValueError("prompt système trop long (20 000 caractères au maximum)")
    params = {}
    for k, (typ, lo, hi) in CUSTOM_PARAMS.items():
        v = data.get("params", {}).get(k)
        if v in (None, ""):
            continue
        try:
            v = typ(v)
        except (TypeError, ValueError):
            raise ValueError("paramètre %s invalide" % k)
        if not lo <= v <= hi:
            raise ValueError("paramètre %s hors limites (%s à %s)" % (k, lo, hi))
        params[k] = v
    body = {"model": name, "from": base, "stream": False}
    if system.strip():
        body["system"] = system
    if params:
        body["parameters"] = params
    code, res = ollama_json("POST", "/api/create", body, timeout=900)
    if code != 200:
        raise ValueError("création impossible : %s" % (res.get("error") or code))
    with _pools_lock:
        models = load_custom()
        models[short_name(name)] = {"base": short_name(base), "system": system, "params": params, "updated": int(time.time())}
        atomic_write(CUSTOM_FILE, json.dumps({"models": models}, ensure_ascii=False, indent=1), 0o644)
    return short_name(name)


def custom_delete(name):
    with _pools_lock:
        models = load_custom()
        if name not in models:
            raise ValueError("modèle personnalisé inconnu")
        code, res = ollama_json("DELETE", "/api/delete", {"model": name, "name": name})
        if code not in (200, 404):
            raise ValueError("suppression impossible : %s" % (res.get("error") or code))
        del models[name]
        atomic_write(CUSTOM_FILE, json.dumps({"models": models}, ensure_ascii=False, indent=1), 0o644)


def load_preload():
    return load_json_file(PRELOAD_FILE, {}).get("models", [])


def set_preload(models):
    models = sorted({short_name(str(m)) for m in models or [] if MODEL_RE.match(str(m))}, key=str.lower)
    atomic_write(PRELOAD_FILE, json.dumps({"models": models}, indent=1), 0o644)
    return models


def preload_once():
    wanted = load_preload()
    if not wanted:
        return
    try:
        loaded = {short_name(m.get("name", "")): m for m in ollama_json("GET", "/api/ps", timeout=5, addr=OLLAMA_ADDR)[1].get("models", [])}
    except (OSError, ValueError):
        return
    for name in wanted:
        m = loaded.get(name)
        if m and str(m.get("expires_at", ""))[:4] > "2100":   # déjà chargé sans échéance
            _preload["state"][name] = "chargé"
            continue
        _preload["state"][name] = "chargement..."
        try:   # requête vide : charge le modèle et fixe sa durée de maintien (-1 = toujours), via le routeur (groupes)
            code, res = ollama_json("POST", "/api/generate", {"model": name, "keep_alive": -1}, timeout=900, addr=OLLAMA_ADDR)
            _preload["state"][name] = "chargé" if code == 200 else "échec : %s" % (res.get("error") or code)
        except OSError as e:
            _preload["state"][name] = "échec : %s" % e


def preload_worker():
    time.sleep(20)   # laisser Ollama démarrer
    while True:
        try:
            preload_once()
        except Exception as e:
            sys.stderr.write("préchargement : %s\n" % e)
        time.sleep(60)


# ------------------------------------------------ gestion de plusieurs serveurs ---
# Serveur géré : l'administrateur autorise une console principale, qui reçoit un jeton
# (empreinte seule conservée ici). Le jeton donne accès à un état résumé et à quelques
# actions de maintenance, jamais aux comptes, réglages ou conversations.
# Console principale : registre des serveurs (jetons, empreinte du certificat épinglée),
# collecte toutes les 15 s, actions à distance. Certificat changé : connexion refusée.
FLEET_MEMBER = os.path.join(ETC, "fleet-member.json")
FLEET_FILE = os.path.join(ETC, "fleet.json")
FLEET_ACTIONS = {"restart-ollama": "Redémarrage d'Ollama", "apt-refresh": "Recherche des mises à jour", "update-security": "Installation des correctifs de sécurité"}
FLEET_URL_RE = re.compile(r"^https://(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]{1,253})(:\d{1,5})?/?$")
_fleet_lock = threading.Lock()
_fleet_state = {}
_fleet_seen = {}
_fleet_fail = {}


class FleetError(Exception):
    pass


def der_fingerprint(der):
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, 64, 2))


def own_fingerprint():
    try:
        return der_fingerprint(ssl.PEM_cert_to_DER_cert(read_text(CERT_FILE)))
    except ValueError:
        return None


# --- côté serveur géré
def load_member():
    return load_json_file(FLEET_MEMBER, {}).get("consoles", [])


def member_view():
    consoles = load_member()
    routed = {c.get("parent") for c in consoles if c.get("scope") == "route"}
    nics, have_eth = power_nics()
    return {"fingerprint": own_fingerprint(), "last_sync": load_json_file(FLEET_MEMBER, {}).get("last_sync"), "power_allow": power_member_allow(), "nics": nics, "ethtool": have_eth,
            "consoles": [dict({k: v for k, v in c.items() if k != "hash"}, last_seen=_fleet_seen.get(c["id"]), route=c["id"] in routed)
                         for c in consoles if c.get("scope", "manage") == "manage"]}


def save_member(consoles):
    d = load_json_file(FLEET_MEMBER, {})
    d["consoles"] = consoles
    d.setdefault("node", secrets.token_hex(6))
    atomic_write(FLEET_MEMBER, json.dumps(d, ensure_ascii=False, indent=1), 0o600)


def member_node():
    d = load_json_file(FLEET_MEMBER, {})
    if not d.get("node"):
        save_member(d.get("consoles", []))
        d = load_json_file(FLEET_MEMBER, {})
    return d.get("node", "?")


def member_create(name, scope="manage", parent=None):
    """Jeton de console principale : « manage » (état, actions) ou « route » (requêtes vers les modèles)."""
    name = str(name or "").strip()
    if not POOL_NAME_RE.match(name):
        raise ValueError("nom invalide (1 à 40 caractères)")
    with _fleet_lock:
        consoles = load_member()
        if len(consoles) >= 20:
            raise ValueError("20 jetons au maximum")
        token = ("obf_" if scope == "manage" else "obr_") + secrets.token_urlsafe(32)
        consoles.append({"id": secrets.token_hex(4), "name": name, "scope": scope, "parent": parent,
                         "hash": hashlib.sha256(token.encode()).hexdigest(), "prefix": token[:10], "created": int(time.time())})
        save_member(consoles)
    return token


def member_revoke(cid):
    with _fleet_lock:
        consoles = load_member()
        kept = [c for c in consoles if c["id"] != cid and c.get("parent") != cid]   # jetons de routage associés compris
        if len(kept) == len(consoles):
            raise ValueError("console inconnue")
        save_member(kept)


def member_auth(headers, ip, scope="manage"):
    """Console principale authentifiée par son jeton (en-tête Authorization: Bearer), de la portée demandée."""
    now = time.time()
    fails = [t for t in _fleet_fail.get(ip, []) if now - t < 300]
    if len(fails) >= 10:
        raise PermissionError(429, "trop d'essais : réessayez dans quelques minutes")
    auth = headers.get("Authorization") or ""
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    digest = hashlib.sha256(token.encode()).hexdigest()
    for c in load_member():
        if token and hmac.compare_digest(c["hash"], digest) and c.get("scope", "manage") == scope:
            _fleet_seen[c.get("parent") or c["id"]] = int(now)
            _fleet_fail.pop(ip, None)
            return c
    _fleet_fail[ip] = fails + [now]
    raise PermissionError(401, "jeton de gestion centralisée invalide ou révoqué")


def fleet_summary():
    s = status()
    try:
        tags = ollama_json("GET", "/api/tags", timeout=5)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    fw, au = firewall_status(), autoupdates_status()
    nics, have_eth = power_nics()
    return dict(s, firewall_active=fw["active"], autoupdates=au["enabled"], node=member_node(), nics=nics, power_allow=power_member_allow(), power_tools={"ethtool": have_eth},
                models={"count": len(tags), "size": sum(m.get("size", 0) for m in tags)},
                model_tags=[{k: m.get(k) for k in ("name", "model", "size", "digest", "modified_at", "details")} for m in tags][:500],
                jobs=[j for j in list_jobs() if not j["done"]])


SYNC_KINDS = {"models": "Modèles", "custom": "Modèles personnalisés", "policy": "Politique d'usage de l'IA", "keys": "Clés d'API"}


def member_sync(caller, payload):
    """Synchronisation reçue de la console principale : politique, clés (empreintes), modèles personnalisés, modèles."""
    report = {}
    payload = payload or {}
    if isinstance(payload.get("policy"), dict):
        p = payload["policy"]
        job = set_policy({k: p[k] for k in ("cloud", "ollama_internet", "webui_locked", "webui") if k in p})
        report["policy"] = "appliquée" + (" (Open WebUI recréé)" if job else "")
    if isinstance(payload.get("keys"), list):
        with _pub_lock:
            pub = load_publication()
            local = [k for k in pub["keys"] if k.get("synced_from") != caller["id"]]
            incoming = []
            for k in payload["keys"][:100]:
                if not (isinstance(k, dict) and re.fullmatch(r"[0-9a-f]{64}", str(k.get("hash", ""))) and KEY_NAME_RE.match(str(k.get("name", "")))):
                    continue
                incoming.append({"id": "s" + str(k.get("id", ""))[:8], "name": k["name"], "hash": k["hash"], "prefix": str(k.get("prefix", ""))[:12],
                                 "perms": validate_perms(k.get("perms")), "models": validate_models(k.get("models")),
                                 "deny": [x for x in KEY_RESTRICTIONS if x in (k.get("deny") or [])], "enabled": bool(k.get("enabled", True)),
                                 "created": k.get("created"), "synced_from": caller["id"]})
                try:
                    if k.get("words"):
                        incoming[-1]["words"] = privacy.words_clean(k["words"], privacy.MAX_KEY_WORDS)
                    if k.get("collections"):
                        incoming[-1]["collections"] = rag.collections_clean(k["collections"])
                except ValueError:
                    pass
            names = {k["name"].lower() for k in incoming}
            pub["keys"] = [k for k in local if k["name"].lower() not in names] + incoming
            save_publication(pub)
        report["keys"] = len(incoming)
    try:
        installed = {short_name(m.get("name", "")) for m in ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])}
    except (OSError, ValueError):
        installed = set()
    if isinstance(payload.get("models"), list):
        missing = [short_name(str(m)) for m in payload["models"] if MODEL_RE.match(str(m)) and short_name(str(m)) not in installed][:100]
        if missing:
            atomic_write(os.path.join(STATE_DIR, "fleet-pull.txt"), "\n".join(missing) + "\n", 0o600)
            report["pull"] = {"models": missing, "job": start_job("fleet-pull")}
        else:
            report["pull"] = {"models": [], "job": None}
    if isinstance(payload.get("custom"), dict):
        done, waiting = [], []
        for name, spec in list(payload["custom"].items())[:100]:
            if not isinstance(spec, dict):
                continue
            if short_name(str(spec.get("base", ""))) not in installed:
                waiting.append(name)   # modèle de base absent (téléchargement en cours ?) : prochaine synchronisation
                continue
            try:
                custom_create({"name": name, "base": spec.get("base"), "system": spec.get("system", ""), "params": spec.get("params") or {}})
                done.append(name)
            except ValueError as e:
                waiting.append("%s (%s)" % (name, e))
        report["custom"] = {"created": done, "waiting": waiting}
    d = load_json_file(FLEET_MEMBER, {})
    d["last_sync"] = {"from": caller["name"], "at": int(time.time()), "report": report}
    atomic_write(FLEET_MEMBER, json.dumps(d, ensure_ascii=False, indent=1), 0o600)
    return report


def member_action(action, caller=None, data=None):
    if action == "sync":
        return {"report": member_sync(caller, data)}
    if action == "route-token":   # répartition de charge : jeton limité aux requêtes vers les modèles
        with _fleet_lock:
            consoles = [c for c in load_member() if not (c.get("scope") == "route" and c.get("parent") == caller["id"])]
            save_member(consoles)
        return {"token": member_create((caller["name"] + " (routage)")[:40], "route", caller["id"])}
    if action == "route-revoke":
        with _fleet_lock:
            save_member([c for c in load_member() if not (c.get("scope") == "route" and c.get("parent") == caller["id"])])
        return None
    if action == "power-sleep":   # mise en veille demandée par la console principale (seulement si ce serveur l'a autorisée)
        power_member_sleep(str((data or {}).get("mode") or ""))
        return None
    if action not in FLEET_ACTIONS:
        raise ValueError("action non autorisée à distance")
    if action == "restart-ollama":
        update_env({})   # redémarre Ollama et les groupes de GPU
        return None
    return start_job(action)


# --- côté console principale
def load_fleet():
    return load_json_file(FLEET_FILE, {}).get("servers", [])


def save_fleet(servers):
    atomic_write(FLEET_FILE, json.dumps({"servers": servers}, ensure_ascii=False, indent=1), 0o600)   # contient les jetons


def fleet_request(url, path, token=None, fingerprint=None, method="GET", body=None, timeout=10):
    u = urllib.parse.urlsplit(url)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # certificats autosignés : remplacé par l'épinglage de l'empreinte
    conn = http.client.HTTPSConnection(u.hostname, u.port or 443, context=ctx, timeout=timeout)
    try:
        conn.connect()
        got = der_fingerprint(conn.sock.getpeercert(binary_form=True))
        if fingerprint and got != fingerprint:
            raise FleetError(got)
        headers = {"X-OB": "1", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = conn.getresponse()
        raw = r.read(4 * 1024 * 1024)
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        return r.status, data, got
    finally:
        conn.close()


def check_fleet_url(url):
    url = str(url or "").strip().rstrip("/")
    if not FLEET_URL_RE.match(url + "/"):
        raise ValueError("adresse invalide : https://adresse[:port] (ex. https://10.0.0.21)")
    return url


def fleet_probe(url):
    url = check_fleet_url(url)
    try:
        code, data, got = fleet_request(url, "/api/ping", timeout=8)
    except (OSError, ssl.SSLError) as e:
        raise ValueError("serveur injoignable : %s" % e)
    if code != 200 or "version" not in data:
        raise ValueError("ce n'est pas une console OllamaBuntu")
    return {"url": url, "fingerprint": got, "version": data["version"]}


def fleet_add(data):
    url, token, fp = check_fleet_url(data.get("url")), str(data.get("token", "")).strip(), str(data.get("fingerprint", "")).strip()
    name = str(data.get("name", "")).strip()
    if not POOL_NAME_RE.match(name):
        raise ValueError("nom invalide (1 à 40 caractères)")
    if not re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", fp):
        raise ValueError("empreinte de certificat manquante : vérifiez d'abord le serveur")
    with _fleet_lock:
        servers = load_fleet()
        if any(s["url"] == url for s in servers):
            raise ValueError("ce serveur est déjà enregistré")
    try:
        code, summary, _ = fleet_request(url, "/api/fleet/status", token, fp)
    except FleetError:
        raise ValueError("le certificat du serveur a changé depuis la vérification : recommencez")
    except (OSError, ssl.SSLError) as e:
        raise ValueError("serveur injoignable : %s" % e)
    if code == 401:
        raise ValueError("jeton refusé par le serveur (copié en entier ? révoqué ?)")
    if code != 200:
        raise ValueError("réponse inattendue du serveur (%d)" % code)
    sid = secrets.token_hex(4)
    with _fleet_lock:
        servers = load_fleet()
        servers.append({"id": sid, "name": name, "url": url, "token": token, "fingerprint": fp, "added": int(time.time())})
        save_fleet(servers)
        _fleet_state[sid] = {"state": "en ligne", "data": summary, "checked": int(time.time())}
    return sid


def fleet_poll_one(s):
    st = {"checked": int(time.time()), "data": (_fleet_state.get(s["id"]) or {}).get("data")}
    try:
        code, data, _ = fleet_request(s["url"], "/api/fleet/status", s["token"], s["fingerprint"])
        if code == 200:
            st.update(state="en ligne", data=data, last_ok=int(time.time()))
        elif code == 401:
            st.update(state="jeton refusé")
        else:
            st.update(state="erreur %d" % code)
    except FleetError as e:
        st.update(state="certificat changé", new_fingerprint=str(e))
    except (OSError, ssl.SSLError) as e:
        st.update(state="hors ligne", error=str(e)[:120])
    st.setdefault("last_ok", (_fleet_state.get(s["id"]) or {}).get("last_ok"))
    _fleet_state[s["id"]] = st


def fleet_worker():
    time.sleep(3)
    while True:
        for s in load_fleet():
            try:
                fleet_poll_one(s)
            except Exception as e:
                sys.stderr.write("gestion centralisée (%s) : %s\n" % (s.get("name"), e))
        try:
            write_fleet_routes()
        except Exception as e:
            sys.stderr.write("gestion centralisée (routes) : %s\n" % e)
        time.sleep(int(os.environ.get("OB_FLEET_INTERVAL", "15")))


def fleet_set_modelmap(sid, mapping):
    """Modèles de remplacement d'un serveur du parc (GPU différents : il ne peut pas faire tourner le même modèle)."""
    if not isinstance(mapping, dict) or len(mapping) > 50:
        raise ValueError("correspondances invalides")
    clean = {}
    for k, v in mapping.items():
        k, v = str(k).strip(), str(v).strip()
        if not k and not v:
            continue
        if (k != "*" and not MODEL_RE.match(k)) or not MODEL_RE.match(v):
            raise ValueError("nom de modèle invalide : %s" % (k if k != "*" and not MODEL_RE.match(k) else v))
        clean[k if k == "*" else short_name(k)] = short_name(v)
    with _fleet_lock:
        servers = load_fleet()
        for x in servers:
            if x["id"] == sid:
                x["model_map"] = clean
                break
        else:
            raise ValueError("serveur inconnu")
        save_fleet(servers)
    write_fleet_routes()


def fleet_view():
    out = []
    for s in load_fleet():
        st = _fleet_state.get(s["id"]) or {"state": "en attente"}
        out.append(dict({k: v for k, v in s.items() if k not in ("token", "route_token")}, route=bool(s.get("route_token")), **st))
    try:
        tags = [m for m in ollama_json("GET", "/api/tags", timeout=3)[1].get("models", []) if not hidden_model(m.get("name", ""))]
    except (OSError, ValueError):
        tags = []
    local = sorted({short_name(m.get("name", "")) for m in tags})
    details = {}
    for m in tags:   # taille de chaque modèle de cette console : sert à proposer un remplacement de taille comparable
        details[short_name(m.get("name", ""))] = int(m.get("size") or 0)
    return {"servers": out, "actions": FLEET_ACTIONS, "sync_kinds": SYNC_KINDS, "local_models": local,
            "local_details": [{"name": n, "size": details.get(n, 0)} for n in local]}


FLEET_ROUTES = os.path.join(ETC, "fleet-routes.json")


def fleet_sync(sid, kinds):
    kinds = [k for k in kinds or [] if k in SYNC_KINDS]
    if not kinds:
        raise ValueError("choisissez au moins un élément à synchroniser")
    payload = {}
    if "policy" in kinds:
        payload["policy"] = {k: v for k, v in load_policy().items() if k in ("cloud", "ollama_internet", "webui_locked", "webui")}
    if "keys" in kinds:   # empreintes seulement : les clés elles-mêmes ne sont jamais conservées
        payload["keys"] = [{k: v for k, v in key.items() if k in ("id", "name", "hash", "prefix", "perms", "models", "deny", "enabled", "created", "words", "collections")}
                           for key in load_publication()["keys"] if not key.get("synced_from")]
    custom = load_custom()
    if "custom" in kinds:
        payload["custom"] = custom
    if "models" in kinds:
        try:
            tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
        except (OSError, ValueError):
            tags = []
        names = [short_name(m.get("name", "")) for m in tags]
        payload["models"] = [n for n in names if n not in custom and not hidden_model(n)]
        if "custom" in kinds:   # modèles de base des modèles personnalisés
            payload["models"] = sorted(set(payload["models"]) | {short_name(c.get("base", "")) for c in custom.values()})
    targets = [x for x in load_fleet() if sid in ("all", x["id"]) and (sid != "all" or (_fleet_state.get(x["id"]) or {}).get("state") == "en ligne")]
    if not targets:
        raise ValueError("aucun serveur en ligne à synchroniser" if sid == "all" else "serveur inconnu")
    results = {}
    for x in targets:
        try:
            code, data, _ = fleet_request(x["url"], "/api/fleet/action", x["token"], x["fingerprint"], "POST", {"action": "sync", "data": payload}, timeout=600)
            results[x["name"]] = data.get("report") if code == 200 else {"error": data.get("error") or "refusé (%d)" % code}
        except FleetError:
            results[x["name"]] = {"error": "certificat changé : approuvez-le d'abord"}
        except (OSError, ssl.SSLError) as e:
            results[x["name"]] = {"error": "injoignable : %s" % e}
        with _fleet_lock:
            servers = load_fleet()
            for y in servers:
                if y["id"] == x["id"]:
                    y["last_sync"] = {"at": int(time.time()), "kinds": kinds, "report": results[x["name"]]}
            save_fleet(servers)
    return results


def avg_load(gpu_live, cpu_usage):
    utils = [g["util"] for g in gpu_live or [] if g.get("util") is not None]
    return round(sum(utils) / len(utils), 1) if utils else float(cpu_usage or 0)


def write_fleet_routes():
    """Serveurs utilisables par le routeur (jetons de routage seulement : ni état ni actions)."""
    servers = []
    wake_on = power_config()["enabled"]
    for s in load_fleet():
        st = _fleet_state.get(s["id"]) or {}
        d = st.get("data") or {}
        if not s.get("route_token"):
            continue
        servers.append({"id": s["id"], "name": s["name"], "url": s["url"], "fingerprint": s["fingerprint"], "token": s["route_token"],
                        "online": st.get("state") == "en ligne", "models": d.get("model_tags", []), "model_map": s.get("model_map") or {},
                        "wake": bool(wake_on and (s.get("power") or {}).get("wake") and (s.get("power") or {}).get("mac")),   # réveillable par la console : le routeur signale alors les modèles qu'il est seul à avoir
                        "loaded": [m.get("name") for m in (d.get("ollama") or {}).get("running", [])],
                        "load": avg_load(d.get("gpu_live"), (d.get("cpu") or {}).get("usage"))})
    try:
        running = [m.get("name") for m in ollama_json("GET", "/api/ps", timeout=3, addr=OLLAMA_ADDR)[1].get("models", [])]
    except (OSError, ValueError):
        running = []
    last = (list(_metrics["samples"]) or [{}])[-1]
    local = {"load": avg_load(gpu_metrics(), last.get("cpu")), "loaded": running}   # même mesure que les serveurs distants : GPU, sinon processeur
    text = json.dumps({"local": local, "servers": servers, "rules": load_rules(), "updated": int(time.time())}, ensure_ascii=False)
    if read_text(FLEET_ROUTES) != text:
        atomic_write(FLEET_ROUTES, text, 0o640)
        gid = ollama_group_id()
        if gid is not None and os.geteuid() == 0:
            os.chown(FLEET_ROUTES, 0, gid)   # lisible par le routeur (utilisateur ollama), pas par les autres



# ------------------------------------------------------- laboratoire : comparateur et tests ---
LAB_FILE = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "lab.json")
_lab_lock = threading.Lock()
_lab = {"cmp": {"running": False, "models": [], "prompts": [], "step": 0, "total": 0, "error": ""},
        "eval": {"running": False, "suite": "", "model": "", "step": 0, "total": 0, "error": ""}}


def lab_load():
    d = load_json_file(LAB_FILE, {})
    return {"suites": [x for x in d.get("suites", []) if isinstance(x, dict)], "runs": [x for x in d.get("runs", []) if isinstance(x, dict)][-60:],
            "compare": d.get("compare") if isinstance(d.get("compare"), dict) else None, "last_version": str(d.get("last_version") or "")}


def lab_save(d):
    atomic_write(LAB_FILE, json.dumps({"suites": d["suites"], "runs": d["runs"][-60:], "compare": d.get("compare"), "last_version": d.get("last_version", "")}, ensure_ascii=False), 0o600)


def lab_generate(model, prompt, num_predict, addr):
    """Une génération déterministe (température 0, graine fixe). Retourne (réponse Ollama, ligne /api/ps du modèle)."""
    code, gen = ollama_json("POST", "/api/generate", {"model": model, "prompt": prompt, "stream": False, "keep_alive": "10m",
                                                      "options": {"temperature": 0, "seed": 1, "num_predict": num_predict}}, timeout=600, addr=addr)
    if code != 200:
        raise ValueError(str(gen.get("error") or "erreur Ollama %s" % code)[:200])
    ps = next((m for m in ollama_json("GET", "/api/ps", timeout=5, addr=addr)[1].get("models", []) if m.get("name") == model), None)
    return gen, ps


def lab_compare_run(models, prompts, num_predict):
    c, rows = _lab["cmp"], []
    try:
        for model in models:
            addr = bench_addr(model)
            for pi, p in enumerate(prompts):
                c["step"] += 1
                try:
                    gen, ps = lab_generate(model, p, num_predict, addr)
                    rows.append(evals.compare_row(model, pi, gen, ps))
                except (OSError, ValueError) as e:
                    rows.append({"model": model, "prompt": pi, "response": "", "error": str(e)[:200], "tokens": 0, "tps": None, "ttft_ms": None, "load_ms": 0, "total_ms": 0, "size": None, "vram_pct": None})
        d = lab_load()
        d["compare"] = {"t": int(time.time()), "models": models, "prompts": prompts, "num_predict": num_predict, "rows": rows, "summary": evals.compare_summary(models, rows)}
        with _lab_lock:
            lab_save(d)
        c["error"] = ""
    except Exception as e:
        c["error"] = str(e)[:200]
    finally:
        c["running"] = False


def lab_compare_start(models, prompts, num_predict):
    models, prompts, num_predict = evals.compare_clean(models, prompts, num_predict)
    if any(not MODEL_RE.match(m) for m in models):
        raise ValueError("nom de modèle invalide")
    if _lab["cmp"]["running"]:
        raise ValueError("une comparaison est déjà en cours")
    _lab["cmp"].update(running=True, models=models, prompts=prompts, step=0, total=len(models) * len(prompts), error="")
    threading.Thread(target=lab_compare_run, args=(models, prompts, num_predict), daemon=True).start()


def lab_suite_find(d, sid):
    return next((x for x in d["suites"] if x.get("id") == sid), None)


def lab_suite_save(data):
    suite = evals.suite_clean(data)
    if suite["model"] and not MODEL_RE.match(suite["model"]):
        raise ValueError("nom de modèle invalide")
    with _lab_lock:
        d = lab_load()
        if suite["id"]:
            if not lab_suite_find(d, suite["id"]):
                raise ValueError("jeu de tests inconnu")
            d["suites"] = [suite if x.get("id") == suite["id"] else x for x in d["suites"]]
        else:
            if len(d["suites"]) >= evals.MAX_SUITES:
                raise ValueError("%d jeux de tests au plus" % evals.MAX_SUITES)
            suite["id"] = secrets.token_hex(4)
            d["suites"].append(suite)
        lab_save(d)
    return suite["id"]


def lab_suite_delete(sid):
    with _lab_lock:
        d = lab_load()
        d["suites"] = [x for x in d["suites"] if x.get("id") != sid]
        d["runs"] = [r for r in d["runs"] if r.get("suite") != sid]
        lab_save(d)


def lab_eval_core(sid, model, who, reason, step=None, notify=True):
    """Rejoue un jeu de tests : un résultat par cas, comparé à la dernière exécution du même jeu et du même modèle. Retourne l'exécution enregistrée."""
    d = lab_load()
    suite = lab_suite_find(d, sid)
    if not suite:
        raise ValueError("jeu de tests inconnu")
    addr, results = bench_addr(model), []
    for case in suite["cases"]:
        if step:
            step()
        try:
            gen, _ps = lab_generate(model, case["prompt"], 400, addr)
            results.append(evals.case_result(case, gen))
        except (OSError, ValueError) as err:
            results.append({"name": case["name"], "ok": False, "why": [], "error": str(err)[:200], "response": "", "tps": None, "ttft_ms": None, "tokens": 0})
    run = {"id": secrets.token_hex(4), "suite": sid, "suite_name": suite["name"], "model": model, "t": int(time.time()), "who": who, "reason": reason, "version": VERSION,
           "env": perf.detect_profile(read_env()), "results": results, "summary": evals.run_summary(results)}
    with _lab_lock:
        d = lab_load()
        prev = next((r for r in reversed(d["runs"]) if r.get("suite") == sid and r.get("model") == model), None)
        run["diff"] = evals.compare_runs(prev, run)
        d["runs"].append(run)
        lab_save(d)
    if notify and run["diff"] and run["diff"]["degraded"]:
        cfg = load_alerts()
        if cfg.get("enabled"):
            txt = "Tests « %s » (%s) : dégradation après %s — %s" % (suite["name"], model, reason, ("%d cas échoue(nt) maintenant" % len(run["diff"]["regressions"])) if run["diff"]["regressions"] else ("débit %+.0f %%" % run["diff"]["tps_pct"]))
            alerts_send(cfg, [{"state": "alert", "text": txt}])
    return run


def lab_eval_run(sid, model, who, reason):
    e = _lab["eval"]
    def step():
        e["step"] += 1
    try:
        lab_eval_core(sid, model, who, reason, step)
        e["error"] = ""
    except Exception as err:
        e["error"] = str(err)[:200]
    finally:
        e["running"] = False


def lab_eval_start(sid, model, who, reason="manuel"):
    d = lab_load()
    suite = lab_suite_find(d, sid)
    if not suite:
        raise ValueError("jeu de tests inconnu")
    model = str(model or suite.get("model") or "")
    if not MODEL_RE.match(model):
        raise ValueError("choisissez un modèle")
    if _lab["eval"]["running"]:
        raise ValueError("un jeu de tests est déjà en cours")
    _lab["eval"].update(running=True, suite=sid, model=model, step=0, total=len(suite["cases"]), error="")
    threading.Thread(target=lab_eval_run, args=(sid, model, who, reason), daemon=True).start()


def lab_autorun(reason, delay=0):
    """Rejoue, l'un après l'autre, les jeux marqués « automatique » (après un changement de profil ou une mise à jour)."""
    def go():
        time.sleep(delay)   # laisse à Ollama le temps de redémarrer
        for suite in [x for x in lab_load()["suites"] if x.get("auto") and x.get("model")]:
            for _ in range(600):   # attend la fin d'une éventuelle exécution en cours
                if not _lab["eval"]["running"]:
                    break
                time.sleep(2)
            try:
                lab_eval_start(suite["id"], suite["model"], "automatique", reason)
            except ValueError:
                continue
            while _lab["eval"]["running"]:
                time.sleep(2)
    threading.Thread(target=go, daemon=True).start()


def lab_worker():
    """Après une mise à jour de la console (version différente de la dernière connue), rejoue les jeux automatiques."""
    time.sleep(150)
    try:
        d = lab_load()
        if d["last_version"] and d["last_version"] != VERSION:
            lab_autorun("la mise à jour %s" % VERSION)
        if d["last_version"] != VERSION:
            with _lab_lock:
                d = lab_load()
                d["last_version"] = VERSION
                lab_save(d)
    except Exception as e:
        sys.stderr.write("laboratoire : %s\n" % e)


def lab_view():
    d = lab_load()
    models = []
    try:
        models = sorted(m.get("name") for m in ollama_json("GET", "/api/tags", timeout=4)[1].get("models", []) if m.get("name") and not m["name"].endswith("-cloud") and not hidden_model(m["name"]))
    except (OSError, ValueError):
        pass
    runs = list(reversed(d["runs"]))[:40]
    return {"models": models, "suites": d["suites"], "runs": [dict(r, results=[dict(x, response=x.get("response", "")[:600]) for x in r.get("results", [])]) for r in runs],
            "compare": d["compare"], "cmp_state": dict(_lab["cmp"]), "eval_state": dict(_lab["eval"]), "default_prompts": evals.COMPARE_PROMPTS}


# ------------------------------------------- mise à jour des modèles avec retour arrière ---
MU_FILE = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "model-updates.json")
_mu_lock = threading.Lock()
_mu = {"running": False, "model": "", "step": "", "done": 0, "total": 0, "error": ""}
MU_SMOKE_PROMPT = "Réponds uniquement par le mot : OK"


def mu_load():
    d = load_json_file(MU_FILE, {})
    try:
        cfg = modelupdate.config_clean(d.get("config") or {})
    except ValueError:
        cfg = modelupdate.config_clean({})
    prev = {k: v for k, v in (d.get("prev") or {}).items() if isinstance(v, dict) and v.get("prev")}
    return {"config": cfg, "history": [h for h in d.get("history", []) if isinstance(h, dict)][-100:], "prev": prev, "last_key": str(d.get("last_key") or "")}


def mu_save(d):
    atomic_write(MU_FILE, json.dumps({"config": d["config"], "history": d["history"][-100:], "prev": d["prev"], "last_key": d.get("last_key", "")}, ensure_ascii=False), 0o600)


def mu_config_set(data):
    cfg = modelupdate.config_clean(data)
    if cfg["suite"] and not lab_suite_find(lab_load(), cfg["suite"]):
        raise ValueError("jeu de tests inconnu")
    if cfg["scope"] != "all" and any(not MODEL_RE.match(m) for m in cfg["scope"]):
        raise ValueError("nom de modèle invalide")
    with _mu_lock:
        d = mu_load()
        d["config"] = cfg
        mu_save(d)


def mu_installed():
    try:
        return [m for m in ollama_json("GET", "/api/tags", timeout=10)[1].get("models", []) if m.get("name") and not hidden_model(m["name"]) and not m["name"].endswith("-cloud")]
    except (OSError, ValueError):
        return []


def mu_check():
    """Modèles installés avec leur état de mise à jour (interroge les registres : quelques secondes)."""
    from concurrent.futures import ThreadPoolExecutor
    installed = mu_installed()
    def one(m):
        try:
            return m, registry_manifest(m["name"]), False
        except (OSError, ValueError):
            return m, None, True
    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for m, r, err in ex.map(one, installed):
            out.append({"name": m["name"], "size": m.get("size", 0), "update": model_update_state(m, r, err), "digest": m.get("digest", "")})
    return out


def mu_smoke(model, addr):
    """Test rapide : deux réponses courtes (la 1re charge le modèle). Retourne (ok, raison, débit de la 2e)."""
    tps = None
    try:
        for _ in range(2):
            gen, _ps = lab_generate(model, MU_SMOKE_PROMPT, 32, addr)
            if not str(gen.get("response") or "").strip():
                return False, "réponse vide", None
            tps = evals.compare_row(model, 0, gen)["tps"]
        return True, "", tps
    except (OSError, ValueError) as e:
        return False, str(e)[:160], None


def mu_unload(model, addr):
    try:
        ollama_json("POST", "/api/generate", {"model": model, "keep_alive": 0}, timeout=60, addr=addr)
    except (OSError, ValueError):
        pass


def mu_copy(src, dst):
    code, res = ollama_json("POST", "/api/copy", {"source": src, "destination": dst}, timeout=300)
    if code != 200:
        raise ValueError(str(res.get("error") or "erreur Ollama %s" % code)[:200])


def mu_delete(name):
    try:
        ollama_json("DELETE", "/api/delete", {"model": name, "name": name}, timeout=60)
    except (OSError, ValueError):
        pass


def mu_digest(name):
    return next((m.get("digest", "") for m in mu_installed() if m["name"] == name), "")


def mu_update_one(name, who, reason, cfg):
    """Met à jour un modèle : copie de sécurité, téléchargement, test, puis conservation ou retour arrière. Retourne la ligne d'historique."""
    prev, old = modelupdate.prev_name(name), mu_digest(name)
    addr = bench_addr(name)
    suite = lab_suite_find(lab_load(), cfg["suite"]) if cfg.get("suite") else None
    try:
        _mu["step"] = "mesure avant la mise à jour"
        _ok, _why, before_tps = mu_smoke(name, addr)
        before_run = lab_eval_core(suite["id"], name, who, "avant la mise à jour de %s" % name, notify=False) if suite else None
        _mu["step"] = "copie de sécurité"
        mu_copy(name, prev)
    except (OSError, ValueError) as e:
        return modelupdate.entry(time.time(), name, "failed", who, reason, "avant la mise à jour : %s" % e)
    try:
        _mu["step"] = "téléchargement"
        with egress_window():
            code, res = ollama_json("POST", "/api/pull", {"model": name, "stream": False}, timeout=7200)
        if code != 200 or res.get("error"):
            raise ValueError(str(res.get("error") or "erreur Ollama %s" % code)[:200])
    except (OSError, ValueError) as e:
        mu_delete(prev)   # rien n'a changé : la copie est inutile
        return modelupdate.entry(time.time(), name, "failed", who, reason, "téléchargement : %s" % e)
    new = mu_digest(name)
    if new == old:
        mu_delete(prev)
        return modelupdate.entry(time.time(), name, "unchanged", who, reason, "déjà à jour", old=old[:12], new=new[:12])
    _mu["step"] = "test après la mise à jour"
    mu_unload(name, addr)
    ok, why, after_tps = mu_smoke(name, addr)
    diff = None
    if suite and ok:
        try:
            diff = evals.compare_runs(before_run, lab_eval_core(suite["id"], name, who, "après la mise à jour de %s" % name, notify=False))
        except (OSError, ValueError) as e:
            ok, why = False, "jeu de tests : %s" % e
    verdict = modelupdate.decide(ok, why, diff, before_tps, after_tps, cfg["drop_pct"])
    extra = dict(old=old[:12], new=new[:12], tps_before=before_tps, tps_after=after_tps)
    if verdict["keep"]:
        with _mu_lock:
            d = mu_load()
            d["prev"][name] = {"prev": prev, "t": int(time.time()), "from": old, "to": new}
            mu_save(d)
        return modelupdate.entry(time.time(), name, "updated", who, reason, "nouvelle version conservée ; l'ancienne reste disponible %d jour(s)" % cfg["keep_days"], **extra)
    _mu["step"] = "retour à l'ancienne version"
    try:
        mu_copy(prev, name)
        mu_delete(prev)
        mu_unload(name, addr)
        return modelupdate.entry(time.time(), name, "rolled_back", who, reason, "; ".join(verdict["reasons"]), **extra)
    except (OSError, ValueError) as e:
        return modelupdate.entry(time.time(), name, "failed", who, reason, "retour arrière impossible (%s) ; la copie reste sous le nom %s" % (e, prev), **extra)



def mu_run(models, who, reason, deadline=None):
    entries = []
    try:
        cfg = mu_load()["config"]
        _mu.update(total=len(models), done=0)
        for name in models:
            if deadline and time.time() > deadline:
                break
            _mu.update(model=name, step="")
            e = mu_update_one(name, who, reason, cfg)
            entries.append(e)
            with _mu_lock:
                d = mu_load()
                d["history"].append(e)
                mu_save(d)
            _mu["done"] += 1
        text = modelupdate.alert_text(entries)
        acfg = load_alerts()
        if text and acfg.get("enabled"):
            alerts_send(acfg, [{"state": "alert", "text": text}])
        _mu["error"] = ""
    except Exception as e:
        _mu["error"] = str(e)[:200]
    finally:
        _mu.update(running=False, model="", step="")
    return entries


def mu_start(models, who):
    if _mu["running"]:
        raise ValueError("une mise à jour est déjà en cours")
    if not isinstance(models, list) or not 1 <= len(models) <= 50 or any(not isinstance(m, str) or not MODEL_RE.match(m) for m in models):
        raise ValueError("choisissez les modèles à mettre à jour")
    names = {m["name"] for m in mu_installed()}
    if any(m not in names for m in models):
        raise ValueError("modèle non installé")
    _mu.update(running=True, model="", step="", done=0, total=len(models), error="")
    threading.Thread(target=mu_run, args=(models, who, "manuelle"), daemon=True).start()


def mu_rollback(name, who):
    """Revient à la version d'avant la dernière mise à jour (tant que la copie de sécurité existe)."""
    if _mu["running"]:
        raise ValueError("une mise à jour est en cours")
    with _mu_lock:
        d = mu_load()
        p = d["prev"].get(name)
    if not p:
        raise ValueError("aucune ancienne version conservée pour ce modèle")
    mu_copy(p["prev"], name)
    mu_delete(p["prev"])
    mu_unload(name, bench_addr(name))
    with _mu_lock:
        d = mu_load()
        d["prev"].pop(name, None)
        d["history"].append(modelupdate.entry(time.time(), name, "manual_rollback", who, "manuelle", "ancienne version rétablie"))
        mu_save(d)


def mu_cleanup():
    with _mu_lock:
        d = mu_load()
        gone = modelupdate.expired(d["prev"], time.time(), d["config"]["keep_days"])
        for m in gone:
            mu_delete(d["prev"][m]["prev"])
            d["prev"].pop(m, None)
        if gone:
            mu_save(d)
    return gone


def mu_worker():
    time.sleep(90)
    last_clean = 0
    while True:
        try:
            if time.time() - last_clean > 3600:
                last_clean = time.time()
                mu_cleanup()
            d = mu_load()
            key = modelupdate.due(d["config"], time.localtime(), d["last_key"])
            if key and not _mu["running"]:
                with _mu_lock:
                    d = mu_load()
                    d["last_key"] = key
                    mu_save(d)
                cfg = d["config"]
                names = [m["name"] for m in mu_check() if m["update"]["state"] == "maj"]
                if cfg["scope"] != "all":
                    names = [n for n in names if n in cfg["scope"]]
                if names:
                    _mu.update(running=True, done=0, total=len(names), error="")
                    end = time.mktime(time.strptime(key + " " + cfg["start"], "%Y-%m-%d %H:%M")) + cfg["window"] * 60
                    mu_run(names, "automatique", "planifiée", end)
        except Exception as e:
            sys.stderr.write("mises à jour des modèles : %s\n" % e)
            _mu["running"] = False
        time.sleep(60)


def mu_view():
    d = mu_load()
    suites = [{"id": x["id"], "name": x["name"]} for x in lab_load()["suites"]]
    return {"config": d["config"], "history": list(reversed(d["history"]))[:50], "prev": d["prev"], "state": dict(_mu), "suites": suites,
            "models": sorted(m["name"] for m in mu_installed())}


# ---------------------------------------------------------------- alertes ---
ALERTS_FILE = os.path.join(ETC, "alerts.json")
ROUTER_LIMITS = os.environ.get("OB_ROUTER_LIMITS", "/var/lib/ollamabuntu-router/limits.json")
RULES_FILE = os.path.join(ETC, "routing-rules.json")
_alerts = {"active": {}, "notifier": monitor.Notifier(), "lock": threading.Lock(), "last_error": ""}


def load_alerts():
    cfg = json.loads(json.dumps(monitor.DEFAULTS))
    stored = load_json_file(ALERTS_FILE, {})
    for k, v in stored.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def alerts_view():
    cfg = load_alerts()
    sm = dict(cfg["smtp"])
    sm["has_password"] = bool(sm.pop("password", ""))
    return {"config": dict(cfg, smtp=sm), "events": monitor.EVENTS, "active": [dict(a, key=k) for k, a in _alerts["active"].items()],
            "last_error": _alerts["last_error"]}


def alerts_save(data):
    with _alerts["lock"]:
        cfg = monitor.clean_config(data, load_alerts())
        atomic_write(ALERTS_FILE, json.dumps(cfg, ensure_ascii=False, indent=1), 0o600)   # contient le mot de passe SMTP


def alert_snapshot():
    now = time.time()
    recent = [x for x in list(_metrics["samples"]) if x.get("t", 0) > now - 600]
    tps = [x["tps"] for x in recent if x.get("tps")]
    st = status()
    servers = [{"name": x["name"], "online": (_fleet_state.get(x["id"]) or {}).get("state") == "en ligne"} for x in load_fleet()
               if (_fleet_state.get(x["id"]) or {}).get("state") not in (None, "en attente")]
    keys = [{"name": k["name"], "days_left": expiry_days(k.get("expires"))} for k in load_publication().get("keys", []) if k.get("enabled", True) and k.get("expires")]
    perf_res = perf_snapshot(st)
    return {"perf": perf_res, "keys": keys, "guard": guard_status(max_age=120)["issues"], "hw": hw_view(max_age=600)["issues"], "service": st["ollama"]["service"], "disk": st["disk"], "gpus": st["gpu_live"], "offload": st["offload"], "servers": servers,
            "tps": {"avg": round(sum(tps) / len(tps), 1) if tps else None, "count": sum(x.get("req") or 0 for x in recent)}, "update": st["update_available"]}


# ------------------------------------------- disponibilité du GPU pour Ollama ---
# Surveille chaque minute que chaque carte de calcul a un pilote fonctionnel ET est utilisée par Ollama ;
# sinon (et si l'incident dure), recharge les modules NVIDIA manquants puis redémarre Ollama (dans la limite de
# 3 tentatives par heure, jamais de redémarrage du serveur). Chaque tentative est journalisée.
GUARD_FILE = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "gpu-guard.json")
MODPROBE = os.environ.get("OB_MODPROBE", "modprobe")
DEV_UVM = os.environ.get("OB_DEV_UVM", "/dev/nvidia-uvm")
_guard = {"state": {}, "last": None, "t": 0.0, "busy": False}
_guard_lock = threading.Lock()


def guard_config():
    c = load_json_file(GUARD_FILE, {})
    return {"auto": c.get("auto", True) is not False, "events": [e for e in c.get("events", []) if isinstance(e, dict)][-30:]}


def guard_store(auto=None, event=None):
    c = guard_config()
    if auto is not None:
        c["auto"] = bool(auto)
    if event:
        c["events"] = (c["events"] + [event])[-30:]
    atomic_write(GUARD_FILE, json.dumps(c, ensure_ascii=False), 0o644)


def guard_snapshot():
    info = gpu_info()
    expected = [d for d in info["devices"] if d["kind"] == "gpu" and not d["dropped"] and (d["vendor"] == "NVIDIA" or d.get("ollama"))]
    live = gpu_metrics()
    try:
        running = ollama_json("GET", "/api/ps", timeout=3, addr=OLLAMA_ADDR)[1].get("models", [])
    except (OSError, ValueError):
        running = []
    lines = ollama_log_text("ollama.service").splitlines()
    starts = [i for i, l in enumerate(lines) if "discovering available GPUs" in l]
    restricted = bool(load_pools()) or any(k in read_env() or k in read_env_file(MAIN_OVERRIDE) for k in VIS_KEYS)
    return {"pci": [{"slot": d["slot"], "name": d["name"], "vendor": d["vendor"]} for d in expected],
            "driver": [g["pci"] for g in live] + [d["slot"] for d in expected if d["vendor"] != "NVIDIA"],
            "ollama": [d["slot"] for d in expected if d.get("ollama")],
            "ollama_active": run(["systemctl", "is-active", "ollama.service"], 5).strip() == "active",
            "loaded": running, "free": {g["pci"]: (g.get("mem_total") or 0) - (g.get("mem_used") or 0) for g in live},
            "restricted": restricted, "log_errors": hw.log_errors(lines[starts[-1]:] if starts else lines[-300:])}


def guard_status(max_age=45):
    """État courant (calculé au plus toutes les `max_age` secondes) + réglage + historique des réparations."""
    with _guard_lock:
        if _guard["last"] is None or time.time() - _guard["t"] > max_age:
            _guard["last"], _guard["t"] = hw.gpu_guard(guard_snapshot()), time.time()
        res = _guard["last"]
    cfg = guard_config()
    return dict(res, auto=cfg["auto"], events=list(reversed(cfg["events"])), repairing=_guard["busy"])


def guard_remediate(plan, who="automatique"):
    """Exécute les étapes d'un plan, vérifie le résultat et le consigne. Bloquant (jusqu'à ~90 s)."""
    if _guard["busy"]:
        raise ValueError("une réparation est déjà en cours")
    _guard["busy"] = True
    done = []
    try:
        for step in plan["steps"]:
            if step == "load-driver":
                run([MODPROBE, "nvidia"], timeout=40)
            elif step == "load-uvm" and not os.path.exists(DEV_UVM):
                run([MODPROBE, "nvidia_uvm"], timeout=30)
                if not os.path.exists(DEV_UVM) and shutil.which("nvidia-modprobe"):
                    run(["nvidia-modprobe", "-u", "-c=0"], timeout=20)
            elif step == "restart-ollama":
                run(["systemctl", "restart", "ollama.service"], timeout=90)
                for p in load_pools():
                    run(["systemctl", "restart", "ollama-pool@%s.service" % p["id"]], timeout=90)
            else:
                continue
            done.append(step)
        gpu_info_cache_clear()
        ok, res = False, None
        for _ in range(12):   # Ollama relance sa détection du matériel : jusqu'à 60 s
            time.sleep(5)
            res = guard_status(max_age=0)
            if not [i for i in res["issues"] if i["severity"] != "info"]:
                ok = True
                break
        guard_store(event={"t": int(time.time()), "who": who, "codes": plan.get("codes", []), "steps": done, "result": "résolu" if ok else "non résolu",
                           "remaining": [i["text"] for i in (res or {})["issues"] if i["severity"] != "info"][:3] if not ok else []})
        print("garde GPU : %s (%s) -> %s" % (", ".join(plan.get("codes", [])), ", ".join(done), "résolu" if ok else "non résolu"), flush=True)
        return ok
    finally:
        _guard["busy"] = False


def gpu_info_cache_clear():
    _gpu_live["t"] = 0   # nvidia-smi relu immédiatement


def guard_repair_now(who):
    """Réparation demandée par l'administrateur : mêmes étapes, sans attendre la persistance ni le délai entre tentatives."""
    res = guard_status(max_age=0)
    codes = {i["code"] for i in res["issues"] if i.get("fix") in ("reload-driver", "restart-ollama")}
    if not codes:
        raise ValueError("rien à réparer : chaque carte est utilisée par Ollama")
    plan = {"steps": (["load-driver"] if "driver_down" in codes else []) + ["load-uvm", "restart-ollama"], "codes": sorted(codes)}
    threading.Thread(target=lambda: guard_remediate(plan, who), daemon=True).start()
    return plan


def guard_worker():
    time.sleep(90)
    while True:
        try:
            res = guard_status(max_age=0)
            plan = hw.guard_plan(res["issues"], _guard["state"], time.time(), guard_config()["auto"])
            if plan:
                guard_remediate(plan)
        except Exception as e:   # la surveillance ne doit jamais s'arrêter
            sys.stderr.write("garde GPU : %s\n" % e)
        time.sleep(60)


# ------------------------------------------------------------ performances ---
PERF_FILE = os.path.join(ETC, "perf.json")
BENCH_FILE = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "bench.json")
WARMUP_FILE = os.path.join(ETC, "warmup.json")
SYSCTL_CONF = "/etc/sysctl.d/90-ollamabuntu.conf"
TMPFILES_CONF = "/etc/tmpfiles.d/ollamabuntu-governor.conf"
WEBUI_LIMITS = os.path.join(ETC, "open-webui.limits")
_perf_lock = threading.Lock()
_perf_last = {"guard": None}
_bench = {"running": False, "model": "", "step": 0, "runs": 0, "error": ""}
_warm = {"log": [], "played": {}, "booted": False}


def perf_config():
    c = load_json_file(PERF_FILE, {})
    g = c.get("guard") if isinstance(c.get("guard"), dict) else {}
    mode = g.get("mode") if g.get("mode") in ("off", "suggest", "auto") else "suggest"
    try:
        drop = min(90, max(10, int(g.get("drop_pct", 50))))
    except (TypeError, ValueError):
        drop = 50
    return {"guard": {"mode": mode, "drop_pct": drop}, "events": [e for e in c.get("events", []) if isinstance(e, dict)][-20:], "last_change": int(c.get("last_change") or 0)}


def perf_store(guard=None, event=None, changed=False):
    with _perf_lock:
        c = perf_config()
        if guard is not None:
            c["guard"] = guard
        if event:
            c["events"] = (c["events"] + [event])[-20:]
        if changed:
            c["last_change"] = int(time.time())
        atomic_write(PERF_FILE, json.dumps(c, ensure_ascii=False), 0o644)


def perf_snapshot(st=None):
    """Chute de débit éventuelle (calculée à chaque passage de la supervision) ; None si le garde-fou est désactivé."""
    cfg = perf_config()["guard"]
    if cfg["mode"] == "off":
        _perf_last["guard"] = None
        return None
    st = st or status()
    with _metrics_lock:
        samples = list(_metrics["samples"])
    res = perf.perf_guard(samples, time.time(), st.get("offload") or [], read_env(), cfg["drop_pct"])
    _perf_last["guard"] = res
    return res


def perf_auto_step(res):
    """Mode automatique : applique un seul pas de réglage, au plus un par heure, jamais pendant une mesure, 3 par jour au maximum."""
    cfg = perf_config()
    if cfg["guard"]["mode"] != "auto" or not res or not res.get("fix") or _bench["running"]:
        return False
    now = time.time()
    if now - cfg["last_change"] < 3600 or sum(1 for e in cfg["events"] if e.get("who") == "automatique" and now - e.get("t", 0) < 86400) >= 3:
        return False
    changes = perf.normalize_env(res["fix"]["changes"], read_env())
    update_env(changes)
    perf_store(event={"t": int(now), "who": "automatique", "text": res["text"], "changes": changes}, changed=True)
    print("garde-fou de débit : %s -> %s" % (res["text"], changes), flush=True)
    return True


def sys_view():
    gov = [read_text(g) for g in sorted(glob.glob(sysp("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor")))]
    sw = read_text(sysp("/proc/sys/vm/swappiness"))
    mi = meminfo()
    swaps = read_text(sysp("/proc/swaps"))
    webui = {"deployed": webui_deployed(), "limit_mb": None, "rss_mb": None}
    if webui["deployed"] and shutil.which("docker"):
        lim = run(["docker", "inspect", "-f", "{{.HostConfig.Memory}}", "open-webui"], timeout=8).strip()
        webui["limit_mb"] = int(lim) // 1048576 if lim.isdigit() and int(lim) > 0 else None
        use = run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", "open-webui"], timeout=10).split("/")[0].strip()
        m = re.fullmatch(r"([\d.]+)\s*(MiB|GiB|KiB|B)", use)
        if m:
            webui["rss_mb"] = round(float(m.group(1)) * {"GiB": 1024, "MiB": 1, "KiB": 1 / 1024.0, "B": 1 / 1048576.0}[m.group(2)])
    return perf.sys_checks({"swappiness": int(sw) if sw.isdigit() else None, "governors": gov, "mem_total": mi.get("MemTotal"), "swap_total": mi.get("SwapTotal"),
                            "zram": "zram" in swaps, "webui": webui})


def sys_fix(fix, value=None):
    if fix == "swappiness":
        atomic_write(sysp(SYSCTL_CONF), "# OllamaBuntu : limite l'écriture précoce en swap (Ollama garde ses modèles en mémoire)\nvm.swappiness=10\n", 0o644)
        run(["sysctl", "-w", "vm.swappiness=10"], timeout=10)
    elif fix == "governor":
        atomic_write(sysp(TMPFILES_CONF), "# OllamaBuntu : fréquence du processeur maximale (latence du premier jeton)\nw /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor - - - - performance\n", 0o644)
        for g in glob.glob(sysp("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor")):
            try:
                with open(g, "w") as f:
                    f.write("performance")
            except OSError:
                pass
    elif fix == "webui_mem":
        mb = perf.parse_limit(value or "2g")
        atomic_write(WEBUI_LIMITS, "MEM=%dm\n" % mb, 0o644)
        if shutil.which("docker"):
            run(["docker", "update", "--memory", "%dm" % mb, "--memory-swap", "%dm" % mb, "open-webui"], timeout=30)
    else:
        raise ValueError("réglage inconnu")


def bench_history():
    return [h for h in load_json_file(BENCH_FILE, {}).get("history", []) if isinstance(h, dict)][-100:]


def bench_addr(model):
    for unit, addr, pool in instances():
        try:
            if any(m.get("name") == model for m in ollama_json("GET", "/api/ps", timeout=3, addr=addr)[1].get("models", [])):
                return addr
        except (OSError, ValueError):
            continue
    return main_addr()


def bench_run(model, runs):
    """Mesure en tâche de fond : `runs` générations identiques (température 0), médiane retenue et comparée à la précédente."""
    results = []
    try:
        addr = bench_addr(model)
        for i in range(runs):
            _bench["step"] = i + 1
            code, gen = ollama_json("POST", "/api/generate", {"model": model, "prompt": perf.BENCH_PROMPT, "stream": False, "keep_alive": "10m",
                                                              "options": {"temperature": 0, "seed": 1, "num_predict": perf.BENCH_TOKENS}}, timeout=600, addr=addr)
            if code != 200:
                raise ValueError(str(gen.get("error") or "erreur Ollama %s" % code)[:200])
            ps = next((m for m in ollama_json("GET", "/api/ps", timeout=5, addr=addr)[1].get("models", []) if m.get("name") == model), None)
            mi = meminfo()
            results.append(perf.bench_result(model, gen, ps, {"used": mi.get("MemTotal", 0) - mi.get("MemAvailable", 0), "total": mi.get("MemTotal")}, read_env()))
        entry = perf.bench_median(results)
        hist = bench_history()
        entry["delta"] = perf.bench_compare(hist, entry)
        gpus = gpu_metrics()
        entry["vram_used"] = sum(g.get("mem_used") or 0 for g in gpus) or None
        entry["vram_total"] = sum(g.get("mem_total") or 0 for g in gpus) or None
        entry["profile"] = perf.detect_profile(read_env())
        atomic_write(BENCH_FILE, json.dumps({"history": (hist + [entry])[-100:]}, ensure_ascii=False), 0o600)
        _bench["error"] = ""
    except (OSError, ValueError) as e:
        _bench["error"] = str(e)[:200]
    finally:
        _bench["running"] = False


def bench_start(model, runs):
    model = str(model or "")
    if not MODEL_RE.match(model):
        raise ValueError("nom de modèle invalide")
    try:
        runs = int(runs or 2)
    except (TypeError, ValueError):
        raise ValueError("nombre de passes invalide")
    if not 1 <= runs <= 3:
        raise ValueError("1 à 3 passes")
    if _bench["running"]:
        raise ValueError("une mesure est déjà en cours")
    _bench.update(running=True, model=model, step=0, runs=runs, error="")
    threading.Thread(target=bench_run, args=(model, runs), daemon=True).start()


def warmup_config():
    try:
        return perf.warmup_clean(load_json_file(WARMUP_FILE, {}))
    except ValueError:
        return {"boot": [], "times": []}


def warm_model(model, why):
    env = read_env()
    keep = env.get("OLLAMA_KEEP_ALIVE") or "30m"
    rec = {"t": int(time.time()), "model": model, "why": why, "ok": False, "error": ""}
    try:
        addr = bench_addr(model)
        code, data = ollama_json("POST", "/api/generate", {"model": model, "prompt": "", "stream": False, "keep_alive": keep}, timeout=300, addr=addr)
        rec["ok"] = code == 200
        rec["error"] = "" if rec["ok"] else str(data.get("error") or code)[:160]
    except (OSError, ValueError) as e:
        rec["error"] = str(e)[:160]
    _warm["log"] = (_warm["log"] + [rec])[-20:]
    return rec["ok"]


def warmup_worker():
    time.sleep(60)
    while True:
        try:
            cfg = warmup_config()
            if not _warm["booted"]:
                try:
                    ollama_json("GET", "/api/tags", timeout=5)
                    _warm["booted"] = True
                    for m in cfg["boot"]:
                        warm_model(m, "démarrage")
                except OSError:
                    pass   # Ollama pas encore prêt : nouvel essai à la prochaine boucle
            for m in perf.warmup_due(cfg, time.localtime(), _warm["played"]):
                warm_model(m, "heure programmée")
        except Exception as e:
            sys.stderr.write("préchauffage : %s\n" % e)
        time.sleep(20)


def perf_view():
    env = read_env()
    cfg = perf_config()
    return {"env": {k: env.get(k, "") for k, _ in ENV_KEYS}, "current": perf.detect_profile(env),
            "profiles": [{"id": k, "label": p["label"], "help": p["help"], "diff": perf.profile_diff(k, env)} for k, p in perf.PROFILES.items()],
            "checks": sys_view(), "guard": cfg["guard"], "events": list(reversed(cfg["events"])), "alert": _perf_last.get("guard"),
            "warmup": dict(warmup_config(), log=list(reversed(_warm["log"]))), "bench": dict(_bench, history=list(reversed(bench_history()))[:30])}


# ------------------------------------------------- journal d'audit ---
AUDIT_FILE = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "audit.jsonl")
AUDIT_MAX = 2 * 1024 * 1024
_audit_lock = threading.Lock()


def audit_record(user, role, ip, path, data, status):
    """Ajoute une ligne au journal d'audit (jamais d'exception : la trace ne doit pas bloquer l'action)."""
    try:
        e = audit.entry(user, role, ip, path, data, status)
        with _audit_lock:
            os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
            try:
                if os.path.getsize(AUDIT_FILE) > AUDIT_MAX:
                    os.replace(AUDIT_FILE, AUDIT_FILE + ".1")
            except OSError:
                pass
            fd = os.open(AUDIT_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception as ex:   # noqa: BLE001
        sys.stderr.write("audit : %s\n" % ex)


def audit_entries(limit=5000):
    out = []
    for path in (AUDIT_FILE + ".1", AUDIT_FILE):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out[-limit:]


def audit_view(query):
    one = lambda k: (query.get(k) or [""])[0]
    rows = audit.search(audit_entries(), one("q"), one("user"), one("status"))
    users = sorted({e.get("user") for e in audit_entries() if e.get("user")})
    return {"entries": rows[:500], "total": len(rows), "users": users}


def audit_clear():
    for path in (AUDIT_FILE, AUDIT_FILE + ".1"):
        try:
            os.remove(path)
        except OSError:
            pass


# ------------------------------------------------ rapport hebdomadaire ---
REPORT_FILE = os.path.join(ETC, "report.json")
_report = {"last_error": "", "booted": time.time()}


def report_config():
    c = load_json_file(REPORT_FILE, {})
    try:
        cfg = report.clean_config(c)
    except ValueError:
        cfg = report.clean_config({})
    cfg["last_sent"] = str(c.get("last_sent") or "")
    return cfg


def models_disk(idle_days=30):
    """Modèles installés avec leur taille, leur dernière utilisation connue (journal des requêtes) et leur état ; inutilisés = candidats à la suppression."""
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    try:
        loaded = {short_name(m.get("name", "")) for m in ollama_json("GET", "/api/ps", timeout=3)[1].get("models", [])}
    except (OSError, ValueError):
        loaded = set()
    last = {}
    for r in read_requests(50000):
        m = r.get("model")
        if m and r.get("ts"):
            last[short_name(m)] = max(last.get(short_name(m), 0), r["ts"])
    pinned = set()
    for p in load_pools():
        pinned |= {short_name(m) for m in p.get("models", [])}
    for m in warmup_config()["boot"]:
        pinned.add(short_name(m))
    for t in warmup_config()["times"]:
        pinned |= {short_name(m) for m in t["models"]}
    now, keep = time.time(), reqlog_settings()["days"]
    out = []
    for t in tags:
        name = t.get("name", "")
        if name.endswith("-cloud"):
            continue
        sn = short_name(name)
        mod = t.get("modified_at") or ""
        try:
            age = (now - calendar.timegm(time.strptime(mod[:19], "%Y-%m-%dT%H:%M:%S"))) / 86400.0 if mod else None
        except ValueError:
            age = None
        seen = last.get(sn)
        idle = (now - seen) / 86400.0 if seen else None
        # inutilisé : aucune requête dans le journal conservé ET installé depuis plus longtemps que ce journal (sinon on ne sait pas)
        unused = seen is None and age is not None and age > max(keep, 1) and age > idle_days and sn not in loaded and sn not in pinned
        unused = unused or (seen is not None and idle > idle_days and sn not in loaded and sn not in pinned)
        out.append({"name": name, "size": t.get("size") or 0, "installed_days": round(age) if age is not None else None, "last_used": int(seen) if seen else None,
                    "idle_days": round(idle) if idle is not None else None, "loaded": sn in loaded, "pinned": sn in pinned, "unused": bool(unused)})
    out.sort(key=lambda m: (not m["unused"], -m["size"]))
    du = shutil.disk_usage(MODELS_DIR if os.path.isdir(MODELS_DIR) else "/")
    return {"models": out, "total": sum(m["size"] for m in out), "reclaimable": sum(m["size"] for m in out if m["unused"]),
            "disk": {"total": du.total, "free": du.free}, "journal_days": keep, "idle_days": idle_days}


def report_data():
    now = time.time()
    reqs = read_requests(50000)
    wk = now - 7 * 86400
    tps = [r["tps"] for r in reqs if r.get("ts", 0) >= wk and r.get("status") == 200 and r.get("tps")]
    st = status()
    keys = []
    for k in load_publication().get("keys", []):
        d = expiry_days(k.get("expires")) if k.get("enabled", True) and k.get("expires") else None
        if d is not None and d <= 14:
            keys.append("Clé d'API « %s » %s" % (k["name"], "expirée" if d < 0 else "expire dans %d jour(s)" % d))
    cfg_g, cfg_p = guard_config(), perf_config()
    return {"host": socket.gethostname(), "version": VERSION, "since": wk, "until": now,
            "usage": usage.aggregate(reqs, now, 7 * 86400, name=short_name), "tps_avg": round(sum(tps) / len(tps), 1) if tps else None,
            "uptime_days": int(st["uptime"] // 86400), "disk": st["disk"], "alerts": [a["text"] for a in _alerts["active"].values() if a.get("severity") != "info"],
            "guard_events": [e for e in cfg_g["events"] if e.get("t", 0) >= wk], "perf_events": ["%s (%s)" % (e["text"], e.get("who", "")) for e in cfg_p["events"] if e.get("t", 0) >= wk],
            "hw": [i["text"] for i in hw_view(600)["issues"]], "keys_expiring": keys, "update": st["update_available"],
            "models_unused": [m for m in models_disk()["models"] if m["unused"]], "costs": costs_week_lines(now)}


def report_send(test=False):
    cfg = load_alerts()["smtp"]
    if not (cfg.get("host") and cfg.get("to") and cfg.get("from")):
        raise ValueError("configurez d'abord le serveur SMTP et les destinataires (Système > Alertes)")
    obj, text, page = report.build(report_data())
    monitor.send_mail(cfg, cfg.get("password"), "[OllamaBuntu %s] %s" % (socket.gethostname(), ("TEST — " if test else "") + obj["title"].split(" — ", 1)[-1]), text, html=page)
    return obj


def report_worker():
    time.sleep(120)
    while True:
        try:
            cfg = report_config()
            if report.due(cfg, time.localtime(), cfg["last_sent"]):
                try:
                    report_send()
                    _report["last_error"] = ""
                except (OSError, ValueError, smtplib.SMTPException) as e:
                    _report["last_error"] = str(e)[:200]
                c = load_json_file(REPORT_FILE, {})
                c["last_sent"] = time.strftime("%Y-%m-%d")   # même en cas d'échec : un seul essai par jour, l'erreur reste affichée
                atomic_write(REPORT_FILE, json.dumps(c), 0o644)
        except Exception as e:   # noqa: BLE001
            sys.stderr.write("rapport : %s\n" % e)
        time.sleep(300)


# ------------------------------------------------ imputation des coûts (par clé d'API et par équipe) ---
COSTS_CONF = os.path.join(ETC, "costs.json")
COSTS_LEDGER = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "costs-ledger.json")
COSTS_DELAY = 1800   # une requête n'entre au registre que 30 min après son début : le journal la contient alors, même si elle a duré longtemps
_costs_lock = threading.Lock()


def costs_config():
    try:
        return costs.config_clean(load_json_file(COSTS_CONF, {}))
    except ValueError:
        return dict(costs.DEFAULTS)


def costs_save(data):
    cfg = costs.config_clean(data, costs_config())
    atomic_write(COSTS_CONF, json.dumps(cfg, ensure_ascii=False), 0o644)
    return cfg


def costs_ledger():
    d = load_json_file(COSTS_LEDGER, {})
    days = d.get("days") if isinstance(d.get("days"), dict) else {}
    try:
        wm = float(d.get("wm") or 0)
    except (TypeError, ValueError):
        wm = 0.0
    return {"wm": wm, "days": days}


def costs_ingest(now=None):
    """Verse au registre les requêtes terminées depuis la dernière fois (le journal des requêtes est purgé, le registre reste 400 jours)."""
    with _costs_lock:
        led = costs_ledger()
        now = now or time.time()
        limit = now - COSTS_DELAY
        if limit <= led["wm"]:
            return 0
        reqs = [r for r in read_request_log(led["wm"]) if led["wm"] < (r.get("ts") or 0) <= limit]
        n = costs.add_requests(led["days"], reqs, short_name)
        led["wm"] = limit
        costs.prune(led["days"], now)
        atomic_write(COSTS_LEDGER, json.dumps(led, separators=(",", ":")), 0o600)
        return n


def costs_teams():
    return {k["name"]: k["team"] for k in load_publication().get("keys", []) if k.get("team")}


def costs_rows(month=None, week=False, now=None):
    """Lignes client × modèle d'un mois (« AAAA-MM ») ou des 7 derniers jours : registre + requêtes récentes pas encore versées."""
    now = now or time.time()
    led = costs_ledger()
    if week:
        dates = costs.last_dates(now, 7)
        keep = lambda d: d in dates
    else:
        dates = costs.month_dates(led["days"], month)
        keep = lambda d: d[:7] == month
    sel = costs.select(led["days"], dates)
    costs.add_requests(sel, [r for r in read_request_log(led["wm"]) if (r.get("ts") or 0) > led["wm"] and keep(costs.day_of(r["ts"]))], short_name)
    return costs.flat(sel), led


def costs_view(month=None, now=None):
    now = now or time.time()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(month or "")):
        month = costs.day_of(now)[:7]
    rows, led = costs_rows(month, now=now)
    cfg, teams = costs_config(), costs_teams()
    days = sorted(led["days"])
    return {"month": month, "months": costs.months(led["days"], now), "summary": costs.summarize(rows, cfg, teams), "first_day": days[0] if days else None,
            "teams": sorted(set(teams.values())), "keys": [{"name": k["name"], "team": k.get("team", "")} for k in load_publication().get("keys", [])],
            "lag_min": COSTS_DELAY // 60}


def costs_week_lines(now=None):
    rows, _ = costs_rows(week=True, now=now)
    return costs.weekly_lines(costs.summarize(rows, costs_config(), costs_teams()))


def costs_export(month):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(month or "")):
        raise ValueError("mois invalide (AAAA-MM)")
    rows, _ = costs_rows(month)
    return costs.csv_month(month, rows, costs_config(), costs_teams())


def costs_worker():
    time.sleep(90)
    while True:
        try:
            costs_ingest()
        except Exception as e:   # noqa: BLE001
            sys.stderr.write("coûts : %s\n" % e)
        time.sleep(300)


# ------------------------------------------------------ santé du matériel ---
_hw_cache = {"t": 0.0, "data": None}


def hw_view(max_age=120):
    if _hw_cache["data"] is not None and time.time() - _hw_cache["t"] < max_age:
        return _hw_cache["data"]
    smart, have = [], bool(shutil.which("smartctl"))
    if have:
        try:
            scan = json.loads(run(["smartctl", "--scan", "-j"], timeout=15) or "{}")
        except ValueError:
            scan = {}
        for d in (scan.get("devices") or [])[:16]:
            name = str(d.get("name") or "")
            if re.fullmatch(r"/dev/[A-Za-z0-9/_-]{1,30}", name):
                r = hw.parse_smart(run(["smartctl", "-j", "-a"] + (["-d", d["type"]] if d.get("type") and re.fullmatch(r"[a-z0-9,]{1,20}", str(d["type"])) else []) + [name], timeout=30))
                if r and (r.get("passed") is not None or r.get("temp") is not None or r.get("hours") is not None):
                    smart.append(r)
    kern = run(["journalctl", "-k", "-b", "-n", "3000", "--no-pager", "-o", "short-unix", "-g", "NVRM: Xid"], timeout=15)
    data = {"smartctl": have, "disks": smart, "raid": hw.parse_mdstat(read_text("/proc/mdstat")), "xid": hw.parse_xid(kern, time.time()), "checked": int(time.time())}
    data["issues"] = hw.hw_issues(smart, data["raid"], data["xid"])
    _hw_cache.update(t=time.time(), data=data)
    return data


# ------------------------------------------------------ export Prometheus ---
PROM_FILE = os.path.join(ETC, "prometheus.json")
_prom_fail = {}


def prom_status():
    c = load_json_file(PROM_FILE, {})
    return {"enabled": bool(c.get("hash")), "created": c.get("created"), "path": "/metrics"}


def prom_token(action):
    """Jeton de lecture seule des mesures : affiché une seule fois, seule l'empreinte est conservée."""
    if action == "revoke":
        try:
            os.remove(PROM_FILE)
        except FileNotFoundError:
            pass
        return None
    if action != "create":
        raise ValueError("action inconnue")
    token = "obm_" + secrets.token_urlsafe(32)
    atomic_write(PROM_FILE, json.dumps({"hash": hashlib.sha256(token.encode()).hexdigest(), "created": int(time.time())}), 0o600)
    return token


def prom_auth(headers, ip):
    now = time.time()
    fails = [t for t in _prom_fail.get(ip, []) if now - t < 300]
    if len(fails) >= 10:
        raise PermissionError(429, "trop d'essais : réessayez dans quelques minutes")
    digest = load_json_file(PROM_FILE, {}).get("hash")
    if not digest:
        raise PermissionError(404, "export Prometheus désactivé")
    auth = headers.get("Authorization") or ""
    if not prom.token_ok(auth[7:].strip() if auth[:7].lower() == "bearer " else "", digest):
        _prom_fail[ip] = fails + [now]
        raise PermissionError(401, "jeton invalide")
    _prom_fail.pop(ip, None)


def prom_text():
    with _metrics_lock:
        last = _metrics["samples"][-1] if _metrics["samples"] else {}
    lim = load_json_file(ROUTER_LIMITS, {}).get("queue") or {}
    servers = [{"name": x["name"], "online": (_fleet_state.get(x["id"]) or {}).get("state") == "en ligne"} for x in load_fleet()
               if (_fleet_state.get(x["id"]) or {}).get("state") not in (None, "en attente")]
    return prom.render({"version": VERSION, "ollama_up": run(["systemctl", "is-active", "ollama.service"], 5).strip() == "active",
                        "cpu": last.get("cpu"), "mem": last.get("mem"), "gpus": gpu_metrics(), "counters": dict(_counters),
                        "queue": {"running": sum(v.get("running", 0) for v in lim.values()), "waiting": sum(v.get("waiting", 0) for v in lim.values())},
                        "servers": servers, "alerts": len(_alerts["active"])})


def alerts_send(cfg, events, test=False):
    """Envoie les événements par les canaux configurés ; retourne {canal: « ok » ou l'erreur}."""
    host = socket.gethostname()
    payload = {"source": "OllamaBuntu", "host": host, "version": VERSION, "test": test, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "events": events}
    res = {}
    if cfg["webhook"].get("url"):
        try:
            monitor.post_webhook(cfg["webhook"]["url"], payload)
            res["webhook"] = "ok"
        except (OSError, ValueError) as e:
            res["webhook"] = str(e)[:200]
    sm = cfg["smtp"]
    if sm.get("host") and sm.get("to"):
        lines = ["%s : %s" % ({"alert": "ALERTE", "resolved": "RÉTABLI"}.get(e.get("state"), "INFO"), e["text"]) for e in events]
        try:
            monitor.send_mail(sm, sm.get("password"), "[OllamaBuntu %s] %s" % (host, "test" if test else "%d événement(s)" % len(events)), "\n".join(lines) + "\n")
            res["email"] = "ok"
        except (OSError, ValueError, smtplib.SMTPException) as e:
            res["email"] = str(e)[:200]
    return res


def alerts_worker():
    time.sleep(30)
    while True:
        try:
            cfg = load_alerts()
            active = monitor.evaluate(alert_snapshot(), dict(cfg, events=list(monitor.EVENTS)))   # toutes visibles dans la console
            _alerts["active"] = {k: a for k, a in active.items() if k.split(":")[0] in cfg["events"]}
            perf_auto_step(_perf_last.get("guard"))
            events = _alerts["notifier"].step(_alerts["active"], time.time())
            if events and cfg["enabled"]:
                res = alerts_send(cfg, events)
                bad = {k: v for k, v in res.items() if v != "ok"}
                _alerts["last_error"] = "; ".join("%s : %s" % kv for kv in bad.items())
        except Exception as e:   # la supervision ne doit jamais s'arrêter
            sys.stderr.write("alertes : %s\n" % e)
        time.sleep(60)


# ------------------------------------------------- réglages recommandés ---
def tuning_view():
    """Contexte et parallélisme qui tiennent dans la mémoire vidéo, pour chaque modèle installé."""
    gpus = gpu_metrics()
    vram = sum(g.get("mem_total") or 0 for g in gpus)
    ctx = context_view()
    try:
        tags = {m["name"]: m for m in ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])}
    except (OSError, ValueError):
        tags = {}
    models = []
    for m in ctx["models"]:
        if m["name"].endswith("-cloud") or hidden_model(m["name"]):
            continue
        weights = (tags.get(m["name"]) or {}).get("size") or 0
        models.append(dict(name=m["name"], weights=weights, max=m["max"], bytes_per_token=m["bytes_per_token"],
                           **monitor.recommend(vram, weights, m["bytes_per_token"], m["max"])))
    return {"vram": vram, "gpus": [g["name"] for g in gpus], "current": {"ctx": ctx["default"], "parallel": ctx["parallel"], "kv_type": ctx["kv_type"]}, "models": models}


def tuning_apply(data):
    try:
        par, ctx = int(data.get("parallel")), int(data.get("ctx"))
    except (TypeError, ValueError):
        raise ValueError("valeurs invalides")
    if not 1 <= par <= 16:
        raise ValueError("parallélisme hors limites (1 à 16)")
    check_ctx(ctx)
    update_env({"OLLAMA_NUM_PARALLEL": str(par), "OLLAMA_CONTEXT_LENGTH": str(ctx)})


# ------------------------------------------- limites par clé, règles, test du parc ---
APPLIANCE_BACKUPS = os.environ.get("OB_BACKUPS", "/var/backups/ollamabuntu")
BACKUP_NAME_RE = re.compile(r"^appliance-(.+)-(\d{8}-\d{6})\.tar\.gz$")


def backups_list():
    """Sauvegardes des fichiers de l'appliance faites avant chaque mise à jour (la plus récente d'abord)."""
    out = []
    try:
        names = os.listdir(APPLIANCE_BACKUPS)
    except OSError:
        return out
    for n in names:
        m = BACKUP_NAME_RE.match(n)
        if m:
            try:
                st = os.stat(os.path.join(APPLIANCE_BACKUPS, n))
            except OSError:
                continue
            out.append({"file": n, "version": m.group(1), "stamp": m.group(2), "size": st.st_size})
    return sorted(out, key=lambda b: b["stamp"], reverse=True)[:20]


def limits_view():
    lim = load_json_file(ROUTER_LIMITS, {})
    queue, tokens = lim.get("queue") or {}, lim.get("tokens") or {}
    keys = []
    for k in load_publication().get("keys", []):
        t, q = tokens.get(k["id"]) or {}, queue.get(k["id"]) or {}
        keys.append({"id": k["id"], "name": k["name"], "max_concurrent": k.get("max_concurrent", 0), "quota_day": k.get("quota_day", 0), "quota_month": k.get("quota_month", 0),
                     "max_ctx": k.get("max_ctx", 0), "max_output": k.get("max_output", 0), "priority": k.get("priority", 2), "running": q.get("running", 0), "waiting": q.get("waiting", 0), "day": t.get("day", 0), "month": t.get("month", 0), "total": t.get("total", 0), "requests": t.get("req", 0)})
    return {"keys": keys, "queue_total": {"running": sum(v.get("running", 0) for v in queue.values()), "waiting": sum(v.get("waiting", 0) for v in queue.values())},
            "updated": lim.get("t")}


QUEUE_CONF = os.path.join(ETC, "queue.json")   # lu à chaud par le routeur
QUEUE_LIMITS = {"max_active": (0, 256), "max_queue": (0, 10000)}
PRIO_NAMES = {1: "haute", 2: "normale", 3: "basse"}


def queue_settings():
    d = load_json_file(QUEUE_CONF, {})
    out = {}
    for k, (lo, hi) in QUEUE_LIMITS.items():
        try:
            out[k] = max(lo, min(hi, int(d.get(k) or 0)))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def queue_save(data):
    """Plafond global de requêtes en cours (protège la mémoire de la carte graphique) et taille maximale de la file ; 0 = sans limite."""
    new = queue_settings()
    labels = {"max_active": "requêtes simultanées au total", "max_queue": "taille de la file"}
    for k, (lo, hi) in QUEUE_LIMITS.items():
        if k in data:
            try:
                v = int(data[k] or 0)
            except (TypeError, ValueError):
                raise ValueError("valeur invalide : %s" % labels[k])
            if not lo <= v <= hi:
                raise ValueError("%s : %d à %d (0 = sans limite)" % (labels[k], lo, hi))
            new[k] = v
    atomic_write(QUEUE_CONF, json.dumps(new), 0o644)
    return new


def queue_view():
    """File d'attente en direct (écrite par le routeur), réglages et priorité de chaque clé."""
    lim = load_json_file(ROUTER_LIMITS, {})
    names = {k["id"]: k["name"] for k in load_publication().get("keys", [])}
    fresh = time.time() - int(lim.get("t") or 0) < 30
    wait = []
    for w in (lim.get("waiting") or []) if fresh else []:
        wait.append({"who": names.get(w.get("kid")) or w.get("who") or w.get("kid"), "model": w.get("model"), "prio": w.get("prio", 2), "eff": w.get("eff", w.get("prio", 2)), "waited": w.get("waited", 0)})
    par = 1
    try:
        par = int(read_env().get("OLLAMA_NUM_PARALLEL") or 1)
    except (TypeError, ValueError, OSError, NameError):
        pass
    return {"settings": queue_settings(), "active": int(lim.get("active") or 0) if fresh else 0, "waiting": wait, "waits": lim.get("waits") or {},
            "parallel": par, "live": fresh,
            "keys": [{"id": k["id"], "name": k["name"], "priority": k.get("priority", 2), "max_concurrent": k.get("max_concurrent", 0)} for k in load_publication().get("keys", [])]}


REDIRECT_CONF = os.path.join(ETC, "redirects.json")   # lu à chaud par le routeur


def redirects_load():
    return [r for r in load_json_file(REDIRECT_CONF, {}).get("rules", []) if isinstance(r, dict)]


def redirects_save(data):
    """Règles « les demandes pour X sont servies par Y » (une seule étape : pas d'enchaînement). `percent` < 100 : essai sur une partie du trafic."""
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list) or len(rules) > 50:
        raise ValueError("règles invalides (50 au maximum)")
    out, seen = [], set()
    for r in rules:
        if not isinstance(r, dict):
            raise ValueError("règle invalide")
        src, dst = str(r.get("from") or "").strip(), str(r.get("to") or "").strip()
        if not src or not dst or len(src) > 200 or len(dst) > 200 or any(c in (src + dst) for c in "\r\n\t"):
            raise ValueError("chaque règle a besoin d'un modèle demandé et d'un modèle servi (200 caractères au plus)")
        if router_norm(src) == router_norm(dst):
            raise ValueError("« %s » : le modèle servi est le même que le modèle demandé" % src)
        if router_norm(src) in seen:
            raise ValueError("« %s » apparaît deux fois : une seule règle par modèle demandé" % src)
        seen.add(router_norm(src))
        try:
            pct = int(r.get("percent", 100))
        except (TypeError, ValueError):
            raise ValueError("pourcentage invalide pour « %s »" % src)
        if not 1 <= pct <= 100:
            raise ValueError("pourcentage de « %s » : 1 à 100" % src)
        out.append({"from": src, "to": dst, "percent": pct, "enabled": r.get("enabled") is not False})
    # Une règle dont le modèle servi est lui-même redirigé ne serait pas suivie : on le dit plutôt que de laisser croire à un enchaînement.
    active = {router_norm(r["from"]) for r in out if r["enabled"]}
    for r in out:
        if router_norm(r["to"]) in active and r["enabled"]:
            raise ValueError("« %s » est servi par « %s », qui est lui-même redirigé : les redirections ne s'enchaînent pas" % (r["from"], r["to"]))
    atomic_write(REDIRECT_CONF, json.dumps({"rules": out}, ensure_ascii=False), 0o644)
    return out


def router_norm(name):
    n = str(name or "").strip()
    for p in ("registry.ollama.ai/library/", "ollama.com/library/", "library/"):
        if n.startswith(p):
            n = n[len(p):]
    if ":" not in n.split("/")[-1]:
        n += ":latest"
    return n.lower()


def redirects_view():
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    names = sorted({t.get("name") for t in tags if t.get("name")}, key=str.lower)
    have = {router_norm(n) for n in names}
    rules = redirects_load()
    for r in rules:
        r["to_installed"] = router_norm(r.get("to")) in have
    return {"rules": rules, "models": names}


def load_rules():
    return load_json_file(RULES_FILE, {}).get("rules", [])


def rules_save(rules):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("règles invalides (100 au maximum)")
    key_ids = {k["id"] for k in load_publication().get("keys", [])}
    fleet_ids = {x["id"] for x in load_fleet() if x.get("route_token")}
    out = []
    for r in rules:
        key, model, server, mode = (str(r.get(f) or "").strip() for f in ("key", "model", "server", "mode"))
        if key != "*" and key not in key_ids:
            raise ValueError("clé inconnue dans une règle")
        if not re.match(r"^[A-Za-z0-9._:/*?\[\]-]{1,100}$", model):
            raise ValueError("motif de modèle invalide : %s" % model[:40])
        if server != "local" and server not in fleet_ids:
            raise ValueError("serveur inconnu ou sans répartition dans une règle")
        if mode not in ("only", "never"):
            raise ValueError("mode de règle invalide")
        out.append({"key": key, "model": model.lower(), "server": server, "mode": mode})
    atomic_write(RULES_FILE, json.dumps({"rules": out}, ensure_ascii=False, indent=1), 0o600)
    write_fleet_routes()


def fleet_check(model=None):
    """Interroge chaque serveur du parc en répartition avec une courte génération : serveur joignable, modèle réellement utilisé, débit."""
    local_tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    names = [short_name(m["name"]) for m in local_tags]
    model = short_name(model) if model else (names[0] if names else None)
    if not model or not MODEL_RE.match(model):
        raise ValueError("aucun modèle à tester")
    body = {"model": None, "prompt": "Réponds : ok", "stream": False, "options": {"num_predict": 8}}
    results = []
    lock = threading.Lock()

    def probe(name, call, note=""):
        t0 = time.time()
        try:
            code, data = call()
            ok = code == 200 and isinstance(data, dict) and "response" in data
            tps = round(data["eval_count"] / (data["eval_duration"] / 1e9), 1) if ok and data.get("eval_count") and data.get("eval_duration") else None
            r = {"server": name, "ok": ok, "ms": round((time.time() - t0) * 1000), "tps": tps, "note": note, "error": None if ok else (data.get("error") if isinstance(data, dict) else None) or "HTTP %s" % code}
        except (OSError, ssl.SSLError, FleetError, ValueError) as e:
            r = {"server": name, "ok": False, "ms": round((time.time() - t0) * 1000), "tps": None, "note": note, "error": str(e)[:160]}
        with lock:
            results.append(r)
    threads = []
    if model in names:
        threads.append(threading.Thread(target=probe, args=("ce serveur", lambda: ollama_json("POST", "/api/generate", dict(body, model=model), timeout=300), "modèle " + model)))
    for x in load_fleet():
        if not x.get("route_token"):
            continue
        st = (_fleet_state.get(x["id"]) or {})
        have = {short_name(m.get("name", "")) for m in (st.get("data") or {}).get("model_tags", [])}
        mp = {short_name(k): short_name(v) for k, v in (x.get("model_map") or {}).items() if k != "*"}
        use = model if model in have else (mp.get(model) or (short_name(x["model_map"]["*"]) if (x.get("model_map") or {}).get("*") else None))
        if st.get("state") != "en ligne":
            results.append({"server": x["name"], "ok": False, "ms": 0, "tps": None, "note": "", "error": "hors ligne"})
        elif not use or use not in have:
            results.append({"server": x["name"], "ok": False, "ms": 0, "tps": None, "note": "", "error": "modèle absent, sans modèle de remplacement installé"})
        else:
            threads.append(threading.Thread(target=probe, args=(x["name"], (lambda x=x, use=use: fleet_request(x["url"], "/api/fleet/ollama/api/generate", x["route_token"], x["fingerprint"], "POST", dict(body, model=use), timeout=300)[:2]),
                                                                 ("modèle " + use) + (" (remplacement de %s)" % model if use != model else ""))))
    for t in threads:
        t.start()
    for t in threads:
        t.join(330)
    return {"model": model, "results": sorted(results, key=lambda r: r["server"])}


def fleet_set_route(sid, enabled):
    s = fleet_server(sid)
    action = "route-token" if enabled else "route-revoke"
    try:
        code, data, _ = fleet_request(s["url"], "/api/fleet/action", s["token"], s["fingerprint"], "POST", {"action": action}, timeout=30)
    except FleetError:
        raise ValueError("certificat du serveur changé : approuvez-le d'abord")
    except (OSError, ssl.SSLError) as e:
        if enabled:
            raise ValueError("serveur injoignable : %s" % e)
        code, data = 0, {}   # désactivation locale même si le serveur est injoignable
    if enabled and (code != 200 or not str(data.get("token", "")).startswith("obr_")):
        raise ValueError(data.get("error") or "le serveur n'a pas fourni de jeton de routage (version trop ancienne ?)")
    with _fleet_lock:
        servers = load_fleet()
        for x in servers:
            if x["id"] == sid:
                if enabled:
                    x["route_token"] = data["token"]
                else:
                    x.pop("route_token", None)
        save_fleet(servers)
    write_fleet_routes()


def fleet_server(sid):
    s = next((x for x in load_fleet() if x["id"] == sid), None)
    if not s:
        raise ValueError("serveur inconnu")
    return s


def fleet_action(sid, action):
    if action not in FLEET_ACTIONS:
        raise ValueError("action inconnue")
    s = fleet_server(sid)
    try:
        code, data, _ = fleet_request(s["url"], "/api/fleet/action", s["token"], s["fingerprint"], "POST", {"action": action}, timeout=60)
    except FleetError:
        raise ValueError("certificat du serveur changé : approuvez-le d'abord")
    except (OSError, ssl.SSLError) as e:
        raise ValueError("serveur injoignable : %s" % e)
    if code != 200:
        raise ValueError(data.get("error") or "refusé par le serveur (%d)" % code)
    threading.Thread(target=fleet_poll_one, args=(s,), daemon=True).start()
    return data


def fleet_remove(sid):
    with _fleet_lock:
        servers = load_fleet()
        kept = [s for s in servers if s["id"] != sid]
        if len(kept) == len(servers):
            raise ValueError("serveur inconnu")
        save_fleet(kept)
        _fleet_state.pop(sid, None)
    write_fleet_routes()


def fleet_repin(sid, fingerprint):
    with _fleet_lock:
        servers = load_fleet()
        s = next((x for x in servers if x["id"] == sid), None)
        st = _fleet_state.get(sid) or {}
        if not s or st.get("state") != "certificat changé" or st.get("new_fingerprint") != fingerprint:
            raise ValueError("aucun nouveau certificat à approuver (ou empreinte différente)")
        s["fingerprint"] = fingerprint
        save_fleet(servers)
    fleet_poll_one(s)


# --------------------------------------------- performances et requêtes (monitoring) ---
# Échantillon toutes les 10 s : charge et mémoire de chaque GPU, processeur, mémoire,
# et, d'après le journal du routeur (métadonnées des requêtes, jamais leur contenu) :
# requêtes, jetons générés, jetons/s, temps avant le premier jeton. 24 h conservées.
REQ_LOG = os.environ.get("OB_ROUTER_REQLOG", "/var/lib/ollamabuntu-router/requests.jsonl")
METRICS_FILE = os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "metrics.json")
METRICS_EVERY = float(os.environ.get("OB_METRICS_INTERVAL", "10"))
_metrics = {"samples": collections.deque(maxlen=int(86400 / max(METRICS_EVERY, 1)) + 10), "names": {}, "offset": 0, "cpu": None}
_metrics_lock = threading.Lock()
_counters = {"requests": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0}   # compteurs Prometheus (depuis le démarrage)


def cpu_times():
    f = read_text("/proc/stat").split("\n", 1)[0].split()[1:]
    v = [int(x) for x in f if x.isdigit()]
    return (v[3] + (v[4] if len(v) > 4 else 0), sum(v)) if len(v) >= 4 else (0, 0)


def new_requests():
    """Lignes ajoutées au journal du routeur depuis le dernier échantillon (rotation gérée)."""
    try:
        size = os.path.getsize(REQ_LOG)
    except OSError:
        return []
    if size < _metrics["offset"]:
        _metrics["offset"] = 0   # fichier remplacé (rotation)
    out = []
    with open(REQ_LOG, "rb") as f:
        f.seek(_metrics["offset"])
        data = f.read(8 * 1024 * 1024)
        _metrics["offset"] += len(data.rsplit(b"\n", 1)[0]) + 1 if b"\n" in data else 0
        for line in data.split(b"\n")[:-1]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def take_sample():
    idle, total = cpu_times()
    prev, cpu = _metrics["cpu"], None
    if prev and total > prev[1]:
        cpu = round(100.0 * (1 - (idle - prev[0]) / (total - prev[1])), 1)
    _metrics["cpu"] = (idle, total)
    mi = meminfo()
    mem = round(100.0 * (mi.get("MemTotal", 0) - mi.get("MemAvailable", 0)) / mi["MemTotal"], 1) if mi.get("MemTotal") else None
    gpus = {}
    for g in gpu_metrics():
        _metrics["names"][g["pci"]] = g["name"]
        gpus[g["pci"]] = {"u": g.get("util"), "m": round(100.0 * g["mem_used"] / g["mem_total"], 1) if g.get("mem_total") else None,
                          "t": g.get("temp"), "p": g.get("power")}
    fresh = new_requests()
    _counters["requests"] += len(fresh)
    _counters["errors"] += sum(1 for r in fresh if r.get("status") != 200)
    _counters["tokens_in"] += sum(r.get("in_tok") or 0 for r in fresh)
    _counters["tokens_out"] += sum(r.get("out_tok") or 0 for r in fresh)
    reqs = [r for r in fresh if r.get("status") == 200]
    tps = [r["tps"] for r in reqs if r.get("tps")]
    ttft = [r["ttft_ms"] for r in reqs if r.get("ttft_ms") is not None]
    s = {"t": int(time.time()), "cpu": cpu, "mem": mem, "gpus": gpus, "req": len(reqs),
         "tok": sum(r.get("out_tok") or 0 for r in reqs), "tps": round(sum(tps) / len(tps), 1) if tps else None,
         "ttft": round(sum(ttft) / len(ttft)) if ttft else None}
    with _metrics_lock:
        _metrics["samples"].append(s)


def metrics_worker():
    stored = load_json_file(METRICS_FILE, {})
    cutoff = time.time() - 86400
    with _metrics_lock:
        _metrics["samples"].extend(x for x in stored.get("samples", []) if x.get("t", 0) > cutoff)
        _metrics["names"].update(stored.get("names", {}))
    try:
        _metrics["offset"] = os.path.getsize(REQ_LOG)   # seules les nouvelles requêtes comptent
    except OSError:
        pass
    last_save, last_purge = time.time(), [0.0]
    while True:
        try:
            take_sample()
            if time.time() - last_purge[0] > 600:   # conservation de l'historique des requêtes
                last_purge[0] = time.time()
                purge_requests()
            if time.time() - last_save > 60:
                with _metrics_lock:
                    data = {"samples": list(_metrics["samples"]), "names": _metrics["names"]}
                atomic_write(METRICS_FILE, json.dumps(data, separators=(",", ":")), 0o600)
                last_save = time.time()
        except Exception as e:
            sys.stderr.write("mesures : %s\n" % e)
        time.sleep(METRICS_EVERY)


def metrics_view(span):
    span = max(60, min(int(span or 3600), 86400))
    now = time.time()
    with _metrics_lock:
        pts = [x for x in _metrics["samples"] if x["t"] >= now - span]
        names = dict(_metrics["names"])
    width = max(METRICS_EVERY, span / 240.0)   # 240 points au plus, jamais plus fin que l'échantillonnage
    out = {}
    for x in pts:   # moyenne par intervalle (240 points au plus) ; débit de requêtes et de jetons : somme
        b = int((x["t"] - (now - span)) // width)
        out.setdefault(b, []).append(x)
    series = []
    for b in sorted(out):
        xs = out[b]
        avg = lambda vals: round(sum(vals) / len(vals), 1) if vals else None
        dur = max(width, METRICS_EVERY)
        gp = {}
        for pci in names:
            gp[pci] = {"u": avg([x["gpus"][pci]["u"] for x in xs if pci in x.get("gpus", {}) and x["gpus"][pci]["u"] is not None]),
                       "m": avg([x["gpus"][pci]["m"] for x in xs if pci in x.get("gpus", {}) and x["gpus"][pci]["m"] is not None]),
                       "t": avg([x["gpus"][pci].get("t") for x in xs if pci in x.get("gpus", {}) and x["gpus"][pci].get("t") is not None]),
                       "p": avg([x["gpus"][pci].get("p") for x in xs if pci in x.get("gpus", {}) and x["gpus"][pci].get("p") is not None])}
        series.append({"t": int(sum(x["t"] for x in xs) / len(xs)), "cpu": avg([x["cpu"] for x in xs if x["cpu"] is not None]),
                       "mem": avg([x["mem"] for x in xs if x["mem"] is not None]), "gpus": gp,
                       "rpm": round(sum(x["req"] for x in xs) * 60.0 / dur, 2), "tok_s": round(sum(x["tok"] for x in xs) / dur, 2),
                       "tps": avg([x["tps"] for x in xs if x["tps"] is not None]), "ttft": avg([x["ttft"] for x in xs if x["ttft"] is not None])})
    return {"span": span, "interval": METRICS_EVERY, "gpus": names, "series": series}


def read_requests(max_lines=5000):
    lines = []
    for path in (REQ_LOG + ".1", REQ_LOG):
        try:
            with open(path, "rb") as f:
                f.seek(max(0, os.path.getsize(path) - 2 * 1024 * 1024))
                lines += f.read().split(b"\n")[1:] if f.tell() > 0 else f.read().split(b"\n")
        except OSError:
            continue
    reqs = []
    for line in lines[-max_lines:]:
        try:
            reqs.append(json.loads(line))
        except ValueError:
            continue
    return reqs


def usage_view(span):
    try:
        span = int(span)
    except (TypeError, ValueError):
        span = 86400
    return usage.aggregate(read_requests(20000), time.time(), span, name=short_name)


def requests_view(limit=200):
    reqs = read_requests()
    hour = [r for r in reqs if r.get("ts", 0) > time.time() - 3600]
    by_model = {}
    for r in hour:
        by_model.setdefault(short_name(r["model"]) if r.get("model") else "?", []).append(r)   # « x » et « x:latest » regroupés
    summary = []
    for m, rs in sorted(by_model.items(), key=lambda kv: -len(kv[1])):
        ok = [r for r in rs if r.get("status") == 200]
        ms = sorted(r["ms"] for r in ok if r.get("ms") is not None)
        tps = [r["tps"] for r in ok if r.get("tps")]
        ttft = [r["ttft_ms"] for r in ok if r.get("ttft_ms") is not None]
        summary.append({"model": m, "count": len(rs), "errors": len(rs) - len(ok), "tok": sum(r.get("out_tok") or 0 for r in ok),
                        "tps": round(sum(tps) / len(tps), 1) if tps else None, "ttft_ms": round(sum(ttft) / len(ttft)) if ttft else None,
                        "p50_ms": ms[len(ms) // 2] if ms else None, "p95_ms": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else None})
    return {"requests": list(reversed(reqs[-max(1, min(int(limit), 1000)):])), "summary": summary, "prompt_excerpt": reqlog_settings()["prompt_excerpt"]}


def logs_since(source, after):
    """Journal par curseur (suivi en direct) : journald (curseur) ou fichier (position en octets)."""
    src = LOG_SOURCES.get(source, LOG_SOURCES["ollama"])
    if isinstance(src, str):
        try:
            size = os.path.getsize(src)
        except OSError:
            return {"text": "", "cursor": "0"}
        pos = int(after) if after and after.isdigit() and int(after) <= size else max(0, size - 64 * 1024)
        with open(src, "rb") as f:
            f.seek(pos)
            data = f.read(1024 * 1024)
        return {"text": data.decode("utf-8", "replace"), "cursor": str(pos + len(data))}
    cmd = [c for c in src]
    if after:
        i = cmd.index("-n")
        cmd[i + 1] = "1000"
        cmd += ["--after-cursor", after]
    out = run(cmd + ["--show-cursor"], timeout=15)
    cursor, lines = after, []
    for line in out.splitlines():
        if line.startswith("-- cursor: "):
            cursor = line[len("-- cursor: "):].strip()
        elif not line.startswith("-- No entries --"):
            lines.append(line)
    return {"text": "\n".join(lines) + ("\n" if lines else ""), "cursor": cursor or ""}


# ------------------------------------------------------ taille du contexte ---
CONTEXT_FILE = os.path.join(ETC, "model-context.json")   # lu par le routeur (aucun secret : 0644)
CTX_MIN, CTX_MAX = 256, 1048576
_show_cache = {}


def model_shape(name, digest):
    """Contexte maximal et mémoire du cache par jeton, d'après l'architecture du modèle (/api/show)."""
    key = (name, digest)
    if key not in _show_cache:
        try:
            info = ollama_json("POST", "/api/show", {"model": name}, timeout=20)[1].get("model_info") or {}
        except (OSError, ValueError):
            info = {}
        arch = info.get("general.architecture", "")
        g = lambda k: info.get("%s.%s" % (arch, k))
        layers, heads, kv, emb = g("block_count"), g("attention.head_count"), g("attention.head_count_kv"), g("embedding_length")
        heads_n = max(heads) if isinstance(heads, list) and heads else heads
        kv = kv if kv is not None else heads
        klen = g("attention.key_length") or (emb // heads_n if isinstance(emb, int) and isinstance(heads_n, int) and heads_n else None)
        vlen = g("attention.value_length") or klen
        kv_total = sum(x for x in kv if isinstance(x, int)) if isinstance(kv, list) else (kv * layers if isinstance(kv, int) and isinstance(layers, int) else None)
        per_token = kv_total * (klen + vlen) if kv_total and klen and vlen else None   # éléments K + V par jeton
        _show_cache[key] = {"max": g("context_length"), "elems_per_token": per_token}
    return _show_cache[key]


def context_view():
    env = read_env()
    conf = load_json_file(CONTEXT_FILE, {}).get("models", {})
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    kv_type = env.get("OLLAMA_KV_CACHE_TYPE") or "f16"
    models = []
    for m in sorted(tags, key=lambda t: t.get("name", "")):
        shape = model_shape(m["name"], m.get("digest"))
        models.append({"name": m["name"], "max": shape["max"], "ctx": conf.get(m["name"]) or conf.get(short_name(m["name"])),
                       "bytes_per_token": shape["elems_per_token"] and shape["elems_per_token"] * {"q8_0": 1, "q4_0": 0.5}.get(kv_type, 2)})
    return {"default": int(env["OLLAMA_CONTEXT_LENGTH"]) if str(env.get("OLLAMA_CONTEXT_LENGTH", "")).isdigit() else None,
            "parallel": int(env["OLLAMA_NUM_PARALLEL"]) if str(env.get("OLLAMA_NUM_PARALLEL", "")).isdigit() else 1,
            "kv_type": kv_type, "models": models}


def check_ctx(value):
    if value in (None, "", 0):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("taille de contexte invalide")
    if not CTX_MIN <= n <= CTX_MAX:
        raise ValueError("taille de contexte hors limites (%d à %d jetons)" % (CTX_MIN, CTX_MAX))
    return n


def set_model_context(model, value):
    model = str(model or "")
    if not MODEL_RE.match(model):
        raise ValueError("nom de modèle invalide")
    n = check_ctx(value)
    mx = model_shape(model, None)["max"]
    if n and isinstance(mx, int) and mx > 0 and n > mx:   # Ollama le ramènerait en silence au maximum
        raise ValueError("au-delà du maximum du modèle (%d jetons)" % mx)
    with _lock:
        d = load_json_file(CONTEXT_FILE, {})
        models = d.setdefault("models", {})
        models.pop(short_name(model), None)
        models.pop(model, None)
        if n:
            models[model] = n
        atomic_write(CONTEXT_FILE, json.dumps(d, ensure_ascii=False, indent=1), 0o644)


# ------------------------------------------- répartition : réglages, diagnostic, journal des requêtes ---
BALANCE_FILE = os.path.join(ETC, "balance.json")      # lu à chaud par le routeur
REQLOG_CONF = os.path.join(ETC, "request-log.json")   # lu à chaud par le routeur (aucun secret)
ROUTER_ADDR = os.environ.get("OB_ROUTER_ADDR", "127.0.0.1:11434")
BALANCE_STRATEGIES = ("spread", "warm")
_reqlog_cache = {"t": 0.0, "data": []}


def reqlog_settings():
    d = load_json_file(REQLOG_CONF, {})

    def num(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(d.get(key, default))))
        except (TypeError, ValueError):
            return default
    return {"prompt_excerpt": d.get("prompt_excerpt") is True, "chars": num("chars", 120, 40, 300), "days": num("days", 7, 1, 90)}


def set_reqlog_settings(data):
    new = reqlog_settings()
    if "prompt_excerpt" in data:
        new["prompt_excerpt"] = data["prompt_excerpt"] is True
    for key, label, lo, hi in (("chars", "longueur de l'extrait", 40, 300), ("days", "durée de conservation", 1, 90)):
        if key in data:
            try:
                v = int(data[key])
            except (TypeError, ValueError):
                raise ValueError("valeur invalide : %s" % label)
            if not lo <= v <= hi:
                raise ValueError("%s hors limites (%d à %d)" % (label, lo, hi))
            new[key] = v
    atomic_write(REQLOG_CONF, json.dumps(new), 0o644)
    purge_requests(new["days"])
    return new


def purge_requests(days=None):
    """Retire de l'historique les requêtes plus anciennes que la durée de conservation."""
    cutoff = time.time() - (days or reqlog_settings()["days"]) * 86400
    for path in (REQ_LOG + ".1", REQ_LOG):
        try:
            st = os.stat(path)
            with open(path, "rb") as f:
                lines = f.read().split(b"\n")
        except OSError:
            continue
        keep, changed = [], False
        for line in lines:
            if not line.strip():
                continue
            try:
                ts = json.loads(line).get("ts", 0)
            except ValueError:
                changed = True
                continue
            if ts >= cutoff:
                keep.append(line)
            else:
                changed = True
        if not changed:
            continue
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(b"\n".join(keep) + (b"\n" if keep else b""))
        if os.geteuid() == 0:
            os.chown(tmp, st.st_uid, st.st_gid)   # le routeur (compte ollama) doit pouvoir continuer d'y écrire
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        if path == REQ_LOG:
            _metrics["offset"] = os.path.getsize(REQ_LOG)   # les graphiques ne relisent pas l'historique
    _reqlog_cache["t"] = 0.0


def clear_requests():
    for path in (REQ_LOG + ".1", REQ_LOG):
        try:
            with open(path, "r+b") as f:
                f.truncate(0)
        except OSError:
            pass
    _metrics["offset"] = 0
    _reqlog_cache["t"] = 0.0


def read_request_log(since):
    if time.time() - _reqlog_cache["t"] < 5:
        return [r for r in _reqlog_cache["data"] if r.get("ts", 0) >= since]
    out = []
    for path in (REQ_LOG + ".1", REQ_LOG):
        try:
            with open(path, "rb") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and r.get("ts", 0) >= since:
                        out.append(r)
        except OSError:
            continue
    _reqlog_cache.update(t=time.time(), data=out)
    return out


def balance_strategy():
    return "warm" if load_json_file(BALANCE_FILE, {}).get("strategy") == "warm" else "spread"


def balance_affinity():
    return load_json_file(BALANCE_FILE, {}).get("affinity", True) is not False


def set_balance_strategy(value, affinity=None):
    if value not in BALANCE_STRATEGIES:
        raise ValueError("stratégie inconnue")
    atomic_write(BALANCE_FILE, json.dumps({"strategy": value, "affinity": balance_affinity() if affinity is None else bool(affinity)}), 0o644)


def balance_view():
    """Pourquoi un serveur du parc est (ou n'est pas) utilisé par la répartition de charge."""
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    local = sorted({short_name(m.get("name", "")) for m in tags})
    served, fails, rescued, lost = {}, {}, 0, 0
    for r in read_request_log(time.time() - 86400):
        if r.get("retried"):   # reprise automatique : la requête a d'abord échoué sur d'autres serveurs
            for x in r["retried"]:
                nm = str(x).split(" : ")[0]
                fails[nm] = fails.get(nm, 0) + 1
            if r.get("status") == 200:
                rescued += 1
            else:
                lost += 1
        if r.get("status") != 200:
            continue
        label = r.get("instance") or ""
        s = served.setdefault(label[len("serveur:"):] if label.startswith("serveur:") else "", {"count": 0, "last": 0})
        s["count"] += 1
        s["last"] = max(s["last"], r.get("ts") or 0)
    servers, on = [], {n: ["local"] for n in local}
    for s in load_fleet():
        st = _fleet_state.get(s["id"]) or {}
        d = st.get("data") or {}
        names = sorted({short_name(m.get("name", "")) for m in d.get("model_tags", [])})
        common = sorted(set(names) & set(local))
        issues = []
        if not s.get("route_token"):
            issues.append("route-off")
        if st.get("state") != "en ligne":
            issues.append("offline")
        elif "model_tags" not in d:
            issues.append("old-version")   # serveur resté sur une version qui n'annonce pas ses modèles
        elif not common:
            issues.append("no-common-model")
        for name in names:
            on.setdefault(name, []).append(s["name"])
        sv = served.get(s["name"], {})
        servers.append({"id": s["id"], "name": s["name"], "state": st.get("state", "en attente"), "route": bool(s.get("route_token")),
                        "models": len(names), "common": len(common), "served": sv.get("count", 0), "last": sv.get("last") or None, "issues": issues,
                        "failures": fails.get(s["name"], 0)})
    loc = served.get("", {})
    return {"strategy": balance_strategy(), "affinity": balance_affinity(), "rescued": {"count": rescued, "lost": lost},
            "local": {"models": len(local), "served": loc.get("count", 0), "last": loc.get("last") or None, "failures": fails.get("local", 0)},
            "servers": servers, "models": [{"name": k, "on": v} for k, v in sorted(on.items())], "active": any(not x["issues"] for x in servers)}


def balance_test(model, count=4):
    """Envoie quelques petites requêtes simultanées par le routeur et relève quels serveurs répondent."""
    if not MODEL_RE.match(str(model or "")):
        raise ValueError("nom de modèle invalide")
    host, port = ROUTER_ADDR.rsplit(":", 1)
    out = [None] * count

    def one(i):
        try:
            c = http.client.HTTPConnection(host, int(port), timeout=300)
            c.request("POST", "/api/generate", json.dumps({"model": model, "prompt": "ok", "stream": False, "options": {"num_predict": 1}}),
                      {"Content-Type": "application/json"})
            r = c.getresponse()
            r.read()
            out[i] = {"status": r.status, "instance": r.getheader("X-OllamaBuntu-Instance") or ""}
            c.close()
        except OSError as e:
            out[i] = {"status": 0, "instance": "", "error": str(e)[:120]}
    threads = [threading.Thread(target=one, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(330)
    by = {}
    for r in out:
        if r and r["status"] == 200:
            lab = r["instance"][len("serveur:"):] if r["instance"].startswith("serveur:") else ""
            by[lab] = by.get(lab, 0) + 1
    return {"count": count, "ok": sum(by.values()), "by": by,
            "errors": [(r or {}).get("error") or "HTTP %s" % (r or {}).get("status") for r in out if not r or r["status"] != 200]}


def main_gpu_list():
    """Cartes vues par l'instance principale, dans l'ordre utilisé par main_gpu."""
    used, _ = ollama_discovery("ollama.service")
    return [u for u in used if u.get("library", "").lower() != "cpu"]


def pin_create(base, index):
    gpus = main_gpu_list()
    if not isinstance(index, int) or not 0 <= index < len(gpus):
        raise ValueError("numéro de GPU invalide (l'instance principale voit %d GPU)" % len(gpus))
    base = short_name(base)
    if re.search(r"-gpu\d+$", base):
        raise ValueError("ce modèle est déjà une variante épinglée")
    variant = "%s-gpu%d" % (base, index)
    code, res = ollama_json("POST", "/api/create", {"model": variant, "from": base, "parameters": {"main_gpu": index},
                                                    "stream": False}, timeout=600)
    if code != 200:
        raise ValueError("création de la variante impossible : %s" % (res.get("error") or code))
    g = gpus[index]
    with _pools_lock:
        pins = load_pins()
        pins[variant] = {"base": base, "index": index, "pci": norm_pci(g.get("pci_id")),
                         "description": g.get("description") or g.get("name")}
        atomic_write(PINS_FILE, json.dumps({"pins": pins}, ensure_ascii=False, indent=1), 0o644)
    return variant


def pin_delete(variant):
    with _pools_lock:
        pins = load_pins()
        if variant not in pins:
            raise ValueError("variante inconnue")
        code, res = ollama_json("DELETE", "/api/delete", {"model": variant, "name": variant})
        if code not in (200, 404):
            raise ValueError("suppression impossible : %s" % (res.get("error") or code))
        del pins[variant]
        atomic_write(PINS_FILE, json.dumps({"pins": pins}, ensure_ascii=False, indent=1), 0o644)


def unit_state(unit):
    if OLLAMA_LOG_DIR:
        return "active" if os.path.exists(os.path.join(OLLAMA_LOG_DIR, unit + ".log")) else "inactive"
    return run(["systemctl", "is-active", unit], timeout=5).strip() or "inconnu"


def placement_status():
    inv = gpu_inventory()
    by_key = {g["key"]: g for g in inv}
    pools = load_pools()
    reserved = {k for p in pools for k in p["gpus"]}
    out_pools = []
    for p in pools:
        unit = "ollama-pool@%s.service" % p["id"]
        seen = {norm_pci(u.get("pci_id")) for u in ollama_discovery(unit)[0] if u.get("library", "").lower() != "cpu"}
        try:
            c = http.client.HTTPConnection("127.0.0.1", int(p["port"]), timeout=3)
            c.request("GET", "/api/ps")
            loaded = [m.get("name") for m in json.loads(c.getresponse().read() or b"{}").get("models", [])]
            c.close()
        except (OSError, ValueError):
            loaded = None
        out_pools.append(dict(p, state=unit_state(unit), loaded=loaded,
                              gpu_details=[dict(by_key.get(k, {"key": k, "description": k}), seen=k in seen) for k in p["gpus"]]))
    main = main_gpu_list()
    pins = []
    for variant, pin in sorted(load_pins().items()):
        cur = main[pin["index"]] if pin["index"] < len(main) else None
        pins.append(dict(pin, variant=variant, ok=bool(cur) and norm_pci(cur.get("pci_id")) == pin["pci"],
                         current=(cur.get("description") or cur.get("name")) if cur else None))
    return {"pools": out_pools, "inventory": inv, "main_free": [g for g in inv if g["key"] not in reserved],
            "main_gpus": [{"index": i, "description": u.get("description") or u.get("name"), "library": u.get("library"),
                           "total": u.get("total"), "pci_id": u.get("pci_id")} for i, u in enumerate(main)],
            "pins": pins, "router": unit_state("ollamabuntu-router.service"),
            "spread": read_env().get("OLLAMA_SCHED_SPREAD") == "1"}


def installed_packages(patterns):
    if FAKE_INSTALLED is not None:
        return sorted(p for p in FAKE_INSTALLED.split(",") if p)
    out = run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}|${Package}\n"] + patterns, timeout=15)
    return sorted(p for s, _, p in (l.partition("|") for l in out.splitlines()) if s.startswith("ii"))


def pci_names():
    names = {}
    for line in run(["lspci", "-mm", "-D"], timeout=10).splitlines():
        try:
            f = shlex.split(line)
        except ValueError:
            continue
        if len(f) >= 4:
            names[f[0].lower()] = (f[2], f[3])
    return names


def norm_pci(p):
    p = (p or "").strip().lower()
    if not p:
        return ""
    if p.count(":") == 1:
        p = "0000:" + p
    if len(p.split(":")[0]) > 4:   # nvidia-smi : 00000000:01:00.0
        p = p[-12:]
    return p


def gpu_info():
    names = pci_names()
    used, dropped = [], []
    for unit, _, pool in instances():
        u, d = ollama_discovery(unit)
        used += [dict(x, instance=pool["name"] if pool else None) for x in u]
        dropped += d
    pkgs = installed_packages(["libnvidia-compute-*", "mesa-vulkan-drivers", "libvulkan1"])
    nv_pkg = next((p for p in reversed(pkgs) if p.startswith("libnvidia-compute-")), "")
    nv_branch = nv_pkg.replace("libnvidia-compute-", "")
    nv_version = read_text(sysp("/sys/module/nvidia/version"))
    vulkan = "mesa-vulkan-drivers" in pkgs and "libvulkan1" in pkgs
    rocm = any(os.path.isdir(p) for p in glob.glob(os.path.join(OLLAMA_LIB, "rocm*")))
    reboot_required = os.path.exists(sysp("/var/run/reboot-required"))
    secure_boot = "enabled" in run(["mokutil", "--sb-state"], timeout=5).lower() if shutil.which("mokutil") else False
    devices = []
    try:
        slots = sorted(os.listdir(PCI_ROOT))
    except OSError:
        slots = []
    live = {g["pci"]: g for g in gpu_metrics()}
    has_amd = any(read_text(os.path.join(PCI_ROOT, x, "vendor")).strip() == "0x1002" for x in slots)
    amd = amd_auto_report() if has_amd and rocm else {}
    kfd = kfd_access() if has_amd else None
    hint = rocm_hint(ollama_log_text("ollama.service")) if has_amd and rocm else None
    for slot in slots:
        d = os.path.join(PCI_ROOT, slot)
        cls = read_text(d + "/class").lower()
        if not cls.startswith(("0x03", "0x12")):
            continue
        vid, did = read_text(d + "/vendor").lower(), read_text(d + "/device").lower()
        drv = os.path.basename(os.readlink(d + "/driver")) if os.path.islink(d + "/driver") else ""
        vname, dname = names.get(slot.lower(), (VENDORS.get(vid, vid), "[%s:%s]" % (vid[2:], did[2:])))
        dev = {"slot": slot, "vendor_id": vid, "vendor": VENDORS.get(vid, vname), "name": dname, "driver": drv,
               "kind": "display" if vid in DISPLAY_ONLY else "gpu", "state": "info", "message": "",
               "actions": [], "ollama": None, "dropped": False, "metrics": live.get(norm_pci(slot))}
        for u in used:
            if u.get("library", "").lower() != "cpu" and norm_pci(u.get("pci_id")) == norm_pci(slot):
                dev["ollama"] = {"library": u.get("library"), "total": u.get("total"),
                                 "available": u.get("available"), "compute": u.get("compute"), "pool": u.get("instance")}
        dev["dropped"] = any(norm_pci(x.get("pci_id")) == norm_pci(slot) for x in dropped)
        msg, actions, state = [], [], "warn"
        if dev["kind"] == "display":
            state, msg = "info", ["Affichage de la console (contrôleur BMC ou carte virtuelle) : non utilisable pour l'IA."]
        elif vid == "0x10de":
            if drv == "nvidia":
                state = "ok"
                msg.append("Pilote NVIDIA %s chargé." % (nv_version or nv_branch) if (nv_version or nv_branch) else "Pilote NVIDIA chargé.")
            elif nv_pkg:
                msg.append("Pilote NVIDIA %s installé mais pas chargé." % nv_branch)
                if reboot_required:
                    msg.append("Redémarrez le serveur pour l'activer.")
                    actions.append("reboot")
                else:
                    msg.append("Il n'a pas été chargé au démarrage"
                               + (" : Secure Boot est actif, la clé du pilote doit être inscrite (MOK)." if secure_boot
                                  else " : consultez Journaux > Noyau."))
            else:
                msg.append("Pilote NVIDIA absent"
                           + (" (pilote libre « %s » actif, inutilisable pour le calcul)." % drv if drv else "."))
                actions.append("install-nvidia")
        elif vid in ("0x1002", "0x8086"):
            want = ("amdgpu",) if vid == "0x1002" else ("i915", "xe")
            if drv not in want:
                msg.append("Pilote noyau %s non chargé (firmware manquant ou carte non prise en charge)." % "/".join(want))
            else:
                msg.append("Pilote noyau %s chargé." % drv)
                if not vulkan:
                    actions.append("install-vulkan")
                if vid == "0x1002" and not rocm:
                    actions.append("install-rocm")
                if vid == "0x1002" and rocm:   # réglage automatique fait avant chaque démarrage d'Ollama
                    st = (amd.get("state") or {}).get(slot.lower(), "")
                    gfx = next((d["gfx"] for d in amd.get("devices", []) if d["pci"] == slot.lower()), None)
                    if st == "natif":
                        msg.append("Prise en charge native par le module ROCm (%s) : aucun contournement nécessaire." % gfx)
                    elif st.startswith("contournement:"):
                        msg.append("Cible %s absente du module ROCm : contournement appliqué automatiquement (HSA_OVERRIDE_GFX_VERSION=%s)." % (gfx, st.split(":", 1)[1]))
                    elif st.startswith("écarté:"):
                        state = "info"
                        msg.append("Écartée automatiquement de ROCm (%s) : %s, pour ne pas gêner les autres cartes." % (gfx, st.split(":", 1)[1]))
                    elif st == "non-pris-en-charge":
                        msg.append("Cible %s non prise en charge par le module ROCm : utilisez Vulkan." % gfx)
                        if vulkan:
                            msg.append("Vulkan est installé.")
            if dev["dropped"]:
                msg.append("GPU intégré écarté par Ollama : autorisez-le pour l'utiliser.")
                actions.append("enable-igpu")
        else:
            msg.append("Accélérateur non géré automatiquement par OllamaBuntu.")
        if dev["kind"] == "gpu" and vid in ("0x10de", "0x1002", "0x8086"):
            ready = (drv == "nvidia") if vid == "0x10de" else (drv in ("amdgpu", "i915", "xe") and (vulkan or (vid == "0x1002" and rocm)))
            dev["ready"] = ready
            if dev["ollama"]:
                state = "ok"
                msg.append("Utilisé par Ollama (%s, %s)." % (dev["ollama"]["library"], dev["ollama"]["total"]))
                actions = [a for a in actions if not a.startswith("install")]
            elif ready and not dev["dropped"]:
                state = "warn"
                msg.append("Pilote prêt mais carte non utilisée par Ollama : redémarrez Ollama, sinon consultez Journaux > Ollama.")
                if vid == "0x1002" and rocm and kfd is False:
                    msg.append("Le compte ollama n'a pas accès au périphérique ROCm (/dev/kfd, groupe render) : appliquez la mise à jour de l'appliance, puis redémarrez le serveur.")
                elif vid == "0x1002" and rocm and hint:
                    msg.append("Dernier message d'Ollama sur ROCm : « %s »." % hint)
                actions.append("restart-ollama")
        if dev["ollama"] and dev["ollama"].get("pool"):
            msg.append("Réservé au groupe « %s »." % dev["ollama"]["pool"])
        dev.update(state=state, message=" ".join(msg), actions=actions)
        devices.append(dev)
    compute = [{"name": u.get("description") or u.get("name"), "library": u.get("library"), "total": u.get("total"),
                "pci_id": u.get("pci_id")} for u in used if u.get("library", "").lower() != "cpu"]
    return {"devices": devices, "compute": compute, "cpu_only": not compute,
            "vulkan_installed": vulkan, "rocm_installed": rocm, "nvidia_package": nv_branch,
            "secure_boot": secure_boot, "reboot_required": reboot_required, "discovered": bool(used),
            "service": ollama_service_info("ollama.service")}


# ----------------------------------------------------------------- statut ---
def meminfo():
    info = {}
    for line in read_text("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if v.strip().split()[:1]:
            info[k] = int(v.split()[0]) * 1024
    return info


def cpu_usage():
    try:
        fields = [int(x) for x in read_text("/proc/stat").splitlines()[0].split()[1:]]
    except (IndexError, ValueError):
        return None
    idle, total = fields[3] + (fields[4] if len(fields) > 4 else 0), sum(fields)
    prev, _cpu_prev[0] = _cpu_prev[0], (idle, total)
    if not prev or total == prev[1]:
        return None
    return round(100.0 * (1 - (idle - prev[0]) / (total - prev[1])), 1)


def models_size():
    total = 0
    try:
        with os.scandir(os.path.join(MODELS_DIR, "blobs")) as it:
            for e in it:
                if e.is_file(follow_symlinks=False):
                    total += e.stat().st_size
    except OSError:
        pass
    return total


def os_name():
    for line in read_text("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return ""


def about():
    try:
        build = json.loads(read_text(BUILD_INFO, "{}"))
    except ValueError:
        build = {}
    history = [l for l in read_text(os.path.join(os.environ.get("OB_STATE", "/var/lib/ollamabuntu"), "updates.log")).splitlines() if l.strip()][-8:]
    return {"version": VERSION, "build": build, "os": os_name(), "kernel": os.uname().release, "updates": history,
            "ollama": ollama_version(), "hostname": socket.gethostname(),
            "boot_time": int(time.time() - uptime())}


# Charge des GPU en temps réel : NVIDIA (nvidia-smi), AMD (sysfs du pilote amdgpu).
# Intel n'expose pas de taux d'utilisation simple : non affiché plutôt qu'approximé.
_gpu_live = {"t": 0.0, "data": []}


def _num(x, scale=1.0):
    try:
        return round(float(x) * scale, 1)
    except (TypeError, ValueError):
        return None


def gpu_metrics():
    if time.time() - _gpu_live["t"] < 2:
        return _gpu_live["data"]
    out = {}
    smi = os.environ.get("OB_NVIDIA_SMI") or shutil.which("nvidia-smi")
    if smi:
        txt = run([smi, "--query-gpu=pci.bus_id,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
                   "--format=csv,noheader,nounits"], timeout=8)
        for line in txt.splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) < 8 or not f[0]:
                continue
            pci = norm_pci(f[0])
            out[pci] = {"pci": pci, "vendor": "NVIDIA", "name": f[1], "util": _num(f[2]),
                        "mem_used": _num(f[3], 1048576), "mem_total": _num(f[4], 1048576),
                        "temp": _num(f[5]), "power": _num(f[6]), "power_limit": _num(f[7])}
    for dev in sorted(glob.glob(os.path.join(PCI_ROOT, "*"))):
        busy = read_text(os.path.join(dev, "gpu_busy_percent"), None)
        if busy is None:
            continue
        pci = norm_pci(os.path.basename(dev))
        hw = sorted(glob.glob(os.path.join(dev, "hwmon", "hwmon*")))
        temp = power = None
        if hw:
            temp = _num(read_text(os.path.join(hw[0], "temp1_input"), None), 0.001)
            power = _num(read_text(os.path.join(hw[0], "power1_average"), None) or read_text(os.path.join(hw[0], "power1_input"), None), 0.000001)
        out[pci] = {"pci": pci, "vendor": "AMD", "name": read_text(os.path.join(dev, "product_name"), "").strip() or "AMD Radeon",
                    "util": _num(busy), "mem_used": _num(read_text(os.path.join(dev, "mem_info_vram_used"), None)),
                    "mem_total": _num(read_text(os.path.join(dev, "mem_info_vram_total"), None)), "temp": temp, "power": power, "power_limit": None}
    _gpu_live.update(t=time.time(), data=list(out.values()))
    return _gpu_live["data"]


def status():
    mem = meminfo()
    du = shutil.disk_usage("/")
    try:
        running = ollama_json("GET", "/api/ps", timeout=3, addr=OLLAMA_ADDR)[1].get("models", [])
    except OSError:
        running = []
    cpu_model = ""
    for line in read_text("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            cpu_model = line.split(":", 1)[1].strip()
            break
    gpu = gpu_info()
    return {
        "gpu_live": gpu_metrics(),
        "version": VERSION, "hostname": socket.gethostname(), "os": os_name(),
        "kernel": os.uname().release, "uptime": uptime(), "boot_time": int(time.time() - uptime()),
        "ips": local_ips(),
        "cpu": {"model": cpu_model, "cores": os.cpu_count(), "load": os.getloadavg(), "usage": cpu_usage()},
        "memory": {"total": mem.get("MemTotal", 0), "available": mem.get("MemAvailable", 0)},
        "disk": {"total": du.total, "used": du.used, "free": du.free, "models": models_size()},
        "gpu": gpu,
        "ollama": {"version": ollama_version(), "service": run(["systemctl", "is-active", "ollama.service"], 5).strip() or "inconnu",
                   "exposed": ollama_exposed(), "running": running,
                   "publication": {k: load_publication()[k] for k in ("enabled", "port", "tls", "auth")}},
        "reboot_required": gpu["reboot_required"],
        "update_available": updater.available(),
        "offload": monitor.offload(running, has_gpu=bool(gpu_metrics())),
        "alerts": [dict(a, key=k) for k, a in _alerts["active"].items()],
    }


# ------------------------------------------------------------------ tâches ---
# File d'attente des tâches système : APT, Docker et mise à jour de l'appliance ne
# s'exécutent qu'une à la fois (verrou dpkg), dans l'ordre des demandes. L'état est
# persisté dans JOBS_DIR : la file reprend après un redémarrage de la console.
_queue_lock = threading.Lock()
_job_procs = {}   # tâches lancées sans systemd : Popen, pour récupérer les processus terminés


def _job_paths(jid):
    return {ext: os.path.join(JOBS_DIR, jid + "." + ext) for ext in ("sh", "log", "rc", "queued", "started")}


def _job_alive(jid):
    """Une tâche démarrée sans code de retour est-elle encore en cours ?"""
    started = read_text(_job_paths(jid)["started"], "")
    if started.startswith("unit:"):
        return run(["systemctl", "is-active", "ob-job-" + jid], timeout=5).strip() in ("active", "activating")
    if jid in _job_procs:
        return _job_procs[jid].poll() is None
    if started.startswith("pid:"):
        try:
            os.kill(int(started[4:]), 0)
            return True
        except (ValueError, OSError):
            return False
    return True


def _launch(jid):
    title = JOBS[jid.split("-", 2)[2]][0]
    p = _job_paths(jid)
    inner = "/bin/bash %s > %s 2>&1; echo $? > %s" % (shlex.quote(p["sh"]), shlex.quote(p["log"]), shlex.quote(p["rc"]))
    if shutil.which("systemd-run") and os.path.isdir("/run/systemd/system"):
        # unité transitoire : la tâche survit à un redémarrage de la console (mises à jour, etc.)
        r = subprocess.run(["systemd-run", "--unit", "ob-job-" + jid, "--collect", "--quiet",
                            "--description", "OllamaBuntu : " + title, "/bin/bash", "-c", inner],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            atomic_write(p["started"], "unit:", 0o600)
            return
        sys.stderr.write("systemd-run indisponible (%s) : exécution directe de la tâche\n" % r.stderr.strip()[:200])
    proc = subprocess.Popen(["/bin/bash", "-c", inner], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _job_procs[jid] = proc
    atomic_write(p["started"], "pid:%d" % proc.pid, 0o600)


def _job_ids():
    files = glob.glob(os.path.join(JOBS_DIR, "*.sh"))
    return [os.path.basename(f)[:-3] for f in sorted(files, key=lambda f: (os.path.basename(f)[:15], os.stat(f).st_mtime_ns))]


def pump_queue():
    """Démarre la tâche suivante si aucune tâche système n'est en cours."""
    with _queue_lock:
        queued = []
        for jid in _job_ids():
            p = _job_paths(jid)
            if os.path.exists(p["rc"]):
                continue
            if os.path.exists(p["started"]):
                if _job_alive(jid):
                    return
                with open(p["log"], "a", encoding="utf-8") as f:
                    f.write("\n>>> Tâche interrompue (redémarrage du serveur ou de la console ?).\n")
                atomic_write(p["rc"], "255\n", 0o600)
            elif os.path.exists(p["queued"]):
                queued.append(jid)
        if queued:
            jid = queued[0]
            os.remove(_job_paths(jid)["queued"])
            _launch(jid)


def start_job(kind, script=None):
    title, default_script = JOBS[kind]
    script = script or default_script
    os.makedirs(JOBS_DIR, mode=0o700, exist_ok=True)
    with _queue_lock:
        jid = time.strftime("%Y%m%d-%H%M%S") + "-" + kind
        while os.path.exists(_job_paths(jid)["sh"]):   # même tâche demandée deux fois dans la seconde
            time.sleep(0.25)
            jid = time.strftime("%Y%m%d-%H%M%S") + "-" + kind
        p = _job_paths(jid)
        with open(p["sh"], "w", encoding="utf-8") as f:
            f.write(script)
        atomic_write(p["queued"], "", 0o600)
    pump_queue()
    return jid


def cancel_job(jid):
    with _queue_lock:
        p = _job_paths(jid)
        if not re.fullmatch(r"\d{8}-\d{6}-[a-z-]+", jid or "") or not os.path.exists(p["queued"]):
            raise ValueError("seule une tâche en attente peut être annulée")
        os.remove(p["queued"])
        with open(p["log"], "w", encoding="utf-8") as f:
            f.write(">>> Tâche annulée avant son démarrage.\n")
        atomic_write(p["rc"], "130\n", 0o600)


def queue_worker():
    while True:
        try:
            pump_queue()
        except Exception as e:   # la file ne doit jamais arrêter la console
            sys.stderr.write("file des tâches : %s\n" % e)
        time.sleep(2)


def job_status(jid):
    m = re.fullmatch(r"(\d{8}-\d{6})-([a-z-]+)", jid or "")
    if not m or m.group(2) not in JOBS:
        return None
    p = _job_paths(jid)
    if not os.path.exists(p["sh"]):
        return None
    rc = read_text(p["rc"], None)
    queued = rc is None and os.path.exists(p["queued"])
    position = None
    if queued:
        waiting = [j for j in _job_ids() if os.path.exists(_job_paths(j)["queued"])]
        running = any(os.path.exists(_job_paths(j)["started"]) and not os.path.exists(_job_paths(j)["rc"]) for j in _job_ids())
        position = waiting.index(jid) + (1 if running else 0) if jid in waiting else None
    return {"id": jid, "title": JOBS[m.group(2)][0], "done": rc is not None, "queued": queued, "position": position,
            "rc": int(rc) if rc and rc.strip().lstrip("-").isdigit() else None,
            "output": tail(p["log"]) if os.path.exists(p["log"]) else ""}


def list_jobs():
    ids = sorted({os.path.basename(p)[:-3] for p in glob.glob(os.path.join(JOBS_DIR, "*.sh"))}, reverse=True)
    out = []
    for jid in ids[:10]:
        st = job_status(jid)
        if st:
            st.pop("output", None)
            out.append(st)
    return out


# =============================================================================
#  Mises à jour du système : dépôt d'origine + criticité (avis Ubuntu via OSV.dev)
# =============================================================================
STATE_DIR = os.environ.get("OB_STATE", "/var/lib/ollamabuntu")
OSV_URL = os.environ.get("OB_OSV_URL", "https://api.osv.dev")
APT_SIM = os.environ.get("OB_APT_SIM", "")          # tests : fichier de sortie d'apt-get -s
PRIORITIES = ["negligible", "low", "medium", "high", "critical"]
INST_RE = re.compile(r"^Inst (\S+) (?:\[([^\]]+)\] )?\((\S+) (.*?) \[([^\]]+)\]\)")
_cache = {}
_apt_pkg = [None]


def os_release():
    d = {}
    for line in read_text("/etc/os-release").splitlines():
        k, _, v = line.partition("=")
        d[k] = v.strip('"')
    return d


def osv_ecosystem():
    r = os_release()
    return "Ubuntu:%s%s" % (r.get("VERSION_ID", ""), ":LTS" if "LTS" in r.get("VERSION", "") else "")


def version_lt(a, b):
    if _apt_pkg[0] is None:
        try:
            import apt_pkg
            apt_pkg.init_system()
            _apt_pkg[0] = apt_pkg
        except Exception:   # python3-apt absent : dpkg fait foi
            _apt_pkg[0] = False
    if _apt_pkg[0]:
        return _apt_pkg[0].version_compare(a, b) < 0
    return subprocess.run(["dpkg", "--compare-versions", a, "lt", b], capture_output=True).returncode == 0


def pocket_kind(origins):
    kinds = set()
    for o in [x.strip() for x in origins.split(",") if x.strip()]:
        suite = o.split("/")[-1]
        if suite.endswith("-security"):
            kinds.add("securite")
        elif suite.endswith("-updates"):
            kinds.add("correctif")
        elif suite.endswith("-backports"):
            kinds.add("retroportage")
        elif not o.lower().startswith("ubuntu"):
            kinds.add("tiers")
        else:
            kinds.add("correctif")
    for k in ("securite", "correctif", "retroportage", "tiers"):
        if k in kinds:
            return k
    return "correctif"


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def http_get(url, accept=None, timeout=15, data=None):
    import urllib.request
    import urllib.error
    headers = {"User-Agent": "OllamaBuntu/%s" % VERSION}
    if accept:
        headers["Accept"] = accept
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


HF_BASE = os.environ.get("OB_HF", "https://huggingface.co")
HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
UNCENSORED_RE = re.compile(r"uncensor|abliterat|unfilter|decensor|heretic|no[-_]?refusal|unrestrict", re.I)
QUANT_RE = re.compile(r"(?:^|[-_.])((?:IQ|Q)\d(?:_[A-Z0-9]+)*|BF16|F16|F32)(?=[-_.]|$)", re.I)
_hf_cache = {}


def hf_get(path):
    """Requête à l'API Hugging Face (cache de 5 minutes)."""
    hit = _hf_cache.get(path)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    try:
        st, raw = http_get(HF_BASE + path, timeout=20)
    except (OSError, ValueError) as e:
        raise ValueError("Hugging Face injoignable : %s" % e)
    if st == 404:
        raise ValueError("dépôt introuvable sur Hugging Face")
    if st != 200:
        raise ValueError("Hugging Face a répondu HTTP %s" % st)
    data = json.loads(raw)
    if len(_hf_cache) > 200:
        _hf_cache.clear()
    _hf_cache[path] = (time.time(), data)
    return data


def hf_is_uncensored(repo_id, tags=()):
    return bool(UNCENSORED_RE.search(repo_id) or any(UNCENSORED_RE.search(str(t)) for t in tags))


def hf_search(q, mode):
    """Modèles GGUF de Hugging Face. mode : standard (sans les versions sans censure), all, uncensored (seulement celles-ci)."""
    q = str(q or "").strip()[:80]
    if mode not in ("standard", "all", "uncensored"):
        mode = "standard"
    if q and not re.match(r"^[\w .:/+-]+$", q):
        raise ValueError("recherche invalide")
    queries = [q]
    if mode == "uncensored":
        queries = ([q] if q else []) + ["uncensored", "abliterated", "unfiltered"]
    words = [w.lower() for w in q.split()]
    found = {}
    for term in queries:
        url = "/api/models?filter=gguf&sort=downloads&direction=-1&limit=%d" % (60 if mode == "uncensored" else 30)
        if term:
            url += "&search=" + urllib.parse.quote(term)
        for m in hf_get(url):
            rid = str(m.get("id") or m.get("modelId") or "")
            if not HF_REPO_RE.match(rid) or m.get("private") or m.get("gated"):
                continue
            unc = hf_is_uncensored(rid, m.get("tags") or [])
            if (mode == "standard" and unc) or (mode == "uncensored" and not unc):
                continue
            if words and not all(w in rid.lower() for w in words):
                continue
            found.setdefault(rid, {"id": rid, "downloads": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0),
                                   "updated": str(m.get("lastModified") or "")[:10], "uncensored": unc})
    return {"models": sorted(found.values(), key=lambda x: -x["downloads"])[:40], "mode": mode}


def hf_fit(quants, vram, ram_total):
    """Place d'une quantification sur ce serveur : gpu (tient en mémoire vidéo avec une marge pour le cache), partial (déborde sur la
    mémoire du serveur : fonctionne, nettement plus lent), no (trop gros même ainsi). Sans GPU, tout se juge sur la mémoire du serveur."""
    for q in quants:
        need = q["size"] * 1.08 + GB_HALF
        if vram and need <= vram * 0.92:
            q["fit"] = "gpu"
        elif need <= (vram * 0.92 if vram else 0) + ram_total * 0.7:
            q["fit"] = "partial"
        else:
            q["fit"] = "no"
    return quants


GB_HALF = 512 * 1024 * 1024


def hf_files(repo):
    """Quantifications GGUF d'un dépôt Hugging Face, avec leur taille (fichiers multiples additionnés)."""
    repo = str(repo or "").strip()
    if not HF_REPO_RE.match(repo):
        raise ValueError("nom de dépôt invalide (utilisateur/dépôt)")
    info = hf_get("/api/models/%s?blobs=true" % repo)
    if info.get("gated"):
        raise ValueError("dépôt à accès restreint (compte Hugging Face requis) : non téléchargeable ici")
    quants = {}
    for f in info.get("siblings") or []:
        name = str(f.get("rfilename") or "")
        if not name.lower().endswith(".gguf") or "mmproj" in name.lower():
            continue
        m = QUANT_RE.search(os.path.basename(name))
        if not m:
            continue
        q = quants.setdefault(m.group(1).upper(), {"quant": m.group(1).upper(), "size": 0, "files": 0})
        q["size"] += int(f.get("size") or 0)
        q["files"] += 1
    gg = info.get("gguf") if isinstance(info.get("gguf"), dict) else {}
    return {"id": repo, "uncensored": hf_is_uncensored(repo, info.get("tags") or []), "quants": sorted(quants.values(), key=lambda x: x["size"]),
            "arch": str(gg.get("architecture") or "")[:40], "ctx": gg.get("context_length") if isinstance(gg.get("context_length"), int) else None,
            "tags": [str(t)[:40] for t in (info.get("tags") or [])[:30]]}


def ubuntu_scores(obj, out):
    """Collecte récursive des niveaux de priorité Ubuntu ({"type": "Ubuntu", "score": "high"})."""
    if isinstance(obj, dict):
        if str(obj.get("type", "")).lower() == "ubuntu" and str(obj.get("score", "")).lower() in PRIORITIES:
            out.append(str(obj["score"]).lower())
        for v in obj.values():
            ubuntu_scores(v, out)
    elif isinstance(obj, list):
        for v in obj:
            ubuntu_scores(v, out)
    return out


def osv_lookup(eco, src, installed, candidate):
    """Failles du paquet source corrigées par le passage installed -> candidate."""
    key = "osv|%s|%s|%s|%s" % (eco, src, installed, candidate)
    def fetch():
        body = json.dumps({"package": {"name": src, "ecosystem": eco}, "version": installed}).encode()
        st, raw = http_get(OSV_URL + "/v1/query", data=body, timeout=20)
        if st != 200:
            raise OSError("OSV HTTP %s" % st)
        res = {"priority": None, "advisories": []}
        for v in json.loads(raw or b"{}").get("vulns", []):
            fixed = []
            for a in v.get("affected", []):
                p = a.get("package", {})
                if p.get("name") == src and p.get("ecosystem") == eco:
                    for r in a.get("ranges", []):
                        fixed += [e["fixed"] for e in r.get("events", []) if "fixed" in e]
            if not any(not version_lt(candidate, f) for f in fixed):
                continue   # pas corrigée par cette mise à jour
            scores = ubuntu_scores(v, [])
            prio = max(scores, key=PRIORITIES.index) if scores else None
            if prio and (res["priority"] is None or PRIORITIES.index(prio) > PRIORITIES.index(res["priority"])):
                res["priority"] = prio
            res["advisories"].append({"id": v.get("id"), "priority": prio, "summary": (v.get("summary") or "")[:160]})
        return res
    return cached(key, 12 * 3600, fetch)


def pending_updates(refresh=False):
    if refresh:
        _cache.pop("updates", None)
    def compute():
        out = read_text(APT_SIM) if APT_SIM else run(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], timeout=240)
        pkgs, phased, in_phased = [], [], False
        for line in out.splitlines():
            m = INST_RE.match(line)
            if m:
                name, cur, new, origins, arch = m.groups()
                pkgs.append({"name": name, "current": cur, "candidate": new, "arch": arch,
                             "origins": [o.strip() for o in origins.split(",")], "kind": pocket_kind(origins),
                             "new": cur is None, "kernel": name.startswith(("linux-image", "linux-modules", "linux-headers")),
                             "priority": None, "advisories": []})
            if "deferred due to phasing" in line:
                in_phased = True
                continue
            if in_phased:
                if line.startswith(" "):
                    phased += line.split()
                else:
                    in_phased = False
        # paquets source (OSV raisonne par paquet source et version installée)
        sec = [p for p in pkgs if p["kind"] == "securite" and p["current"]]
        src = {}
        if sec:
            q = run(["dpkg-query", "-W", "-f=${binary:Package}|${source:Package}|${source:Version}\n"] + [p["name"] for p in sec], timeout=30)
            for line in q.splitlines():
                b, _, rest = line.partition("|")
                s, _, sv = rest.partition("|")
                src[b.split(":")[0]] = (s, sv)
        eco, osv_state = osv_ecosystem(), "ok"
        groups = {}
        for p in sec:
            s, sv = src.get(p["name"], (p["name"], p["current"]))
            p["source"] = s
            groups.setdefault((s, sv), []).append(p)
        if groups:
            from concurrent.futures import ThreadPoolExecutor
            def one(item):
                (s, sv), members = item
                # une même source peut produire des binaires avec ou sans époque (« 1:2.39 » / « 2.39 ») :
                # on compare avec la version candidate qui suit la convention de la version source
                cands = [m["candidate"] for m in members]
                cand = next((c for c in cands if (":" in c) == (":" in sv)), cands[0])
                try:
                    return members, osv_lookup(eco, s, sv, cand)
                except (OSError, ValueError) as e:
                    return members, e
            with ThreadPoolExecutor(max_workers=8) as ex:
                for members, res in ex.map(one, list(groups.items())):
                    if isinstance(res, Exception):
                        osv_state = "indisponible : %s" % res
                        continue
                    for p in members:
                        p["priority"], p["advisories"] = res["priority"], res["advisories"]
        rank = {k: i for i, k in enumerate(["securite", "correctif", "retroportage", "tiers"])}
        pkgs.sort(key=lambda p: (rank[p["kind"]], -(PRIORITIES.index(p["priority"]) if p["priority"] else -1), p["name"]))
        summary = {k: sum(1 for p in pkgs if p["kind"] == k) for k in rank}
        by_prio = {k: sum(1 for p in pkgs if p["kind"] == "securite" and p["priority"] == k) for k in PRIORITIES}
        by_prio["inconnue"] = sum(1 for p in pkgs if p["kind"] == "securite" and not p["priority"])
        stamps = [f for f in ["/var/lib/apt/periodic/update-success-stamp"] if os.path.exists(f)] or glob.glob("/var/lib/apt/lists/*InRelease")
        last = int(max(os.path.getmtime(f) for f in stamps)) if stamps else None
        return {"count": len(pkgs), "summary": summary, "security_priority": by_prio, "packages": pkgs,
                "phased": phased, "last_check": last, "osv": osv_state, "ecosystem": eco,
                "kernel": any(p["kernel"] for p in pkgs), "reboot_required": os.path.exists(sysp("/var/run/reboot-required"))}
    return cached("updates", 120, compute)


# =============================================================================
#  Modèles : registre Ollama, compatibilité avec le matériel, mises à jour
# =============================================================================
REGISTRY = os.environ.get("OB_REGISTRY", "https://registry.ollama.ai")
MANIFEST_ACCEPT = ", ".join(["application/vnd.docker.distribution.manifest.v2+json", "application/vnd.oci.image.manifest.v1+json",
                             "application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.oci.image.index.v1+json"])
GIB = 1024 ** 3


def parse_model_name(name):
    n, tag = name, "latest"
    if ":" in n.split("/")[-1]:
        n, tag = n.rsplit(":", 1)
    parts = n.split("/")
    if len(parts) == 1:
        return "registry.ollama.ai", "library", parts[0], tag
    if len(parts) == 2:
        return "registry.ollama.ai", parts[0], parts[1], tag
    return parts[0], "/".join(parts[1:-1]), parts[-1], tag


def short_name(name):
    host, ns, model, tag = parse_model_name(name)
    base = model if (host, ns) == ("registry.ollama.ai", "library") else "%s/%s" % (ns, model) if host == "registry.ollama.ai" else "%s/%s/%s" % (host, ns, model)
    return "%s:%s" % (base, tag)


def model_source(name):
    """Registre d'origine d'un modèle : « Hugging Face » (hf.co/...), « Ollama » (registre officiel) ou l'adresse d'un registre privé."""
    host = parse_model_name(name)[0]
    return "Ollama" if host == "registry.ollama.ai" else "Hugging Face" if host in ("hf.co", "huggingface.co") else host


def registry_manifest(name):
    """Manifeste distant (liste de manifestes GGUF/MLX gérée) + configuration du modèle. None si absent."""
    host, ns, model, tag = parse_model_name(name)
    if tag == "cloud" or tag.endswith("-cloud"):
        return {"cloud": True}
    def fetch():
        base = REGISTRY if host == "registry.ollama.ai" else "https://" + host
        st, raw = http_get("%s/v2/%s/%s/manifests/%s" % (base, ns, model, tag), MANIFEST_ACCEPT)
        if st == 404:
            return None
        if st != 200:
            raise OSError("registre HTTP %s" % st)
        data = json.loads(raw)
        if data.get("manifests") and not data.get("layers"):   # liste : on suit la variante GGUF (llama.cpp)
            entries = data["manifests"]
            pick = next((e for e in entries if "gguf" in json.dumps(e).lower()), None) or \
                next((e for e in entries if "mlx" not in json.dumps(e).lower()), entries[0])
            st, raw = http_get("%s/v2/%s/%s/manifests/%s" % (base, ns, model, pick["digest"]), MANIFEST_ACCEPT)
            if st != 200:
                raise OSError("registre HTTP %s" % st)
            data = json.loads(raw)
        layers = data.get("layers", [])
        kinds = [l.get("mediaType", "").rsplit(".", 1)[-1] for l in layers]
        cfg = {}
        cdig = (data.get("config") or {}).get("digest")
        if cdig:
            try:
                st, craw = http_get("%s/v2/%s/%s/blobs/%s" % (base, ns, model, cdig), timeout=15)
                cfg = json.loads(craw) if st == 200 else {}
            except (OSError, ValueError):
                cfg = {}
        return {"digest": hashlib.sha256(raw).hexdigest(), "size": sum(l.get("size", 0) for l in layers),
                "layers": sorted([l["digest"] for l in layers if l.get("digest")] + ([cdig] if cdig else [])),
                "sizes": {l["digest"]: l.get("size", 0) for l in layers if l.get("digest")},
                "vision": "projector" in kinds, "draft": "draft" in kinds,
                "params": cfg.get("model_type"), "quant": cfg.get("file_type"), "family": cfg.get("model_family"),
                "requires": cfg.get("requires")}
    return cached("reg|" + name, 6 * 3600, fetch)


def local_manifest(name):
    host, ns, model, tag = parse_model_name(name)
    hosts = [host] + (["ollama.com"] if host == "registry.ollama.ai" else [])
    for sub in ("manifests-v2", "manifests"):
        for h in hosts:
            p = os.path.join(MODELS_DIR, sub, h, ns, model, tag)
            if os.path.isfile(p):
                try:
                    with open(p, "rb") as f:
                        raw = f.read()
                    return json.loads(raw), hashlib.sha256(raw).hexdigest()
                except (OSError, ValueError):
                    pass
    return None, None


def parse_size(text):
    m = re.match(r"\s*([\d.]+)\s*([KMGT]i?B)", str(text or ""))
    if not m:
        return 0
    return float(m.group(1)) * 1024 ** {"K": 1, "M": 2, "G": 3, "T": 4}[m.group(2)[0]]


def capacity():
    gpus = gpu_inventory()
    mem = meminfo()
    return {"vram": sum(parse_size(u.get("total")) for u in gpus),
            "gpus": ["%s (%s, %s)" % (u.get("description") or u.get("name"), u.get("library"), u.get("total")) for u in gpus],
            "ram_total": mem.get("MemTotal", 0), "ram_available": mem.get("MemAvailable", 0)}


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:3])


def assess_fit(size, cap, requires=None, current=None):
    if requires and current and version_tuple(current) < version_tuple(requires):
        return {"level": "incompatible", "label": "Nécessite Ollama %s (installé : %s)" % (requires, current)}
    need = size * 1.15 + 1.0 * GIB   # poids + cache de contexte par défaut + moteur
    if cap["vram"] > 0:
        if need <= cap["vram"] * 0.95:
            return {"level": "gpu", "label": "Entièrement sur GPU", "need": need}
        if need <= cap["vram"] + cap["ram_available"] * 0.8:
            return {"level": "mixte", "label": "GPU + mémoire système (ralenti)", "need": need}
        return {"level": "trop", "label": "Trop gros pour ce serveur", "need": need}
    if need <= cap["ram_total"] * 0.8:
        speed = "réactif" if size < 3 * GIB else "lent" if size < 9 * GIB else "très lent"
        return {"level": "cpu", "label": "Sur processeur (%s)" % speed, "need": need}
    return {"level": "trop", "label": "Trop gros pour ce serveur", "need": need}


def load_catalog():
    for p in (os.path.join(ETC, "catalog.json"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog.json")):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("models", [])
        except (OSError, ValueError):
            continue
    return []


def model_update_state(m, r, registry_error):
    """État de mise à jour d'un modèle installé : m = ligne de /api/tags, r = manifeste du registre (ou None), registry_error = le registre n'a pas répondu."""
    local, local_sha = local_manifest(m["name"])
    if r is None and not registry_error:
        return {"state": "local", "label": "Absent du registre (modèle local ou personnalisé)"}
    if r is None:
        return {"state": "inconnu", "label": "Registre injoignable"}
    if r.get("cloud"):
        return {"state": "cloud", "label": "Modèle cloud"}
    if r["digest"] in (m.get("digest"), local_sha):
        return {"state": "a_jour", "label": "À jour"}
    have = set()
    if local:
        have = {l.get("digest") for l in local.get("layers", [])} | {(local.get("config") or {}).get("digest")}
    missing = [d for d in r["layers"] if d not in have]
    if local and not missing:
        return {"state": "a_jour", "label": "À jour"}
    dl = sum(r["sizes"].get(d, 0) for d in missing)
    return {"state": "maj", "label": "Mise à jour disponible (%.1f Go à télécharger)" % (dl / 1e9), "download": dl}


def model_insights(refresh=False):
    if refresh:
        for k in [k for k in _cache if k.startswith("reg|")]:
            _cache.pop(k, None)
    cap, current = capacity(), ollama_version()
    try:
        installed = [m for m in ollama_json("GET", "/api/tags", timeout=10)[1].get("models", []) if not modelupdate.is_prev(m.get("name", ""))]
    except OSError:
        installed = []
    catalog = load_catalog()
    names = sorted({m["name"] for m in installed} | {c["name"] for c in catalog})
    remote, errors = {}, []
    from concurrent.futures import ThreadPoolExecutor
    def one(n):
        try:
            return n, registry_manifest(n), None
        except (OSError, ValueError) as e:
            return n, None, str(e)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for n, man, err in ex.map(one, names):
            remote[n] = man
            if err:
                errors.append("%s : %s" % (n, err))
    inst_out = []
    for m in installed:
        r = remote.get(m["name"])
        upd = model_update_state(m, r, any(m["name"] in e for e in errors))
        inst_out.append({"name": m["name"], "source": model_source(m["name"]), "size": m.get("size", 0), "details": m.get("details", {}),
                         "modified_at": m.get("modified_at"), "update": upd,
                         "fit": assess_fit(m.get("size", 0), cap, (r or {}).get("requires"), current)})
    have_names = {short_name(m["name"]) for m in installed}
    cat_out = []
    for c in catalog:
        r = remote.get(c["name"])
        item = dict(c, installed=short_name(c["name"]) in have_names, source=model_source(c["name"]))
        if r and not r.get("cloud"):
            item.update(available=True, size=r["size"], vision=r["vision"], draft=r["draft"], params=r["params"],
                        quant=(r["quant"] if str(r["quant"]).lower() not in ("", "unknown") else parse_model_name(c["name"])[3]),
                        fit=assess_fit(r["size"], cap, r.get("requires"), current))
        else:
            item.update(available=False, fit=None)
        cat_out.append(item)
    order = {"gpu": 0, "cpu": 1, "mixte": 2, "trop": 3, "incompatible": 4, None: 5}
    cat_out.sort(key=lambda c: (order[(c.get("fit") or {}).get("level")], c.get("size") or 0))
    sources = {}
    for c in cat_out:
        s_ = sources.setdefault(c["source"], {"total": 0, "available": 0})
        s_["total"] += 1
        s_["available"] += 1 if c.get("available") else 0
    return {"capacity": cap, "ollama": current, "installed": inst_out, "catalog": cat_out, "sources": sources,
            "registry": {"ok": not errors, "errors": errors[:5], "checked": int(time.time())}}


def model_check(name):
    cap, current = capacity(), ollama_version()
    r = registry_manifest(name)
    if r is None:
        return {"name": name, "found": False}
    if r.get("cloud"):
        return {"name": name, "found": True, "cloud": True}
    return {"name": name, "found": True, "size": r["size"], "vision": r["vision"], "draft": r["draft"],
            "params": r["params"], "quant": r["quant"], "family": r["family"], "requires": r.get("requires"),
            "fit": assess_fit(r["size"], cap, r.get("requires"), current)}


# =============================================================================
#  Open WebUI : conteneur Docker + relais HTTPS (port 8443)
# =============================================================================
WEBUI_ENV = os.path.join(ETC, "open-webui.env")
WEBUI_PORT = int(os.environ.get("OB_WEBUI_PORT", "3000"))
WEBUI_TLS_PORT = int(os.environ.get("OB_WEBUI_TLS_PORT", "8443"))
WEBUI_HELPER = os.environ.get("OB_WEBUI_HELPER", "/usr/local/lib/ollamabuntu/open-webui.sh")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def webui_status():
    st = {"docker": bool(shutil.which("docker")), "configured": os.path.exists(WEBUI_ENV), "container": None,
          "running": False, "version": None, "latest": None, "tls_port": WEBUI_TLS_PORT, "admin_email": None}
    for line in read_text(WEBUI_ENV).splitlines():
        if line.startswith("WEBUI_ADMIN_EMAIL="):
            st["admin_email"] = line.split("=", 1)[1]
    if st["docker"]:
        out = run(["docker", "inspect", "--format", "{{.State.Status}}|{{.Config.Image}}|{{.State.StartedAt}}", "open-webui"], timeout=15).strip()
        if out.count("|") == 2:
            status_, image, started = out.split("|")
            st.update(container=status_, running=status_ == "running", image=image, started=started[:19].replace("T", " "))
    if st["running"]:
        try:
            code, raw = http_get("http://127.0.0.1:%d/api/version" % WEBUI_PORT, timeout=4)
            st["version"] = json.loads(raw).get("version") if code == 200 else None
            st["healthy"] = code == 200
        except (OSError, ValueError):
            st["healthy"] = False
    try:
        st["latest"] = cached("webui-latest", 6 * 3600, lambda: _latest_webui())
    except OSError:
        st["latest"] = None
    return st


def _latest_webui():
    import urllib.request
    req = urllib.request.Request("https://github.com/open-webui/open-webui/releases/latest", method="HEAD",
                                 headers={"User-Agent": "OllamaBuntu"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.geturl().rsplit("/", 1)[-1].lstrip("v")


def webui_configure(email, password, name):
    if not EMAIL_RE.match(email or ""):
        raise ValueError("Adresse e-mail de l'administrateur Open WebUI invalide.")
    if len(password) < 8 or any(ord(c) < 32 for c in password):
        raise ValueError("Mot de passe Open WebUI refusé (8 caractères minimum).")
    name = re.sub(r"[^\w .'-]", "", name or "Administrateur")[:60] or "Administrateur"
    lines = ["# Open WebUI (géré par OllamaBuntu)", "OLLAMA_BASE_URL=http://127.0.0.1:11434", "HOST=127.0.0.1",
             "PORT=%d" % WEBUI_PORT, "WEBUI_NAME=OllamaBuntu", "WEBUI_SECRET_KEY=" + secrets.token_hex(32),
             "WEBUI_ADMIN_EMAIL=" + email, "WEBUI_ADMIN_NAME=" + name, "WEBUI_ADMIN_PASSWORD=" + password]
    atomic_write(WEBUI_ENV, "\n".join(lines) + "\n", 0o600)


async def _pipe(reader, writer):
    import asyncio
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _webui_client(cr, cw):
    import asyncio
    try:
        ur, uw = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", WEBUI_PORT), 10)
    except (OSError, asyncio.TimeoutError):
        msg = "Open WebUI ne répond pas : il n'est pas déployé, ou il démarre encore.\n".encode()
        cw.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\n"
                 b"Content-Length: " + str(len(msg)).encode() + b"\r\n\r\n" + msg)
        try:
            await cw.drain()
        finally:
            cw.close()
        return
    await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw))


def start_webui_proxy(ctx):
    """Relais TLS -> Open WebUI (127.0.0.1:3000) : même certificat que la console, WebSockets compris."""
    import asyncio
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(asyncio.start_server(_webui_client, port=WEBUI_TLS_PORT, ssl=ctx))
        except OSError as e:
            sys.stderr.write("relais Open WebUI indisponible : %s\n" % e)
            return
        loop.run_forever()
    threading.Thread(target=runner, daemon=True).start()


# ---------------------------------------------------------------- serveur ---
ADMIN_GET = {"/api/status", "/api/gpu", "/api/logs", "/api/logs/live", "/api/metrics", "/api/requests", "/api/requests/settings", "/api/fleet/balance", "/api/jobs", "/api/users", "/api/ollama-env",
             "/api/updates", "/api/models/insights", "/api/webui", "/api/update/online", "/api/hf/search", "/api/hf/files", "/api/alerts", "/api/tuning", "/api/limits", "/api/queue", "/api/redirects", "/api/fit", "/api/fit/hf", "/api/llama", "/api/llama/logs", "/api/power", "/api/costs", "/api/costs/export", "/api/privacy", "/api/rag", "/api/sso/config", "/api/fleet/rules", "/api/update/backups", "/api/usage", "/api/requests/export", "/api/prom", "/api/gpu/guard", "/api/hw", "/api/perf", "/api/audit", "/api/audit/export", "/api/report", "/api/models/disk", "/api/lab", "/api/mu", "/api/mu/check"}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "OllamaBuntu"
    sys_version = ""
    protocol_version = "HTTP/1.0"
    timeout = 300

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.client_address[0], fmt % args))

    def send_head(self, code, ctype, length=None, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def send_blob(self, data, filename):
        self.send_head(200, "application/octet-stream", len(data), {"Content-Disposition": 'attachment; filename="%s"' % filename})
        self.wfile.write(data)

    def send_json(self, code, obj, extra=None):
        a = getattr(self, "_audit", None)
        if a:
            self._audit = None
            audit_record(a[0], a[1], self.client_address[0], a[2], a[3], code)
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_head(code, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self.send_json(404, {"error": "introuvable"})
        self.send_head(200, ctype, len(body))
        self.wfile.write(body)

    def read_json(self, limit=None):
        n = int(self.headers.get("Content-Length") or 0)
        if n > (limit or MAX_BODY):
            raise ValueError("requête trop volumineuse")
        data = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if not isinstance(data, dict):
            raise ValueError("objet JSON attendu")
        return data

    def cookie(self, name):
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return None
        m = jar.get(name)
        return m.value if m else None

    def token(self):
        return self.cookie("ob_session")

    def redirect(self, location, cookies=()):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def sso_start(self):
        if too_many_failures(self.client_address[0]):
            return self.redirect("/?sso=idp")
        try:
            url, state = sso_oidc_begin()
        except ValueError as e:
            sys.stderr.write("SSO OIDC : début de connexion impossible : %s\n" % e)
            return self.redirect("/?sso=" + ("config" if str(e) == "config" else "idp"))
        return self.redirect(url, ["ob_sso=%s; Path=/sso; HttpOnly; Secure; SameSite=Lax; Max-Age=600" % state])

    def sso_callback(self, query):
        ip, one = self.client_address[0], (lambda k: (query.get(k) or [""])[0])
        clear = "ob_sso=; Path=/sso; HttpOnly; Secure; SameSite=Lax; Max-Age=0"
        state, code, mine = one("state"), one("code"), self.cookie("ob_sso") or ""
        if not state or not code or not mine or not hmac.compare_digest(mine, state) or one("error"):
            with _sso_lock:
                _sso_pending.pop(state, None)
            record_failure(ip)
            audit_record("?", "", ip, "/sso/oidc/callback", {"erreur": "state" if not one("error") else "fournisseur"}, 403)
            return self.redirect("/?sso=" + ("idp" if one("error") else "state"), [clear])
        try:
            name, role, rec = sso_oidc_finish(code, state)
        except ValueError as e:
            err = str(e) if str(e) in SSO_ERRORS else "idp"
            record_failure(ip)
            audit_record("?", "", ip, "/sso/oidc/callback", {"erreur": err}, 403)
            return self.redirect("/?sso=" + err, [clear])
        audit_record(name, role, ip, "/sso/oidc/callback", {}, 200)
        token = new_session(name, role, rec.get("rev"))
        return self.redirect("/", ["ob_session=%s; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=%d" % (token, SESSION_TTL), clear])

    def forbidden(self):
        return self.send_json(403, {"error": "Réservé aux administrateurs."})

    # -- GET
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        if path in STATIC:
            name, ctype = STATIC[path]
            return self.send_file(os.path.join(WEB_DIR, name), ctype)
        if path in ("/logo.svg", "/favicon.svg", "/favicon.ico"):
            return self.send_file(os.path.join(SHARE, "icon.svg"), "image/svg+xml")
        if path == "/api/ping":   # public : version + empreinte du démarrage (suivi d'un redémarrage)
            lang = read_text(os.path.join(ETC, "lang"), "fr").strip()
            return self.send_json(200, {"ok": True, "version": VERSION, "lang": lang if lang in ("fr", "en") else "fr",
                                        "boot": hashlib.sha256(boot_id().encode()).hexdigest()[:12]})
        if path == "/api/sso/providers":   # public : boutons de la page de connexion
            return self.send_json(200, sso_providers())
        if path == "/sso/oidc/start":
            return self.sso_start()
        if path == "/sso/oidc/callback":
            return self.sso_callback(query)
        if path == "/metrics":   # jeton dédié (lecture seule des mesures), pas de session
            try:
                prom_auth(self.headers, self.client_address[0])
            except PermissionError as e:
                return self.send_json(e.args[0], {"error": e.args[1]})
            body = prom_text().encode()
            return self.send_head(200, "text/plain; version=0.0.4; charset=utf-8", len(body)) or self.wfile.write(body)
        if not path.startswith("/api/"):
            return self.send_json(404, {"error": "introuvable"})
        if path.startswith("/api/fleet/ollama/"):
            return self.fleet_proxy("GET", path, None)
        if path == "/api/fleet/status":   # console principale (jeton de gestion centralisée)
            try:
                member_auth(self.headers, self.client_address[0])
            except PermissionError as e:
                return self.send_json(e.args[0], {"error": e.args[1]})
            return self.send_json(200, fleet_summary())
        sess = session_get(self.token())
        if not sess:
            return self.send_json(401, {"error": "authentification requise"})
        user, role = sess
        if path == "/api/models/context":
            return self.send_json(200, context_view())
        if path in ("/api/fleet/member", "/api/fleet/servers") and role != "admin":
            return self.forbidden()
        if path == "/api/fleet/member":
            return self.send_json(200, member_view())
        if path == "/api/fleet/servers":
            return self.send_json(200, fleet_view())
        if path == "/api/rag/collections":   # noms et tailles seulement, pour le choix d'une base dans la conversation
            return self.send_json(200, {"collections": rag_store().collections()})
        if path in ADMIN_GET and role != "admin":
            return self.forbidden()
        try:
            if path == "/api/session":
                return self.send_json(200, {"user": user, "role": role, "version": VERSION})
            if path == "/api/about":
                return self.send_json(200, about())
            if path == "/api/credits":
                try:
                    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "credits.json"), encoding="utf-8") as f:
                        return self.send_json(200, json.load(f))
                except (OSError, ValueError):
                    return self.send_json(200, {"items": []})
            if path == "/api/status":
                return self.send_json(200, status())
            if path == "/api/publication":
                if role != "admin":
                    return self.forbidden()
                return self.send_json(200, publication_view())
            if path == "/api/security/policy":
                if role != "admin":
                    return self.forbidden()
                return self.send_json(200, policy_view())
            if path == "/api/models/custom":
                if role != "admin":
                    return self.forbidden()
                return self.send_json(200, {"custom": [dict(v, name=k) for k, v in sorted(load_custom().items())],
                                            "preload": load_preload(), "preload_state": _preload["state"]})
            if path == "/api/security":
                if role != "admin":
                    return self.forbidden()
                return self.send_json(200, {"firewall": firewall_status(), "updates": autoupdates_status(), "audit": hardening_audit()})
            if path == "/api/gpu/placement":
                if role != "admin":
                    return self.forbidden()
                return self.send_json(200, placement_status())
            if path == "/api/gpu":
                return self.send_json(200, gpu_info())
            refresh = (query.get("refresh") or ["0"])[0] == "1"
            if path == "/api/updates":
                return self.send_json(200, pending_updates(refresh))
            if path == "/api/update/online":
                return self.send_json(200, updater.view())
            if path == "/api/alerts":
                return self.send_json(200, alerts_view())
            if path == "/api/tuning":
                return self.send_json(200, tuning_view())
            if path == "/api/limits":
                return self.send_json(200, limits_view())
            if path == "/api/queue":
                return self.send_json(200, queue_view())
            if path == "/api/redirects":
                return self.send_json(200, redirects_view())
            if path == "/api/fit":
                return self.send_json(200, fit_view((query.get("model") or [""])[0] or None))
            if path == "/api/fit/hf":
                try:
                    return self.send_json(200, fit_hf((query.get("repo") or [""])[0]))
                except ValueError as e:
                    return self.send_json(400, {"error": str(e)})
            if path == "/api/llama":
                return self.send_json(200, llama_view())
            if path == "/api/llama/logs":
                try:
                    return self.send_json(200, engine_logs((query.get("id") or [""])[0]))
                except ValueError as e:
                    return self.send_json(400, {"error": str(e)})
            if path == "/api/power":
                return self.send_json(200, power_view())
            if path == "/api/sso/config":
                return self.send_json(200, sso_view())
            if path == "/api/costs":
                return self.send_json(200, costs_view((query.get("month") or [""])[0]))
            if path == "/api/costs/export":
                month = (query.get("month") or [""])[0] or costs.day_of(time.time())[:7]
                try:
                    body = ("\ufeff" + costs_export(month)).encode("utf-8")
                except ValueError as e:
                    return self.send_json(400, {"error": str(e)})
                print("coûts du mois %s exportés par %s" % (month, user), flush=True)
                return self.send_head(200, "text/csv; charset=utf-8", len(body), {"Content-Disposition": 'attachment; filename="couts-%s.csv"' % month}) or self.wfile.write(body)
            if path == "/api/privacy":
                return self.send_json(200, privacy_view())
            if path == "/api/rag":
                return self.send_json(200, rag_view())
            if path == "/api/update/backups":
                return self.send_json(200, {"backups": backups_list(), "installed": VERSION})
            if path == "/api/fleet/rules":
                return self.send_json(200, {"rules": load_rules()})
            if path in ("/api/hf/search", "/api/hf/files"):
                try:
                    if path == "/api/hf/search":
                        return self.send_json(200, hf_search((query.get("q") or [""])[0], (query.get("mode") or ["standard"])[0]))
                    r = hf_files((query.get("repo") or [""])[0])
                    r["vram"] = sum(g.get("mem_total") or 0 for g in gpu_metrics())
                    r["ram"] = meminfo().get("MemTotal", 0)
                    hf_fit(r["quants"], r["vram"], r["ram"])
                    return self.send_json(200, r)
                except ValueError as e:
                    return self.send_json(400, {"error": str(e)})
            if path == "/api/models/insights":
                return self.send_json(200, model_insights(refresh))
            if path == "/api/webui":
                return self.send_json(200, webui_status())
            if path == "/api/models":
                code, data = ollama_json("GET", "/api/tags")
                if code == 200 and isinstance(data.get("models"), list):
                    data["models"] = [m for m in data["models"] if not modelupdate.is_prev(m.get("name", ""))]   # copies de sécurité des mises à jour : cachées
                return self.send_json(code, data)
            if path == "/api/users":
                return self.send_json(200, {"users": public_users()})
            if path == "/api/ollama-env":
                env = read_env()
                return self.send_json(200, {"settings": [{"key": k, "label": lbl, "value": env.get(k, "")} for k, lbl in ENV_KEYS]})
            if path == "/api/metrics":
                return self.send_json(200, metrics_view((query.get("span") or ["3600"])[0]))
            if path == "/api/requests/settings":
                return self.send_json(200, reqlog_settings())
            if path == "/api/fleet/balance":
                return self.send_json(200, balance_view())
            if path == "/api/requests":
                return self.send_json(200, requests_view((query.get("limit") or ["200"])[0]))
            if path == "/api/usage":
                return self.send_json(200, usage_view((query.get("span") or ["86400"])[0]))
            if path == "/api/prom":
                return self.send_json(200, prom_status())
            if path == "/api/gpu/guard":
                return self.send_json(200, guard_status())
            if path == "/api/perf":
                return self.send_json(200, perf_view())
            if path == "/api/lab":
                return self.send_json(200, lab_view())
            if path == "/api/mu":
                return self.send_json(200, mu_view())
            if path == "/api/mu/check":
                return self.send_json(200, {"models": mu_check()})
            if path == "/api/audit":
                return self.send_json(200, audit_view(query))
            if path == "/api/audit/export":
                one = lambda k: (query.get(k) or [""])[0]
                return self.send_blob(audit.to_csv(audit.search(audit_entries(), one("q"), one("user"), one("status"))).encode("utf-8-sig"), "audit-ollamabuntu-%s.csv" % time.strftime("%Y%m%d-%H%M"))
            if path == "/api/report":
                obj, text, _ = report.build(report_data())
                return self.send_json(200, {"config": report_config(), "preview": obj, "text": text, "last_error": _report["last_error"],
                                            "smtp": bool(load_alerts()["smtp"].get("host") and load_alerts()["smtp"].get("to"))})
            if path == "/api/models/disk":
                try:
                    days = max(1, min(365, int((query.get("days") or ["30"])[0])))
                except ValueError:
                    days = 30
                return self.send_json(200, models_disk(days))
            if path == "/api/hw":
                return self.send_json(200, hw_view(0 if (query.get("refresh") or [""])[0] == "1" else 120))
            if path == "/api/requests/export":
                reqs = read_requests()
                q = {k: (query.get(k) or [""])[0].strip().lower() for k in ("q", "model", "client", "status")}
                if q["q"]:   # recherche libre : modèle, client, point d'API, extrait de la demande
                    reqs = [r for r in reqs if any(q["q"] in str(r.get(f) or "").lower() for f in ("model", "client", "path", "prompt"))]
                if q["model"]:
                    reqs = [r for r in reqs if q["model"] in str(r.get("model") or "").lower()]
                if q["client"]:
                    reqs = [r for r in reqs if q["client"] in str(r.get("client") or "").lower()]
                if q["status"] in ("ok", "error"):
                    reqs = [r for r in reqs if (r.get("status") == 200 and not r.get("aborted")) == (q["status"] == "ok")]
                print("journal des requêtes exporté par %s (%d lignes)" % (user, len(reqs)), flush=True)
                body = ("\ufeff" + usage.to_csv(reqs)).encode("utf-8")   # BOM : Excel lit l'UTF-8
                return self.send_head(200, "text/csv; charset=utf-8", len(body),
                                      {"Content-Disposition": 'attachment; filename="requetes-%s.csv"' % time.strftime("%Y%m%d-%H%M")}) or self.wfile.write(body)
            if path == "/api/logs/live":
                return self.send_json(200, logs_since((query.get("source") or ["ollama"])[0], (query.get("after") or [""])[0]))
            if path == "/api/logs":
                src = LOG_SOURCES.get((query.get("source") or ["ollama"])[0], LOG_SOURCES["ollama"])
                text = tail(src) if isinstance(src, str) else run(src, timeout=15)
                return self.send_json(200, {"text": text or "(vide)"})
            if path == "/api/jobs":
                return self.send_json(200, {"jobs": list_jobs()})
            m = re.fullmatch(r"/api/jobs/([A-Za-z0-9-]+)", path)
            if m:
                if role != "admin":
                    return self.forbidden()
                st = job_status(m.group(1))
                return self.send_json(200 if st else 404, st or {"error": "tâche inconnue"})
        except OSError as e:
            return self.send_json(502, {"error": "Ollama injoignable : %s" % e})
        return self.send_json(404, {"error": "introuvable"})

    # -- POST
    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if self.headers.get("X-OB") != "1":
            return self.send_json(403, {"error": "requête refusée"})
        limit = MAX_BODY
        if path == "/api/rag/upload":   # gros corps : seulement pour un administrateur connecté (vérifié AVANT de lire)
            sess = session_get(self.token())
            if not sess or sess[1] != "admin":
                self.close_connection = True
                return self.send_json(401 if not sess else 403, {"error": "authentification requise" if not sess else "Réservé aux administrateurs."})
            limit = MAX_UPLOAD_BODY
        try:
            data = self.read_json(limit)
        except ValueError as e:
            return self.send_json(400, {"error": str(e)})
        if path == "/api/login":
            return self.login(data)
        if path == "/api/fleet/action":   # console principale (jeton de gestion centralisée)
            try:
                c = member_auth(self.headers, self.client_address[0])
                job = member_action(str(data.get("action", "")), c, data.get("data"))
            except PermissionError as e:
                return self.send_json(e.args[0], {"error": e.args[1]})
            except ValueError as e:
                return self.send_json(400, {"error": str(e)})
            print("gestion centralisée : action %s demandée par « %s »" % (data.get("action"), c["name"]), flush=True)
            if isinstance(job, dict):
                return self.send_json(200, dict(job, ok=True))
            return self.send_json(200, {"ok": True, "job": job})
        if path.startswith("/api/fleet/ollama/"):
            return self.fleet_proxy("POST", path, data)
        sess = session_get(self.token())
        if not sess:
            return self.send_json(401, {"error": "authentification requise"})
        user, role = sess
        if not audit.skipped(path):
            self._audit = (user, role, path, data)
        try:
            if path == "/api/logout":
                return self.logout()
            if path == "/api/password":
                return self.change_own_password(user, data)
            if path == "/api/chat":
                return self.chat(data)
            if path == "/api/rag/search":   # tout utilisateur connecté, comme la conversation
                return self.send_json(200, rag_search(data))
            if role != "admin":
                return self.forbidden()
            if path == "/api/rag/upload":
                return self.send_json(200, {"ok": True, "id": rag_upload(data)})
            if path == "/api/rag/delete":
                rag_delete(data.get("id"))
                return self.send_json(200, {"ok": True})
            if path == "/api/rag/reindex":
                return self.send_json(200, {"ok": True, "ids": rag_reindex(data.get("id"))})
            if path == "/api/rag/config":
                return self.send_json(200, {"ok": True, "config": rag_save(data)})
            if path == "/api/models/pull":
                name = str(data.get("name", "")).strip()
                if not MODEL_RE.match(name):
                    return self.send_json(400, {"error": "nom de modèle invalide"})
                with egress_window():
                    return self.stream("/api/pull", {"model": name, "stream": True})
            if path == "/api/models/delete":
                name = str(data.get("name", "")).strip()
                if not MODEL_RE.match(name):
                    return self.send_json(400, {"error": "nom de modèle invalide"})
                code, res = ollama_json("DELETE", "/api/delete", {"model": name, "name": name})
                return self.send_json(code, res if code != 200 else {"ok": True})
            if path == "/api/action":
                return self.action(user, data)
            if path in ("/api/update/online/check", "/api/update/online/config"):
                return self.online_update(path, user, data)
            if path in ("/api/publication", "/api/publication/keys/create", "/api/publication/keys/update", "/api/publication/keys/delete"):
                if path == "/api/publication":
                    set_publication(data); res = {"ok": True}
                elif path.endswith("/create"):
                    token, key = key_create(data); res = {"ok": True, "key": key, "token": token}
                elif path.endswith("/update"):
                    key_update(data); res = {"ok": True}
                else:
                    key_delete(str(data.get("id", ""))); res = {"ok": True}
                print("publication API Ollama : %s %s (par %s)" % (path, json.dumps(data, ensure_ascii=False)[:200], user), flush=True)
                return self.send_json(200, res)
            if path.startswith("/api/fleet/") and role != "admin":
                return self.forbidden()
            if path == "/api/fleet/member/create":
                return self.send_json(200, {"ok": True, "token": member_create(data.get("name")), "fingerprint": own_fingerprint()})
            if path == "/api/fleet/member/revoke":
                member_revoke(str(data.get("id", "")))
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/servers/probe":
                return self.send_json(200, fleet_probe(data.get("url")))
            if path == "/api/fleet/servers/add":
                return self.send_json(200, {"ok": True, "id": fleet_add(data)})
            if path == "/api/fleet/servers/action":
                return self.send_json(200, {"ok": True, "result": fleet_action(str(data.get("id", "")), str(data.get("action", "")))})
            if path == "/api/fleet/servers/sync":
                return self.send_json(200, {"ok": True, "results": fleet_sync(str(data.get("id", "")), data.get("kinds"))})
            if path == "/api/fleet/servers/route":
                fleet_set_route(str(data.get("id", "")), bool(data.get("enabled")))
                return self.send_json(200, {"ok": True})
            if path == "/api/backup/export":
                blob = backup.export_bytes(ETC, str(data.get("passphrase") or ""), VERSION)
                print("sauvegarde de la configuration exportée par %s" % user, flush=True)
                return self.send_blob(blob, "ollamabuntu-config-%s.obbk" % time.strftime("%Y%m%d-%H%M"))
            if path == "/api/backup/import":
                try:
                    raw = base64.b64decode(str(data.get("data") or ""), validate=True)
                except ValueError:
                    raise ValueError("fichier de sauvegarde illisible")
                meta, files = backup.read_bytes(raw, str(data.get("passphrase") or ""))
                summary = {"version": meta.get("version"), "created": meta.get("created"), "files": sorted(files)}
                if not data.get("apply"):
                    return self.send_json(200, {"ok": True, "applied": False, "summary": summary})
                written = backup.restore(ETC, meta, files)
                print("configuration restaurée par %s : %s" % (user, ", ".join(written)), flush=True)
                return self.send_json(200, {"ok": True, "applied": True, "summary": summary, "job": start_job("config-reload")})
            if path == "/api/audit/clear":
                audit_clear()
                return self.send_json(200, {"ok": True})
            if path == "/api/report/config":
                cfg = report.clean_config(data, report_config())
                c = load_json_file(REPORT_FILE, {})
                c.update(cfg)
                atomic_write(REPORT_FILE, json.dumps(c), 0o644)
                return self.send_json(200, {"ok": True})
            if path == "/api/report/send":
                try:
                    report_send(test=True)
                except (OSError, smtplib.SMTPException) as e:
                    raise ValueError("envoi impossible : %s" % str(e)[:160])
                return self.send_json(200, {"ok": True})
            if path == "/api/perf/profile":
                name = str(data.get("id", ""))
                diff = perf.profile_diff(name, read_env())
                if not data.get("apply"):
                    return self.send_json(200, {"diff": diff})
                if diff:
                    update_env(perf.normalize_env({d["key"]: d["to"] for d in diff}, read_env()))
                    perf_store(event={"t": int(time.time()), "who": user, "text": "Profil « %s » appliqué" % perf.PROFILES[name]["label"], "changes": {d["key"]: d["to"] for d in diff}}, changed=True)
                    lab_autorun("le profil « %s »" % perf.PROFILES[name]["label"], 25)
                return self.send_json(200, {"ok": True, "changed": len(diff)})
            if path == "/api/perf/fix":
                sys_fix(str(data.get("id", "")), data.get("value"))
                return self.send_json(200, {"ok": True})
            if path == "/api/perf/guard":
                mode = data.get("mode")
                if mode not in ("off", "suggest", "auto"):
                    raise ValueError("mode inconnu")
                try:
                    drop = int(data.get("drop_pct", 50))
                except (TypeError, ValueError):
                    raise ValueError("seuil invalide")
                perf_store(guard={"mode": mode, "drop_pct": min(90, max(10, drop))})
                return self.send_json(200, {"ok": True})
            if path == "/api/perf/apply-suggestion":
                res = perf_snapshot()
                if not res or not res.get("fix"):
                    raise ValueError("aucune suggestion en cours")
                changes = perf.normalize_env(res["fix"]["changes"], read_env())
                update_env(changes)
                perf_store(event={"t": int(time.time()), "who": user, "text": res["text"], "changes": changes}, changed=True)
                return self.send_json(200, {"ok": True, "changes": changes})
            if path == "/api/perf/warmup":
                cfg = perf.warmup_clean(data)
                atomic_write(WARMUP_FILE, json.dumps(cfg, ensure_ascii=False), 0o644)
                return self.send_json(200, {"ok": True})
            if path == "/api/perf/warmup/run":
                models = [m for m in data.get("models") or [] if MODEL_RE.match(str(m))][:6]
                if not models:
                    raise ValueError("aucun modèle")
                threading.Thread(target=lambda: [warm_model(m, "manuel (%s)" % user) for m in models], daemon=True).start()
                return self.send_json(200, {"ok": True})
            if path == "/api/bench/run":
                bench_start(data.get("model"), data.get("runs"))
                return self.send_json(200, {"ok": True})
            if path == "/api/mu/config":
                mu_config_set(data.get("config"))
                return self.send_json(200, {"ok": True})
            if path == "/api/mu/run":
                mu_start(data.get("models"), user)
                return self.send_json(200, {"ok": True})
            if path == "/api/mu/rollback":
                mu_rollback(str(data.get("model", "")), user)
                return self.send_json(200, {"ok": True})
            if path == "/api/lab/compare":
                lab_compare_start(data.get("models"), data.get("prompts"), data.get("num_predict"))
                return self.send_json(200, {"ok": True})
            if path == "/api/lab/suite":
                return self.send_json(200, {"ok": True, "id": lab_suite_save(data.get("suite"))})
            if path == "/api/lab/suite/delete":
                lab_suite_delete(str(data.get("id", "")))
                return self.send_json(200, {"ok": True})
            if path == "/api/lab/run":
                lab_eval_start(str(data.get("id", "")), data.get("model"), user)
                return self.send_json(200, {"ok": True})
            if path == "/api/bench/clear":
                atomic_write(BENCH_FILE, json.dumps({"history": []}), 0o600)
                return self.send_json(200, {"ok": True})
            if path == "/api/gpu/guard/config":
                guard_store(auto=bool(data.get("auto")))
                return self.send_json(200, {"ok": True})
            if path == "/api/gpu/guard/repair":
                return self.send_json(200, {"ok": True, "plan": guard_repair_now(user)})
            if path == "/api/prom/token":
                token = prom_token(str(data.get("action", "")))
                print("export Prometheus : %s par %s" % (data.get("action"), user), flush=True)
                return self.send_json(200, {"ok": True, "token": token})
            if path == "/api/alerts/config":
                alerts_save(data)
                return self.send_json(200, {"ok": True})
            if path == "/api/alerts/test":
                cfg = load_alerts()
                res = alerts_send(cfg, [{"state": "alert", "key": "test", "severity": "info", "text": "Message de test d'OllamaBuntu"}], test=True)
                return self.send_json(200, {"ok": True, "results": res or {"aucun canal": "configurez un webhook ou un e-mail"}})
            if path == "/api/tuning/apply":
                tuning_apply(data)
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/rules":
                rules_save(data.get("rules"))
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/check":
                return self.send_json(200, fleet_check(data.get("model")))
            if path == "/api/fleet/servers/modelmap":
                fleet_set_modelmap(str(data.get("id", "")), data.get("map"))
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/servers/remove":
                fleet_remove(str(data.get("id", "")))
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/servers/repin":
                fleet_repin(str(data.get("id", "")), str(data.get("fingerprint", "")))
                return self.send_json(200, {"ok": True})
            if path == "/api/requests/settings":
                return self.send_json(200, {"ok": True, "settings": set_reqlog_settings(data)})
            if path == "/api/requests/clear":
                clear_requests()
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/balance/strategy":
                set_balance_strategy(str(data.get("strategy") or balance_strategy()), data.get("affinity") if "affinity" in data else None)
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/balance/test":
                return self.send_json(200, balance_test(data.get("model")))
            if path == "/api/sso/config":
                sso_save(data)
                return self.send_json(200, {"ok": True, "config": sso_view()})
            if path == "/api/sso/test":
                return self.send_json(200, sso_test(data))
            if path == "/api/costs/config":
                return self.send_json(200, {"ok": True, "config": costs_save(data)})
            if path == "/api/privacy/config":
                return self.send_json(200, {"ok": True, "config": privacy_save(data)})
            if path == "/api/privacy/test":
                return self.send_json(200, privacy_test(data))
            if path == "/api/queue/config":
                return self.send_json(200, {"ok": True, "settings": queue_save(data)})
            if path == "/api/redirects/config":
                return self.send_json(200, {"ok": True, "rules": redirects_save(data)})
            if path == "/api/fit/config":
                return self.send_json(200, {"ok": True, "conf": fit_save_conf(data)})
            if path == "/api/fit/measure-ram":
                return self.send_json(200, {"ok": True, "ram_gbps": fit_measure_ram()})
            if path == "/api/fit/calibrate":
                return self.send_json(200, dict(fit_calibrate(str(data.get("model") or "")), ok=True))
            if path == "/api/fit/apply":
                return self.send_json(200, dict(fit_apply(data), ok=True))
            if path == "/api/llama/install":
                llama_install(str(data.get("backend") or ""))
                return self.send_json(200, {"ok": True})
            if path == "/api/llama/save":
                return self.send_json(200, {"ok": True, "engine": engine_save(data)})
            if path == "/api/llama/action":
                engine_action(str(data.get("id") or ""), str(data.get("action") or ""))
                return self.send_json(200, {"ok": True})
            if path == "/api/llama/delete":
                engine_delete(str(data.get("id") or ""))
                return self.send_json(200, {"ok": True})
            if path == "/api/power/config":
                return self.send_json(200, {"ok": True, "settings": power_save(data)})
            if path == "/api/power/server":
                return self.send_json(200, {"ok": True, "power": fleet_set_power(str(data.get("id", "")), data)})
            if path == "/api/power/wake":
                return self.send_json(200, dict(power_wake(str(data.get("id", "")), "demandé par %s" % user), ok=True))
            if path == "/api/power/sleep":
                return self.send_json(200, dict(power_sleep(str(data.get("id", "")), "demandé par %s" % user, data.get("mode") or None), ok=True))
            if path == "/api/power/member":   # ce serveur : autoriser ou refuser sa mise en veille par la console principale
                return self.send_json(200, {"ok": True, "member": power_member_save(data)})
            if path == "/api/power/wol":      # ce serveur : réveil réseau d'une carte
                power_wol_set(str(data.get("iface", "")), bool(data.get("enable")))
                return self.send_json(200, {"ok": True})
            if path == "/api/models/context":
                set_model_context(data.get("model"), data.get("num_ctx"))
                return self.send_json(200, {"ok": True})
            if path == "/api/models/context/default":
                n = check_ctx(data.get("num_ctx"))
                update_env({"OLLAMA_CONTEXT_LENGTH": str(n) if n else ""})
                return self.send_json(200, {"ok": True})
            if path == "/api/security/policy":
                job = set_policy(data)
                print("politique d'usage de l'IA : %s (par %s)" % (json.dumps(data, ensure_ascii=False)[:300], user), flush=True)
                return self.send_json(200, {"ok": True, "job": job, "policy": policy_view()})
            if path == "/api/models/custom/create":
                return self.send_json(200, {"ok": True, "name": custom_create(data)})
            if path == "/api/models/custom/delete":
                custom_delete(str(data.get("name", "")))
                return self.send_json(200, {"ok": True})
            if path == "/api/models/preload":
                models = set_preload(data.get("models"))
                threading.Thread(target=preload_once, daemon=True).start()
                return self.send_json(200, {"ok": True, "preload": models})
            if path == "/api/security/firewall":
                set_firewall(data, self.client_address[0])
                print("pare-feu : %s (par %s)" % (json.dumps(data, ensure_ascii=False)[:200], user), flush=True)
                return self.send_json(200, {"ok": True, "firewall": firewall_status()})
            if path == "/api/security/updates":
                set_autoupdates(data)
                print("mises à jour automatiques : %s (par %s)" % (json.dumps(data, ensure_ascii=False)[:200], user), flush=True)
                return self.send_json(200, {"ok": True, "updates": autoupdates_status()})
            if path == "/api/jobs/cancel":
                cancel_job(str(data.get("id", "")))
                return self.send_json(200, {"ok": True})
            if path in ("/api/gpu/pools/create", "/api/gpu/pools/update", "/api/gpu/pools/delete", "/api/models/pin", "/api/models/unpin"):
                try:
                    if path == "/api/gpu/pools/create":
                        res = {"ok": True, "id": pool_create(data)}
                    elif path == "/api/gpu/pools/update":
                        pool_update(data); res = {"ok": True}
                    elif path == "/api/gpu/pools/delete":
                        pool_delete(str(data.get("id", ""))); res = {"ok": True}
                    elif path == "/api/models/pin":
                        name = str(data.get("name", "")).strip()
                        if not MODEL_RE.match(name):
                            raise ValueError("nom de modèle invalide")
                        res = {"ok": True, "variant": pin_create(name, data.get("index"))}
                    else:
                        pin_delete(str(data.get("variant", ""))); res = {"ok": True}
                except ValueError as e:
                    return self.send_json(400, {"error": str(e)})
                print("placement GPU : %s %s (par %s)" % (path, json.dumps(data, ensure_ascii=False)[:200], user), flush=True)
                return self.send_json(200, res)
            if path == "/api/models/check":
                name = str(data.get("name", "")).strip()
                if not MODEL_RE.match(name):
                    return self.send_json(400, {"error": "nom de modèle invalide"})
                try:
                    return self.send_json(200, model_check(name))
                except (OSError, ValueError) as e:
                    return self.send_json(502, {"error": "Registre Ollama injoignable : %s" % e})
            if path == "/api/webui/deploy":
                webui_configure(str(data.get("email", "")).strip(), str(data.get("password", "")), str(data.get("name", "")))
                try:
                    return self.send_json(200, {"job": start_job("webui-install")})
                except (OSError, subprocess.SubprocessError) as e:
                    return self.send_json(500, {"error": "impossible de lancer le déploiement : %s" % e})
            if path == "/api/ollama-env":
                return self.set_ollama_env(data)
            if path == "/api/users/create":
                return self.user_create(data)
            if path == "/api/users/update":
                return self.user_update(user, data)
            if path == "/api/users/delete":
                return self.user_delete(user, data)
        except OSError as e:
            return self.send_json(502, {"error": "Ollama injoignable : %s" % e})
        except ValueError as e:
            return self.send_json(400, {"error": str(e)})
        return self.send_json(404, {"error": "introuvable"})

    def login(self, data):
        ip = self.client_address[0]
        if too_many_failures(ip):
            return self.send_json(429, {"error": "Trop de tentatives : réessayez dans quelques minutes."})
        users = load_users()
        if not users:
            return self.send_json(503, {"error": "Aucun compte n'est configuré."})
        name, password = str(data.get("user", "")), str(data.get("password", ""))
        rec = users.get(name)
        local = bool(rec and "hash" in rec)   # un compte SSO n'a pas de mot de passe local
        ok = verify_password(password, rec if local else {"salt": "AAAA", "hash": "AAAA", "iterations": PBKDF2_ITERATIONS}) and local
        via = None
        if not ok and name and not name.startswith(("ldap:", "sso:")) and sso_providers()["ldap"]:
            try:   # compte local absent ou mot de passe différent : on essaie l'annuaire
                name, role, rec = sso_ldap_login(name, password)
                ok, via = True, "ldap"
            except PermissionError as e:
                record_failure(ip)
                audit_record("ldap:" + str(e.args[0])[:40], "", ip, "/api/login", {"via": "ldap", "erreur": "aucun groupe autorisé"}, 403)
                time.sleep(1)
                return self.send_json(403, {"error": "Connexion refusée : votre compte n'appartient à aucun groupe autorisé."})
            except sso.AuthFailed:
                pass
            except ValueError as e:
                sys.stderr.write("SSO LDAP : %s\n" % e)
                audit_record(name, "", ip, "/api/login", {"via": "ldap", "erreur": "annuaire indisponible"}, 503)
        if not ok:
            record_failure(ip)
            audit_record(name or "?", "", ip, "/api/login", {}, 403)
            time.sleep(1)
            return self.send_json(403, {"error": "Identifiant ou mot de passe incorrect."})
        role = rec.get("role", "utilisateur")
        audit_record(name, role, ip, "/api/login", {"via": via} if via else {}, 200)
        token = new_session(name, role, rec.get("rev"))
        cookie = "ob_session=%s; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=%d" % (token, SESSION_TTL)
        return self.send_json(200, {"user": name, "role": role, "version": VERSION}, {"Set-Cookie": cookie})

    def logout(self):
        with _lock:
            _sessions.pop(self.token() or "", None)
        return self.send_json(200, {"ok": True},
                              {"Set-Cookie": "ob_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"})

    def chat(self, data):
        model = str(data.get("model", ""))
        msgs = data.get("messages")
        if not MODEL_RE.match(model) or not isinstance(msgs, list) or not msgs or len(msgs) > 500:
            return self.send_json(400, {"error": "requête de chat invalide"})
        clean = []
        for m in msgs:
            if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant"):
                return self.send_json(400, {"error": "message invalide"})
            clean.append({"role": m["role"], "content": str(m.get("content", ""))})
        req = {"model": model, "messages": clean, "stream": True}
        try:
            n = check_ctx(data.get("num_ctx"))
        except ValueError as e:
            return self.send_json(400, {"error": str(e)})
        if n:
            mx = model_shape(model, None)["max"]
            req["options"] = {"num_ctx": min(n, mx) if isinstance(mx, int) and mx > 0 else n}   # taille choisie pour cette conversation, plafonnée au modèle
        return self.stream("/api/chat", req)

    FLEET_PROXY_PATHS = ("/api/generate", "/api/chat", "/api/embed", "/api/embeddings", "/api/show", "/api/tags", "/api/ps", "/api/version",
                         "/v1/chat/completions", "/v1/completions", "/v1/embeddings", "/v1/models", "/v1/responses", "/v1/messages")

    def fleet_proxy(self, method, path, data):
        """Requête de la console principale (jeton de routage) vers les modèles de ce serveur, via son routeur local :
        groupes de GPU et politique d'usage de l'IA de ce serveur appliqués. Utilisation et consultation uniquement."""
        try:
            member_auth(self.headers, self.client_address[0], scope="route")
        except PermissionError as e:
            return self.send_json(e.args[0], {"error": e.args[1]})
        rest = path[len("/api/fleet/ollama"):]
        if rest not in self.FLEET_PROXY_PATHS:
            return self.send_json(403, {"error": "requête non autorisée par la répartition de charge"})
        host, port = OLLAMA_ADDR.rsplit(":", 1)
        conn = http.client.HTTPConnection(host, int(port), timeout=900)
        try:
            body = json.dumps(data).encode() if data is not None else None
            conn.request(method, rest, body=body, headers={"Content-Type": "application/json"} if body else {})
            resp = conn.getresponse()
        except OSError as e:
            conn.close()
            return self.send_json(502, {"error": "Ollama injoignable sur ce serveur : %s" % e})
        try:
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.getheader("Content-Type", "application/json"))
            self.send_header("X-OllamaBuntu-Node", member_node())
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        finally:
            conn.close()

    def stream(self, path, body):
        conn = ollama_conn(900, OLLAMA_ADDR if path == "/api/chat" else None)
        try:
            conn.request("POST", path, body=json.dumps(body).encode(),
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            self.send_head(resp.status, "application/x-ndjson; charset=utf-8")
            while True:
                line = resp.readline()
                if not line:
                    break
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        finally:
            conn.close()

    def action(self, user, data):
        act = data.get("action")
        if act == "restart-ollama":
            run(["systemctl", "restart", "ollama.service"], timeout=60)
            return self.send_json(200, {"ok": True})
        if act == "expose-api":   # compatibilité : préférer /api/publication
            set_publication({"enabled": bool(data.get("enabled"))})
            return self.send_json(200, {"ok": True, "exposed": ollama_exposed()})
        if act == "enable-igpu":
            update_env({"OLLAMA_IGPU_ENABLE": "1"})
            return self.send_json(200, {"ok": True})
        if act in ("reboot", "poweroff"):
            sys.stderr.write("%s du serveur demandé par %s\n" % ("Redémarrage" if act == "reboot" else "Arrêt", user))
            # --check-inhibitors=no : une session ouverte (console, SSH) ne doit pas bloquer
            # une demande explicite de l'administrateur.
            try:
                r = subprocess.run(["systemctl", "--no-block", "--check-inhibitors=no", act],
                                   capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.SubprocessError) as e:
                return self.send_json(500, {"error": "systemctl : %s" % e})
            if r.returncode != 0:
                return self.send_json(500, {"error": "Le serveur a refusé : %s" % (r.stderr or r.stdout).strip()[:300]})
            return self.send_json(200, {"ok": True})
        if act in ("webui-start", "webui-stop", "webui-restart"):
            r = subprocess.run(["/bin/bash", WEBUI_HELPER, act.split("-")[1]], capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                return self.send_json(500, {"error": (r.stderr or r.stdout).strip()[:300] or "échec"})
            return self.send_json(200, {"ok": True})
        if act == "appliance-rollback":
            name = str(data.get("file") or "")
            if name not in {b["file"] for b in backups_list()}:
                return self.send_json(400, {"error": "sauvegarde inconnue"})
            print("retour arrière demandé par %s : %s" % (user, name), flush=True)
            try:
                return self.send_json(200, {"job": start_job(act, "exec /bin/bash /usr/local/lib/ollamabuntu/rollback.sh restore %s\n" % shlex.quote(os.path.join(APPLIANCE_BACKUPS, name)))})
            except (OSError, subprocess.SubprocessError) as e:
                return self.send_json(500, {"error": "impossible de lancer la tâche : %s" % e})
        if act == "appliance-update-online":   # la version affichée à l'administrateur est celle qui est installée
            tag = str(data.get("tag") or "")
            script = None
            if tag:
                if not updater.TAG_RE.match(tag):
                    return self.send_json(400, {"error": "version invalide"})
                script = "exec /usr/bin/python3 /usr/local/lib/ollamabuntu/admin/updater.py apply --yes --tag %s\n" % shlex.quote(tag)
            print("mise à jour en ligne demandée par %s (%s)" % (user, tag or "dernière version"), flush=True)
            try:
                return self.send_json(200, {"job": start_job(act, script)})
            except (OSError, subprocess.SubprocessError) as e:
                return self.send_json(500, {"error": "impossible de lancer la tâche : %s" % e})
        if act in JOBS:
            try:
                return self.send_json(200, {"job": start_job(act)})
            except (OSError, subprocess.SubprocessError) as e:
                return self.send_json(500, {"error": "impossible de lancer la tâche : %s" % e})
        return self.send_json(400, {"error": "action inconnue"})

    def online_update(self, path, user, data):
        """Mise à jour depuis Internet : réglages et recherche d'une nouvelle version (l'application passe par /api/action)."""
        if path.endswith("/config"):
            try:
                updater.save_config(data)
            except ValueError as e:
                return self.send_json(400, {"error": str(e)})
            print("mise à jour en ligne : réglages modifiés par %s (dépôt %s, canal %s, vérification automatique : %s)" % (
                user, data.get("repo"), data.get("channel"), data.get("auto_check")), flush=True)   # jamais le jeton
            return self.send_json(200, dict(updater.view(), ok=True))
        try:
            with _online_check_lock:   # une recherche à la fois ; deux clics rapprochés ne font qu'un appel à GitHub
                if time.time() - (updater.load_json(updater.STATE_FILE, {}).get("checked_at") or 0) > 5:
                    updater.check()
        except updater.UpdateError as e:
            return self.send_json(200, dict(updater.view(), ok=False, error=str(e)))
        return self.send_json(200, dict(updater.view(), ok=True))

    def set_ollama_env(self, data):
        values = data.get("values")
        if not isinstance(values, dict):
            raise ValueError("paramètres invalides")
        allowed = {k for k, _ in ENV_KEYS}
        changes = {}
        for k, v in values.items():
            v = str(v).strip()
            if k not in allowed or not ENV_VALUE_RE.match(v):
                raise ValueError("valeur refusée pour %s" % k)
            changes[k] = v
        update_env(perf.normalize_env(changes, read_env()))
        return self.send_json(200, {"ok": True})

    # -- comptes
    def change_own_password(self, user, data):
        current, new = str(data.get("current", "")), str(data.get("new", ""))
        with _users_lock:
            users = load_users()
            rec = users.get(user)
            if not rec or not verify_password(current, rec):
                return self.send_json(403, {"error": "Mot de passe actuel incorrect."})
            problem = password_problem(user, new)
            if problem:
                return self.send_json(400, {"error": problem})
            if rec.get("linux"):
                linux_cmd(["chpasswd"], "%s:%s\n" % (user, new))
            rec.update(hash_password(new))
            rec.update(updated=int(time.time()), rev=secrets.token_hex(8))
            save_users(users)
        session_restamp(self.token(), rec["rev"])
        return self.send_json(200, {"ok": True})

    def user_create(self, data):
        name = str(data.get("user", "")).strip()
        password = str(data.get("password", ""))
        role = data.get("role")
        linux = bool(data.get("linux"))
        if not USER_RE.match(name):
            raise ValueError("Identifiant invalide : une minuscule puis lettres, chiffres, « _ » ou « - » (32 max).")
        if role not in ROLES:
            raise ValueError("Rôle invalide.")
        problem = password_problem(name, password)
        if problem:
            raise ValueError(problem)
        with _users_lock:
            users = load_users()
            if name in users:
                raise ValueError("Ce compte existe déjà.")
            if not linux and sys_user(name) and sys_user(name).pw_uid < 1000:
                raise ValueError("Ce nom est réservé à un compte système.")
            if linux:
                linux_create(name, password, role)
            now = int(time.time())
            users[name] = {"role": role, "linux": linux, "created": now, "updated": now, "rev": secrets.token_hex(8),
                           **hash_password(password)}
            save_users(users)
        return self.send_json(200, {"ok": True})

    def user_update(self, me, data):
        name = str(data.get("user", ""))
        with _users_lock:
            users = load_users()
            rec = users.get(name)
            if not rec:
                raise ValueError("Compte inconnu.")
            role = data.get("role")
            if rec.get("sso") and ((role is not None and role != rec.get("role")) or data.get("password")):
                raise ValueError("Compte géré par l'annuaire : le rôle suit les groupes et le mot de passe est celui de l'annuaire.")
            if role is not None and role != rec.get("role"):
                if role not in ROLES:
                    raise ValueError("Rôle invalide.")
                if rec.get("role") == "admin" and sum(1 for r in users.values() if r.get("role") == "admin" and not r.get("sso")) <= 1:
                    raise ValueError("Impossible : il doit rester au moins un administrateur.")
                if name == me:
                    raise ValueError("Vous ne pouvez pas modifier votre propre rôle.")
                if rec.get("linux"):
                    linux_set_role(name, role)
                rec["role"] = role
            password = data.get("password")
            if password:
                password = str(password)
                problem = password_problem(name, password)
                if problem:
                    raise ValueError(problem)
                if rec.get("linux"):
                    linux_cmd(["chpasswd"], "%s:%s\n" % (name, password))
                rec.update(hash_password(password))
            rec.update(updated=int(time.time()), rev=secrets.token_hex(8))   # invalide les sessions de ce compte
            save_users(users)
        if name == me:
            session_restamp(self.token(), rec["rev"])
        return self.send_json(200, {"ok": True})

    def user_delete(self, me, data):
        name = str(data.get("user", ""))
        with _users_lock:
            users = load_users()
            rec = users.get(name)
            if not rec:
                raise ValueError("Compte inconnu.")
            if name == me:
                raise ValueError("Vous ne pouvez pas supprimer votre propre compte.")
            if rec.get("role") == "admin" and not rec.get("sso") and sum(1 for r in users.values() if r.get("role") == "admin" and not r.get("sso")) <= 1:
                raise ValueError("Impossible : il doit rester au moins un administrateur local.")
            if rec.get("linux"):
                linux_delete(name)
            del users[name]
            save_users(users)
            if os.path.exists(os.path.join(ETC, "admin-user")) and read_text(os.path.join(ETC, "admin-user")) == name:
                nxt = next((u for u, r in sorted(users.items()) if r.get("role") == "admin"), "")
                atomic_write(os.path.join(ETC, "admin-user"), nxt + "\n", 0o644)
        return self.send_json(200, {"ok": True})


class Redirect(http.server.BaseHTTPRequestHandler):
    server_version = "OllamaBuntu"
    sys_version = ""

    def log_message(self, *args):
        pass

    def do_GET(self):
        host = self.headers.get("Host") or ""
        if host.startswith("["):
            host = host.split("]")[0] + "]"
        else:
            host = host.split(":")[0]
        if not re.fullmatch(r"[\w.\-]+|\[[0-9A-Fa-f:.]+\]", host or "-"):
            host = socket.gethostname()
        port = "" if HTTPS_PORT == 443 else ":%d" % HTTPS_PORT
        self.send_response(301)
        self.send_header("Location", "https://%s%s/" % (host, port))
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_HEAD = do_GET


def make_server(port, handler):
    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            sys.stderr.write("%s - connexion interrompue : %s\n" % (client_address[0], sys.exc_info()[1]))

    try:
        class Server6(Server):
            address_family = socket.AF_INET6

            def server_bind(self):
                try:
                    self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except OSError:
                    pass
                super().server_bind()

        return Server6(("::", port), handler)
    except OSError:
        return Server(("0.0.0.0", port), handler)


def main():
    # commandes de secours (installation, menu console) : sans démarrer la console web
    if len(sys.argv) > 1 and sys.argv[1] == "--render-firewall":
        sys.stdout.write(render_firewall())
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--firewall-reset":
        cfg = load_firewall()
        cfg.update(enabled=True, admin_allow=[])
        atomic_write(FW_FILE, json.dumps(cfg, indent=1), 0o644)
        ok, msg = apply_firewall(force=True)
        print("Pare-feu : administration (SSH, console) autorisée depuis tous les réseaux - %s" % msg)
        sys.exit(0 if ok else 1)
    load_users()   # migration éventuelle de l'ancien format
    if not (os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)):
        regen_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    httpd = make_server(HTTPS_PORT, Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True, do_handshake_on_connect=False)
    if WEBUI_TLS_PORT:
        start_webui_proxy(ctx)
    if HTTP_PORT:
        try:
            redirect = make_server(HTTP_PORT, Redirect)
            threading.Thread(target=redirect.serve_forever, daemon=True).start()
        except OSError as e:
            sys.stderr.write("redirection HTTP indisponible : %s\n" % e)
    threading.Thread(target=queue_worker, daemon=True).start()
    threading.Thread(target=firewall_worker, daemon=True).start()
    threading.Thread(target=online_update_worker, daemon=True).start()
    threading.Thread(target=preload_worker, daemon=True).start()
    threading.Thread(target=fleet_worker, daemon=True).start()
    threading.Thread(target=power_worker, daemon=True).start()
    threading.Thread(target=metrics_worker, daemon=True).start()
    threading.Thread(target=alerts_worker, daemon=True).start()
    threading.Thread(target=guard_worker, daemon=True).start()
    threading.Thread(target=warmup_worker, daemon=True).start()
    threading.Thread(target=report_worker, daemon=True).start()
    threading.Thread(target=lab_worker, daemon=True).start()
    threading.Thread(target=costs_worker, daemon=True).start()
    threading.Thread(target=mu_worker, daemon=True).start()
    print("OllamaBuntu %s : console d'administration sur le port %d" % (VERSION, HTTPS_PORT), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--set-password":
        set_admin_cli(args[1], sys.stdin.read())
    elif args == ["--regen-cert"]:
        regen_cert()
    elif args == ["--version"]:
        print(VERSION)
    elif args in (["--render-firewall"], ["--firewall-reset"]):
        main()
    elif args == ["--init-autoupdates"]:   # installation : réglages par défaut, sans systemctl (hors ligne)
        files = uu_files(True, "03:30", False, "04:00")
        for path, text in zip((UU_PERIODIC, UU_CONF, UU_TIMER), files):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atomic_write(path, text, 0o644)
        print("mises à jour de sécurité automatiques : chaque jour vers 03:30, sans redémarrage automatique")
    elif not args:
        main()
    else:
        print(__doc__)
        sys.exit(2)
