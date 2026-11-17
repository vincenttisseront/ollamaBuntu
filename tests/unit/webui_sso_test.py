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

sh = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "open-webui.sh")).read()
ok("--env-file /etc/ollamabuntu/open-webui-sso.env" in sh and "apply-sso)" in sh and "open-webui-sso.json" in sh, "script : fichier passé au conteneur, action apply-sso, nettoyage à la suppression")
ok("apply-sso" in server.JOBS.get("webui-apply-sso", ("", ""))[1], "tâche d'application déclarée")
ok(__import__("audit").LABELS.get("/api/webui/sso") and "secret" in __import__("audit").SECRET_WORDS, "audit : action libellée, secret masqué")
print("%d contrôles réussis" % n)
