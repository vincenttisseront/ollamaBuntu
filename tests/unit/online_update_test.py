#!/usr/bin/env python3
"""Mise à jour en ligne (updater.py + points d'entrée de la console) : tests portables.

Un faux serveur GitHub local sert des releases signées avec une clé de test ; on vérifie la recherche des versions,
le téléchargement, la signature, les sommes, le contenu de l'archive, la protection contre les falsifications et
les routes de la console (réservées aux administrateurs). Nécessite : python3, openssl.
"""
import glob, hashlib, http.server, io, json, os, shutil, ssl, subprocess, sys, tarfile, tempfile, threading, time
import http.client

TMP = tempfile.mkdtemp(prefix="ob-online-")
HERE = os.path.dirname(os.path.abspath(__file__))
ADMIN = os.path.join(HERE, "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin")
n = [0]


def check(cond, msg):
    n[0] += 1
    print(("[%02d] OK   - " if cond else "[%02d] ÉCHEC - ") % n[0] + msg, flush=True)
    if not cond:
        shutil.rmtree(TMP, ignore_errors=True)
        sys.exit(1)


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


# --- clés de test (la clé de production n'est jamais utilisée ici)
KEY, KEY2 = os.path.join(TMP, "k1.pem"), os.path.join(TMP, "k2.pem")
for k in (KEY, KEY2):
    sh("openssl", "genpkey", "-algorithm", "ed25519", "-out", k)
PUB = os.path.join(TMP, "pub.pem")
sh("openssl", "pkey", "-in", KEY, "-pubout", "-out", PUB)


def make_bundle(version, ollama="v0.50.0", extra=None, bad_version_file=None):
    buf = io.BytesIO()
    files = {"VERSION": (bad_version_file or version) + "\n", "OLLAMA_VERSION": ollama + "\n", "LANG": "fr\n", "ONLINE": "1\n",
             "rootfs.tar": "faux", "update.sh": "#!/bin/bash\necho \"$@\" > \"$OB_TEST_OUT\"\nls \"$4\" >> \"$OB_TEST_OUT\"\nexit ${OB_TEST_RC:-0}\n"}
    files.update(extra or {})
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            if isinstance(content, tarfile.TarInfo):
                tf.addfile(content)
                continue
            data = content.encode()
            ti = tarfile.TarInfo(name); ti.size = len(data); ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def sign(sums, key=KEY):
    p = os.path.join(TMP, "sums.tmp")
    open(p, "wb").write(sums)
    out = os.path.join(TMP, "sig.tmp")
    sh("openssl", "pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", p, "-out", out)
    return open(out, "rb").read()


# --- faux GitHub
ASSETS = {}      # id -> octets
RELEASES = []    # réponse de /releases
SEEN_AUTH = []
_next = [100]


def add_release(version, *, prerelease=False, draft=False, bundle=None, key=KEY, tamper=False, drop=None, tag=None):
    bundle = bundle if bundle is not None else make_bundle(version)
    name = "ollamabuntu-update-%s.tar.gz" % version
    sums = ("%s  %s\n" % (hashlib.sha256(bundle).hexdigest(), name)).encode()
    sig = sign(sums, key)
    if tamper:
        bundle = bundle + b"x"
    assets = []
    for nm, data in ((name, bundle), ("SHA256SUMS", sums), ("SHA256SUMS.sig", sig)):
        if nm == drop:
            continue
        _next[0] += 1
        ASSETS[_next[0]] = data
        assets.append({"id": _next[0], "name": nm, "size": len(data), "state": "uploaded"})
    RELEASES.append({"tag_name": tag or "v" + version, "name": "Version " + version, "body": "Notes de " + version, "draft": draft,
                     "prerelease": prerelease, "html_url": "https://github.com/o/r/releases/tag/v" + version,
                     "published_at": "2026-11-10T09:00:00Z", "assets": assets})


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        SEEN_AUTH.append(self.headers.get("Authorization"))
        if self.path.startswith("/repos/o/r/releases?"):
            body = json.dumps(RELEASES).encode()
        elif self.path.startswith("/repos/o/r/releases/assets/"):
            body = ASSETS.get(int(self.path.rsplit("/", 1)[1]))
            if body is None:
                self.send_error(404); return
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

# --- environnement de l'appliance simulée (avant d'importer les modules)
ETC, STATE, LIB, CACHE = (os.path.join(TMP, d) for d in ("etc", "state", "lib", "cache"))
for d in (ETC, STATE, LIB):
    os.makedirs(d)
open(os.path.join(ETC, "version"), "w").write("2026.01.01-0000\n")
json.dump({"ollama": "v0.50.0"}, open(os.path.join(ETC, "build-info.json"), "w"))
json.dump({"repo": "o/r"}, open(os.path.join(LIB, "update-defaults.json"), "w"))
FAKE_OLLAMA = os.path.join(TMP, "ollama")
open(FAKE_OLLAMA, "w").write("#!/bin/sh\n"); os.chmod(FAKE_OLLAMA, 0o755)
os.environ.update(OB_ETC=ETC, OB_STATE=STATE, OB_LIB=LIB, OB_UPDATE_CACHE=CACHE, OB_GITHUB_API="http://127.0.0.1:%d" % PORT,
                  OB_UPDATE_PUBKEY=PUB, OB_OLLAMA_BIN=FAKE_OLLAMA, OB_OLLAMA_LIB=os.path.join(TMP, "nolib"), OB_UPDATE_LOCK=os.path.join(TMP, "lock"),
                  OB_TEST_OUT=os.path.join(TMP, "update-args.txt"), OB_UPDATE_NO_ROOT_CHECK="1", OB_JOBS=os.path.join(STATE, "jobs"), PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True
sys.path.insert(0, ADMIN)
import updater  # noqa: E402

OUT = os.environ["OB_TEST_OUT"]


def apply(**kw):
    """apply() en capturant la sortie ; rend (code, texte, exception)."""
    old, buf = sys.stdout, io.StringIO()
    sys.stdout = buf
    try:
        return updater.apply(**kw), buf.getvalue(), None
    except updater.UpdateError as e:
        return None, buf.getvalue(), str(e)
    finally:
        sys.stdout = old


# ---------------------------------------------------------------- versions
check(updater.newer("2026.11.10-1200", "2026.01.01-0000") and not updater.newer("2026.01.01-0000", "2026.01.01-0000")
      and not updater.newer("2025.12.31-2359", "2026.01.01-0000") and updater.newer("2026.01.01-0000", "?") and not updater.newer("n'importe quoi", "2026.01.01-0000"),
      "comparaison des versions AAAA.MM.JJ-HHMM (plus récente, identique, plus ancienne, inconnue, invalide)")

# ---------------------------------------------------------------- choix de la release
add_release("2026.03.01-0900")
add_release("2026.06.01-0900", prerelease=True)
add_release("2026.07.01-0900", draft=True)
add_release("2026.08.01-0900", drop="SHA256SUMS.sig")      # signature absente : release ignorée
add_release("2026.09.01-0900", tag="v2026.09.01-0900-rc")  # tag mal formé : ignoré
add_release("2026.09.15-0900", tag="latest")               # tag mal formé : ignoré
st = updater.pick_release(RELEASES, "stable")
check(st and st["version"] == "2026.03.01-0900", "canal stable : préversions, brouillons, releases sans signature et tags mal formés ignorés (retenu : %s)" % (st and st["version"]))
pv = updater.pick_release(RELEASES, "preview")
check(pv and pv["version"] == "2026.06.01-0900", "canal préversions : la plus récente valide (%s)" % (pv and pv["version"]))
check(updater.pick_release(RELEASES, "stable", "v2026.06.01-0900")["prerelease"], "une version précise peut être demandée explicitement")
check(updater.pick_release([], "stable") is None, "aucune release : pas de version")

# ---------------------------------------------------------------- réglages
check(updater.load_config() == {"repo": "o/r", "channel": "stable", "auto_check": False}, "réglages par défaut : dépôt livré avec l'appliance, canal stable, vérification automatique désactivée")
for bad in ({"repo": "pas un dépôt"}, {"repo": "../etc/passwd"}, {"repo": "a/b/c"}, {"channel": "nightly"}, {"token": "court"}, {"token": "x" * 30 + " ; rm -rf /"}):
    try:
        updater.save_config(bad); ok = False
    except ValueError:
        ok = True
    check(ok, "réglage refusé : %s" % json.dumps(bad)[:50])
c = updater.save_config({"repo": "https://github.com/o/r.git", "channel": "stable", "auto_check": True, "token": "github_pat_" + "A1b2C3d4" * 4})
check(c["repo"] == "o/r" and c["auto_check"] is True, "adresse GitHub complète normalisée en « propriétaire/dépôt »")
mode = os.stat(updater.TOKEN_FILE).st_mode & 0o777
check(mode == 0o600, "fichier du jeton en 0600 (%o)" % mode)
check("github_pat_" not in json.dumps(updater.view()) and updater.view()["token_set"] is True, "le jeton n'apparaît jamais dans la vue renvoyée à la console")
check("github_pat_" not in open(updater.CONF_FILE).read(), "le jeton n'est pas dans le fichier de réglages (lisible par tous)")

# ---------------------------------------------------------------- recherche
s = updater.check()
check(s["latest"]["version"] == "2026.03.01-0900" and updater.available() == "2026.03.01-0900", "recherche : version 2026.03.01-0900 disponible")
check(SEEN_AUTH and SEEN_AUTH[0] == "Bearer github_pat_" + "A1b2C3d4" * 4, "le jeton est envoyé à l'API GitHub")
check(updater.view()["available"] and updater.view()["latest"]["notes"] == "Notes de 2026.03.01-0900", "vue : version disponible + notes de version")
open(os.path.join(ETC, "version"), "w").write("2026.03.01-0900\n")
check(updater.available() is None and not updater.view()["available"], "une fois la version installée, plus de mise à jour annoncée (sans nouvelle requête)")
open(os.path.join(ETC, "version"), "w").write("2026.01.01-0000\n")
updater.save_config({"clear_token": True})
check(not os.path.exists(updater.TOKEN_FILE) and not updater.view()["token_set"], "jeton retiré")
updater.save_config({"repo": "o/autre"})
check(updater.view()["latest"] is None and updater.view()["checked_at"] is None, "changer de dépôt efface le résultat de l'ancien")
updater.save_config({"repo": "o/r"})
SEEN_AUTH.clear(); updater.check()
check(SEEN_AUTH and SEEN_AUTH[0] is None, "sans jeton, aucun en-tête Authorization")
try:
    updater.save_config({"repo": "o/introuvable"}); updater.check(); ok = False
except updater.UpdateError as e:
    ok = "introuvable" in str(e)
check(ok and updater.view()["error"], "dépôt inexistant : erreur lisible mémorisée dans l'état")
updater.save_config({"repo": "o/r"})

# ---------------------------------------------------------------- redirection : le jeton ne quitte pas api.github.com
req = __import__("urllib.request").request.Request("https://api.github.com/repos/o/r/releases/assets/1", headers={"Authorization": "Bearer secret"})
h = updater._Redirect()
new = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/x/y")
check(new is not None and new.get_header("Authorization") is None, "redirection vers le CDN GitHub : en-tête Authorization retiré")
try:
    h.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/x"); ok = False
except updater.UpdateError:
    ok = True
check(ok, "redirection vers un autre hôte refusée")
check(not updater._allowed("http://api.github.com/x") and not updater._allowed("https://github.com.evil.example/x") and updater._allowed("https://release-assets.githubusercontent.com/x"),
      "hôtes autorisés : HTTPS vers github.com, api.github.com et *.githubusercontent.com seulement")

# ---------------------------------------------------------------- application
RELEASES.clear(); ASSETS.clear()
add_release("2026.05.01-0800")
if os.path.exists(OUT):
    os.remove(OUT)
rc, out, err = apply()
args = open(OUT).read().split("\n") if os.path.exists(OUT) else []
check(rc == 0 and err is None and args and args[0].startswith("--target / --source "), "mise à jour appliquée : update.sh lancé avec --target / --source (%s)" % (args[:1],))
check("rootfs.tar" in args and "VERSION" in args and "ONLINE" in args, "update.sh voit rootfs.tar, VERSION et le marqueur ONLINE dans la source")
check("signature valide" in out and "conforme à la signature" in out, "journal : signature et somme vérifiées avant application")
check(not os.path.exists(CACHE), "dossier de téléchargement supprimé après la mise à jour")

# déjà à jour
open(os.path.join(ETC, "version"), "w").write("2026.05.01-0800\n"); os.remove(OUT)
rc, out, err = apply()
check(rc == 0 and not os.path.exists(OUT) and "Déjà à jour" in out, "version identique : rien n'est appliqué")
rc, out, err = apply(tag="v2026.05.01-0800", force=True)
check(rc == 0 and os.path.exists(OUT), "--force réapplique la même version")
open(os.path.join(ETC, "version"), "w").write("2026.01.01-0000\n")

# échec d'update.sh
os.environ["OB_TEST_RC"] = "3"
rc, out, err = apply()
check(rc is None and err and "code 3" in err, "update.sh en échec : erreur claire (%s)" % (err or "")[:70])
del os.environ["OB_TEST_RC"]

# ---------------------------------------------------------------- falsifications : rien ne doit être appliqué
def refuse(label, expect, **release):
    RELEASES.clear(); ASSETS.clear()
    add_release("2026.05.01-0800", **release)
    if os.path.exists(OUT):
        os.remove(OUT)
    rc, out, err = apply()
    check(rc is None and err and expect in err and not os.path.exists(OUT) and not os.path.exists(CACHE), "%s : refusé (« %s »), update.sh non lancé" % (label, err[:60] if err else err))

refuse("archive modifiée après signature", "Somme SHA-256 de l'archive incorrecte", tamper=True)
refuse("signature faite avec une autre clé", "SIGNATURE INVALIDE", key=KEY2)
refuse("VERSION de l'archive ≠ version publiée", "ne correspond pas", bundle=make_bundle("2026.05.01-0800", bad_version_file="2026.99.99-9999"))
refuse("fichier inattendu dans l'archive", "contenu inattendu", bundle=make_bundle("2026.05.01-0800", extra={"evil.sh": "x"}))
ti = tarfile.TarInfo("../../etc/cron.d/evil"); ti.size = 0
refuse("chemin hors de l'archive (../)", "contenu inattendu", bundle=make_bundle("2026.05.01-0800", extra={"../../etc/cron.d/evil": ti}))
ln = tarfile.TarInfo("rootfs.tar"); ln.type = tarfile.SYMTYPE; ln.linkname = "/etc/shadow"
refuse("lien symbolique à la place d'un fichier", "contenu inattendu", bundle=make_bundle("2026.05.01-0800", extra={"rootfs.tar": ln}))
refuse("version d'Ollama invalide", "version d'Ollama incorrecte", bundle=make_bundle("2026.05.01-0800", ollama="v1; rm -rf /"))
refuse("update.sh remplacé par un lien symbolique", "contenu inattendu", bundle=make_bundle("2026.05.01-0800", extra={"update.sh": ln}))
_inc = make_bundle("2026.05.01-0800"); _src = tarfile.open(fileobj=io.BytesIO(_inc)); _buf = io.BytesIO()
with tarfile.open(fileobj=_buf, mode="w:gz") as _t:
    for _m in _src.getmembers():
        if _m.name != "update.sh":
            _t.addfile(_m, _src.extractfile(_m))
refuse("archive incomplète (update.sh absent)", "incomplète", bundle=_buf.getvalue())

# clé publique absente : on ne contourne jamais la vérification
RELEASES.clear(); ASSETS.clear(); add_release("2026.05.01-0800")
os.rename(PUB, PUB + ".off")
rc, out, err = apply()
os.rename(PUB + ".off", PUB)
check(rc is None and err and "Clé publique" in err, "clé publique absente : mise à jour refusée")

# version plus ancienne : pas de retour en arrière sans --force
RELEASES.clear(); ASSETS.clear(); add_release("2025.01.01-0000")
open(os.path.join(ETC, "version"), "w").write("2026.01.01-0000\n")
if os.path.exists(OUT):
    os.remove(OUT)
rc, out, err = apply()
check(rc == 0 and not os.path.exists(OUT), "version publiée plus ancienne : aucune rétrogradation")

# ---------------------------------------------------------------- Ollama
open(os.path.join(TMP, "src-ollama"), "w").close()
src = os.path.join(TMP, "src"); os.makedirs(src)
open(os.path.join(src, "OLLAMA_URL"), "w").write("https://example.com/ollama-linux-amd64.tar.zst\n")
open(os.path.join(src, "OLLAMA_SHA256"), "w").write("a" * 64 + "\n")
try:
    updater._fetch_ollama(src, "", "OLLAMA_URL", "OLLAMA_SHA256", "Ollama"); ok = False
except updater.UpdateError:
    ok = True
check(ok, "archive Ollama : adresse hors github.com/ollama/ollama refusée")
open(os.path.join(src, "OLLAMA_URL"), "w").write(updater.OLLAMA_URL_PREFIX + "v0.50.0/ollama-linux-amd64.tar.zst\n")
real_dl = updater._download
updater._download = lambda url, dest, limit, label, token=None, accept=None: (open(dest, "wb").write(b"x"), "b" * 64)[1]
try:
    updater._fetch_ollama(src, "", "OLLAMA_URL", "OLLAMA_SHA256", "Ollama"); ok = False
except updater.UpdateError as e:
    ok = "incorrecte" in str(e)
check(ok and not os.path.exists(os.path.join(src, "ollama-linux-amd64.tar.zst")), "archive Ollama : somme SHA-256 différente de celle de l'archive signée → fichier supprimé et mise à jour refusée")
updater._download = lambda url, dest, limit, label, token=None, accept=None: (open(dest, "wb").write(b"x"), "a" * 64)[1]
updater._fetch_ollama(src, "", "OLLAMA_URL", "OLLAMA_SHA256", "Ollama")
check(os.path.exists(os.path.join(src, "ollama-linux-amd64.tar.zst")), "archive Ollama : somme conforme → conservée sous le nom attendu par update.sh")
updater._download = real_dl

# Ollama différent de celui installé : téléchargé avant l'application (ici : remplacé par un faux)
RELEASES.clear(); ASSETS.clear(); add_release("2026.05.01-0800", bundle=make_bundle("2026.05.01-0800", ollama="v0.60.0", extra={
    "OLLAMA_URL": updater.OLLAMA_URL_PREFIX + "v0.60.0/ollama-linux-amd64.tar.zst\n", "OLLAMA_SHA256": "c" * 64 + "\n"}))
calls = []
updater._download = lambda url, dest, limit, label, token=None, accept=None: (calls.append(url), open(dest, "wb").write(b"x"), "c" * 64)[2] if "ollama/ollama" in url else real_dl(url, dest, limit, label, token, accept or "application/octet-stream")
if os.path.exists(OUT):
    os.remove(OUT)
rc, out, err = apply()
check(rc == 0 and calls and "ollama-linux-amd64.tar.zst" in open(OUT).read(), "Ollama v0.50.0 → v0.60.0 : archive officielle téléchargée puis fournie à update.sh")
updater._download = real_dl

# ---------------------------------------------------------------- console web (serveur réel, session simulée)
os.makedirs(os.path.join(ETC, "tls"), exist_ok=True)
import server  # noqa: E402
RELEASES.clear(); ASSETS.clear(); add_release("2026.05.01-0800")
with open(server.USERS_FILE, "w") as f:
    json.dump({"users": {"adm": {"role": "admin", "rev": "r1", "linux": False}, "usr": {"role": "utilisateur", "rev": "r2", "linux": False}}}, f)
server._sessions["tok-adm"] = {"user": "adm", "role": "admin", "stamp": "r1", "exp": time.time() + 600}
server._sessions["tok-usr"] = {"user": "usr", "role": "utilisateur", "stamp": "r2", "exp": time.time() + 600}
web = server.make_server(0, server.Handler)
threading.Thread(target=web.serve_forever, daemon=True).start()
WP = web.server_address[1]


def call(method, path, body=None, tok="tok-adm"):
    c = http.client.HTTPConnection("127.0.0.1", WP, timeout=30)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if tok:
        h["Cookie"] = "ob_session=" + tok
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse(); d = r.read(); c.close()
    try:
        d = json.loads(d)
    except ValueError:
        pass
    return r.status, d


for m, p in (("GET", "/api/update/online"), ("POST", "/api/update/online/check"), ("POST", "/api/update/online/config"), ("POST", "/api/action")):
    st_, _ = call(m, p, {"action": "appliance-update-online"} if m == "POST" else None, tok="tok-usr")
    check(st_ == 403, "utilisateur non administrateur : %s %s refusé (403)" % (m, p))
    st_, _ = call(m, p, {}, tok=None)
    check(st_ == 401, "sans session : %s %s refusé (401)" % (m, p))
st_, d = call("GET", "/api/update/online")
check(st_ == 200 and d["installed"] == "2026.01.01-0000" and d["config"]["repo"] == "o/r" and d["signed"], "GET /api/update/online : version installée, réglages, clé de vérification présente")
st_, d = call("POST", "/api/update/online/check", {})
check(st_ == 200 and d["ok"] and d["available"] and d["latest"]["version"] == "2026.05.01-0800", "POST …/check : nouvelle version 2026.05.01-0800 détectée")
st_, d = call("GET", "/api/status")
check(st_ == 200 and d.get("update_available") == "2026.05.01-0800", "/api/status annonce la mise à jour disponible (bandeau de la vue d'ensemble)")
st_, d = call("POST", "/api/update/online/config", {"repo": "pas valide"})
check(st_ == 400, "réglages invalides refusés (400)")
st_, d = call("POST", "/api/update/online/config", {"repo": "o/r", "channel": "preview", "auto_check": True, "token": "ghp_" + "Z9y8X7w6" * 4})
check(st_ == 200 and d["config"]["channel"] == "preview" and d["token_set"] and "ghp_" not in json.dumps(d), "réglages enregistrés, jeton jamais renvoyé")
st_, d = call("POST", "/api/update/online/config", {"repo": "o/r", "channel": "stable", "auto_check": False, "clear_token": True})
check(st_ == 200 and not d["token_set"], "jeton retiré depuis la console")
st_, d = call("POST", "/api/action", {"action": "appliance-update-online", "tag": "v2026.05.01-0800; reboot"})
check(st_ == 400, "action de mise à jour avec une version mal formée refusée (injection de commande)")
os.makedirs(server.JOBS_DIR, mode=0o700, exist_ok=True)
server.pump_queue = lambda: None   # on ne lance rien : on vérifie seulement le script mis en file
st_, d = call("POST", "/api/action", {"action": "appliance-update-online", "tag": "v2026.05.01-0800"})
script = open(os.path.join(server.JOBS_DIR, d["job"] + ".sh")).read() if st_ == 200 else ""
check(st_ == 200 and "updater.py apply --yes --tag v2026.05.01-0800" in script, "action de mise à jour : tâche en file avec la version affichée → %s" % script.strip()[-70:])
st_, d = call("POST", "/api/action", {"action": "appliance-update-online"})
script = open(os.path.join(server.JOBS_DIR, d["job"] + ".sh")).read()
check(st_ == 200 and script.strip().endswith("updater.py apply --yes"), "sans version précisée : dernière version du canal")
check(server.job_status(d["job"])["title"].startswith("Mise à jour de l'appliance depuis Internet"), "titre de la tâche dans la file")

web.shutdown(); srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d vérifications réussies" % n[0])
