#!/usr/bin/env python3
"""Open WebUI : connexion unique OIDC (validation, fichiers d'environnement, secret, essai du fournisseur)."""
import os, sys, tempfile, json
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def err(f, *a):
    try: f(*a); return None
    except ValueError as e: return str(e)
def env(path):
    return dict(l.split("=", 1) for l in open(path).read().splitlines() if l and not l.startswith("#"))

tmp = tempfile.mkdtemp()
server.ETC = tmp
server.WEBUI_SSO_FILE = os.path.join(tmp, "open-webui-sso.json")
server.WEBUI_SSO_ENV = os.path.join(tmp, "open-webui-sso.env")
server.WEBUI_URL_FILE = os.path.join(tmp, "open-webui-url.env")
OK = {"enabled": True, "name": "Entreprise", "issuer": "https://login.x.fr/realms/ia/", "client_id": "owui", "client_secret": "s3cret", "redirect_base": "https://ia.x.fr/"}

ok(not server.webui_sso_load()["enabled"] and server.webui_sso_view()["redirect_uri"] == "" and not server.webui_sso_view()["secret_set"], "sans réglage : désactivé, aucune adresse de retour")
for bad, why in (({"enabled": True}, "émetteur"), (dict(OK, issuer="http://login.x.fr"), "https"), (dict(OK, client_id=""), "identifiant"), (dict(OK, client_secret=""), "secret"),
                 (dict(OK, redirect_base=""), "adresse d'Open WebUI"), (dict(OK, redirect_base="https://ia.x.fr/chemin"), "adresse avec chemin"),
                 (dict(OK, scopes="profile email"), "scope openid"), (dict(OK, scopes="openid;rm"), "scopes"), (dict(OK, name="x" * 31), "nom trop long"),
                 (dict(OK, admin_roles="admin"), "rôles sans revendication"),
                 (dict(OK, roles_claim="roles;x"), "revendication"), (dict(OK, allowed_domains="a=b.fr", roles_claim=""), "domaine avec =")):
    ok(err(server.webui_sso_clean, bad) is not None, "refusé : " + why)
ok(not os.path.exists(server.WEBUI_SSO_FILE), "rien d'écrit après un refus")

c = server.webui_sso_save(OK)
ok(c["issuer"] == "https://login.x.fr/realms/ia" and c["redirect_base"] == "https://ia.x.fr", "adresses normalisées (« / » final retiré)")
ok(oct(os.stat(server.WEBUI_SSO_FILE).st_mode & 0o777) == "0o600" and oct(os.stat(server.WEBUI_SSO_ENV).st_mode & 0o777) == "0o600", "fichiers réservés à root")
e = env(server.WEBUI_SSO_ENV)
ok(e["ENABLE_PERSISTENT_CONFIG"] == "false", "ENABLE_PERSISTENT_CONFIG=false (sinon Open WebUI garde l'ancien réglage)")
ok(e["OPENID_PROVIDER_URL"] == "https://login.x.fr/realms/ia/.well-known/openid-configuration" and e["OPENID_REDIRECT_URI"] == "https://ia.x.fr/oauth/oidc/callback", "adresse de découverte et adresse de retour")
ok(e["OAUTH_CLIENT_ID"] == "owui" and e["OAUTH_CLIENT_SECRET"] == "s3cret" and e["OAUTH_PROVIDER_NAME"] == "Entreprise" and e["OAUTH_SCOPES"] == "openid email profile", "identifiants, nom et scopes transmis")
ok(e["ENABLE_OAUTH_SIGNUP"] == "true" and e["OAUTH_MERGE_ACCOUNTS_BY_EMAIL"] == "true" and e["ENABLE_LOGIN_FORM"] == "true" and e["OAUTH_ALLOWED_DOMAINS"] == "*", "valeurs par défaut prudentes (formulaire local gardé)")
ok(e["ENABLE_OAUTH_ROLE_MANAGEMENT"] == "false" and e["ENABLE_OAUTH_GROUP_MANAGEMENT"] == "false" and "OAUTH_ROLES_CLAIM" not in e, "rôles et groupes non gérés par défaut")
v = server.webui_sso_view()
ok("client_secret" not in v and v["secret_set"] and v["redirect_uri"] == "https://ia.x.fr/oauth/oidc/callback", "la vue n'expose jamais le secret")
ok("s3cret" not in json.dumps(v), "secret absent de la réponse JSON")

c = server.webui_sso_save(dict(OK, client_id="a\nENABLE_LOGIN_FORM=false\r\nX=1", name="Nouveau", client_secret=""))
lines = [l for l in open(server.WEBUI_SSO_ENV).read().splitlines() if l and not l.startswith("#")]
ok(len(lines) == len(set(l.split("=", 1)[0] for l in lines)) and env(server.WEBUI_SSO_ENV)["ENABLE_LOGIN_FORM"] == "true", "retour à la ligne dans un champ : aucune variable injectée")
c = server.webui_sso_save(dict(OK, client_secret="", name="Nouveau"))
ok(c["client_secret"] == "s3cret" and c["name"] == "Nouveau", "secret vide : l'ancien est conservé")
c = server.webui_sso_save(dict(OK, client_secret="autre"))
ok(env(server.WEBUI_SSO_ENV)["OAUTH_CLIENT_SECRET"] == "autre", "nouveau secret pris en compte")

c = server.webui_sso_save(dict(OK, roles_claim="roles", admin_roles="ia-admins, direction", allowed_roles="ia-users,ia-admins", groups_claim="groups", allowed_domains="x.fr, y.fr",
                               login_form=False, merge_by_email=False, signup=False))
e = env(server.WEBUI_SSO_ENV)
ok(e["ENABLE_OAUTH_ROLE_MANAGEMENT"] == "true" and e["OAUTH_ROLES_CLAIM"] == "roles" and e["OAUTH_ADMIN_ROLES"] == "ia-admins,direction" and e["OAUTH_ALLOWED_ROLES"] == "ia-users,ia-admins", "rôles : revendication, administrateurs, autorisés")
ok(e["ENABLE_OAUTH_GROUP_MANAGEMENT"] == "true" and e["OAUTH_GROUP_CLAIM"] == "groups" and e["OAUTH_ALLOWED_DOMAINS"] == "x.fr,y.fr", "groupes et domaines")
ok(e["ENABLE_LOGIN_FORM"] == "false" and e["OAUTH_MERGE_ACCOUNTS_BY_EMAIL"] == "false" and e["ENABLE_OAUTH_SIGNUP"] == "false", "les trois options à faux sont transmises")
c = server.webui_sso_save(dict(OK, roles_claim="roles", admin_roles="ia-admins", allowed_roles=""))
ok(env(server.WEBUI_SSO_ENV)["OAUTH_ALLOWED_ROLES"] == "user,admin", "rôles autorisés vides : valeur par défaut d'Open WebUI")

c = server.webui_sso_save({"enabled": False})
e = env(server.WEBUI_SSO_ENV)
ok(not c["enabled"] and e["OAUTH_CLIENT_ID"] == "" and e["OAUTH_CLIENT_SECRET"] == "" and e["OPENID_PROVIDER_URL"] == "" and e["ENABLE_LOGIN_FORM"] == "true" and e["ENABLE_OAUTH_SIGNUP"] == "false",
   "désactivation : valeurs neutres forcées (le conteneur ne garde pas l'ancien réglage)")
ok(server.webui_sso_load()["client_secret"] == "s3cret", "désactivation : le secret reste mémorisé pour une réactivation")
c = server.webui_sso_save({"enabled": True, "redirect_base": "https://ia.x.fr", "issuer": "https://login.x.fr", "client_id": "owui"})
ok(c["enabled"] and c["client_secret"], "réactivation avec le secret mémorisé")

class Fake:
    calls = []
    @staticmethod
    def discovery(cfg):
        Fake.calls.append(cfg["issuer"])
        if "mauvais" in cfg["issuer"]: raise ValueError("fournisseur injoignable : refusé")
        return {"issuer": cfg["issuer"], "authorization_endpoint": cfg["issuer"] + "/auth", "scopes_supported": ["openid", "email"], "claims_supported": ["sub", "groups"]}
    https_url = staticmethod(server.sso.https_url)
real = server.sso
server.sso = Fake
r = server.webui_sso_test({"issuer": "https://login.x.fr/"})
ok(r["ok"] and Fake.calls[-1] == "https://login.x.fr" and "groups" in r["claims"], "essai : émetteur du formulaire interrogé (sans « / » final)")
ok(server.webui_sso_test({})["issuer"] == "https://login.x.fr", "essai sans valeur : émetteur enregistré")
ok(err(server.webui_sso_test, {"issuer": "https://mauvais.x.fr"}) == "fournisseur injoignable : refusé", "essai : erreur du fournisseur remontée")
ok(err(server.webui_sso_test, {"issuer": "http://login.x.fr"}) is not None, "essai : http refusé")
server.sso = real

# --- connexion par en-tête (reverse proxy)
HB = {"enabled": False, "header_auth": True, "header_email": "X-Forwarded-Email", "trusted_proxies": "192.168.1.10"}
server.webui_sso_save({"enabled": False})
for bad, why in (({"header_auth": True, "header_email": "", "trusted_proxies": "10.0.0.1"}, "en-tête de l'e-mail vide"), (dict(HB, trusted_proxies=""), "aucun reverse proxy déclaré"),
                 (dict(HB, trusted_proxies="0.0.0.0/0"), "tout le monde (IPv4)"), (dict(HB, trusted_proxies="::/0"), "tout le monde (IPv6)"), (dict(HB, trusted_proxies="pas-une-ip"), "adresse invalide"),
                 (dict(HB, header_email="X Forwarded"), "nom d'en-tête invalide"), (dict(HB, header_name="a\r\nX: y"), "en-tête avec retour à la ligne"),
                 (dict(HB, trusted_proxies=",".join("10.0.0.%d" % i for i in range(21))), "plus de 20 adresses"),
                 (dict(OK, header_auth=True, trusted_proxies="192.168.1.10"), "combiné au bouton OpenID Connect")):
    ok(err(server.webui_sso_clean, bad) is not None, "en-tête refusé : " + why)
c = server.webui_sso_save(dict(HB, login_form=True, header_name="X-Auth-Name", header_groups="X-Auth-Groups", trusted_proxies="192.168.1.10, 10.0.0.0/8\n2001:db8::1"))
e = env(server.WEBUI_SSO_ENV)
ok(c["trusted_proxies"] == "192.168.1.10/32,10.0.0.0/8,2001:db8::1/128", "reverse proxy normalisés : " + c["trusted_proxies"])
ok(e["WEBUI_AUTH_TRUSTED_EMAIL_HEADER"] == "X-Forwarded-Email" and e["WEBUI_AUTH_TRUSTED_NAME_HEADER"] == "X-Auth-Name" and e["WEBUI_AUTH_TRUSTED_GROUPS_HEADER"] == "X-Auth-Groups", "variables d'en-tête transmises à Open WebUI")
ok(e["OAUTH_CLIENT_ID"] == "" and e["ENABLE_OAUTH_SIGNUP"] == "false", "OpenID Connect neutralisé dans ce mode")
ok(e["ENABLE_LOGIN_FORM"] == "true", "formulaire local gardé par défaut")
server.webui_sso_save(dict(HB, login_form=False))
ok(env(server.WEBUI_SSO_ENV)["ENABLE_LOGIN_FORM"] == "false", "formulaire local retirable à la demande")
server.webui_sso_save(dict(HB, header_name="", header_groups="", login_form=True))
ok(env(server.WEBUI_SSO_ENV)["WEBUI_AUTH_TRUSTED_NAME_HEADER"] == "", "nom et groupes vides par défaut")
ok(server.webui_sso_view()["header_auth"] and server.webui_sso_view()["trusted_proxies"], "la vue expose le mode et les adresses")
ok(server.webui_proxy_allowed("192.168.1.10") and not server.webui_proxy_allowed("192.168.1.11") and not server.webui_proxy_allowed("8.8.8.8"), "port d'Open WebUI : seul le reverse proxy déclaré est accepté")
ok(server.webui_proxy_allowed("::ffff:192.168.1.10") and not server.webui_proxy_allowed("::ffff:192.168.1.11"), "adresse IPv4 portée par IPv6 reconnue")
ok(not server.webui_proxy_allowed("n'importe quoi") and not server.webui_proxy_allowed(""), "adresse illisible : refusée")
server.webui_sso_save(dict(HB, trusted_proxies="10.0.0.0/8"))
ok(server.webui_proxy_allowed("10.200.3.4") and not server.webui_proxy_allowed("192.168.1.10"), "le changement de liste est pris en compte sans redémarrage")
server.webui_sso_save({"header_auth": False})
ok(server.webui_proxy_allowed("8.8.8.8") and env(server.WEBUI_SSO_ENV)["WEBUI_AUTH_TRUSTED_EMAIL_HEADER"] == "", "mode désactivé : tout le monde accepté, en-tête retiré du conteneur")
os.remove(server.WEBUI_SSO_FILE)
ok(server.webui_proxy_allowed("8.8.8.8"), "aucune configuration : tout le monde accepté")

# --- le relais refuse réellement les autres sources
import asyncio
class W:
    def __init__(self, ip): self.ip, self.out, self.closed = ip, b"", False
    def get_extra_info(self, k): return (self.ip, 1234)
    def write(self, b): self.out += b
    async def drain(self): pass
    def close(self): self.closed = True
server.webui_sso_save(dict(HB, trusted_proxies="192.168.1.10"))
w = W("203.0.113.9"); asyncio.run(server._webui_client(None, w))
ok(w.out.startswith(b"HTTP/1.1 403") and w.closed, "relais : source non déclarée refusée en 403, avant toute connexion à Open WebUI")
server.WEBUI_PORT = 1   # aucun Open WebUI ne répond : une source déclarée passe le contrôle et reçoit l'erreur 503 habituelle
w = W("192.168.1.10"); asyncio.run(server._webui_client(None, w))
ok(w.out.startswith(b"HTTP/1.1 503") and w.closed, "relais : source déclarée acceptée (puis 503 : aucun Open WebUI dans ce test)")
os.remove(server.WEBUI_SSO_FILE) if os.path.exists(server.WEBUI_SSO_FILE) else None

sh = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "open-webui.sh")).read()
ok("--env-file /etc/ollamabuntu/open-webui-sso.env" in sh and "apply-sso)" in sh and "open-webui-sso.json" in sh, "script : fichier passé au conteneur, action apply-sso, nettoyage à la suppression")
ok("apply-sso" in server.JOBS.get("webui-apply-sso", ("", ""))[1], "tâche d'application déclarée")
ok(__import__("audit").LABELS.get("/api/webui/sso") and "secret" in __import__("audit").SECRET_WORDS, "audit : action libellée, secret masqué")
print("%d contrôles réussis" % n)
