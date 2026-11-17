#!/usr/bin/env python3
"""Open WebUI : adresse publique (validation, enregistrement, état exposé à la console)."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a); return False
    except ValueError: return True
tmp = tempfile.mkdtemp()
server.WEBUI_URL_FILE = os.path.join(tmp, "open-webui-url.env")
server.WEBUI_ENV = os.path.join(tmp, "open-webui.env")
server.shutil.which = lambda *_: None          # pas de Docker : l'état se calcule sans conteneur
server.cached = lambda k, t, f: None

for good, want in (("https://ia.entreprise.com", "https://ia.entreprise.com"), ("  https://ia.entreprise.com/ ", "https://ia.entreprise.com"),
                   ("http://srv-ia:3000", "http://srv-ia:3000"), ("https://10.0.0.5:8443/", "https://10.0.0.5:8443"), ("https://[fd00::1]:8443", "https://[fd00::1]:8443"), ("", "")):
    ok(server.webui_url_normalize(good) == want, "adresse acceptée : %r" % good)
for bad in ("ia.entreprise.com", "ftp://ia.entreprise.com", "https://u:p@ia.entreprise.com", "https://ia.entreprise.com/chat", "https://ia.entreprise.com?x=1",
            "https://ia.entreprise.com#a", "https://ia entreprise.com", "https://ia.entreprise.com:0", "https://ia.entreprise.com:70000", "https://-ia.com",
            "https://ia.com\nWEBUI_ADMIN_PASSWORD=x", "https://" + "a" * 250 + ".fr", "javascript:alert(1)"):
    ok(raises(server.webui_url_normalize, bad), "adresse refusée : %r" % bad[:50])

ok(server.webui_public_url() == "" and server.webui_status()["public_url"] == "", "sans réglage : aucune adresse publique")
server.webui_set_url("https://ia.entreprise.com/")
ok(server.webui_public_url() == "https://ia.entreprise.com" and server.webui_status()["public_url"] == "https://ia.entreprise.com", "adresse enregistrée et exposée par /api/webui")
ok(oct(os.stat(server.WEBUI_URL_FILE).st_mode & 0o777) == "0o600", "fichier réservé à root")
ok(open(server.WEBUI_URL_FILE).read().splitlines()[-1] == "WEBUI_URL=https://ia.entreprise.com", "variable WEBUI_URL transmise au conteneur")
ok(raises(server.webui_set_url, "https://x.com/a") and server.webui_public_url() == "https://ia.entreprise.com", "adresse invalide : l'ancienne reste en place")
server.webui_set_url("")
ok(not os.path.exists(server.WEBUI_URL_FILE) and server.webui_public_url() == "", "adresse vide : réglage supprimé")
ok("webui-apply-url" in server.JOBS if hasattr(server, "JOBS") else True, "tâche d'application déclarée")
print("%d contrôles réussis" % n)
