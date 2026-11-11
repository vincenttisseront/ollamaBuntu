#!/usr/bin/env python3
"""Confidentialité, côté console : réglages, statistiques tirées du journal, essai sur un texte, termes interdits par clé, routes HTTP, audit, sauvegarde."""
import http.client, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_STATE=os.path.join(tmp, "state"), OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import privacy, server, audit, backup
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a, **k):
    try: f(*a, **k); return False
    except ValueError: return True
server.AUDIT_FILE = os.path.join(tmp, "audit.jsonl")
server.save_users({"admin": dict(server.hash_password("Secret-123"), role="admin", linux=False, rev="r0", created=1, updated=1),
                   "jean": dict(server.hash_password("Secret-456"), role="utilisateur", linux=False, rev="r1", created=1, updated=1)})
server.apply_firewall = lambda **k: None; server.ensure_router_tls = lambda: None
NOW = time.time()

# --- statistiques (module pur)
R = lambda dt, client, **k: dict({"ts": NOW - dt, "client": client, "model": "m", "status": 200}, **k)
reqs = [R(100, "RH", pii=["email", "phone"]), R(200, "RH", pii=["email"], masked=True), R(300, "Compta"), R(400, "Compta", blocked=True, status=403),
        R(500, "RH", blocked=True, status=403), R(90000, "RH", pii=["iban"]), R(100, "local", pii=["bidon"]), R(100, "x", pii="email")]
d = privacy.stats(reqs, NOW, 86400)
ok(d["n"] == 7 and d["with_pii"] == 2 and d["masked"] == 1 and d["blocked"] == 2 and d["by_cat"] == {"email": 2, "phone": 1}, "24 h : demandes, demandes avec données sensibles, masquées, refusées, par catégorie (catégories inconnues et champs mal formés ignorés)")
ok([c["client"] for c in d["clients"]] == ["RH", "Compta"] and d["clients"][0] == {"client": "RH", "n": 3, "pii": 2, "masked": 1, "blocked": 1}, "par client, les plus concernés d'abord ; clients sans événement omis")
w = privacy.stats(reqs, NOW, 7 * 86400); ok(w["n"] == 8 and w["by_cat"]["iban"] == 1, "7 jours : inclut les demandes plus anciennes")
ok(privacy.stats([], NOW, 86400) == {"n": 0, "with_pii": 0, "masked": 0, "blocked": 0, "by_cat": {}, "clients": []}, "journal vide")

# --- réglages enregistrés
server.PRIVACY_FILE = os.path.join(ETC, "privacy.json")
ok(server.privacy_config() == privacy.default_config(), "sans fichier : réglages par défaut")
c = server.privacy_save({"anonymize": True, "words": "projet orion\nsalaire", "categories": {"ip": True}})
ok(c["anonymize"] and c["words"] == ["projet orion", "salaire"] and c["categories"]["ip"] and oct(os.stat(server.PRIVACY_FILE).st_mode & 0o777) == "0o644", "enregistrés (lisibles par le routeur, qui n'est pas root)")
ok(server.privacy_save({"words_action": "mask"})["words"] == ["projet orion", "salaire"], "enregistrement partiel : le reste est conservé")
before = open(server.PRIVACY_FILE).read()
ok(raises(server.privacy_save, {"words": ["x"]}) and raises(server.privacy_save, {"words_action": "?"}) and open(server.PRIVACY_FILE).read() == before, "réglage invalide refusé sans toucher au fichier")
open(server.PRIVACY_FILE, "w").write("{cassé"); ok(server.privacy_config() == privacy.default_config(), "fichier corrompu : valeurs par défaut")
server.privacy_save({"anonymize": True, "words": ["salaire"], "words_action": "block"})

# --- essai sur un texte
t = server.privacy_test({"text": "Le SALAIRE de marie@exemple.fr, tel 06 12 34 56 78, projet Orion"})
ok(t["masked"] == "Le SALAIRE de [e-mail], tel [téléphone], projet Orion" and t["categories"] == ["email", "phone"] and t["hits"] == ["SALAIRE"] and t["action"] == "block" and t["anonymize"], "essai : texte masqué, catégories, termes interdits trouvés, action en vigueur")
t = server.privacy_test({"text": "projet Orion", "words": ["orion"]}); ok(t["hits"] == ["Orion"], "essai d'un terme propre à une clé (non enregistré)")
ok(raises(server.privacy_test, {"text": "x", "words": ["a"]}) and len(server.privacy_test({"text": "a" * 9000})["masked"]) == 5000, "terme invalide refusé ; texte d'essai borné à 5000 caractères")

# --- termes interdits par clé
pub = {"enabled": False, "keys": []}
server.load_publication = lambda: pub; server.save_publication = lambda p: None
server.load_publication = lambda: {"enabled": False, "port": 11435, "tls": False, "keys": pub["keys"], "auth": True}
tok, key = server.key_create({"name": "RH", "perms": ["inference"], "words": "confidentiel; Projet Orion"})
k0 = pub["keys"][0]
ok(key["words"] == ["confidentiel", "Projet Orion"], "clé créée avec ses termes interdits")
server.save_publication = lambda p: pub.update(keys=p["keys"])
server.key_update({"id": k0["id"], "words": ["salaire", "Salaire"]}); ok(pub["keys"][0]["words"] == ["salaire"], "modification : dédoublonnée")
server.key_update({"id": k0["id"], "words": []}); ok("words" not in pub["keys"][0], "liste vide : champ retiré")
ok(raises(server.key_update, {"id": k0["id"], "words": ["a"]}) and raises(server.key_update, {"id": k0["id"], "words": ["mot%03d" % i for i in range(51)]}), "terme invalide ou plus de 50 termes : refusé")
tok2, key2 = server.key_create({"name": "Sans", "perms": ["inference"]}); ok("words" not in key2, "clé sans terme : aucun champ")
server.key_update({"id": k0["id"], "words": ["salaire"]})
sync = [{k: v for k, v in kk.items() if k in ("id", "name", "hash", "prefix", "perms", "models", "deny", "enabled", "created", "words")} for kk in pub["keys"]]
ok(sync[0]["words"] == ["salaire"], "les termes d'une clé font partie des champs synchronisés avec le parc")

# --- routes HTTP
httpd = server.make_server(0, server.Handler); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
def req(method, path, cookie="", body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = cookie
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    cookies = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    return r.status, cookies, json.loads(raw or b"{}")
def login(u, p):
    st, ck, d = req("POST", "/api/login", body={"user": u, "password": p})
    return next(c.split(";")[0] for c in ck if c.startswith("ob_session="))
adm, usr = login("admin", "Secret-123"), login("jean", "Secret-456")
open(os.environ["OB_ROUTER_REQLOG"], "w").write("\n".join(json.dumps(r) for r in reqs) + "\n")
st, _, d = req("GET", "/api/privacy", adm)
ok(st == 200 and d["config"]["words"] == ["salaire"] and d["day"]["blocked"] == 2 and d["week"]["n"] == 8 and d["categories"] == list(privacy.CATEGORIES) and d["limits"] == {"words": 200, "key_words": 50}, "GET /api/privacy : réglages, statistiques 24 h et 7 jours")
ok([k["name"] for k in d["keys"]] == ["RH", "Sans"] and d["keys"][0]["words"] == ["salaire"], "…et les termes de chaque clé")
ok(req("GET", "/api/privacy", usr)[0] == 403 and req("GET", "/api/privacy")[0] == 401, "réservé aux administrateurs")
ok(req("POST", "/api/privacy/config", usr, {"anonymize": False})[0] == 403 and privacy.config_clean(json.load(open(server.PRIVACY_FILE)))["anonymize"], "modification refusée à un simple utilisateur")
st, _, d = req("POST", "/api/privacy/config", adm, {"anonymize": False, "words": "alpha\nbêta"}); ok(st == 200 and d["config"]["words"] == ["alpha", "bêta"] and not d["config"]["anonymize"], "POST /api/privacy/config")
st, _, d = req("POST", "/api/privacy/config", adm, {"words": ["a"]}); ok(st == 400 and "terme interdit" in d["error"], "réglage invalide : 400 avec message")
st, _, d = req("POST", "/api/privacy/test", adm, {"text": "écrire à a.b@exemple.fr (alpha)"}); ok(st == 200 and d["masked"] == "écrire à [e-mail] (alpha)" and d["hits"] == ["alpha"], "POST /api/privacy/test")
ok(req("POST", "/api/privacy/test", usr, {"text": "x"})[0] == 403, "essai réservé aux administrateurs")
log = open(server.AUDIT_FILE).read()
ok("Confidentialité des demandes" in log and "a.b@exemple.fr" not in log and "privacy/test" not in log, "audit : réglages consignés, texte d'essai jamais consigné")
ok("privacy.json" in backup.FILES, "réglages inclus dans la sauvegarde de la configuration")
print("\n%d vérifications réussies." % n)
