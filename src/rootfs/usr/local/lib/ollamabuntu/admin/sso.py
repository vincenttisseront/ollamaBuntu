#!/usr/bin/env python3
"""OllamaBuntu - connexion unique (SSO) : OpenID Connect (code d'autorisation + PKCE) et annuaire LDAP / Active Directory.
Bibliothèque standard de Python uniquement (l'appliance n'installe aucune dépendance) : la vérification des jetons RS256 et le client LDAP
sont écrits ici ; ils ne parlent qu'au réseau quand la console le leur demande et se testent avec un fournisseur et un annuaire simulés.

Principes de sécurité :
- OIDC : « state » lié au navigateur par un cookie, « nonce », PKCE S256, signature RS256/384/512 vérifiée avec les clés publiques du fournisseur,
  « iss », « aud », « azp », « exp » contrôlés ; l'algorithme « none » et les en-têtes jku/x5u sont ignorés ; adresses https obligatoires.
- LDAP : mot de passe vide refusé (sinon un « bind » sans authentification réussit), identifiant échappé dans le filtre (RFC 4515),
  LDAPS ou StartTLS avec vérification du certificat (autorité propre à l'entreprise acceptée), un seul compte trouvé exigé.
- Les rôles viennent des groupes du fournisseur ; sans groupe reconnu et sans rôle par défaut, la connexion est refusée."""
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import time
import urllib.parse

ALLOW_HTTP = os.environ.get("OB_SSO_ALLOW_HTTP") == "1"   # essais seulement : jamais en production
ROLES = ("admin", "utilisateur")
MAX_RULES = 50


class AuthFailed(ValueError):
    """Identifiants refusés (ou compte introuvable / ambigu) : message générique pour l'utilisateur."""


# ------------------------------------------------------------------ utilitaires ---
def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    s = str(s)
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _pem_ctx(ca_pem):
    ctx = ssl.create_default_context()
    if ca_pem:
        try:
            ctx.load_verify_locations(cadata=ca_pem)
        except (ssl.SSLError, ValueError):
            raise ValueError("certificat d'autorité illisible (format PEM attendu)")
    return ctx


def https_url(u, what="adresse"):
    u = str(u or "").strip()
    p = urllib.parse.urlsplit(u)
    if p.scheme not in (("https", "http") if ALLOW_HTTP else ("https",)) or not p.hostname or p.username or p.password:
        raise ValueError("%s : une adresse https:// est exigée" % what)
    return u


# ------------------------------------------------------------------ configuration ---
OIDC_DEFAULT = {"enabled": False, "name": "SSO", "issuer": "", "client_id": "", "client_secret": "", "scopes": "openid profile email",
                "groups_claim": "groups", "redirect_base": "", "ca_pem": ""}
LDAP_DEFAULT = {"enabled": False, "host": "", "port": 636, "tls": "ldaps", "bind_dn": "", "bind_password": "", "base_dn": "",
                "user_filter": "(sAMAccountName={user})", "group_attr": "memberOf", "group_base": "", "group_filter": "", "ca_pem": ""}
DEFAULTS = {"oidc": OIDC_DEFAULT, "ldap": LDAP_DEFAULT, "roles": [], "default_role": ""}


def _txt(d, k, cur, maxlen, label, required=False):
    v = " ".join(str(d.get(k, cur.get(k, ""))).split()) if k not in ("ca_pem",) else str(d.get(k, cur.get(k, "")) or "").strip()
    if len(v) > maxlen or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", v):
        raise ValueError("%s : %d caractères au plus" % (label, maxlen))
    if required and not v:
        raise ValueError("%s : champ obligatoire" % label)
    return v


def config_clean(data, cur=None):
    """Valide la configuration complète (ValueError si invalide). Un mot de passe / secret vide garde la valeur actuelle."""
    cur = json.loads(json.dumps(cur or DEFAULTS))
    for sec in ("oidc", "ldap"):
        for k, v in DEFAULTS[sec].items():
            cur.setdefault(sec, {}).setdefault(k, v)
    data = data if isinstance(data, dict) else {}
    out = {"oidc": dict(cur["oidc"]), "ldap": dict(cur["ldap"])}
    o, d = out["oidc"], data.get("oidc") if isinstance(data.get("oidc"), dict) else {}
    o["enabled"] = bool(d.get("enabled", o["enabled"]))
    o["name"] = _txt(d, "name", o, 30, "nom du bouton") or "SSO"
    o["issuer"] = _txt(d, "issuer", o, 300, "émetteur (issuer)")
    o["client_id"] = _txt(d, "client_id", o, 200, "identifiant client")
    if d.get("client_secret"):
        o["client_secret"] = _txt(d, "client_secret", o, 500, "secret client")
    o["scopes"] = _txt(d, "scopes", o, 200, "scopes") or "openid"
    if "openid" not in o["scopes"].split():
        raise ValueError("scopes : « openid » est obligatoire")
    o["groups_claim"] = _txt(d, "groups_claim", o, 100, "revendication des groupes") or "groups"
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", o["groups_claim"]):
        raise ValueError("revendication des groupes : caractères non autorisés")
    o["redirect_base"] = _txt(d, "redirect_base", o, 200, "adresse publique de la console").rstrip("/")
    o["ca_pem"] = _txt(d, "ca_pem", o, 20000, "certificat d'autorité")
    if o["enabled"]:
        https_url(o["issuer"], "émetteur")
        https_url(o["redirect_base"], "adresse publique de la console")
        if urllib.parse.urlsplit(o["redirect_base"]).path not in ("", "/") or urllib.parse.urlsplit(o["redirect_base"]).query:
            raise ValueError("adresse publique de la console : sans chemin (ex. https://ollama.exemple.fr)")
        if not o["client_id"] or not o["client_secret"]:
            raise ValueError("OIDC : identifiant et secret du client obligatoires")
    if o["ca_pem"]:
        _pem_ctx(o["ca_pem"])
    l, d = out["ldap"], data.get("ldap") if isinstance(data.get("ldap"), dict) else {}
    l["enabled"] = bool(d.get("enabled", l["enabled"]))
    l["host"] = _txt(d, "host", l, 253, "serveur LDAP")
    if l["host"] and not re.fullmatch(r"[A-Za-z0-9.\-]+|\[[0-9A-Fa-f:.]+\]", l["host"]):
        raise ValueError("serveur LDAP : nom d'hôte ou adresse IP")
    try:
        l["port"] = int(d.get("port", l["port"]))
    except (TypeError, ValueError):
        raise ValueError("port LDAP invalide")
    if not 1 <= l["port"] <= 65535:
        raise ValueError("port LDAP invalide")
    l["tls"] = str(d.get("tls", l["tls"]))
    if l["tls"] not in ("ldaps", "starttls", "none"):
        raise ValueError("chiffrement : ldaps, starttls ou none")
    l["bind_dn"] = _txt(d, "bind_dn", l, 500, "compte de service (DN)")
    if d.get("bind_password"):
        l["bind_password"] = _txt(d, "bind_password", l, 500, "mot de passe du compte de service")
    l["base_dn"] = _txt(d, "base_dn", l, 500, "base de recherche (DN)")
    l["user_filter"] = _txt(d, "user_filter", l, 500, "filtre de recherche de l'utilisateur") or "(sAMAccountName={user})"
    l["group_attr"] = _txt(d, "group_attr", l, 60, "attribut des groupes")
    l["group_base"] = _txt(d, "group_base", l, 500, "base des groupes")
    l["group_filter"] = _txt(d, "group_filter", l, 500, "filtre des groupes")
    l["ca_pem"] = _txt(d, "ca_pem", l, 20000, "certificat d'autorité")
    if l["ca_pem"]:
        _pem_ctx(l["ca_pem"])
    if l["group_attr"] and not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", l["group_attr"]):
        raise ValueError("attribut des groupes : nom d'attribut LDAP")
    if l["enabled"]:
        if not l["host"] or not l["base_dn"]:
            raise ValueError("LDAP : serveur et base de recherche obligatoires")
        if "{user}" not in l["user_filter"]:
            raise ValueError("filtre de l'utilisateur : doit contenir {user}")
        parse_filter(l["user_filter"].replace("{user}", "x"))   # valide la syntaxe
        if l["group_filter"]:
            parse_filter(l["group_filter"].replace("{dn}", "x").replace("{user}", "x"))
        if not l["group_attr"] and not (l["group_base"] and l["group_filter"]):
            raise ValueError("LDAP : indiquez l'attribut des groupes (ex. memberOf) ou une recherche de groupes")
    roles = data.get("roles", cur.get("roles", []))
    if not isinstance(roles, list) or len(roles) > MAX_RULES:
        raise ValueError("au plus %d correspondances groupe → rôle" % MAX_RULES)
    clean = []
    for r in roles:
        g, role = " ".join(str((r or {}).get("group", "")).split()), (r or {}).get("role")
        if not g or len(g) > 500 or role not in ROLES:
            raise ValueError("correspondance groupe → rôle invalide")
        clean.append({"group": g, "role": role})
    out["roles"] = clean
    dr = data.get("default_role", cur.get("default_role", ""))
    if dr not in ("", "utilisateur"):
        raise ValueError("rôle par défaut : aucun ou utilisateur (jamais administrateur)")
    out["default_role"] = dr
    if (out["oidc"]["enabled"] or out["ldap"]["enabled"]) and not clean and not dr:
        raise ValueError("indiquez au moins un groupe → rôle, ou un rôle par défaut : sinon personne ne pourrait se connecter")
    return out


def public_view(cfg):
    """Configuration sans secret : un booléen indique si le secret est enregistré."""
    cfg = json.loads(json.dumps(cfg))
    cfg["oidc"]["client_secret_set"] = bool(cfg["oidc"].pop("client_secret", ""))
    cfg["ldap"]["bind_password_set"] = bool(cfg["ldap"].pop("bind_password", ""))
    for sec in ("oidc", "ldap"):
        cfg[sec]["ca_set"] = bool(cfg[sec].get("ca_pem"))
    return cfg


# ------------------------------------------------------------------ rôles ---
def dn_cn(dn):
    m = re.match(r"(?i)\s*cn=((?:[^,\\]|\\.)+)", str(dn))
    return m.group(1).replace("\\,", ",").strip() if m else None


def group_keys(groups):
    """Formes comparables d'un groupe : valeur entière et, pour un DN, son nom commun (CN)."""
    keys = set()
    for g in groups or []:
        g = str(g).strip().lower()
        if g:
            keys.add(g)
            cn = dn_cn(g)
            if cn:
                keys.add(cn.lower())
    return keys


def role_for(groups, rules, default=""):
    """Rôle accordé selon les groupes : administrateur si un groupe administrateur correspond, sinon utilisateur, sinon le rôle par défaut (ou None)."""
    have = group_keys(groups)
    hits = [r["role"] for r in rules or [] if r["group"].strip().lower() in have]
    if "admin" in hits:
        return "admin"
    if hits:
        return "utilisateur"
    return default or None


def account_name(prefix, raw):
    """Nom de compte local d'un utilisateur SSO : préfixé (« ldap: », « sso: ») pour ne jamais être confondu avec un compte local."""
    s = re.sub(r"[^a-z0-9._@+-]+", "_", str(raw or "").strip().lower())[:60].strip("_")
    return "%s:%s" % (prefix, s) if s else None


# ------------------------------------------------------------------ OpenID Connect ---
def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    return verifier, b64u(hashlib.sha256(verifier.encode()).digest())


def auth_url(endpoint, client_id, redirect_uri, scopes, state, nonce, challenge):
    q = urllib.parse.urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": scopes, "state": state,
                                "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"})
    return endpoint + ("&" if "?" in endpoint else "?") + q


def fetch(url, data=None, headers=None, ca_pem="", timeout=10, limit=1 << 20):
    """GET ou POST (formulaire) vers le fournisseur : https seulement, aucune redirection suivie, réponse bornée. Retourne (statut, octets)."""
    https_url(url)
    p = urllib.parse.urlsplit(url)
    ctx = _pem_ctx(ca_pem) if p.scheme == "https" else None
    conn = (http.client.HTTPSConnection(p.hostname, p.port or 443, timeout=timeout, context=ctx) if p.scheme == "https"
            else http.client.HTTPConnection(p.hostname, p.port or 80, timeout=timeout))
    try:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        h = {"Accept": "application/json", "User-Agent": "OllamaBuntu-SSO"}
        if body is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        h.update(headers or {})
        conn.request("POST" if data is not None else "GET", (p.path or "/") + ("?" + p.query if p.query else ""), body=body, headers=h)
        r = conn.getresponse()
        raw = r.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("réponse du fournisseur trop volumineuse")
        return r.status, raw
    except (OSError, http.client.HTTPException) as e:
        raise ValueError("fournisseur injoignable : %s" % str(e)[:150])
    finally:
        conn.close()


def fetch_json(url, **kw):
    status, raw = fetch(url, **kw)
    try:
        doc = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        doc = {}
    if status >= 400:
        raise ValueError("le fournisseur a répondu %d%s" % (status, " : " + str(doc.get("error_description") or doc.get("error"))[:150] if isinstance(doc, dict) and (doc.get("error") or doc.get("error_description")) else ""))
    if not isinstance(doc, dict):
        raise ValueError("réponse du fournisseur inattendue")
    return doc


def discovery(cfg):
    """Document de découverte du fournisseur, avec les contrôles (émetteur identique, adresses https)."""
    iss = cfg["issuer"].rstrip("/")
    doc = fetch_json(iss + "/.well-known/openid-configuration", ca_pem=cfg.get("ca_pem", ""))
    if str(doc.get("issuer", "")).rstrip("/") != iss:
        raise ValueError("l'émetteur annoncé par le fournisseur ne correspond pas à celui configuré")
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        https_url(doc.get(k), k)
    if doc.get("userinfo_endpoint"):
        https_url(doc["userinfo_endpoint"], "userinfo_endpoint")
    return doc


def jwt_parts(token):
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise ValueError("jeton mal formé")
    try:
        header, claims = json.loads(b64u_dec(parts[0])), json.loads(b64u_dec(parts[1]))
        sig = b64u_dec(parts[2])
    except (ValueError, TypeError):
        raise ValueError("jeton mal formé")
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("jeton mal formé")
    return header, claims, (parts[0] + "." + parts[1]).encode("ascii"), sig


_DIGEST_INFO = {"RS256": (hashlib.sha256, bytes.fromhex("3031300d060960864801650304020105000420")),
                "RS384": (hashlib.sha384, bytes.fromhex("3041300d060960864801650304020205000430")),
                "RS512": (hashlib.sha512, bytes.fromhex("3051300d060960864801650304020305000440"))}


def rsa_verify(jwk, alg, signing_input, sig):
    """Signature PKCS#1 v1.5 (RSASSA) vérifiée avec la clé publique du fournisseur (module ≥ 2048 bits)."""
    if alg not in _DIGEST_INFO:
        return False
    try:
        n, e = int.from_bytes(b64u_dec(jwk["n"]), "big"), int.from_bytes(b64u_dec(jwk["e"]), "big")
    except (KeyError, ValueError, TypeError):
        return False
    k = (n.bit_length() + 7) // 8
    if n.bit_length() < 2048 or e < 3 or e % 2 == 0 or len(sig) != k:
        return False
    s = int.from_bytes(sig, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    h, prefix = _DIGEST_INFO[alg]
    t = prefix + h(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def pick_key(jwks, kid):
    keys = [k for k in (jwks or {}).get("keys", []) if isinstance(k, dict) and k.get("kty") == "RSA" and k.get("use") in (None, "sig")]
    if kid:
        return next((k for k in keys if k.get("kid") == kid), None)
    return keys[0] if len(keys) == 1 else None


def verify_id_token(token, jwks, issuer, client_id, nonce=None, now=None, leeway=120):
    """Vérifie signature et revendications d'un jeton d'identité ; retourne les revendications. ValueError sinon."""
    header, claims, signing_input, sig = jwt_parts(token)
    alg = header.get("alg")
    if alg not in _DIGEST_INFO:
        raise ValueError("algorithme de signature non accepté (%s)" % str(alg)[:20])
    key = pick_key(jwks, header.get("kid"))
    if not key:
        raise ValueError("clé de signature inconnue")
    if not rsa_verify(key, alg, signing_input, sig):
        raise ValueError("signature invalide")
    now = now if now is not None else time.time()
    if str(claims.get("iss", "")).rstrip("/") != issuer.rstrip("/"):
        raise ValueError("émetteur du jeton inattendu")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if client_id not in auds:
        raise ValueError("jeton destiné à une autre application")
    if len(auds) > 1 and claims.get("azp") != client_id:
        raise ValueError("partie autorisée (azp) inattendue")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp < now - leeway:
        raise ValueError("jeton expiré")
    iat = claims.get("iat")
    if isinstance(iat, (int, float)) and iat > now + leeway:
        raise ValueError("jeton émis dans le futur")
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), str(nonce)):
        raise ValueError("nonce inattendu")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise ValueError("jeton sans identifiant (sub)")
    return claims


def claim_values(claims, path):
    """Valeurs (liste de textes) d'une revendication, éventuellement imbriquée (« realm_access.roles »)."""
    v = claims
    for part in str(path).split("."):
        if not isinstance(v, dict) or part not in v:
            if isinstance(claims, dict) and path in claims:
                v = claims[path]
                break
            return []
        v = v[part]
    if isinstance(v, str):
        return [x for x in re.split(r"[,\s]+", v) if x] if "," in v else [v]
    if isinstance(v, list):
        return [str(x) for x in v if isinstance(x, (str, int))]
    return []


def token_request(cfg, disco, code, redirect_uri, verifier):
    """Échange du code d'autorisation contre les jetons (canal direct entre la console et le fournisseur)."""
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": cfg["client_id"], "code_verifier": verifier}
    headers = {}
    methods = disco.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    if "client_secret_post" in methods or "client_secret_basic" not in methods:
        data["client_secret"] = cfg["client_secret"]
    else:
        headers["Authorization"] = "Basic " + base64.b64encode(("%s:%s" % (urllib.parse.quote(cfg["client_id"], safe=""), urllib.parse.quote(cfg["client_secret"], safe=""))).encode()).decode()
    return fetch_json(disco["token_endpoint"], data=data, headers=headers, ca_pem=cfg.get("ca_pem", ""))


# ------------------------------------------------------------------ LDAP : encodage BER ---
def _len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def tlv(tag, content=b""):
    return bytes([tag]) + _len(len(content)) + content


def enc_int(n, tag=0x02):
    b = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True)
    return tlv(tag, b)


def enc_str(s, tag=0x04):
    return tlv(tag, s if isinstance(s, bytes) else str(s).encode("utf-8"))


def read_tlv(buf, pos=0):
    """(tag, début du contenu, fin du contenu) de l'élément à `pos` ; ValueError si tronqué ou incohérent."""
    if pos + 2 > len(buf):
        raise ValueError("message LDAP tronqué")
    tag, ln, pos = buf[pos], buf[pos + 1], pos + 2
    if ln & 0x80:
        nb = ln & 0x7F
        if nb == 0 or nb > 4 or pos + nb > len(buf):
            raise ValueError("longueur LDAP invalide")
        ln, pos = int.from_bytes(buf[pos:pos + nb], "big"), pos + nb
    if pos + ln > len(buf):
        raise ValueError("message LDAP tronqué")
    return tag, pos, pos + ln


def children(buf, start, end):
    out, pos = [], start
    while pos < end:
        tag, s, e = read_tlv(buf, pos)
        out.append((tag, buf[s:e]))
        pos = e
    return out


def dec_int(b):
    return int.from_bytes(b, "big", signed=True) if b else 0


def escape_filter(s):
    """Échappement d'une valeur dans un filtre LDAP (RFC 4515) : *, (, ), \\ et NUL."""
    return "".join("\\%02x" % ord(c) if c in "*()\\\x00" else c for c in str(s))


def parse_filter(text):
    """Filtre LDAP (RFC 4515, sous-ensemble) → BER. Pris en charge : &, |, !, égalité, présence (attr=*), règle de correspondance étendue (attr:oid:=valeur)."""
    s = str(text).strip()
    pos = [0]

    def err():
        raise ValueError("filtre LDAP invalide : %s" % s[:80])

    def unescape(v):
        raw, out, i = v.encode("utf-8"), bytearray(), 0
        while i < len(raw):
            if raw[i] == 0x5C:
                h = raw[i + 1:i + 3]
                if not re.fullmatch(rb"[0-9a-fA-F]{2}", h):
                    err()
                out.append(int(h, 16))
                i += 3
            else:
                out.append(raw[i])
                i += 1
        return bytes(out)

    def item():
        if pos[0] >= len(s) or s[pos[0]] != "(":
            err()
        pos[0] += 1
        c = s[pos[0]] if pos[0] < len(s) else err()
        if c in "&|":
            pos[0] += 1
            subs = []
            while pos[0] < len(s) and s[pos[0]] == "(":
                subs.append(item())
            if not subs:
                err()
            out = tlv(0xA0 if c == "&" else 0xA1, b"".join(subs))
        elif c == "!":
            pos[0] += 1
            out = tlv(0xA2, item())
        else:
            end = s.find(")", pos[0])
            while end != -1 and s[end - 1] == "\\":
                end = s.find(")", end + 1)
            if end == -1:
                err()
            body = s[pos[0]:end]
            pos[0] = end
            m = re.fullmatch(r"([A-Za-z][A-Za-z0-9;.-]*)(?::(dn))?(?::([0-9.]+))?:=(.*)", body, re.S)
            if m and (m.group(3) or m.group(2)):
                parts = b""
                if m.group(3):
                    parts += enc_str(m.group(3), 0x81)
                parts += enc_str(m.group(1), 0x82) + enc_str(unescape(m.group(4)), 0x83)
                if m.group(2):
                    parts += tlv(0x84, b"\xff")
                out = tlv(0xA9, parts)
            else:
                m = re.fullmatch(r"([A-Za-z][A-Za-z0-9;.-]*)=(.*)", body, re.S)
                if not m:
                    err()
                if m.group(2) == "*":
                    out = enc_str(m.group(1), 0x87)
                elif "*" in m.group(2).replace("\\2a", "").replace("\\2A", ""):
                    raise ValueError("filtre LDAP : les jokers au milieu d'une valeur ne sont pas pris en charge")
                else:
                    out = tlv(0xA3, enc_str(m.group(1)) + enc_str(unescape(m.group(2))))
        if pos[0] >= len(s) or s[pos[0]] != ")":
            err()
        pos[0] += 1
        return out
    res = item()
    if pos[0] != len(s):
        err()
    return res


def bind_request(mid, dn, password):
    return tlv(0x30, enc_int(mid) + tlv(0x60, enc_int(3) + enc_str(dn) + enc_str(password, 0x80)))


def start_tls_request(mid):
    return tlv(0x30, enc_int(mid) + tlv(0x77, enc_str("1.3.6.1.4.1.1466.20037", 0x80)))


def unbind_request(mid):
    return tlv(0x30, enc_int(mid) + tlv(0x42))


def search_request(mid, base, flt, attrs, scope=2, size=0):
    op = enc_str(base) + enc_int(scope, 0x0A) + enc_int(0, 0x0A) + enc_int(size) + enc_int(10) + tlv(0x01, b"\x00") + parse_filter(flt) + tlv(0x30, b"".join(enc_str(a) for a in attrs))
    return tlv(0x30, enc_int(mid) + tlv(0x63, op))


def parse_message(buf):
    """Message LDAP → (identifiant, étiquette de l'opération, contenu de l'opération)."""
    tag, s, e = read_tlv(buf, 0)
    if tag != 0x30:
        raise ValueError("message LDAP invalide")
    items = children(buf, s, e)
    if len(items) < 2 or items[0][0] != 0x02:
        raise ValueError("message LDAP invalide")
    return dec_int(items[0][1]), items[1][0], items[1][1]


def parse_result(content):
    """LDAPResult → (code, diagnostic)."""
    it = children(content, 0, len(content))
    if len(it) < 3 or it[0][0] != 0x0A:
        raise ValueError("réponse LDAP invalide")
    return dec_int(it[0][1]), it[2][1].decode("utf-8", "replace")


def parse_entry(content):
    """SearchResultEntry → (dn, {attribut en minuscules: [valeurs]})."""
    it = children(content, 0, len(content))
    if len(it) < 2:
        raise ValueError("entrée LDAP invalide")
    attrs = {}
    for _, val in children(it[1][1], 0, len(it[1][1])):
        parts = children(val, 0, len(val))
        if len(parts) >= 2:
            attrs[parts[0][1].decode("utf-8", "replace").lower()] = [v.decode("utf-8", "replace") for _, v in children(parts[1][1], 0, len(parts[1][1]))]
    return it[0][1].decode("utf-8", "replace"), attrs


# ------------------------------------------------------------------ LDAP : connexion ---
class LdapConn:
    MAXMSG = 8 << 20

    def __init__(self, host, port, tls="ldaps", ca_pem="", timeout=8):
        self.mid = 0
        host = host.strip("[]")
        try:
            raw = socket.create_connection((host, port), timeout=timeout)
        except OSError as e:
            raise ValueError("annuaire injoignable : %s" % str(e)[:150])
        raw.settimeout(timeout)
        self.sock, self.host, self.ca_pem = raw, host, ca_pem
        try:
            if tls == "ldaps":
                self.sock = _pem_ctx(ca_pem).wrap_socket(raw, server_hostname=host)
            elif tls == "starttls":
                code, diag = self._call(start_tls_request(self._id()), 0x78)
                if code != 0:
                    raise ValueError("StartTLS refusé par l'annuaire : %s" % diag[:100])
                self.sock = _pem_ctx(ca_pem).wrap_socket(raw, server_hostname=host)
        except ssl.SSLError as e:
            self.close()
            raise ValueError("connexion chiffrée à l'annuaire impossible : %s" % str(e)[:150])
        except ValueError:
            self.close()
            raise
        except OSError as e:
            self.close()
            raise ValueError("annuaire injoignable : %s" % str(e)[:150])

    def _id(self):
        self.mid += 1
        return self.mid

    def _recv(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ValueError("connexion à l'annuaire interrompue")
            out += chunk
        return out

    def read_message(self):
        head = self._recv(2)
        if head[0] != 0x30:
            raise ValueError("réponse LDAP invalide")
        ln = head[1]
        if ln & 0x80:
            nb = ln & 0x7F
            if nb == 0 or nb > 4:
                raise ValueError("réponse LDAP invalide")
            lb = self._recv(nb)
            ln, head = int.from_bytes(lb, "big"), head + lb
        if ln > self.MAXMSG:
            raise ValueError("réponse LDAP trop volumineuse")
        return head + self._recv(ln)

    def _call(self, msg, expect):
        try:
            self.sock.sendall(msg)
            _, op, content = parse_message(self.read_message())
        except OSError as e:
            raise ValueError("annuaire injoignable : %s" % str(e)[:150])
        if op != expect:
            raise ValueError("réponse LDAP inattendue")
        return parse_result(content)

    def bind(self, dn, password):
        """(code, diagnostic) : 0 = authentifié."""
        return self._call(bind_request(self._id(), dn, password), 0x61)

    def search(self, base, flt, attrs, scope=2, size=0):
        mid = self._id()
        try:
            self.sock.sendall(search_request(mid, base, flt, attrs, scope, size))
        except OSError as e:
            raise ValueError("annuaire injoignable : %s" % str(e)[:150])
        out = []
        while True:
            try:
                got, op, content = parse_message(self.read_message())
            except OSError as e:
                raise ValueError("annuaire injoignable : %s" % str(e)[:150])
            if got != mid:
                continue
            if op == 0x64:
                out.append(parse_entry(content))
            elif op == 0x65:
                code, diag = parse_result(content)
                if code not in (0, 4):   # 4 = limite de taille atteinte : on garde ce qu'on a
                    raise ValueError("recherche LDAP refusée (code %d) : %s" % (code, diag[:100]))
                return out
            # 0x73 : références vers d'autres annuaires, ignorées

    def close(self):
        try:
            self.sock.sendall(unbind_request(self._id()))
        except (OSError, ValueError):
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def ldap_connect(cfg):
    return LdapConn(cfg["host"], cfg["port"], cfg["tls"], cfg.get("ca_pem", ""))


def ldap_login(cfg, username, password, connect=ldap_connect):
    """Authentifie un utilisateur de l'annuaire. Retourne {dn, login, name, mail, groups}. AuthFailed si refusé, ValueError si l'annuaire est mal réglé / injoignable."""
    if not username or not password or len(username) > 256 or len(password) > 1024 or "\x00" in username + password:
        raise AuthFailed("identifiants refusés")   # un mot de passe vide ferait réussir un « bind » anonyme : toujours refusé
    flt = cfg["user_filter"].replace("{user}", escape_filter(username))
    attrs = ["cn", "displayName", "mail", "memberOf", "sAMAccountName", "uid", "userPrincipalName"] + ([cfg["group_attr"]] if cfg.get("group_attr") else [])
    svc = connect(cfg)
    try:
        code, diag = svc.bind(cfg.get("bind_dn", ""), cfg.get("bind_password", "")) if cfg.get("bind_dn") else svc.bind("", "")
        if code != 0:
            raise ValueError("le compte de service est refusé par l'annuaire (code %d) : %s" % (code, diag[:100]))
        found = svc.search(cfg["base_dn"], flt, list(dict.fromkeys(attrs)), 2, 2)
        if len(found) != 1:
            raise AuthFailed("identifiants refusés")
        dn, at = found[0]
        groups = list(at.get((cfg.get("group_attr") or "").lower(), []))
        if cfg.get("group_base") and cfg.get("group_filter"):
            gflt = cfg["group_filter"].replace("{dn}", escape_filter(dn)).replace("{user}", escape_filter(username))
            groups += [g_dn for g_dn, _ in svc.search(cfg["group_base"], gflt, ["cn"], 2, 500)]
    finally:
        svc.close()
    usr = connect(cfg)
    try:
        code, _ = usr.bind(dn, password)
    finally:
        usr.close()
    if code != 0:
        raise AuthFailed("identifiants refusés")
    first = lambda k: (at.get(k) or [""])[0]
    login = first("samaccountname") or first("uid") or first("userprincipalname") or username
    return {"dn": dn, "login": login, "name": first("displayname") or first("cn") or login, "mail": first("mail"), "groups": groups}
