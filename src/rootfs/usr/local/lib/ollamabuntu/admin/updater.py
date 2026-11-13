#!/usr/bin/env python3
"""OllamaBuntu - mise à jour de l'appliance depuis Internet (versions publiées sur GitHub).

Bibliothèque standard de Python 3 + openssl (vérification de la signature).

  updater.py check [--json]                      cherche une version plus récente
  updater.py apply [--yes] [--tag vAAAA.MM.JJ-HHMM] [--force]
                                                 télécharge, vérifie, puis applique la mise à jour

Chaîne de confiance : une version publiée = une « release » GitHub contenant
  ollamabuntu-update-<version>.tar.gz   fichiers de l'appliance (même contenu que l'ISO, sans Ollama ni modèles)
  SHA256SUMS                            somme SHA-256 de l'archive
  SHA256SUMS.sig                        signature Ed25519 de SHA256SUMS (clé publique : update-pubkey.pem, livrée avec l'appliance)
L'archive contient aussi la somme SHA-256 de l'archive Ollama officielle : elle est donc couverte par la signature.
Rien n'est appliqué si la signature, une somme ou la version ne correspond pas.
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

ETC = os.environ.get("OB_ETC", "/etc/ollamabuntu")
STATE_DIR = os.environ.get("OB_STATE", "/var/lib/ollamabuntu")
LIB = os.environ.get("OB_LIB", "/usr/local/lib/ollamabuntu")
CACHE_DIR = os.environ.get("OB_UPDATE_CACHE", "/var/cache/ollamabuntu/update")
API = os.environ.get("OB_GITHUB_API", "https://api.github.com").rstrip("/")
OLLAMA_BIN = os.environ.get("OB_OLLAMA_BIN", "/usr/local/bin/ollama")
OLLAMA_LIB = os.environ.get("OB_OLLAMA_LIB", "/usr/local/lib/ollama")
LOCK_FILE = os.environ.get("OB_UPDATE_LOCK", "/run/ollamabuntu-online-update.lock")

CONF_FILE = os.path.join(ETC, "update.json")            # réglages de l'administrateur (jamais écrasés par une mise à jour)
TOKEN_FILE = os.path.join(ETC, "update-token")          # jeton d'accès en lecture (dépôt privé), 0600
DEFAULTS_FILE = os.path.join(LIB, "update-defaults.json")   # valeurs livrées avec l'appliance
PUBKEY_FILE = os.environ.get("OB_UPDATE_PUBKEY", os.path.join(LIB, "update-pubkey.pem"))
STATE_FILE = os.path.join(STATE_DIR, "update-check.json")
VERSION_FILE = os.path.join(ETC, "version")
BUILD_INFO = os.path.join(ETC, "build-info.json")

VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}-\d{4}$")
TAG_RE = re.compile(r"^v(\d{4}\.\d{2}\.\d{2}-\d{4})$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{20,255}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
OLLAMA_VER_RE = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.\-+]{0,30}$")
OLLAMA_URL_PREFIX = "https://github.com/ollama/ollama/releases/download/"
CHANNELS = ("stable", "preview")
BUNDLE_FILES = {"VERSION", "OLLAMA_VERSION", "LANG", "rootfs.tar", "update.sh", "ONLINE",
                "OLLAMA_URL", "OLLAMA_SHA256", "OLLAMA_ROCM_URL", "OLLAMA_ROCM_SHA256"}
MAX_API = 4 << 20
MAX_SMALL = 1 << 20
MAX_BUNDLE = 512 << 20
MAX_OLLAMA = 6 << 30


class UpdateError(Exception):
    """Erreur affichable telle quelle à l'administrateur."""


# ------------------------------------------------------------------ outils ---
def read_text(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def write_file(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def installed_version():
    return read_text(VERSION_FILE, "?").strip() or "?"


def installed_ollama():
    v = str(load_json(BUILD_INFO, {}).get("ollama", "")).split(" ")[0]
    return v


def newer(a, b):
    """a est-il plus récent que b ? (AAAA.MM.JJ-HHMM : l'ordre alphabétique est l'ordre chronologique)"""
    if not VERSION_RE.match(a or ""):
        return False
    return not VERSION_RE.match(b or "") or a > b


_tr_cache = {}


def tr(text):
    """Texte dans la langue de l'appliance (même catalogue que la console web)."""
    lang = read_text(os.path.join(ETC, "lang"), "fr").strip()
    if lang == "fr" or lang not in ("en",):
        return text
    try:
        if "cat" not in _tr_cache:
            import importlib.util
            os.environ.setdefault("OB_I18N_DIR", os.path.join(LIB, "admin", "web", "i18n"))
            spec = importlib.util.spec_from_file_location("ob_i18n", os.path.join(LIB, "i18n.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _tr_cache["cat"] = mod.Catalog(lang)
        return _tr_cache["cat"].text(text, literal_newlines=False)
    except Exception:   # la traduction ne doit jamais empêcher la mise à jour
        return text


def say(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), tr(msg)), flush=True)


# --------------------------------------------------------------- réglages ---
def load_config():
    d = load_json(DEFAULTS_FILE, {})
    c = load_json(CONF_FILE, {})
    repo = c.get("repo") or d.get("repo") or ""
    channel = c.get("channel") or d.get("channel") or "stable"
    return {"repo": repo if REPO_RE.match(repo or "") else "",
            "channel": channel if channel in CHANNELS else "stable",
            "auto_check": bool(c.get("auto_check", d.get("auto_check", False)))}


def token_set():
    return bool(read_text(TOKEN_FILE).strip())


def save_config(data):
    """data : repo, channel, auto_check, token (remplace), clear_token."""
    cur = load_config()
    repo = str(data.get("repo", cur["repo"])).strip()
    if repo.startswith("https://github.com/"):
        repo = repo[len("https://github.com/"):].rstrip("/")
        if repo.endswith(".git"):
            repo = repo[:-4]
    if not REPO_RE.match(repo):
        raise ValueError("dépôt GitHub invalide : attendu « propriétaire/dépôt »")
    channel = str(data.get("channel", cur["channel"]))
    if channel not in CHANNELS:
        raise ValueError("canal inconnu")
    new = {"repo": repo, "channel": channel, "auto_check": bool(data.get("auto_check", cur["auto_check"]))}
    token = data.get("token")
    if token not in (None, ""):
        token = str(token).strip()
        if not TOKEN_RE.match(token):
            raise ValueError("jeton d'accès invalide")
        write_file(TOKEN_FILE, token + "\n", 0o600)
    elif data.get("clear_token"):
        try:
            os.remove(TOKEN_FILE)
        except OSError:
            pass
    write_file(CONF_FILE, json.dumps(new, indent=1) + "\n", 0o644)
    if (repo, channel) != (cur["repo"], cur["channel"]):
        write_file(STATE_FILE, "{}\n", 0o600)   # résultat de l'ancien dépôt : sans objet
    return new


# ------------------------------------------------------------------ réseau ---
def _allowed(url):
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    base = urllib.parse.urlsplit(API)
    if API != "https://api.github.com" and u.scheme == base.scheme and host == (base.hostname or "").lower():
        return True   # essais : faux serveur GitHub local
    return u.scheme == "https" and (host in ("api.github.com", "github.com") or host.endswith(".githubusercontent.com"))


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise UpdateError("redirection refusée vers un hôte non autorisé")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.headers.pop("Authorization", None)   # le jeton ne quitte jamais api.github.com
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def _open(url, token=None, accept="application/vnd.github+json", timeout=30):
    if not _allowed(url):
        raise UpdateError("adresse non autorisée")
    req = urllib.request.Request(url, headers={"User-Agent": "OllamaBuntu-updater", "Accept": accept,
                                               "X-GitHub-Api-Version": "2022-11-28"})
    if token and url.startswith(API + "/"):
        req.add_header("Authorization", "Bearer " + token)
    try:
        return urllib.request.build_opener(_Redirect).open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise UpdateError("Jeton refusé par GitHub.")
        if e.code == 404:
            raise UpdateError("Dépôt ou fichier introuvable sur GitHub (dépôt privé : renseignez un jeton d'accès).")
        if e.code in (403, 429):
            raise UpdateError("Limite de requêtes GitHub atteinte : réessayez plus tard.")
        raise UpdateError("GitHub a répondu par une erreur HTTP %d." % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.stderr.write("mise à jour en ligne : %s\n" % e)
        raise UpdateError("GitHub injoignable : vérifiez l'accès Internet, le proxy et le DNS du serveur.")


def _read_limited(resp, limit):
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("réponse trop volumineuse")
    return data


def _token():
    t = read_text(TOKEN_FILE).strip()
    return t if TOKEN_RE.match(t) else None


# ------------------------------------------------------------- recherche ---
def list_releases(cfg):
    if not cfg["repo"]:
        raise UpdateError("Aucun dépôt GitHub configuré.")
    with _open("%s/repos/%s/releases?per_page=30" % (API, cfg["repo"]), token=_token()) as r:
        try:
            data = json.loads(_read_limited(r, MAX_API))
        except ValueError:
            raise UpdateError("Réponse de GitHub illisible.")
    return data if isinstance(data, list) else []


def pick_release(releases, channel, tag=None):
    best = None
    for r in releases:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        if r.get("prerelease") and channel == "stable" and not tag:
            continue
        m = TAG_RE.match(str(r.get("tag_name", "")))
        if not m or (tag and r.get("tag_name") != tag):
            continue
        ver = m.group(1)
        assets = {}
        for a in r.get("assets") or []:
            if isinstance(a, dict) and isinstance(a.get("name"), str) and a.get("id") and a.get("state", "uploaded") == "uploaded":
                assets[a["name"]] = {"id": int(a["id"]), "size": int(a.get("size") or 0)}
        bundle = "ollamabuntu-update-%s.tar.gz" % ver
        if not all(n in assets for n in (bundle, "SHA256SUMS", "SHA256SUMS.sig")):
            continue
        if best is None or ver > best["version"]:
            html = str(r.get("html_url", ""))
            best = {"version": ver, "tag": r["tag_name"], "name": str(r.get("name") or r["tag_name"])[:120],
                    "notes": str(r.get("body") or "")[:4000], "prerelease": bool(r.get("prerelease")),
                    "published_at": str(r.get("published_at") or "")[:25],
                    "url": html if html.startswith("https://github.com/") else "",
                    "bundle": bundle, "assets": assets}
    return best


def check():
    """Interroge GitHub et mémorise le résultat. Lève UpdateError (état conservé, erreur notée)."""
    cfg = load_config()
    state = load_json(STATE_FILE, {})
    now = int(time.time())
    try:
        rel = pick_release(list_releases(cfg), cfg["channel"])
    except UpdateError as e:
        state.update(checked_at=now, error=str(e), repo=cfg["repo"])
        write_file(STATE_FILE, json.dumps(state, ensure_ascii=False) + "\n", 0o600)
        raise
    state = {"checked_at": now, "error": None, "repo": cfg["repo"], "channel": cfg["channel"],
             "latest": ({k: v for k, v in rel.items() if k != "assets"} if rel else None)}
    write_file(STATE_FILE, json.dumps(state, ensure_ascii=False) + "\n", 0o600)
    return state


def available():
    """Version plus récente connue (dernière vérification), ou None. Sans accès réseau."""
    s = load_json(STATE_FILE, {})
    latest = s.get("latest") or {}
    v = latest.get("version")
    return v if v and newer(v, installed_version()) else None


def view():
    cfg = load_config()
    s = load_json(STATE_FILE, {})
    latest = s.get("latest") or None
    return {"installed": installed_version(), "config": cfg, "token_set": token_set(),
            "checked_at": s.get("checked_at"), "error": s.get("error"), "latest": latest,
            "available": bool(latest and newer(latest.get("version"), installed_version())),
            "signed": os.path.exists(PUBKEY_FILE)}


# ---------------------------------------------------------- téléchargement ---
def _download(url, dest, limit, label, token=None, accept="application/octet-stream", progress=None):
    """Téléchargement vers dest (fichier .part puis renommage), SHA-256 renvoyé."""
    with _open(url, token=token, accept=accept, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        if total > limit:
            raise UpdateError("Fichier trop volumineux (%d Mo) : %s" % (total >> 20, label))
        free = shutil.disk_usage(os.path.dirname(dest)).free
        if total and free < total + (300 << 20):
            raise UpdateError("Espace disque insuffisant : %d Mo libres, %d Mo nécessaires." % (free >> 20, (total + (300 << 20)) >> 20))
        h = hashlib.sha256()
        got, last, t0 = 0, time.time(), time.time()
        part = dest + ".part"
        with open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
                if got > limit:
                    raise UpdateError("Fichier trop volumineux : %s" % label)
                h.update(chunk)
                f.write(chunk)
                if total > (20 << 20) and time.time() - last >= 5:
                    last = time.time()
                    say("      %s : %d %% (%d / %d Mo)" % (label, got * 100 // total, got >> 20, total >> 20))
                    if progress:
                        progress(got, total)
        if total and got != total:
            raise UpdateError("Téléchargement interrompu : %s" % label)
    os.replace(part, dest)
    if total > (20 << 20):
        say("      %s : 100 %% (%d Mo) en %d s" % (label, got >> 20, time.time() - t0))
    return h.hexdigest()


def _asset_url(rel, name):
    return "%s/repos/%s/releases/assets/%d" % (API, load_config()["repo"], rel["assets"][name]["id"])


def verify_signature(sums, sig):
    if not os.path.exists(PUBKEY_FILE):
        raise UpdateError("Clé publique de vérification absente de cette appliance : mise à jour en ligne impossible.")
    try:
        r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", PUBKEY_FILE, "-rawin", "-in", sums, "-sigfile", sig],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise UpdateError("openssl indisponible : signature impossible à vérifier.")
    if r.returncode != 0:
        raise UpdateError("SIGNATURE INVALIDE : la mise à jour n'est pas authentique, elle est refusée.")


def parse_sums(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-f]{64}) [ *]([A-Za-z0-9._-]+)$", line.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_extract(archive, dest):
    """Extrait l'archive de mise à jour : fichiers ordinaires attendus seulement, à plat, sans lien ni chemin relatif."""
    os.makedirs(dest, mode=0o700, exist_ok=True)
    total = 0
    with tarfile.open(archive, "r:gz") as tf:
        for m in tf:
            name = m.name[2:] if m.name.startswith("./") else m.name
            if m.isdir() and name in ("", "."):
                continue
            if not m.isreg() or name not in BUNDLE_FILES:
                raise UpdateError("Archive de mise à jour refusée : contenu inattendu (%s)." % re.sub(r"[^\w./-]", "?", name)[:60])
            total += m.size
            if total > MAX_BUNDLE:
                raise UpdateError("Archive de mise à jour refusée : taille anormale.")
            with tf.extractfile(m) as src, open(os.path.join(dest, name), "wb") as out:
                shutil.copyfileobj(src, out)
            os.chmod(os.path.join(dest, name), 0o755 if name == "update.sh" else 0o644)
    for needed in ("VERSION", "OLLAMA_VERSION", "rootfs.tar", "update.sh", "ONLINE"):
        if not os.path.isfile(os.path.join(dest, needed)):
            raise UpdateError("Archive de mise à jour incomplète (%s absent)." % needed)


def _fetch_ollama(src, kind, url_file, sha_file, label):
    url = read_text(os.path.join(src, url_file)).strip()
    sha = read_text(os.path.join(src, sha_file)).strip().lower()
    if not url.startswith(OLLAMA_URL_PREFIX) or not SHA_RE.match(sha):
        raise UpdateError("Archive de mise à jour invalide : adresse ou somme d'Ollama incorrecte.")
    ext = ".tar.zst" if url.endswith(".tar.zst") else ".tgz" if url.endswith(".tgz") else None
    if not ext:
        raise UpdateError("Archive de mise à jour invalide : format d'Ollama inconnu.")
    dest = os.path.join(src, "ollama-linux-amd64%s%s" % (kind, ext))
    say("      téléchargement : %s" % label)
    got = _download(url, dest, MAX_OLLAMA, label)
    if got != sha:
        os.remove(dest)
        raise UpdateError("Somme SHA-256 incorrecte pour %s : téléchargement refusé." % label)
    say("      %s : somme SHA-256 vérifiée" % label)


# --------------------------------------------------------------- application ---
def apply(tag=None, force=False):
    if os.geteuid() != 0 and not os.environ.get("OB_UPDATE_NO_ROOT_CHECK"):   # variable réservée aux tests
        raise UpdateError("Cette commande doit être lancée en tant que root.")
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise UpdateError("Une mise à jour en ligne est déjà en cours.")
    cfg = load_config()
    cur = installed_version()
    say("OllamaBuntu : mise à jour en ligne depuis github.com/%s (canal %s)" % (cfg["repo"], cfg["channel"]))
    say("[1/5] Recherche de la version publiée")
    rel = pick_release(list_releases(cfg), cfg["channel"], tag)
    if not rel:
        raise UpdateError("Version demandée introuvable." if tag else "Aucune version publiée dans ce dépôt.")
    ver = rel["version"]
    say("      version installée : %s - version publiée : %s%s" % (cur, ver, " (préversion)" if rel["prerelease"] else ""))
    if not newer(ver, cur) and not force:
        say("Déjà à jour : aucune mise à jour à appliquer.")
        return 0
    if not newer(ver, cur):
        say("Attention : version identique ou plus ancienne, appliquée sur demande explicite.")

    work = os.path.join(CACHE_DIR, ver)
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
    os.makedirs(work, mode=0o700)
    token = _token()
    try:
        say("[2/5] Téléchargement et vérification de la signature")
        sums, sig, bundle = (os.path.join(work, n) for n in ("SHA256SUMS", "SHA256SUMS.sig", rel["bundle"]))
        _download(_asset_url(rel, "SHA256SUMS"), sums, MAX_SMALL, "SHA256SUMS", token)
        _download(_asset_url(rel, "SHA256SUMS.sig"), sig, MAX_SMALL, "SHA256SUMS.sig", token)
        verify_signature(sums, sig)
        say("      signature valide")
        expected = parse_sums(read_text(sums)).get(rel["bundle"])
        if not expected:
            raise UpdateError("La somme de l'archive est absente de SHA256SUMS : mise à jour refusée.")
        got = _download(_asset_url(rel, rel["bundle"]), bundle, MAX_BUNDLE, rel["bundle"], token)
        if got != expected:
            raise UpdateError("Somme SHA-256 de l'archive incorrecte : mise à jour refusée.")
        say("      archive %s : somme SHA-256 conforme à la signature" % rel["bundle"])

        say("[3/5] Contrôle du contenu")
        src = os.path.join(work, "src")
        safe_extract(bundle, src)
        os.remove(bundle)
        if read_text(os.path.join(src, "VERSION")).strip() != ver:
            raise UpdateError("La version contenue dans l'archive ne correspond pas à la version publiée : mise à jour refusée.")
        new_ollama = read_text(os.path.join(src, "OLLAMA_VERSION")).strip()
        if not OLLAMA_VER_RE.match(new_ollama):
            raise UpdateError("Archive de mise à jour invalide : version d'Ollama incorrecte.")
        say("      version %s, Ollama %s" % (ver, new_ollama))

        say("[4/5] Ollama")
        old_ollama = installed_ollama()
        if new_ollama != old_ollama or not os.access(OLLAMA_BIN, os.X_OK):
            say("      Ollama %s -> %s" % (old_ollama or "?", new_ollama))
            _fetch_ollama(src, "", "OLLAMA_URL", "OLLAMA_SHA256", "Ollama %s" % new_ollama)
            if os.path.isdir(OLLAMA_LIB) and any(n.startswith("rocm") for n in os.listdir(OLLAMA_LIB)) \
                    and os.path.exists(os.path.join(src, "OLLAMA_ROCM_URL")):
                _fetch_ollama(src, "-rocm", "OLLAMA_ROCM_URL", "OLLAMA_ROCM_SHA256", "Ollama %s (ROCm)" % new_ollama)
        else:
            say("      Ollama %s déjà installé : conservé" % new_ollama)

        say("[5/5] Application de la mise à jour")
        sys.stdout.flush()
        rc = subprocess.call(["/bin/bash", os.path.join(src, "update.sh"), "--target", "/", "--source", src])
        if rc != 0:
            raise UpdateError("L'application de la mise à jour a échoué (code %d) : voir /tmp/ollamabuntu-update.log." % rc)
        return 0
    finally:
        shutil.rmtree(CACHE_DIR, ignore_errors=True)


# --------------------------------------------------------------------- CLI ---
def main(argv):
    if not argv or argv[0] not in ("check", "apply"):
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "check":
            s = check()
            if "--json" in args:
                print(json.dumps(view(), ensure_ascii=False, indent=1))
            else:
                v = available()
                print(tr("Nouvelle version disponible : %s (installée : %s)" % (v, installed_version())) if v
                      else tr("Aucune version plus récente que %s." % installed_version()))
            return 0
        tag, force, yes = None, False, False
        it = iter(args)
        for a in it:
            if a == "--tag":
                tag = next(it, "")
                if not TAG_RE.match(tag):
                    print("tag invalide", file=sys.stderr)
                    return 2
            elif a == "--force":
                force = True
            elif a in ("--yes", "-y"):
                yes = True
            else:
                print(__doc__)
                return 2
        if not yes:
            if input(tr("Mettre à jour l'appliance depuis Internet (les services IA redémarrent) ? [o/N] ")).strip().lower()[:1] not in ("o", "y"):
                return 1
        return apply(tag, force)
    except UpdateError as e:
        print("[%s] %s" % (tr("ERREUR"), tr(str(e))), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
