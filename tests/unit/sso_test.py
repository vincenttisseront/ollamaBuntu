#!/usr/bin/env python3
"""Connexion unique : jetons OpenID Connect (signés par openssl), client LDAP (annuaire simulé en LDAPS et StartTLS), rôles par groupe,
et vrais échanges HTTP avec la console (fournisseur OIDC simulé)."""
import base64, hashlib, http.client, http.server, json, os, socketserver, ssl, subprocess, sys, tempfile, threading, time, urllib.parse
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_STATE=os.path.join(tmp, "state"), OB_SSO_ALLOW_HTTP="1")
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin")
sys.path.insert(0, LIB)
import sso, server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(exc, f, *a, **k):
    try: f(*a, **k); return False
    except exc: return True
def sh(*args, inp=None):
    return subprocess.run(args, input=inp, capture_output=True, check=True).stdout

# ------------------------------------------------------------------ clés RSA et jetons signés par openssl (indépendant de sso.py)
def rsa_key(bits=2048):
    p = os.path.join(tmp, "k%d-%d.pem" % (bits, len(os.listdir(tmp))))
    sh("openssl", "genrsa", "-out", p, str(bits))
    mod = sh("openssl", "rsa", "-in", p, "-noout", "-modulus").decode().strip().split("=")[1]
    return p, {"kty": "RSA", "use": "sig", "n": sso.b64u(bytes.fromhex(mod)), "e": "AQAB"}
def sign(keyfile, data, h="sha256"):
    return sh("openssl", "dgst", "-" + h, "-sign", keyfile, inp=data)
def jwt(keyfile, claims, alg="RS256", kid="k1", h="sha256", header=None):
    hd = header or {"alg": alg, "kid": kid, "typ": "JWT"}
    si = sso.b64u(json.dumps(hd).encode()) + "." + sso.b64u(json.dumps(claims).encode())
    return si + "." + sso.b64u(sign(keyfile, si.encode(), h))
KEY, JWK = rsa_key(); JWK["kid"] = "k1"; JWKS = {"keys": [JWK]}
KEY2, JWK2 = rsa_key(); JWK2["kid"] = "k2"
NOW = int(time.time()); ISS, CID = "https://idp.corp.local", "ollamabuntu"
good = {"iss": ISS, "aud": CID, "sub": "u-123", "exp": NOW + 600, "iat": NOW, "nonce": "N1", "preferred_username": "Alice", "groups": ["OllamaAdmins"]}

# --- 1. vérification des jetons
tok = jwt(KEY, good)
c = sso.verify_id_token(tok, JWKS, ISS, CID, "N1", NOW)
ok(c["sub"] == "u-123", "jeton RS256 signé par openssl : signature, émetteur, destinataire, nonce et durée acceptés")
ok(sso.verify_id_token(jwt(KEY, good, "RS384", h="sha384"), JWKS, ISS, CID, "N1", NOW)["sub"] == "u-123" and sso.verify_id_token(jwt(KEY, good, "RS512", h="sha512"), JWKS, ISS, CID, "N1", NOW)["sub"] == "u-123", "RS384 et RS512 acceptés aussi")
bad = lambda t, **kw: raises(ValueError, sso.verify_id_token, t, kw.get("jwks", JWKS), kw.get("iss", ISS), kw.get("cid", CID), kw.get("nonce", "N1"), NOW)
head, body, sig = tok.split(".")
forged = sso.b64u(json.dumps(dict(good, preferred_username="root", groups=["OllamaAdmins"], sub="x")).encode())
ok(bad(head + "." + forged + "." + sig), "contenu modifié après signature : refusé")
ok(bad(jwt(KEY2, good)), "signé avec une autre clé que celle publiée (même identifiant de clé) : refusé")
ok(bad(jwt(KEY, good, kid="inconnue")), "identifiant de clé inconnu : refusé")
ok(bad(jwt(KEY, good, alg="none", header={"alg": "none", "typ": "JWT"})) and bad(head + "." + body + "."), "algorithme « none » et signature vide : refusés")
ok(bad(jwt(KEY, good, header={"alg": "HS256", "kid": "k1"})), "algorithme HS256 (confusion clé publique / secret partagé) : refusé")
ok(bad(jwt(KEY, dict(good, iss="https://evil.example"))) and bad(jwt(KEY, dict(good, aud="autre-app"))) and bad(jwt(KEY, dict(good, aud=["x", CID]))) and not bad(jwt(KEY, dict(good, aud=["x", CID], azp=CID))), "émetteur ou destinataire inattendu refusés ; plusieurs destinataires exigent azp")
ok(bad(jwt(KEY, dict(good, exp=NOW - 3600))) and not bad(jwt(KEY, dict(good, exp=NOW - 30))) and bad(jwt(KEY, dict(good, iat=NOW + 3600))), "jeton expiré refusé (marge de 2 minutes pour l'écart d'horloge), émis dans le futur refusé")
ok(bad(tok, nonce="AUTRE") and bad(jwt(KEY, {k: v for k, v in good.items() if k != "nonce"})) and bad(jwt(KEY, {k: v for k, v in good.items() if k != "sub"})), "nonce différent ou absent refusé ; jeton sans « sub » refusé")
k1024, j1024 = rsa_key(1024); j1024["kid"] = "k1"
ok(bad(jwt(k1024, good), jwks={"keys": [j1024]}), "clé RSA de moins de 2048 bits : refusée")
ok(bad("pas.un.jeton") and bad("a.b") and bad("") and bad(None), "jetons mal formés refusés")
ok(sso.pick_key({"keys": [JWK]}, None) == JWK and sso.pick_key({"keys": [JWK, JWK2]}, None) is None, "sans identifiant de clé : accepté seulement s'il n'y a qu'une clé publiée")
v, ch = sso.pkce_pair()
ok(43 <= len(v) <= 128 and ch == sso.b64u(hashlib.sha256(v.encode()).digest()) and "=" not in ch, "PKCE S256 : vérificateur de 43 à 128 caractères, défi = SHA-256 en base64url")
u = urllib.parse.urlsplit(sso.auth_url("https://idp/auth?x=1", "cid", "https://app/cb", "openid email", "ST", "NO", ch)); q = urllib.parse.parse_qs(u.query)
ok(q["response_type"] == ["code"] and q["state"] == ["ST"] and q["nonce"] == ["NO"] and q["code_challenge_method"] == ["S256"] and q["x"] == ["1"] and q["redirect_uri"] == ["https://app/cb"], "adresse d'autorisation : code, state, nonce, PKCE")

# --- 2. groupes et rôles
ok(sso.claim_values({"groups": ["a", "b"]}, "groups") == ["a", "b"] and sso.claim_values({"realm_access": {"roles": ["r1"]}}, "realm_access.roles") == ["r1"] and sso.claim_values({"g": "x"}, "g") == ["x"] and sso.claim_values({}, "groups") == [], "groupes lus dans la revendication (liste, imbriquée, texte, absente)")
RULES = [{"group": "OllamaAdmins", "role": "admin"}, {"group": "CN=Staff,OU=Groups,DC=corp,DC=local", "role": "utilisateur"}]
ok(sso.role_for(["CN=OllamaAdmins,OU=G,DC=c"], RULES) == "admin" and sso.role_for(["ollamaadmins"], RULES) == "admin", "groupe reconnu par son nom commun (CN) d'un DN, sans tenir compte de la casse")
ok(sso.role_for(["cn=staff,ou=groups,dc=corp,dc=local"], RULES) == "utilisateur" and sso.role_for(["Staff", "OllamaAdmins"], RULES) == "admin", "DN complet reconnu ; administrateur l'emporte sur utilisateur")
ok(sso.role_for(["Autre"], RULES) is None and sso.role_for([], RULES) is None and sso.role_for(["Autre"], RULES, "utilisateur") == "utilisateur" and sso.role_for([], [], "") is None, "aucun groupe reconnu : refus, sauf rôle par défaut")
ok(sso.account_name("sso", "Alice.Martin@Corp.Fr") == "sso:alice.martin@corp.fr" and sso.account_name("ldap", "a b/c") == "ldap:a_b_c" and sso.account_name("sso", "") is None and ":" in sso.account_name("ldap", "x"), "nom de compte SSO normalisé et préfixé (jamais confondu avec un compte local)")

# --- 3. configuration
def conf(**over):
    base = {"oidc": {"enabled": True, "issuer": "https://idp.corp.local/", "client_id": "app", "client_secret": "sec", "redirect_base": "https://ollama.corp.local:8443/"},
            "ldap": {"enabled": True, "host": "ad.corp.local", "base_dn": "dc=corp,dc=local"}, "roles": RULES}
    base.update(over); return base
cfg = sso.config_clean(conf())
ok(cfg["oidc"]["redirect_base"] == "https://ollama.corp.local:8443" and cfg["ldap"]["port"] == 636 and cfg["ldap"]["tls"] == "ldaps" and cfg["oidc"]["groups_claim"] == "groups", "configuration valide : valeurs par défaut (LDAPS 636, revendication « groups »), adresse sans barre finale")
pv = sso.public_view(cfg)
ok("client_secret" not in pv["oidc"] and pv["oidc"]["client_secret_set"] is True and "bind_password" not in pv["ldap"] and pv["ldap"]["bind_password_set"] is False, "vue publique : aucun secret, seulement s'il est enregistré")
keep = sso.config_clean({"oidc": {"name": "X"}}, cfg)
ok(keep["oidc"]["client_secret"] == "sec" and keep["oidc"]["name"] == "X", "secret laissé vide : valeur actuelle conservée")
bads = [conf(oidc={"enabled": True, "issuer": "http://idp.corp.local", "client_id": "a", "client_secret": "s", "redirect_base": "https://x"}) if not sso.ALLOW_HTTP else None,
        conf(roles=[]), conf(roles=[{"group": "g", "role": "root"}]), conf(default_role="admin"), conf(ldap={"enabled": True, "host": "ad;rm", "base_dn": "dc=x"}),
        conf(ldap={"enabled": True, "host": "ad", "base_dn": "dc=x", "user_filter": "(uid=x)"}), conf(ldap={"enabled": True, "host": "ad", "base_dn": "dc=x", "user_filter": "(uid={user}"}),
        conf(ldap={"enabled": True, "host": "ad", "base_dn": "dc=x", "tls": "ssl3"}), conf(ldap={"enabled": True, "host": "ad", "port": 70000, "base_dn": "dc=x"}),
        conf(oidc={"enabled": True, "issuer": "https://i", "client_id": "a", "client_secret": "", "redirect_base": "https://x"}),
        conf(oidc={"enabled": True, "issuer": "https://i", "client_id": "a", "client_secret": "s", "redirect_base": "https://x/chemin"}),
        conf(oidc={"enabled": True, "issuer": "https://i", "client_id": "a", "client_secret": "s", "redirect_base": "https://x", "scopes": "email"}),
        conf(oidc={"enabled": True, "issuer": "https://i", "client_id": "a", "client_secret": "s", "redirect_base": "https://x", "ca_pem": "pas un certificat"}),
        conf(ldap={"enabled": True, "host": "ad", "base_dn": "dc=x", "group_attr": "", "group_base": ""})]
ok(all(raises(ValueError, sso.config_clean, b) for b in bads if b), "configurations dangereuses ou incomplètes refusées (rôle admin par défaut, filtre sans {user}, TLS inconnu, secret absent, certificat illisible…)")
ok(raises(ValueError, sso.config_clean, {"oidc": {"enabled": True, "issuer": "https://i", "client_id": "a", "client_secret": "s", "redirect_base": "https://x"}}), "fournisseur activé sans aucun groupe → rôle ni rôle par défaut : refusé (personne ne pourrait se connecter)")
off = sso.config_clean({})
ok(not off["oidc"]["enabled"] and not off["ldap"]["enabled"] and off["roles"] == [], "SSO désactivé par défaut, configuration vide acceptée")

# --- 4. LDAP : encodage BER
ok(sso.bind_request(1, "", "").hex() == "300c020101600702010304008000", "requête de connexion LDAP identique au vecteur de la RFC 4511 (connexion anonyme, version 3)")
ok(sso.unbind_request(2).hex() == "30050201024200", "requête de déconnexion identique au vecteur de référence")
m = sso.search_request(3, "dc=corp,dc=local", "(&(objectClass=user)(|(sAMAccountName=al\\2ace)(mail=*))(!(memberOf:1.2.840.113556.1.4.1941:=cn=x,dc=y)))", ["cn", "memberOf"])
asn = sh("openssl", "asn1parse", "-inform", "DER", "-i").decode() if False else subprocess.run(["openssl", "asn1parse", "-inform", "DER"], input=m, capture_output=True).stdout.decode()
ok("appl [ 3 ]" in asn and "dc=corp,dc=local" in asn and "al*ce" in asn and "cont [ 9 ]" in asn and "cont [ 7 ]" in asn and "memberOf" in asn, "requête de recherche : relue par openssl (ASN.1 indépendant) avec filtre &, |, !, présence, règle étendue et séquence \\2a décodée")
ok(sso.escape_filter("a*b(c)\\d\x00") == "a\\2ab\\28c\\29\\5cd\\00" and sso.escape_filter("alice") == "alice", "échappement des caractères spéciaux d'un filtre (RFC 4515)")
ok(all(raises(ValueError, sso.parse_filter, f) for f in ("", "uid=x", "(uid=x", "(uid=x))", "(&)", "(uid=a*b)", "(=x)", "(uid=a\\zz)", "(uid>=3)")), "filtres mal formés ou non pris en charge refusés")
big = sso.tlv(0x30, b"x" * 300)
ok(sso.read_tlv(big)[2] == len(big) and raises(ValueError, sso.read_tlv, big[:-1]) and raises(ValueError, sso.read_tlv, b"\x30\x85\x00\x00\x00\x00\x01") and raises(ValueError, sso.read_tlv, b"\x30"), "longueurs BER longues lues ; messages tronqués ou longueurs absurdes refusés")

# ------------------------------------------------------------------ annuaire simulé
sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", tmp + "/ldap.key", "-out", tmp + "/ldap.crt", "-days", "2", "-subj", "/CN=ad.test", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost")
CA = open(tmp + "/ldap.crt").read()
U = lambda dn, sam, pw, groups=(), **kw: dict(dn=dn, pw=pw, attrs=dict({"samaccountname": [sam], "displayname": [sam.title() + " Test"], "cn": [sam.title()], "mail": [sam + "@corp.local"], "memberof": list(groups)}, **kw))
USERS = [U("CN=Alice,OU=Users,DC=corp,DC=local", "alice", "alice-pw", ["CN=OllamaAdmins,OU=Groups,DC=corp,DC=local"]),
         U("CN=Bob,OU=Users,DC=corp,DC=local", "bob", "bob-pw", ["CN=Staff,OU=Groups,DC=corp,DC=local"]),
         U("CN=Carl,OU=Users,DC=corp,DC=local", "carl", "carl-pw"),
         U("CN=Dupe1,OU=Users,DC=corp,DC=local", "dupe", "x1"), U("CN=Dupe2,OU=Users,DC=corp,DC=local", "dupe", "x2"), U("CN=Dupe3,OU=Users,DC=corp,DC=local", "dupe", "x3"),
         U("CN=Dave,OU=Users,DC=corp,DC=local", "dave", "dave-pw")]
GROUPS = [dict(dn="cn=llm-users,ou=groups,dc=corp,dc=local", pw=None, attrs={"cn": ["llm-users"], "member": ["CN=Dave,OU=Users,DC=corp,DC=local"]})]
class Fake:
    def __init__(self, tls):
        self.tls, self.binds, self.searches = tls, [], []
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(tmp + "/ldap.crt", tmp + "/ldap.key"); self.ctx = ctx
        fake = self
        class H(socketserver.BaseRequestHandler):
            def handle(self): fake.serve(self.request)
        class S(socketserver.ThreadingTCPServer): daemon_threads = True; allow_reuse_address = True
        self.srv = S(("127.0.0.1", 0), H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def recv_msg(self, s):
        def rd(k):
            b = b""
            while len(b) < k:
                c = s.recv(k - len(b))
                if not c: raise EOFError
                b += c
            return b
        h = rd(2); ln = h[1]
        if ln & 0x80: lb = rd(ln & 0x7f); ln = int.from_bytes(lb, "big"); h += lb
        return h + rd(ln)
    def reply(self, s, mid, op, code=0, diag=""):
        s.sendall(sso.tlv(0x30, sso.enc_int(mid) + sso.tlv(op, sso.enc_int(code, 0x0a) + sso.enc_str("") + sso.enc_str(diag))))
    def match(self, f, at):
        tag, st, en = sso.read_tlv(f)
        if tag == 0x87: return bool(at.get(f[st:en].decode().lower()))
        ch = sso.children(f, st, en) if tag & 0x20 else []
        if tag == 0xA0: return all(self.match(sso.tlv(t, c), at) for t, c in ch)
        if tag == 0xA1: return any(self.match(sso.tlv(t, c), at) for t, c in ch)
        if tag == 0xA2: return not self.match(sso.tlv(ch[0][0], ch[0][1]), at)
        if tag == 0xA3: return ch[1][1].decode().lower() in [v.lower() for v in at.get(ch[0][1].decode().lower(), [])]
        return False
    def serve(self, s):
        try:
            if self.tls == "ldaps": s = self.ctx.wrap_socket(s, server_side=True)
            while True:
                msg = self.recv_msg(s); mid, op, c = sso.parse_message(msg)
                if op == 0x60:
                    it = sso.children(c, 0, len(c)); dn, pw = it[1][1].decode(), it[2][1].decode(); self.binds.append((dn, pw))
                    good = (dn == "" and pw == "") or (dn == "cn=svc,dc=corp,dc=local" and pw == "svcpw") or any(u["dn"] == dn and u["pw"] == pw for u in USERS)
                    self.reply(s, mid, 0x61, 0 if good else 49, "" if good else "invalid credentials")
                elif op == 0x77:
                    self.reply(s, mid, 0x78, 0)
                    if self.tls == "starttls": s = self.ctx.wrap_socket(s, server_side=True)
                elif op == 0x63:
                    t, st, en = sso.read_tlv(msg, 0); parts = sso.children(c, 0, len(c)); base = parts[0][1].decode(); size = sso.dec_int(parts[3][1])
                    off = 0
                    for i in range(6): off = sso.read_tlv(c, off)[2]
                    f_tag, fs, fe = sso.read_tlv(c, off); flt = c[off:fe]
                    self.searches.append((base, flt))
                    pool = [e for e in USERS + GROUPS if e["dn"].lower().endswith(base.lower())]
                    found = [e for e in pool if self.match(flt, e["attrs"])]
                    for e in found[:size or None]:
                        attrs = b"".join(sso.tlv(0x30, sso.enc_str(k) + sso.tlv(0x31, b"".join(sso.enc_str(v) for v in vs))) for k, vs in e["attrs"].items())
                        s.sendall(sso.tlv(0x30, sso.enc_int(mid) + sso.tlv(0x64, sso.enc_str(e["dn"]) + sso.tlv(0x30, attrs))))
                    self.reply(s, mid, 0x65, 4 if size and len(found) > size else 0)
                elif op == 0x42: return
        except (EOFError, OSError, ssl.SSLError): pass
        finally:
            try: s.close()
            except OSError: pass
def ldap_cfg(fake, tls, **over):
    return dict({"enabled": True, "host": "127.0.0.1", "port": fake.port, "tls": tls, "bind_dn": "cn=svc,dc=corp,dc=local", "bind_password": "svcpw", "base_dn": "dc=corp,dc=local",
                 "user_filter": "(sAMAccountName={user})", "group_attr": "memberOf", "group_base": "", "group_filter": "", "ca_pem": CA}, **over)

# --- 5. LDAP : connexion réelle (LDAPS, StartTLS, sans chiffrement)
for mode in ("ldaps", "starttls", "none"):
    F = Fake(mode); lc = ldap_cfg(F, mode)
    info = sso.ldap_login(lc, "alice", "alice-pw")
    ok(info["dn"] == "CN=Alice,OU=Users,DC=corp,DC=local" and info["login"] == "alice" and info["name"] == "Alice Test" and info["groups"] == ["CN=OllamaAdmins,OU=Groups,DC=corp,DC=local"] and info["mail"] == "alice@corp.local", "connexion LDAP en mode « %s » : compte trouvé, groupes lus (memberOf)" % mode)
    ok(F.binds[0] == ("cn=svc,dc=corp,dc=local", "svcpw") and F.binds[1] == ("CN=Alice,OU=Users,DC=corp,DC=local", "alice-pw"), "mode « %s » : recherche par le compte de service, puis connexion avec le mot de passe de l'utilisateur" % mode)
F = Fake("ldaps"); lc = ldap_cfg(F, "ldaps")
nb = len(F.binds)
ok(raises(sso.AuthFailed, sso.ldap_login, lc, "alice", "") and len(F.binds) == nb, "mot de passe vide : refusé sans même interroger l'annuaire (un « bind » sans mot de passe réussirait)")
ok(raises(sso.AuthFailed, sso.ldap_login, lc, "alice", "mauvais") and raises(sso.AuthFailed, sso.ldap_login, lc, "inconnu", "x") and raises(sso.AuthFailed, sso.ldap_login, lc, "", "x"), "mauvais mot de passe, compte inconnu, identifiant vide : refusés (même message)")
F.searches.clear()
ok(raises(sso.AuthFailed, sso.ldap_login, lc, "*)(sAMAccountName=*", "x") and F.searches[-1][1][0] == 0xA3 and b"*)(sAMAccountName=*" in F.searches[-1][1], "injection dans le filtre (*)(…) : la valeur reste une simple valeur d'égalité (un seul test, pas de filtre ajouté), aucun compte trouvé")
ok(raises(sso.AuthFailed, sso.ldap_login, lc, "dupe", "x1"), "identifiant qui correspond à plusieurs comptes : refusé (jamais le premier venu)")
ok(raises(ValueError, sso.ldap_login, ldap_cfg(F, "ldaps", bind_password="faux"), "alice", "alice-pw") and not raises(sso.AuthFailed, lambda: 0), "compte de service refusé : erreur de configuration (pas un refus d'utilisateur)")
try: sso.ldap_login(ldap_cfg(F, "ldaps", bind_password="faux"), "alice", "alice-pw")
except sso.AuthFailed: ok(False, "compte de service refusé ne doit pas passer pour un mauvais mot de passe")
except ValueError as e: ok("compte de service" in str(e), "message d'erreur explicite pour l'administrateur")
try: sso.ldap_login(ldap_cfg(F, "ldaps", ca_pem=""), "alice", "alice-pw"); ok(False, "certificat inconnu accepté")
except sso.AuthFailed: ok(False, "certificat inconnu : mauvaise exception")
except ValueError as e: ok("chiffrée" in str(e), "certificat de l'annuaire non reconnu : connexion refusée (la vérification TLS est réelle)")
try: sso.ldap_login(ldap_cfg(F, "ldaps", port=1), "alice", "alice-pw"); ok(False, "annuaire injoignable accepté")
except sso.AuthFailed: ok(False, "annuaire injoignable : mauvaise exception")
except ValueError as e: ok("injoignable" in str(e), "annuaire injoignable : erreur claire, pas un refus d'utilisateur")
g = sso.ldap_login(ldap_cfg(F, "ldaps", group_attr="", group_base="ou=groups,dc=corp,dc=local", group_filter="(member={dn})"), "dave", "dave-pw")
ok(g["groups"] == ["cn=llm-users,ou=groups,dc=corp,dc=local"], "groupes cherchés dans une branche dédiée (posixGroup / groupOfNames) avec le DN de l'utilisateur")
ok(sso.ldap_login(ldap_cfg(F, "ldaps"), "carl", "carl-pw")["groups"] == [], "utilisateur sans groupe : connexion LDAP valide, groupes vides")

# ------------------------------------------------------------------ console : stockage et comptes SSO
server.SSO_FILE = os.path.join(ETC, "sso.json"); server.AUDIT_FILE = os.path.join(tmp, "audit.jsonl")
server.save_users({"admin": dict(server.hash_password("Secret-123"), role="admin", linux=False, rev="r0", created=1, updated=1)})
sc = sso.config_clean({"ldap": ldap_cfg(F, "ldaps"), "roles": [{"group": "OllamaAdmins", "role": "admin"}, {"group": "Staff", "role": "utilisateur"}, {"group": "llm-users", "role": "utilisateur"}]})
server.sso_save(sc)
ok(oct(os.stat(server.SSO_FILE).st_mode & 0o777) == "0o600", "fichier de configuration SSO réservé à root (il contient les secrets)")
ok(server.sso_providers() == {"oidc": None, "ldap": True}, "page de connexion : seul l'annuaire est proposé quand OIDC est désactivé")
name, role, rec = server.sso_ldap_login("alice", "alice-pw")
ok(name == "ldap:alice" and role == "admin" and rec["sso"] == "ldap" and "hash" not in rec and "salt" not in rec and server.load_users()["ldap:alice"]["display"] == "Alice Test", "premier passage : compte « ldap:alice » créé, administrateur d'après son groupe, sans mot de passe local")
name, role, rec = server.sso_ldap_login("bob", "bob-pw")
ok(name == "ldap:bob" and role == "utilisateur", "groupe « Staff » → rôle utilisateur")
try: server.sso_ldap_login("carl", "carl-pw"); ok(False, "utilisateur sans groupe admis")
except PermissionError: ok("ldap:carl" not in server.load_users(), "utilisateur sans groupe autorisé : refusé et aucun compte créé")
c2 = server.sso_config(); c2["default_role"] = "utilisateur"; server.sso_save(c2)
ok(server.sso_ldap_login("carl", "carl-pw")[1] == "utilisateur", "avec un rôle par défaut « utilisateur », le même utilisateur entre (jamais administrateur)")
c2["default_role"] = ""; server.sso_save(c2)
sc3 = server.sso_config(); sc3["roles"][0]["role"] = "utilisateur"; server.sso_save(sc3)
ok(server.sso_ldap_login("alice", "alice-pw")[1] == "utilisateur" and server.load_users()["ldap:alice"]["role"] == "utilisateur", "rôle recalculé à chaque connexion : le groupe de l'annuaire change, le compte suit")
sc3["roles"][0]["role"] = "admin"; server.sso_save(sc3)
ok(server.sso_ldap_login("alice", "alice-pw")[1] == "admin", "rôle administrateur rétabli à la connexion suivante")
users = server.load_users(); rev0 = users["ldap:alice"]["rev"]
server.sso_ldap_login("alice", "alice-pw")
ok(server.load_users()["ldap:alice"]["rev"] == rev0, "reconnexion : la session ouverte ailleurs n'est pas invalidée")
ok(raises(ValueError, server.sso_upsert, "ldap", "alice", "admin", sub="CN=Autre,OU=Users,DC=corp,DC=local"), "un autre compte d'annuaire qui reprendrait le même identifiant est refusé (réattribution d'identifiant)")

# ------------------------------------------------------------------ fournisseur OIDC simulé
IDP = {"mode": "ok", "codes": {}, "token_req": None, "userinfo": {}, "calls": []}
class Idp(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, o, code=200):
        raw = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        IDP["calls"].append(self.path)
        if self.path == "/.well-known/openid-configuration":
            b = IDP["iss"]; self.out({"issuer": b, "authorization_endpoint": b + "/authorize", "token_endpoint": b + "/token", "jwks_uri": b + "/jwks", "userinfo_endpoint": b + "/userinfo",
                                      "id_token_signing_alg_values_supported": ["RS256"], "token_endpoint_auth_methods_supported": ["client_secret_post"]})
        elif self.path == "/jwks": self.out(JWKS)
        elif self.path == "/userinfo":
            self.out(IDP["userinfo"] if self.headers.get("Authorization") == "Bearer AT-1" else {"error": "invalid_token"}, 200 if self.headers.get("Authorization") == "Bearer AT-1" else 401)
        else: self.out({}, 404)
    def do_POST(self):
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()); f = lambda k: (form.get(k) or [""])[0]
        IDP["token_req"] = {k: f(k) for k in form}
        c = IDP["codes"].pop(f("code"), None)
        if IDP["mode"] == "token_error" or not c or f("client_secret") != "s3cret" or f("client_id") != CID or f("redirect_uri") != c["redirect_uri"] or sso.b64u(hashlib.sha256(f("code_verifier").encode()).digest()) != c["challenge"]:
            return self.out({"error": "invalid_grant", "error_description": "refusé"}, 400)
        claims = dict({"iss": IDP["iss"], "aud": CID, "exp": int(time.time()) + 600, "iat": int(time.time()), "nonce": c["nonce"]}, **c["claims"])
        mode = IDP["mode"]
        if mode == "wrong_nonce": claims["nonce"] = "autre"
        if mode == "wrong_aud": claims["aud"] = "autre-application"
        self.out({"access_token": "AT-1", "token_type": "Bearer", "id_token": jwt(KEY2 if mode == "bad_sig" else KEY, claims)})
idp = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Idp); IDP["iss"] = "http://127.0.0.1:%d" % idp.server_address[1]
threading.Thread(target=idp.serve_forever, daemon=True).start()
REDIR = "https://ollama.corp.local:8443"
oc = {"enabled": True, "name": "Entreprise", "issuer": IDP["iss"], "client_id": CID, "client_secret": "s3cret", "scopes": "openid profile email groups", "groups_claim": "groups", "redirect_base": REDIR}
cfg = server.sso_config(); cfg["oidc"] = dict(cfg["oidc"], **oc); server.sso_save(cfg)
ok(server.sso_providers() == {"oidc": "Entreprise", "ldap": True}, "page de connexion : bouton « Entreprise » et formulaire (annuaire)")
res = server.sso_test({"kind": "oidc"})
ok(res["ok"] and res["keys"] == 1 and res["issuer"] == IDP["iss"], "essai OIDC : découverte et clés du fournisseur lues")
IDP["iss_real"] = IDP["iss"]; IDP["iss"] = "http://127.0.0.1:1/autre"
server.sso_save(cfg)
ok(raises(ValueError, server.sso_test, {"kind": "oidc"}), "émetteur annoncé différent de l'émetteur configuré : refusé (confusion de fournisseur)")
IDP["iss"] = IDP["iss_real"]
tk = server.sso_test({"kind": "ldap"})
ok(tk["ok"] and tk["bound"] == "cn=svc,dc=corp,dc=local", "essai LDAP sans identifiant : connexion et compte de service")
tk = server.sso_test({"kind": "ldap", "user": "alice", "password": "alice-pw"})
ok(tk["role"] == "admin" and tk["groups"] and tk["dn"].startswith("CN=Alice") and not any("alice-pw" in str(v) for v in tk.values()), "essai LDAP avec un compte : groupes et rôle obtenus, mot de passe jamais renvoyé")
ok(raises(ValueError, server.sso_test, {"kind": "ldap", "user": "alice", "password": "faux"}) and raises(ValueError, server.sso_test, {"kind": "x"}), "essai LDAP avec un mauvais mot de passe ou un type inconnu : erreur")

# ------------------------------------------------------------------ vraies requêtes HTTP vers la console
httpd = server.make_server(0, server.Handler); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
def req(method, path, cookie="", body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = cookie
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    cookies = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    try: data = json.loads(raw or b"{}")
    except ValueError: data = {}
    return r.status, {k.lower(): v for k, v in r.getheaders()}, cookies, data
def reset(): server._failures.clear()
def begin():
    st, h, ck, _ = req("GET", "/sso/oidc/start")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(h.get("location", "")).query)
    return st, h, ck, q
def authorize(q, claims, cookie_state=None):
    code = "code-" + sso.b64u(os.urandom(6)); IDP["codes"][code] = {"nonce": q["nonce"][0], "challenge": q["code_challenge"][0], "redirect_uri": q["redirect_uri"][0], "claims": claims}
    return code
def callback(code, state, cookie=True, extra=""):
    return req("GET", "/sso/oidc/callback?code=%s&state=%s%s" % (code, state, extra), "ob_sso=%s" % state if cookie is True else (cookie or ""))
st, _, _, data = req("GET", "/api/sso/providers")
ok(st == 200 and data == {"oidc": "Entreprise", "ldap": True}, "liste des fournisseurs publique (sans session) et sans aucun détail de configuration")
reset(); IDP["mode"] = "ok"
st, h, ck, q = begin()
ok(st == 302 and h["location"].startswith(IDP["iss"] + "/authorize?") and q["state"] and q["nonce"] and q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == [REDIR + "/sso/oidc/callback"] and q["client_id"] == [CID], "début de connexion : redirection vers le fournisseur avec state, nonce, PKCE et l'adresse de retour configurée")
ok(any(c.startswith("ob_sso=" + q["state"][0]) and "HttpOnly" in c and "Secure" in c and "SameSite=Lax" in c and "Path=/sso" in c for c in ck), "le state est aussi posé dans un cookie court (HttpOnly, Secure) qui lie la connexion à ce navigateur")
code = authorize(q, {"sub": "u-alice", "preferred_username": "Alice", "name": "Alice Martin", "groups": ["OllamaAdmins"]})
st, h, ck, _ = callback(code, q["state"][0])
ses = next((c.split(";")[0] for c in ck if c.startswith("ob_session=") and not c.startswith("ob_session=;")), "")
ok(st == 302 and h["location"] == "/" and ses and any("HttpOnly" in c and "SameSite=Strict" in c for c in ck if c.startswith("ob_session=")) and any(c.startswith("ob_sso=;") for c in ck), "retour du fournisseur : session ouverte, cookie de liaison effacé, redirection vers la console")
tr = IDP["token_req"]
ok(tr["grant_type"] == "authorization_code" and tr["client_secret"] == "s3cret" and tr["redirect_uri"] == REDIR + "/sso/oidc/callback" and len(tr["code_verifier"]) >= 43, "échange du code : secret du client, adresse de retour et vérificateur PKCE envoyés au fournisseur")
st, _, _, data = req("GET", "/api/session", ses)
ok(st == 200 and data["user"] == "sso:alice" and data["role"] == "admin", "la session ouverte désigne le compte « sso:alice », administrateur d'après son groupe")
ok(server.load_users()["sso:alice"]["sub"] == "u-alice" and "hash" not in server.load_users()["sso:alice"], "compte créé avec l'identifiant stable du fournisseur (sub), sans mot de passe local")
st, h, ck, _ = callback(code, q["state"][0])
ok(h["location"] == "/?sso=state" and not any(c.startswith("ob_session=") and not c.startswith("ob_session=;") for c in ck), "rejeu du même retour (state déjà consommé) : refusé, aucune session")
reset(); st, h, ck, q = begin(); code = authorize(q, {"sub": "u-alice", "preferred_username": "Alice", "groups": ["OllamaAdmins"]})
ok(callback(code, q["state"][0], cookie=False)[1]["location"] == "/?sso=state", "retour sans le cookie de liaison (connexion lancée depuis un autre navigateur / CSRF de connexion) : refusé")
reset(); st, h, ck, q = begin(); code = authorize(q, {"sub": "u-alice", "preferred_username": "Alice", "groups": ["OllamaAdmins"]})
ok(callback(code, q["state"][0], cookie="ob_sso=autre")[1]["location"] == "/?sso=state", "cookie de liaison différent du state : refusé")
ok(callback("zzz", "inconnu")[1]["location"] == "/?sso=state" and callback("", "")[1]["location"] == "/?sso=state", "state inconnu ou paramètres absents : refusé")
reset(); st, h, ck, q = begin()
ok(callback("x", q["state"][0], extra="&error=access_denied")[1]["location"] == "/?sso=idp", "refus renvoyé par le fournisseur : retour à la page de connexion")
for mode, why in (("wrong_nonce", "nonce différent"), ("wrong_aud", "jeton destiné à une autre application"), ("bad_sig", "signature d'une autre clé"), ("token_error", "échange du code refusé")):
    reset(); IDP["mode"] = mode; st, h, ck, q = begin(); code = authorize(q, {"sub": "u-evil", "preferred_username": "Evil", "groups": ["OllamaAdmins"]})
    st, h, ck, _ = callback(code, q["state"][0])
    ok(h["location"] == "/?sso=idp" and "sso:evil" not in server.load_users() and not any(c.startswith("ob_session=") and not c.startswith("ob_session=;") for c in ck), "%s : connexion refusée, aucun compte créé" % why)
IDP["mode"] = "ok"
reset(); st, h, ck, q = begin(); code = authorize(q, {"sub": "u-zed", "preferred_username": "Zed", "groups": ["Inconnu"]})
ok(callback(code, q["state"][0])[1]["location"] == "/?sso=denied" and "sso:zed" not in server.load_users(), "aucun groupe autorisé : refus explicite, aucun compte créé")
reset(); IDP["userinfo"] = {"sub": "u-bea", "groups": ["Staff"]}
st, h, ck, q = begin(); code = authorize(q, {"sub": "u-bea", "preferred_username": "Bea", "email": "bea@corp.local"})
st, h, ck, _ = callback(code, q["state"][0])
ok(h["location"] == "/" and server.load_users()["sso:bea"]["role"] == "utilisateur", "groupes absents du jeton d'identité : lus auprès de l'endpoint userinfo (Staff → utilisateur)")
reset(); IDP["userinfo"] = {"sub": "AUTRE-SUB", "groups": ["OllamaAdmins"]}
st, h, ck, q = begin(); code = authorize(q, {"sub": "u-cy", "preferred_username": "Cy"})
ok(callback(code, q["state"][0])[1]["location"] == "/?sso=denied" and "sso:cy" not in server.load_users(), "userinfo d'une autre personne (sub différent) : ses groupes ne sont pas pris en compte")
reset(); st, h, ck, q = begin(); code = authorize(q, {"sub": "u-USURPATEUR", "preferred_username": "alice", "groups": ["OllamaAdmins"]})
ok(callback(code, q["state"][0])[1]["location"] == "/?sso=user" and server.load_users()["sso:alice"]["sub"] == "u-alice", "même identifiant affiché mais « sub » différent : refusé, le compte existant n'est pas repris")
reset()
for i in range(5):
    st, h, ck, q = begin(); callback("x", q["state"][0], cookie=False)
st, h, ck, q = begin()
ok(h.get("location") == "/?sso=idp" and "state" not in q, "après 5 échecs depuis la même adresse : nouvelles connexions refusées un moment")
reset()
oc_off = server.sso_config(); oc_off["oidc"]["enabled"] = False; server.sso_save(oc_off)
st, h, ck, q = begin()
ok(h["location"] == "/?sso=config", "OIDC désactivé : le point d'entrée renvoie vers la page de connexion avec une erreur de configuration")
server.sso_save(dict(oc_off, oidc=dict(oc_off["oidc"], enabled=True)))

# --- connexion par le formulaire (annuaire) et comptes locaux
reset()
login = lambda u, p: req("POST", "/api/login", body={"user": u, "password": p})
st, h, ck, data = login("bob", "bob-pw")
ok(st == 200 and data["user"] == "ldap:bob" and data["role"] == "utilisateur" and any(c.startswith("ob_session=") for c in ck), "formulaire : identifiant et mot de passe de l'annuaire acceptés, compte « ldap:bob »")
st, h, ck, data = login("alice", "alice-pw")
adm = next(c.split(";")[0] for c in ck if c.startswith("ob_session="))
ok(st == 200 and data["role"] == "admin", "administrateur d'après son groupe d'annuaire")
st, _, _, data = login("bob", "faux")
ok(st == 403 and data["error"] == "Identifiant ou mot de passe incorrect.", "mauvais mot de passe de l'annuaire : message générique")
st, _, _, data = login("carl", "carl-pw")
ok(st == 403 and "groupe autorisé" in data["error"], "mot de passe correct mais aucun groupe autorisé : refus avec explication")
st, _, _, data = login("ldap:alice", "alice-pw"); ok(st == 403, "saisir le nom interne « ldap:alice » ne permet pas de contourner : refusé")
st, _, _, data = login("admin", "Secret-123")
ok(st == 200 and data["user"] == "admin" and data["role"] == "admin", "le compte local d'urgence continue de fonctionner à côté de l'annuaire")
reset(); down = server.sso_config(); down["ldap"]["port"] = 1; server.sso_save(down)
st, _, _, data = login("admin", "Secret-123"); ok(st == 200, "annuaire en panne : le compte local se connecte toujours")
st, _, _, data = login("bob", "bob-pw"); ok(st == 403 and data["error"] == "Identifiant ou mot de passe incorrect.", "annuaire en panne : refus générique (la panne est dans le journal, pas dans la réponse)")
server.sso_save({"ldap": sc["ldap"], "roles": sc["roles"]})
reset()
ok(any("ldap" in e["detail"] for e in server.audit_entries() if e["path"] == "/api/login" and e["ok"]), "connexions par l'annuaire consignées dans le journal d'audit (via=ldap)")

# --- gestion des comptes SSO
server.session_get_real = server.session_get
users_list = req("GET", "/api/users", adm)[3]
rows = {u["user"]: u for u in users_list["users"]} if "users" in users_list else {u["user"]: u for u in users_list}
ok(rows["ldap:bob"]["sso"] == "ldap" and rows["admin"]["sso"] == "" and rows["sso:alice"]["display"] == "Alice Martin", "liste des comptes : origine (annuaire / SSO) et nom affiché")
st, _, _, d = req("POST", "/api/users/update", adm, {"user": "ldap:bob", "role": "admin"})
ok(st == 400 and "annuaire" in d["error"], "rôle d'un compte d'annuaire non modifiable à la main (il suit les groupes)")
st, _, _, d = req("POST", "/api/users/update", adm, {"user": "ldap:bob", "password": "NouveauMdp-123"})
ok(st == 400 and "hash" not in server.load_users()["ldap:bob"], "mot de passe local impossible à poser sur un compte d'annuaire")
st, _, _, d = req("POST", "/api/password", adm.replace(adm.split("=")[1], req("POST", "/api/login", body={"user": "bob", "password": "bob-pw"})[2][0].split(";")[0].split("=")[1]), {"current": "bob-pw", "new": "NouveauMdp-123"})
ok(st == 403 and "hash" not in server.load_users()["ldap:bob"], "un compte d'annuaire ne peut pas non plus se créer un mot de passe local par « Mon compte »")
st, _, _, d = req("POST", "/api/users/update", adm, {"user": "admin", "role": "utilisateur"})
ok(st == 400, "le dernier administrateur local ne peut pas être rétrogradé, même s'il existe des administrateurs d'annuaire")
st, _, _, d = req("POST", "/api/users/delete", adm, {"user": "admin"})
ok(st == 400, "ni supprimé")
st, _, _, d = req("POST", "/api/users/delete", adm, {"user": "ldap:bob"})
ok(st == 200 and "ldap:bob" not in server.load_users() and login("bob", "bob-pw")[0] == 200 and "ldap:bob" in server.load_users(), "suppression d'un compte d'annuaire : il est recréé à sa prochaine connexion s'il y a toujours droit")
st, _, _, d = req("GET", "/api/sso/config", adm)
raw = json.dumps(d)
ok(st == 200 and "s3cret" not in raw and "svcpw" not in raw and d["oidc"]["client_secret_set"] and d["ldap"]["bind_password_set"] and d["oidc"]["redirect_uri"] == REDIR + "/sso/oidc/callback", "configuration lue par la console : aucun secret, adresse de retour à déclarer chez le fournisseur")
st, _, _, d = req("GET", "/api/sso/config", "")
ok(st == 401, "configuration SSO illisible sans session")
st, _, _, d = req("POST", "/api/sso/config", adm, {"oidc": {"enabled": True, "issuer": "http://", "client_id": "x", "client_secret": "y", "redirect_base": "https://z"}, "ldap": {}, "roles": []})
ok(st == 400 and server.sso_config()["oidc"]["issuer"] == IDP["iss"], "configuration invalide refusée sans modifier l'existante")
st, _, _, d = req("POST", "/api/sso/config", adm, {"oidc": {"name": "Portail RH"}})
ok(st == 200 and server.sso_config()["oidc"]["name"] == "Portail RH" and server.sso_config()["oidc"]["client_secret"] == "s3cret", "enregistrement partiel : le secret déjà enregistré est conservé")
st, _, _, d = req("POST", "/api/sso/test", adm, {"kind": "ldap"})
ok(st == 200 and d["ok"], "essai depuis la console")
print("\n%d vérifications réussies." % n)
