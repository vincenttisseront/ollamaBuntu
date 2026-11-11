#!/usr/bin/env python3
"""Sauvegarde chiffrée de la configuration, sauvegardes avant mise à jour, adaptation des quantifications à la VRAM."""
import io, json, os, sys, tarfile, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import backup, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a); return False
    except backup.BackupError: return True
PW = "une-phrase-secrete-longue"
etc = tempfile.mkdtemp()
open(os.path.join(etc, "users.json"), "w").write(json.dumps({"users": {"admin": {"hash": "h"}}})); os.chmod(os.path.join(etc, "users.json"), 0o600)
open(os.path.join(etc, "ollama.env"), "w").write("OLLAMA_NUM_PARALLEL=2\n"); os.chmod(os.path.join(etc, "ollama.env"), 0o644)
os.makedirs(os.path.join(etc, "tls")); open(os.path.join(etc, "tls", "key.pem"), "w").write("SECRET-TLS")
open(os.path.join(etc, "pools.json"), "w").write("{}")

blob = backup.export_bytes(etc, PW, "2026.11.10-1055")
ok(blob.startswith(b"OBBK1") and b"admin" not in blob and b"OLLAMA_NUM" not in blob, "sauvegarde chiffrée : aucun contenu lisible")
meta, files = backup.read_bytes(blob, PW)
ok(sorted(files) == ["ollama.env", "users.json"] and meta["version"] == "2026.11.10-1055", "relecture : seuls les fichiers de la liste blanche (ni clés TLS, ni groupes de GPU)")
ok(raises(backup.read_bytes, blob, "mauvaise-phrase-secrete") , "mauvaise phrase secrète refusée (MAC vérifié avant déchiffrement)")
bad = bytearray(blob); bad[-5] ^= 1
ok(raises(backup.read_bytes, bytes(bad), PW), "sauvegarde altérée refusée")
ok(raises(backup.read_bytes, b"n'importe quoi" * 20, PW) and raises(backup.export_bytes, etc, "court") and raises(backup.read_bytes, blob, "court"), "format inconnu et phrase trop courte refusés")
ok(raises(backup.read_bytes, blob + b"x" * (2 * 1024 * 1024), PW), "fichier trop volumineux refusé")

# archive piégée, correctement chiffrée : doit être refusée au contenu
def forged(name, data=b"{}"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        ti = tarfile.TarInfo(name); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        m = json.dumps({"files": {}}).encode(); ti = tarfile.TarInfo("manifest.json"); ti.size = len(m); tf.addfile(ti, io.BytesIO(m))
    salt = os.urandom(16); body = backup._openssl("-e", buf.getvalue(), PW)
    return backup.MAGIC + salt + backup._mac(PW, salt, body) + body
ok(raises(backup.read_bytes, forged("../../etc/passwd"), PW) and raises(backup.read_bytes, forged("/etc/shadow"), PW) and raises(backup.read_bytes, forged("tls/key.pem"), PW), "noms hors liste blanche ou chemins dangereux refusés")
ok(raises(backup.read_bytes, forged("users.json", b"pas du json"), PW), "JSON invalide refusé")

dest = tempfile.mkdtemp(); open(os.path.join(dest, "users.json"), "w").write("{}"); os.chmod(os.path.join(dest, "users.json"), 0o640)
written = backup.restore(dest, meta, files)
ok(sorted(written) == ["ollama.env", "users.json"] and json.load(open(os.path.join(dest, "users.json")))["users"]["admin"], "restauration : contenu écrit")
ok(oct(os.stat(os.path.join(dest, "users.json")).st_mode & 0o777) == "0o640" and oct(os.stat(os.path.join(dest, "ollama.env")).st_mode & 0o777) == "0o644", "droits existants conservés, droits de la sauvegarde pour les nouveaux fichiers")
ok(not [f for f in os.listdir(dest) if f.endswith(".restore")], "aucun fichier temporaire")

# sauvegardes avant mise à jour
bk = tempfile.mkdtemp(); server.APPLIANCE_BACKUPS = bk
for nm in ("appliance-2026.11.06-1509-20261110-105500.tar.gz", "appliance-2026.10.01-0800-20261001-080500.tar.gz", "autre.tar.gz", "appliance-x-123.tar.gz"):
    open(os.path.join(bk, nm), "w").write("x")
b = server.backups_list(); ok([x["version"] for x in b] == ["2026.11.06-1509", "2026.10.01-0800"] and b[0]["stamp"] == "20261110-105500", "sauvegardes listées, la plus récente d'abord, fichiers étrangers ignorés")

# quantifications et VRAM
GB = 1024 ** 3
q = server.hf_fit([{"size": 2 * GB}, {"size": 7 * GB}, {"size": 20 * GB}, {"size": 200 * GB}], 8 * GB, 16 * GB)
ok([x["fit"] for x in q] == ["gpu", "partial", "no", "no"], "8 Go de VRAM + 16 Go de RAM : 2 Go tient, 7 Go déborde, 20 Go et 200 Go trop gros")
q = server.hf_fit([{"size": 2 * GB}, {"size": 30 * GB}], 0, 16 * GB)
ok([x["fit"] for x in q] == ["partial", "no"], "sans GPU : jugé sur la mémoire du serveur (jamais « gpu »)")
