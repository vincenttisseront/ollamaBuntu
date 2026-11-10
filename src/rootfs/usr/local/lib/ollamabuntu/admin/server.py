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
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import updater  # noqa: E402  mise à jour depuis Internet (GitHub)

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
    return [{"user": u, "role": r.get("role", "utilisateur"), "linux": bool(r.get("linux")),
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


def ollama_log_text(unit="ollama.service"):
    if OLLAMA_LOG_DIR:
        return read_text(os.path.join(OLLAMA_LOG_DIR, unit + ".log"))
    if OLLAMA_LOG_FILE and unit == "ollama.service":
        return read_text(OLLAMA_LOG_FILE)
    return run(["journalctl", "-u", unit, "-b", "-n", "5000", "--no-pager", "-o", "cat"], timeout=15)


def ollama_discovery(unit="ollama.service"):
    """Dernière détection de matériel faite par une instance Ollama (journal du démarrage en cours)."""
    return parse_discovery(ollama_log_text(unit))


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
    usage = load_json_file(ROUTER_USAGE, {})
    keys = [{k: v for k, v in key.items() if k != "hash"} | {"usage": usage.get(key.get("id"), {})} for key in pub.get("keys", [])]
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
        pub["keys"].append(key)
        save_publication(pub)   # le routeur relit le fichier : aucune interruption
    return token, {k: v for k, v in key.items() if k != "hash"}


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
    return {"fingerprint": own_fingerprint(), "last_sync": load_json_file(FLEET_MEMBER, {}).get("last_sync"),
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
    return dict(s, firewall_active=fw["active"], autoupdates=au["enabled"], node=member_node(),
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
        local = sorted({short_name(m.get("name", "")) for m in ollama_json("GET", "/api/tags", timeout=3)[1].get("models", [])
                        if not re.search(r"-gpu\d+$", m.get("name", ""))})
    except (OSError, ValueError):
        local = []
    return {"servers": out, "actions": FLEET_ACTIONS, "sync_kinds": SYNC_KINDS, "local_models": local}


FLEET_ROUTES = os.path.join(ETC, "fleet-routes.json")


def fleet_sync(sid, kinds):
    kinds = [k for k in kinds or [] if k in SYNC_KINDS]
    if not kinds:
        raise ValueError("choisissez au moins un élément à synchroniser")
    payload = {}
    if "policy" in kinds:
        payload["policy"] = {k: v for k, v in load_policy().items() if k in ("cloud", "ollama_internet", "webui_locked", "webui")}
    if "keys" in kinds:   # empreintes seulement : les clés elles-mêmes ne sont jamais conservées
        payload["keys"] = [{k: v for k, v in key.items() if k in ("id", "name", "hash", "prefix", "perms", "models", "deny", "enabled", "created")}
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
        payload["models"] = [n for n in names if n not in custom and not re.search(r"-gpu\d+$", n)]
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
    for s in load_fleet():
        st = _fleet_state.get(s["id"]) or {}
        d = st.get("data") or {}
        if not s.get("route_token"):
            continue
        servers.append({"id": s["id"], "name": s["name"], "url": s["url"], "fingerprint": s["fingerprint"], "token": s["route_token"],
                        "online": st.get("state") == "en ligne", "models": d.get("model_tags", []), "model_map": s.get("model_map") or {},
                        "loaded": [m.get("name") for m in (d.get("ollama") or {}).get("running", [])],
                        "load": avg_load(d.get("gpu_live"), (d.get("cpu") or {}).get("usage"))})
    try:
        running = [m.get("name") for m in ollama_json("GET", "/api/ps", timeout=3, addr=OLLAMA_ADDR)[1].get("models", [])]
    except (OSError, ValueError):
        running = []
    last = (list(_metrics["samples"]) or [{}])[-1]
    local = {"load": avg_load(gpu_metrics(), last.get("cpu")), "loaded": running}   # même mesure que les serveurs distants : GPU, sinon processeur
    text = json.dumps({"local": local, "servers": servers, "updated": int(time.time())}, ensure_ascii=False)
    if read_text(FLEET_ROUTES) != text:
        atomic_write(FLEET_ROUTES, text, 0o640)
        gid = ollama_group_id()
        if gid is not None and os.geteuid() == 0:
            os.chown(FLEET_ROUTES, 0, gid)   # lisible par le routeur (utilisateur ollama), pas par les autres


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
        gpus[g["pci"]] = {"u": g.get("util"), "m": round(100.0 * g["mem_used"] / g["mem_total"], 1) if g.get("mem_total") else None}
    reqs = [r for r in new_requests() if r.get("status") == 200]
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
                       "m": avg([x["gpus"][pci]["m"] for x in xs if pci in x.get("gpus", {}) and x["gpus"][pci]["m"] is not None])}
        series.append({"t": int(sum(x["t"] for x in xs) / len(xs)), "cpu": avg([x["cpu"] for x in xs if x["cpu"] is not None]),
                       "mem": avg([x["mem"] for x in xs if x["mem"] is not None]), "gpus": gp,
                       "rpm": round(sum(x["req"] for x in xs) * 60.0 / dur, 2), "tok_s": round(sum(x["tok"] for x in xs) / dur, 2),
                       "tps": avg([x["tps"] for x in xs if x["tps"] is not None]), "ttft": avg([x["ttft"] for x in xs if x["ttft"] is not None])})
    return {"span": span, "interval": METRICS_EVERY, "gpus": names, "series": series}


def requests_view(limit=200):
    lines = []
    for path in (REQ_LOG + ".1", REQ_LOG):
        try:
            with open(path, "rb") as f:
                f.seek(max(0, os.path.getsize(path) - 2 * 1024 * 1024))
                lines += f.read().split(b"\n")[1:] if f.tell() > 0 else f.read().split(b"\n")
        except OSError:
            continue
    reqs = []
    for line in lines[-5000:]:
        try:
            reqs.append(json.loads(line))
        except ValueError:
            continue
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


def set_balance_strategy(value):
    if value not in BALANCE_STRATEGIES:
        raise ValueError("stratégie inconnue")
    atomic_write(BALANCE_FILE, json.dumps({"strategy": value}), 0o644)


def balance_view():
    """Pourquoi un serveur du parc est (ou n'est pas) utilisé par la répartition de charge."""
    try:
        tags = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
    except (OSError, ValueError):
        tags = []
    local = sorted({short_name(m.get("name", "")) for m in tags})
    served = {}
    for r in read_request_log(time.time() - 86400):
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
                        "models": len(names), "common": len(common), "served": sv.get("count", 0), "last": sv.get("last") or None, "issues": issues})
    loc = served.get("", {})
    return {"strategy": balance_strategy(), "local": {"models": len(local), "served": loc.get("count", 0), "last": loc.get("last") or None},
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
            "secure_boot": secure_boot, "reboot_required": reboot_required, "discovered": bool(used)}


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


def model_insights(refresh=False):
    if refresh:
        for k in [k for k in _cache if k.startswith("reg|")]:
            _cache.pop(k, None)
    cap, current = capacity(), ollama_version()
    try:
        installed = ollama_json("GET", "/api/tags", timeout=10)[1].get("models", [])
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
        local, local_sha = local_manifest(m["name"])
        if r is None and not any(m["name"] in e for e in errors):
            upd = {"state": "local", "label": "Absent du registre (modèle local ou personnalisé)"}
        elif r is None:
            upd = {"state": "inconnu", "label": "Registre injoignable"}
        elif r.get("cloud"):
            upd = {"state": "cloud", "label": "Modèle cloud"}
        elif r["digest"] in (m.get("digest"), local_sha):
            upd = {"state": "a_jour", "label": "À jour"}
        else:
            have = set()
            if local:
                have = {l.get("digest") for l in local.get("layers", [])} | {(local.get("config") or {}).get("digest")}
            missing = [d for d in r["layers"] if d not in have]
            if local and not missing:
                upd = {"state": "a_jour", "label": "À jour"}
            else:
                dl = sum(r["sizes"].get(d, 0) for d in missing)
                upd = {"state": "maj", "label": "Mise à jour disponible (%.1f Go à télécharger)" % (dl / 1e9), "download": dl}
        inst_out.append({"name": m["name"], "size": m.get("size", 0), "details": m.get("details", {}),
                         "modified_at": m.get("modified_at"), "update": upd,
                         "fit": assess_fit(m.get("size", 0), cap, (r or {}).get("requires"), current)})
    have_names = {short_name(m["name"]) for m in installed}
    cat_out = []
    for c in catalog:
        r = remote.get(c["name"])
        item = dict(c, installed=short_name(c["name"]) in have_names)
        if r and not r.get("cloud"):
            item.update(available=True, size=r["size"], vision=r["vision"], draft=r["draft"], params=r["params"],
                        quant=r["quant"], fit=assess_fit(r["size"], cap, r.get("requires"), current))
        else:
            item.update(available=False, fit=None)
        cat_out.append(item)
    order = {"gpu": 0, "cpu": 1, "mixte": 2, "trop": 3, "incompatible": 4, None: 5}
    cat_out.sort(key=lambda c: (order[(c.get("fit") or {}).get("level")], c.get("size") or 0))
    return {"capacity": cap, "ollama": current, "installed": inst_out, "catalog": cat_out,
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
             "/api/updates", "/api/models/insights", "/api/webui", "/api/update/online"}


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

    def send_json(self, code, obj, extra=None):
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

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("requête trop volumineuse")
        data = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if not isinstance(data, dict):
            raise ValueError("objet JSON attendu")
        return data

    def token(self):
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return None
        m = jar.get("ob_session")
        return m.value if m else None

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
            if path == "/api/models/insights":
                return self.send_json(200, model_insights(refresh))
            if path == "/api/webui":
                return self.send_json(200, webui_status())
            if path == "/api/models":
                code, data = ollama_json("GET", "/api/tags")
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
        try:
            data = self.read_json()
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
        try:
            if path == "/api/logout":
                return self.logout()
            if path == "/api/password":
                return self.change_own_password(user, data)
            if path == "/api/chat":
                return self.chat(data)
            if role != "admin":
                return self.forbidden()
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
                set_balance_strategy(str(data.get("strategy", "")))
                return self.send_json(200, {"ok": True})
            if path == "/api/fleet/balance/test":
                return self.send_json(200, balance_test(data.get("model")))
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
        ok = verify_password(password, rec or {"salt": "AAAA", "hash": "AAAA", "iterations": PBKDF2_ITERATIONS})
        if not (rec and ok):
            record_failure(ip)
            time.sleep(1)
            return self.send_json(403, {"error": "Identifiant ou mot de passe incorrect."})
        role = rec.get("role", "utilisateur")
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
        update_env(changes)
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
            if role is not None and role != rec.get("role"):
                if role not in ROLES:
                    raise ValueError("Rôle invalide.")
                if rec.get("role") == "admin" and sum(1 for r in users.values() if r.get("role") == "admin") <= 1:
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
            if rec.get("role") == "admin" and sum(1 for r in users.values() if r.get("role") == "admin") <= 1:
                raise ValueError("Impossible : il doit rester au moins un administrateur.")
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
    threading.Thread(target=metrics_worker, daemon=True).start()
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
