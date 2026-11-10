import re
import json, ssl, http.client, subprocess, re
ctx = ssl._create_unverified_context(); n = [0]
def req(method, path, body=None, cookie=None):
    c = http.client.HTTPSConnection("127.0.0.1", 18443, context=ctx, timeout=60)
    h = {"Content-Type": "application/json", "X-OB": "1"}
    if cookie: h["Cookie"] = cookie
    c.request(method, path, json.dumps(body) if body is not None else None, h); r = c.getresponse(); d = r.read(); c.close()
    try: d = json.loads(d)
    except ValueError: pass
    return r, d
def login(u, p):
    r, d = req("POST", "/api/login", {"user": u, "password": p})
    return (r.getheader("Set-Cookie", "").split(";")[0] if r.status == 200 else None), d
def check(cond, msg):
    n[0] += 1; print(("[%02d] OK   - " if cond else "[%02d] ÉCHEC - ") % n[0] + msg)
    if not cond: raise SystemExit(1)
def chroot(*cmd): return subprocess.run(["chroot", "/tmp/target", *cmd], capture_output=True, text=True)
def linux_pw_ok(u, p):
    return chroot("python3", "-W", "ignore", "-c", "import crypt,spwd,sys; h=spwd.getspnam(sys.argv[1]).sp_pwdp; print(crypt.crypt(sys.argv[2],h)==h)", u, p).stdout.strip() == "True"

r, d = req("GET", "/api/ping"); check(r.status == 200 and re.fullmatch(r"\d{4}\.\d{2}\.\d{2}(-\d{4})?", d["version"]) and len(d["boot"]) == 12, "ping public : version %s + empreinte de démarrage" % d["version"])
adm, d = login("vti", "Ollama-2026!"); check(adm and d["role"] == "admin" and re.fullmatch(r"\d{4}\.\d{2}\.\d{2}(-\d{4})?", d["version"]), "connexion de l'admin créé par l'assistant (rôle admin, version renvoyée)")
r, d = req("GET", "/api/about", cookie=adm); check(bool(re.match(r"v\d+\.\d+\.\d+$", d["build"]["ollama"])) and "Ubuntu" in d["build"]["ubuntu"], "À propos : build %s, Ollama %s, %s" % (d["build"]["build_date"], d["ollama"], d["build"]["ubuntu"][:30]))
r, d = req("GET", "/api/gpu", cookie=adm); check(len(d["devices"]) == 8 and len(d["compute"]) == 2, "onglet GPU : 8 cartes analysées, 2 utilisées par Ollama")
# --- comptes
r, d = req("POST", "/api/users/create", {"user": "alice", "password": "Alice-2026", "role": "utilisateur", "linux": False}, adm); check(r.status == 200, "création d'un utilisateur web « alice » (sans compte Linux)")
check(chroot("id", "alice").returncode != 0, "aucun compte Linux créé pour alice")
r, d = req("POST", "/api/users/create", {"user": "bob", "password": "Bob-2026!", "role": "admin", "linux": True}, adm); check(r.status == 200, "création d'un administrateur « bob » avec compte Linux")
g = chroot("id", "-nG", "bob").stdout.split(); check({"sudo", "adm", "ollama"} <= set(g) and linux_pw_ok("bob", "Bob-2026!"), "bob : compte Linux dans sudo/adm/ollama, mot de passe Linux valide")
for bad, why in [({"user": "Bad Name", "password": "xxxxxxxx1", "role": "admin"}, "identifiant invalide"), ({"user": "carol", "password": "court", "role": "admin"}, "mot de passe trop court"),
                 ({"user": "alice", "password": "Alice-2027", "role": "admin"}, "doublon"), ({"user": "root", "password": "Rootroot1", "role": "admin", "linux": True}, "compte système root"),
                 ({"user": "dave", "password": "Dave-2026!", "role": "superuser"}, "rôle inconnu")]:
    r, d = req("POST", "/api/users/create", bad, adm); check(r.status == 400, "refusé (%s) : %s" % (why, d.get("error", "")[:60]))
# --- rôle utilisateur
al, d = login("alice", "Alice-2026"); check(al and d["role"] == "utilisateur", "connexion d'alice (rôle utilisateur)")
for path in ["/api/status", "/api/gpu", "/api/users", "/api/logs", "/api/jobs", "/api/ollama-env"]:
    r, d = req("GET", path, cookie=al); check(r.status == 403, "alice : GET %s refusé" % path)
for path, body in [("/api/action", {"action": "reboot"}), ("/api/models/pull", {"name": "x"}), ("/api/users/create", {"user": "eve", "password": "Eve-20266", "role": "admin"}), ("/api/ollama-env", {"values": {}})]:
    r, d = req("POST", path, body, al); check(r.status == 403, "alice : POST %s refusé" % path)
r, d = req("GET", "/api/models", cookie=al); check(r.status == 200, "alice : liste des modèles autorisée")
r, d = req("POST", "/api/chat", {"model": "inexistant", "messages": [{"role": "user", "content": "x"}]}, al); check(r.status != 403, "alice : chat autorisé")
r, d = req("POST", "/api/password", {"current": "Alice-2026", "new": "Alice-2027"}, al); check(r.status == 200, "alice change son propre mot de passe")
r, d = req("GET", "/api/session", cookie=al); check(r.status == 200, "sa session reste valide après son propre changement")
# --- administration des comptes
r, d = req("POST", "/api/users/update", {"user": "alice", "password": "Reset-2026"}, adm); check(r.status == 200, "l'admin réinitialise le mot de passe d'alice")
r, d = req("GET", "/api/session", cookie=al); check(r.status == 401, "l'ancienne session d'alice est aussitôt invalidée")
r, d = req("POST", "/api/users/update", {"user": "bob", "password": "Bob-2027!"}, adm); check(r.status == 200 and linux_pw_ok("bob", "Bob-2027!"), "mot de passe de bob réinitialisé : synchronisé avec Linux")
r, d = req("POST", "/api/users/update", {"user": "bob", "role": "utilisateur"}, adm); g = chroot("id", "-nG", "bob").stdout.split()
check(r.status == 200 and "sudo" not in g, "bob rétrogradé : retiré du groupe sudo")
r, d = req("POST", "/api/users/update", {"user": "vti", "role": "utilisateur"}, adm); check(r.status == 400, "impossible de modifier son propre rôle / retirer le dernier admin")
r, d = req("POST", "/api/users/delete", {"user": "vti"}, adm); check(r.status == 400, "impossible de supprimer son propre compte")
r, d = req("POST", "/api/users/delete", {"user": "bob"}, adm); check(r.status == 200 and chroot("id", "bob").returncode != 0, "suppression de bob : compte Linux supprimé")
check(chroot("test", "-d", "/home/bob").returncode == 0, "dossier personnel de bob conservé")
r, d = req("GET", "/api/users", cookie=adm); check([u["user"] for u in d["users"]] == ["alice", "vti"], "comptes restants : %s" % [u["user"] for u in d["users"]])
# --- paramètres Ollama
r, d = req("POST", "/api/ollama-env", {"values": {"OLLAMA_KEEP_ALIVE": "1h", "HSA_OVERRIDE_GFX_VERSION": "10.3.0"}}, adm); env = open("/tmp/target/etc/ollamabuntu/ollama.env").read()
check(r.status == 200 and "OLLAMA_KEEP_ALIVE=1h" in env and "OLLAMA_HOST=127.0.0.1:11434" in env, "paramètres avancés enregistrés, OLLAMA_HOST conservé")
r, d = req("POST", "/api/ollama-env", {"values": {"OLLAMA_KEEP_ALIVE": "1h; rm -rf /"}}, adm); check(r.status == 400, "valeur dangereuse refusée")
r, d = req("POST", "/api/ollama-env", {"values": {"LD_PRELOAD": "/tmp/x.so"}}, adm); check(r.status == 400, "variable hors liste refusée (LD_PRELOAD)")
r, d = req("POST", "/api/action", {"action": "enable-igpu"}, adm); check("OLLAMA_IGPU_ENABLE=1" in open("/tmp/target/etc/ollamabuntu/ollama.env").read(), "bouton « Autoriser le GPU intégré » : OLLAMA_IGPU_ENABLE=1")
# --- alimentation : sans systemd (chroot), l'erreur doit remonter clairement
r, d = req("POST", "/api/action", {"action": "reboot"}, adm); check(r.status == 500 and "refusé" in d.get("error", ""), "redémarrage impossible ici (pas de systemd) : erreur remontée -> %s" % d.get("error", "")[:70])
