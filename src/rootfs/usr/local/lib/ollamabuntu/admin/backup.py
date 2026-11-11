#!/usr/bin/env python3
"""OllamaBuntu - sauvegarde et restauration chiffrées de la configuration (comptes, clés d'API, politique, parc, alertes...).
Format : « OBBK1 » + sel (16) + MAC HMAC-SHA256 (32) + chiffrement AES-256-CBC d'openssl (clé dérivée par PBKDF2) ; le MAC
est vérifié avant tout déchiffrement. Contenu : tar.gz de fichiers de la liste blanche, jamais de clés TLS."""
import base64
import grp
import hashlib
import hmac
import io
import json
import os
import subprocess
import tarfile
import time

MAGIC = b"OBBK1"
ITER = 600000
FILES = ["users.json", "publication.json", "ai-policy.json", "custom-models.json", "preload.json", "fleet.json", "alerts.json", "routing-rules.json",
         "model-context.json", "balance.json", "request-log.json", "firewall.json", "update.json", "ollama.env", "sso.json", "queue.json", "costs.json"]
LIMIT_FILE, LIMIT_TOTAL, LIMIT_BLOB = 1024 * 1024, 5 * 1024 * 1024, 1536 * 1024


class BackupError(ValueError):
    pass


def _check_pass(passphrase):
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise BackupError("phrase secrète trop courte (12 caractères au minimum)")


def _openssl(mode, data, passphrase):
    r, w = os.pipe()
    os.write(w, passphrase.encode() + b"\n")
    os.close(w)
    try:
        p = subprocess.run(["openssl", "enc", mode, "-aes-256-cbc", "-pbkdf2", "-iter", str(ITER), "-pass", "fd:%d" % r],
                           input=data, capture_output=True, pass_fds=(r,), timeout=60)
    finally:
        os.close(r)
    if p.returncode != 0:
        raise BackupError("chiffrement impossible (openssl)")
    return p.stdout


def _mac(passphrase, salt, body):
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt + b"mac", ITER, 32)
    return hmac.new(key, salt + body, hashlib.sha256).digest()


def export_bytes(etc, passphrase, version="?"):
    _check_pass(passphrase)
    buf = io.BytesIO()
    meta = {"version": version, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": {}}
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in FILES:
            path = os.path.join(etc, name)
            try:
                st = os.stat(path)
                with open(path, "rb") as f:
                    raw = f.read(LIMIT_FILE + 1)
            except OSError:
                continue
            if len(raw) > LIMIT_FILE:
                raise BackupError("fichier trop volumineux : %s" % name)
            try:
                group = grp.getgrgid(st.st_gid).gr_name
            except KeyError:
                group = ""
            meta["files"][name] = {"mode": st.st_mode & 0o777, "group": group}
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.mtime = len(raw), 0o600, int(st.st_mtime)
            tf.addfile(ti, io.BytesIO(raw))
        m = json.dumps(meta).encode()
        ti = tarfile.TarInfo("manifest.json")
        ti.size, ti.mode, ti.mtime = len(m), 0o600, int(time.time())
        tf.addfile(ti, io.BytesIO(m))
    salt = os.urandom(16)
    body = _openssl("-e", buf.getvalue(), passphrase)
    return MAGIC + salt + _mac(passphrase, salt, body) + body


def read_bytes(blob, passphrase):
    """Contenu déchiffré et validé : (manifeste, {nom: octets}). Aucune écriture."""
    _check_pass(passphrase)
    if len(blob) > LIMIT_BLOB:
        raise BackupError("fichier de sauvegarde trop volumineux")
    if len(blob) < len(MAGIC) + 48 + 16 or not blob.startswith(MAGIC):
        raise BackupError("ce n'est pas une sauvegarde OllamaBuntu")
    salt, mac, body = blob[5:21], blob[21:53], blob[53:]
    if not hmac.compare_digest(mac, _mac(passphrase, salt, body)):
        raise BackupError("phrase secrète incorrecte ou sauvegarde altérée")
    plain = _openssl("-d", body, passphrase)
    files, total, meta = {}, 0, None
    try:
        with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tf:
            for ti in tf.getmembers():
                if not ti.isfile() or ti.size > LIMIT_FILE or "/" in ti.name or ti.name not in FILES + ["manifest.json"]:
                    raise BackupError("contenu inattendu dans la sauvegarde : %s" % ti.name[:60])
                total += ti.size
                if total > LIMIT_TOTAL:
                    raise BackupError("sauvegarde trop volumineuse une fois décompressée")
                data = tf.extractfile(ti).read()
                if ti.name == "manifest.json":
                    meta = json.loads(data)
                else:
                    files[ti.name] = data
    except (tarfile.TarError, EOFError, OSError) as e:
        raise BackupError("sauvegarde illisible : %s" % e)
    if not isinstance(meta, dict) or not files:
        raise BackupError("sauvegarde vide ou sans manifeste")
    for name, raw in files.items():
        if name.endswith(".json"):
            try:
                json.loads(raw)
            except ValueError:
                raise BackupError("fichier JSON invalide : %s" % name)
    return meta, files


def restore(etc, meta, files, atomic_write_bytes=None):
    """Écrit les fichiers (de façon atomique) en conservant, s'ils existent, droits et groupe actuels."""
    written = []
    for name, raw in files.items():
        path = os.path.join(etc, name)
        info = (meta.get("files") or {}).get(name) or {}
        mode, gid = int(info.get("mode", 0o600)) & 0o777, None
        try:
            st = os.stat(path)
            mode, gid = st.st_mode & 0o777, st.st_gid
        except OSError:
            if info.get("group"):
                try:
                    gid = grp.getgrnam(info["group"]).gr_gid
                except KeyError:
                    gid = None
        tmp = path + ".restore"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.chmod(tmp, mode)
        if gid is not None and os.geteuid() == 0:
            os.chown(tmp, 0, gid)
        os.replace(tmp, path)
        written.append(name)
    return written


def b64(data):
    return base64.b64encode(data).decode()
