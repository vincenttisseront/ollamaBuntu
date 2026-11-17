#!/usr/bin/env python3
"""Open WebUI : réinitialisation du mot de passe administrateur depuis la console (script réel, base SQLite temporaire)."""
import os, sys, tempfile, sqlite3
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import server
try:
    import bcrypt
except ImportError:
    print("bcrypt absent : test ignoré (présent dans l'image Open WebUI)"); sys.exit(0)
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(exc, f, *a):
    try: f(*a); return None
    except exc as e: return str(e)

tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "webui.db")
con = sqlite3.connect(db)
con.executescript("CREATE TABLE user (id TEXT PRIMARY KEY, email TEXT, role TEXT, created_at INTEGER);"
                  "CREATE TABLE auth (id TEXT PRIMARY KEY, email TEXT, password TEXT, active INTEGER);")
old = bcrypt.hashpw(b"ancien-secret", bcrypt.gensalt()).decode()
for i, (mail, role, t) in enumerate((("alice@x.fr", "admin", 1), ("bob@x.fr", "user", 2), ("zoe@x.fr", "admin", 3))):
    con.execute("INSERT INTO user VALUES (?,?,?,?)", ("u%d" % i, mail, role, t))
    con.execute("INSERT INTO auth VALUES (?,?,?,1)", ("u%d" % i, mail, old))
con.commit(); con.close()

server.ETC = tmp
server.WEBUI_ENV = os.path.join(tmp, "open-webui.env")
server.webui_exec_cmd = lambda: [sys.executable, "-I", "-c", server.WEBUI_PWD_SCRIPT, db]
def pw(mail):
    c = sqlite3.connect(db); r = c.execute("SELECT password FROM auth WHERE email=?", (mail,)).fetchone()[0]; c.close(); return r
def good(mail, secret): return bcrypt.checkpw(secret.encode(), pw(mail).encode())

ok(raises(ValueError, server.webui_reset_password, "alice@x.fr", "court") is not None, "mot de passe trop court refusé")
ok(raises(ValueError, server.webui_reset_password, "alice@x.fr", "é" * 40) is not None, "plus de 72 octets refusé")
ok(raises(ValueError, server.webui_reset_password, "alice@x.fr", "bon\nmot-de-passe") is not None, "caractère de contrôle refusé")
ok(raises(ValueError, server.webui_reset_password, "pas-un-mail", "nouveau-secret-1") is not None, "adresse invalide refusée")
ok(raises(ValueError, server.webui_reset_password, "alice@x.fr", "nouveau-secret-1") == "Open WebUI n'est pas déployé.", "refusé tant qu'Open WebUI n'est pas déployé")
open(server.WEBUI_ENV, "w").write("WEBUI_ADMIN_EMAIL=alice@x.fr\n")
ok(good("alice@x.fr", "ancien-secret"), "état initial : ancien mot de passe valide")

ok(server.webui_reset_password("bob@x.fr", "Secret-de-Bob-1") == "bob@x.fr" and good("bob@x.fr", "Secret-de-Bob-1"), "compte désigné : nouveau mot de passe valide")
ok(not good("bob@x.fr", "ancien-secret") and good("alice@x.fr", "ancien-secret") and good("zoe@x.fr", "ancien-secret"), "les autres comptes sont inchangés")
ok(pw("bob@x.fr").startswith("$2"), "haché en bcrypt, comme Open WebUI")
ok(server.webui_reset_password("", "Nouveau-Admin-2") == "alice@x.fr" and good("alice@x.fr", "Nouveau-Admin-2"), "sans adresse : premier administrateur")
ok(server.webui_reset_password("ZOE@x.fr", "Casse-Ignoree-3") == "zoe@x.fr" and good("zoe@x.fr", "Casse-Ignoree-3"), "adresse insensible à la casse")
msg = raises(LookupError, server.webui_reset_password, "inconnu@x.fr", "nouveau-secret-1")
ok(msg and "alice@x.fr" in msg and "zoe@x.fr" in msg and "bob@x.fr" not in msg, "compte inconnu : erreur listant les administrateurs")
ok(good("alice@x.fr", "Nouveau-Admin-2"), "compte inconnu : rien n'a été modifié")
ok(server.webui_reset_password("alice@x.fr", "Pa$$'\"; DROP TABLE auth;--") and good("alice@x.fr", "Pa$$'\"; DROP TABLE auth;--"), "caractères spéciaux sans effet de bord")
ok(raises(RuntimeError, (lambda: (setattr(server, "webui_exec_cmd", lambda: ["/bin/false"]), server.webui_reset_password("", "nouveau-secret-1"))[1])) is not None, "conteneur arrêté : erreur claire")
ok("password" in __import__("audit").SECRET_WORDS and __import__("audit").LABELS.get("/api/webui/password"), "mot de passe masqué dans le journal d'audit, action libellée")
print("%d contrôles réussis" % n)
