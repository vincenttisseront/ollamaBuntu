#!/usr/bin/env python3
"""SearXNG, moteur de recherche d'Open WebUI : déploiement par le script (faux docker), état, surveillant, absence de commande pour l'arrêter."""
import os, sys, tempfile, subprocess, stat, re
sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
LIB = os.path.join(ROOT, "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, os.path.join(LIB, "admin"))
import server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)

tmp = tempfile.mkdtemp()
bindir, state, log = os.path.join(tmp, "bin"), os.path.join(tmp, "state"), os.path.join(tmp, "docker.log")
os.makedirs(bindir); os.makedirs(state)
def fake(name, body):
    p = os.path.join(bindir, name); open(p, "w").write("#!/bin/bash\n" + body); os.chmod(p, 0o755)
fake("docker", r'''
echo "docker $*" >> "$FAKE_LOG"
S="$FAKE_STATE"
case "$1" in
  inspect) n="${@: -1}"; [[ -f $S/$n ]] && { cat "$S/$n"; exit 0; } || { echo "Error: No such object: $n" >&2; exit 1; } ;;
  run) for a in "$@"; do [[ $a == --name ]] && grab=1 && continue; [[ -n ${grab:-} ]] && { echo running > "$S/$a"; grab=; }; done ;;
  rm) for a in "$@"; do [[ $a != rm && $a != -f ]] && rm -f "$S/$a"; done ;;
  start) echo running > "$S/$2" ;;
  stop) echo exited > "$S/$2" ;;
  logs) echo "journal factice" ;;
esac
exit 0''')
fake("curl", 'echo "curl $*" >> "$FAKE_LOG"; [[ -n ${FAKE_CURL_FAIL:-} ]] && exit 22; exit 0')
fake("systemctl", "exit 0")
fake("sleep", "exit 0")
sh = open(os.path.join(LIB, "open-webui.sh"), encoding="utf-8").read()
sh = re.sub(r"^export PATH=.*$", "export PATH=%s:/usr/bin:/bin" % bindir, sh, count=1, flags=re.M)
script = os.path.join(tmp, "open-webui.sh"); open(script, "w").write(sh)
envf, sdir, senv = os.path.join(tmp, "open-webui.env"), os.path.join(tmp, "searxng"), os.path.join(tmp, "search.env")
open(envf, "w").write("WEBUI_ADMIN_EMAIL=a@x.fr\n")
E = dict(os.environ, FAKE_LOG=log, FAKE_STATE=state, OB_WEBUI_ENV=envf, OB_SEARXNG_DIR=sdir, OB_WEBUI_SEARCH_ENV=senv, OB_WEBUI_MIN_FREE_KB="0")
def sh_run(*args, **kw):
    open(log, "w").close()
    r = subprocess.run(["/bin/bash", script] + list(args), env=dict(E, **kw), capture_output=True, text=True, timeout=60)
    return r, open(log).read()
def runs(l): return [x for x in l.splitlines() if x.startswith("docker run")]

r, l = sh_run("install")
ok(r.returncode == 0, "install : le script se termine sans erreur : " + (r.stderr or r.stdout)[-200:])
ok(os.path.exists(os.path.join(state, "searxng")) and os.path.exists(os.path.join(state, "open-webui")), "install : les deux conteneurs sont lancés")
rs = [x for x in runs(l) if "--name searxng" in x][0]
ok("-p 127.0.0.1:8888:8080" in rs and "--restart always" in rs, "SearXNG : publié seulement sur 127.0.0.1, redémarrage automatique")
ok(l.index("--name searxng") < l.index("--name open-webui"), "SearXNG est lancé avant Open WebUI")
ok("pull docker.io/searxng/searxng:latest" in l, "install : image SearXNG téléchargée")
y = open(os.path.join(sdir, "settings.yml")).read()
ok("- json" in y and "limiter: false" in y and re.search(r'secret_key: "[0-9a-f]{64}"', y) and "use_default_settings: true" in y, "settings.yml : format JSON, pas de limiteur, clé secrète aléatoire")
key1 = re.search(r'secret_key: "([0-9a-f]+)"', y).group(1)
ev = open(senv).read()
ok("WEB_SEARCH_ENGINE=searxng" in ev and "SEARXNG_QUERY_URL=http://127.0.0.1:8888/search\n" in ev and "ENABLE_PERSISTENT_CONFIG=false" in ev, "variables d'Open WebUI : moteur searxng, adresse sans ?q=, configuration non persistante")
ok(oct(os.stat(senv).st_mode & 0o777) == "0o600", "fichier d'environnement réservé à root")
ow = [x for x in runs(l) if "--name open-webui" in x][0]
ok("--env-file " + senv in ow, "Open WebUI : reçoit le fichier d'environnement de SearXNG")

r, l = sh_run("apply")
ok(r.returncode == 0 and open(os.path.join(sdir, "settings.yml")).read().count(key1) == 1, "apply : la clé secrète de SearXNG est conservée")
ok(not any("--name searxng" in x for x in runs(l)), "apply : SearXNG déjà en service n'est pas recréé")

os.remove(os.path.join(state, "searxng"))
r, l = sh_run("apply")
ok(r.returncode == 0 and any("--name searxng" in x for x in runs(l)), "apply : SearXNG absent est recréé avant Open WebUI")

open(os.path.join(state, "searxng"), "w").write("exited\n")
r, l = sh_run("ensure-searx")
ok(r.returncode == 0 and "docker start searxng" in l, "ensure-searx : conteneur arrêté : redémarré")
r, l = sh_run("ensure-searx", FAKE_CURL_FAIL="1")
ok("--name searxng" in l and "docker rm -f searxng" in l, "ensure-searx : conteneur actif mais muet : recréé")
r, l = sh_run("apply", FAKE_CURL_FAIL="1")
ok("docker run" in l and any("--name open-webui" in x for x in runs(l)), "apply : Open WebUI est tout de même recréé si SearXNG est indisponible")
ok("AVERTISSEMENT" in r.stdout + r.stderr, "apply : avertissement affiché")

r, l = sh_run("stop")
ok("docker stop open-webui" in l and "searxng" not in l, "stop : n'arrête que Open WebUI")
r, l = sh_run("restart")
ok("docker restart open-webui" in l and "searxng" not in l, "restart : ne touche que Open WebUI")
r, l = sh_run("update")
ok("pull docker.io/searxng/searxng:latest" in l and any("--name searxng" in x for x in runs(l)), "update : image SearXNG mise à jour et conteneur recréé")
r, l = sh_run("remove")
ok(not os.path.exists(os.path.join(state, "searxng")) and not os.path.exists(os.path.join(state, "open-webui")) and os.path.exists(sdir), "remove : les deux conteneurs partent, les réglages restent")
sh_run("install")
r, l = sh_run("purge")
ok(not os.path.exists(sdir) and not os.path.exists(senv) and "docker volume rm open-webui" in l, "purge : réglages de SearXNG supprimés")

# --- côté console
open(os.path.join(tmp, "open-webui.env"), "w").write("x=1\n")
server.ETC = tmp
class Fake:
    out = "running|docker.io/searxng/searxng:latest|2026-11-17T10:00:00.123Z|2"
server.run = lambda cmd, timeout=10, **kw: Fake.out
server.http_get = lambda url, **kw: (200, b"OK")
server.shutil.which = lambda *_: "/usr/bin/docker"
st = server.searx_status()
ok(st["running"] and st["healthy"] and st["restarts"] == 2 and st["port"] == 8888 and st["started"] == "2026-11-17 10:00:00", "état : en service, répond")
server.http_get = lambda url, **kw: (500, b"")
ok(server.searx_status()["running"] and not server.searx_status()["healthy"], "état : actif mais ne répond pas")
Fake.out = ""
ok(server.searx_status()["container"] is None and not server.searx_status()["running"], "état : conteneur absent")
for k in ("fails", "last_fix", "fixes"): server._searx_state[k] = 0
calls = []
step = lambda now: server.searx_watch_once(now=now, runner=lambda: calls.append(now))
ok(step(1000) == "attente" and not calls, "surveillant : un premier échec ne déclenche rien")
ok(step(1030) == "relancé" and calls == [1030], "surveillant : deux échecs de suite : relance")
ok(step(1060) == "attente" and calls == [1030], "surveillant : pas de relance en rafale (2 minutes d'écart)")
ok(step(1200) == "relancé" and calls == [1030, 1200], "surveillant : relance de nouveau après 2 minutes")
Fake.out = "running|x|2026-11-17T10:00:00Z|0"; server.http_get = lambda url, **kw: (200, b"OK")
ok(step(1300) == "ok" and server._searx_state["fails"] == 0, "surveillant : retour à la normale, compteur remis à zéro")
os.remove(os.path.join(tmp, "open-webui.env"))
ok(step(5000) == "inactif" and len(calls) == 2, "surveillant : sans Open WebUI déployé, ne fait rien")
open(os.path.join(tmp, "open-webui.env"), "w").write("x=1\n")
server.WEBUI_ENV = os.path.join(tmp, "open-webui.env")
ok(server.webui_status().get("searxng", {}).get("running"), "/api/webui expose l'état de SearXNG")
os.remove(os.path.join(tmp, "open-webui.env"))
ok(server.webui_status().get("searxng") is None, "/api/webui : pas de SearXNG sans Open WebUI")

src = open(os.path.join(LIB, "admin", "server.py"), encoding="utf-8").read()
acts = re.findall(r'"(webui-[a-z-]+)"', src)
ok(not any("searx" in a and a != "webui-searx" for a in acts) and "searxng" not in " ".join(re.findall(r'if act in \(([^)]*)\)', src)), "aucune action de la console ne vise SearXNG (ni arrêt, ni suppression)")
print("%d contrôles réussis" % n)
