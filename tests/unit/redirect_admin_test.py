#!/usr/bin/env python3
"""Redirection de modèles côté console : validation des règles, routes HTTP, droits, audit, sauvegarde."""
import http.client, json, os, sys, tempfile, threading
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_STATE=os.path.join(tmp, "state"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import server, backup
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a)
    except ValueError as e: return str(e)
    return None
os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
server.AUDIT_FILE = os.path.join(tmp, "audit.jsonl")
server.save_users({"admin": dict(server.hash_password("Secret-123"), role="admin", linux=False, rev="r0", created=1, updated=1),
                   "jean": dict(server.hash_password("Secret-456"), role="utilisateur", linux=False, rev="r1", created=1, updated=1)})
server.ollama_json = lambda m, p, **k: (200, {"models": [{"name": "gemma4:12b"}, {"name": "hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M"}]})

ok(server.redirects_load() == [], "aucune règle au départ")
out = server.redirects_save({"rules": [{"from": " gemma4:12b ", "to": "hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M", "percent": 100}]})
ok(out == [{"from": "gemma4:12b", "to": "hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M", "percent": 100, "enabled": True}] and server.redirects_load() == out, "règle enregistrée (espaces retirés, active par défaut)")
ok(oct(os.stat(server.REDIRECT_CONF).st_mode & 0o777) == "0o644", "fichier lisible par le routeur (0644)")
ok("même que" in (raises(server.redirects_save, {"rules": [{"from": "a", "to": "a:latest"}]}) or ""), "modèle servi identique au modèle demandé : refusé (a == a:latest)")
ok("deux fois" in (raises(server.redirects_save, {"rules": [{"from": "a:1b", "to": "b:1b"}, {"from": "A:1B", "to": "c:1b"}]}) or ""), "deux règles pour le même modèle demandé : refusé")
ok("s'enchaînent" in (raises(server.redirects_save, {"rules": [{"from": "a:1b", "to": "b:1b"}, {"from": "b:1b", "to": "c:1b"}]}) or ""), "enchaînement a -> b -> c : refusé avec explication")
ok(raises(server.redirects_save, {"rules": [{"from": "a:1b", "to": "b:1b"}, {"from": "b:1b", "to": "c:1b", "enabled": False}]}) is None, "…mais une règle désactivée n'empêche pas d'en enregistrer une autre")
ok(raises(server.redirects_save, {"rules": [{"from": "", "to": "b"}]}) is not None and raises(server.redirects_save, {"rules": [{"from": "a", "to": ""}]}) is not None, "modèle vide : refusé")
ok(raises(server.redirects_save, {"rules": [{"from": "a", "to": "b", "percent": 0}]}) and raises(server.redirects_save, {"rules": [{"from": "a", "to": "b", "percent": 101}]}) and raises(server.redirects_save, {"rules": [{"from": "a", "to": "b", "percent": "x"}]}), "pourcentage hors 1 à 100 ou illisible : refusé")
ok(raises(server.redirects_save, {"rules": "x"}) and raises(server.redirects_save, {"rules": [{"from": "a", "to": "b"}] * 51}), "liste invalide ou de plus de 50 règles : refusé")
ok(raises(server.redirects_save, {"rules": [{"from": "a\nb", "to": "c"}]}) is not None, "saut de ligne dans un nom : refusé")
# cascade : conditions et repli
out = server.redirects_save({"rules": [{"from": "g:1b", "to": "p:1b", "short_chars": "2000", "no_tools": True, "no_images": True, "fallback": True}]})
ok(out == [{"from": "g:1b", "to": "p:1b", "percent": 100, "enabled": True, "short_chars": 2000, "no_tools": True, "no_images": True, "fallback": True}] and server.redirects_load() == out, "cascade : taille maximale, sans outils, sans images et repli enregistrés")
out = server.redirects_save({"rules": [{"from": "g:1b", "to": "p:1b", "short_chars": "", "no_tools": "oui", "fallback": False}]})
ok(out == [{"from": "g:1b", "to": "p:1b", "percent": 100, "enabled": True}], "conditions vides ou non booléennes : rien n'est enregistré (simple redirection)")
ok("caractères" in (raises(server.redirects_save, {"rules": [{"from": "a", "to": "b", "short_chars": "beaucoup"}]}) or "") and "1 à 1 000 000" in (raises(server.redirects_save, {"rules": [{"from": "a", "to": "b", "short_chars": 2_000_000}]}) or "") and raises(server.redirects_save, {"rules": [{"from": "a", "to": "b", "short_chars": -5}]}), "taille maximale invalide : refusée")
import router as _r
server.redirects_save({"rules": [{"from": "g:1b", "to": "p:1b", "short_chars": 300, "no_images": True, "fallback": True}]})
_r.REDIRECT_CONF = server.REDIRECT_CONF; _r._rdc.update(mtime=None, data={})
ok(_r.redirect_rules() == [(_r.norm("g:1b"), "p:1b", 100, {"short_chars": 300, "no_images": True}, True)], "ce que la console écrit est exactement ce que le routeur lit")
server.redirects_save({"rules": [{"from": "gemma4:12b", "to": "qwen3:14b", "percent": 25, "enabled": False}]})
v = server.redirects_view()
ok(v["models"] == ["gemma4:12b", "hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M"] and v["rules"][0]["to_installed"] is False and v["rules"][0]["percent"] == 25 and v["rules"][0]["enabled"] is False, "vue : modèles installés pour les listes, cible non installée signalée")
ok("redirects.json" in backup.FILES if hasattr(backup, "FILES") else "redirects.json" in open(os.path.join(LIB, "admin", "backup.py")).read(), "inclus dans la sauvegarde de configuration")

httpd = server.make_server(0, server.Handler); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
def req(method, path, cookie="", body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = cookie
    try:
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = c.getresponse(); out = r.read(); cookies = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    finally: c.close()
    try: return r.status, cookies, json.loads(out or b"{}")
    except ValueError: return r.status, cookies, {}
def login(u, p):
    st, ck, d = req("POST", "/api/login", body={"user": u, "password": p}); return next(c.split(";")[0] for c in ck if c.startswith("ob_session="))
adm, usr = login("admin", "Secret-123"), login("jean", "Secret-456")
st, _, d = req("GET", "/api/redirects", adm); ok(st == 200 and len(d["rules"]) == 1 and "models" in d, "GET /api/redirects")
ok(req("GET", "/api/redirects", usr)[0] == 403 and req("GET", "/api/redirects")[0] == 401, "réservé aux administrateurs")
st, _, d = req("POST", "/api/redirects/config", adm, {"rules": [{"from": "gemma4:12b", "to": "qwen3:14b", "percent": 50}]}); ok(st == 200 and d["rules"][0]["percent"] == 50, "POST /api/redirects/config")
ok(req("POST", "/api/redirects/config", adm, {"rules": [{"from": "a", "to": "a"}]})[0] == 400, "règle invalide : 400")
ok(req("POST", "/api/redirects/config", usr, {"rules": []})[0] == 403, "simple utilisateur : 403")
ok("Redirection de modèles" in open(server.AUDIT_FILE).read(), "modification consignée au journal d'audit")
print("\n%d vérifications réussies" % n)
