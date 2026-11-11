#!/usr/bin/env python3
"""Routeur : une clé d'API expirée est refusée (401) par rights(), avec la vraie lecture de publication.json."""
import hashlib, json, os, sys, tempfile, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp()
os.environ.update(OB_ETC=tmp)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import router
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)

def key(name, token, **kw):
    return dict({"id": name, "name": name, "hash": hashlib.sha256(token.encode()).hexdigest(), "perms": ["inference"], "models": [], "enabled": True}, **kw)
today = time.strftime("%Y-%m-%d"); past = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400)); future = time.strftime("%Y-%m-%d", time.localtime(time.time() + 3 * 86400))
pub = {"enabled": True, "auth": True, "allow": [], "keys": [key("vieille", "t_old", expires=past), key("aujourdhui", "t_today", expires=today), key("future", "t_future", expires=future), key("sans", "t_none"), key("vide", "t_empty", expires="")]}
open(os.path.join(tmp, "publication.json"), "w").write(json.dumps(pub))
router.PUB_FILE = os.path.join(tmp, "publication.json")

class H:   # contexte minimal pour Router.rights
    class server: public = True
    client_address = ("10.1.2.3", 1234)
    def __init__(self, token): self.headers = {"Authorization": "Bearer " + token} if token else {}
def rights(token):
    try:
        return router.Router.rights(H(token))
    except PermissionError as e:
        return e.args
ok(rights("t_old")[0] == 401 and "expirée" in rights("t_old")[1] and past in rights("t_old")[1], "clé expirée : 401 avec la date dans le message")
ok(rights("t_today")[0] == "aujourdhui", "clé expirant aujourd'hui : encore valable jusqu'à la fin du jour")
ok(rights("t_future")[0] == "future" and rights("t_none")[0] == "sans" and rights("t_empty")[0] == "vide", "échéance future, absente ou vide : acceptée")
ok(rights("t_inconnu")[0] == 401 and "invalide" in rights("t_inconnu")[1], "clé inconnue : message distinct de « expirée »")
print("\n%d vérifications réussies" % n)
