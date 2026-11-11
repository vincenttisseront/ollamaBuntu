#!/usr/bin/env python3
"""File d'attente avec priorités : limiteur (module pur), réglages de la console et vrais échanges HTTP avec le routeur."""
import http.client, http.server, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(1, os.path.join(LIB, "admin"))
import limits, router, server
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a); return False
    except ValueError: return True

# --- 1. limiteur : plafond global et ordre de passage
L = limits.Limiter()
ok(L.acquire_ex("a", 0, 1) == (True, None) and L.acquire_ex("a", 0, 1, total=0) == (True, None) and L.snapshot() == {}, "sans plafond de clé ni plafond global : la requête ne passe pas par la file")
ok(L.acquire_ex(None, 0, 1, total=2) == (True, None) and L.total_running() == 0, "sans identifiant de clé : jamais comptée")
ok(L.acquire_ex("hold", 0, 1, total=1) == (True, None) and L.total_running() == 1, "plafond global de 1 : la première requête passe")
t0 = time.time(); r = L.acquire_ex("x", 0, 0.3, total=1)
ok(r == (False, "timeout") and time.time() - t0 >= 0.25, "plafond global atteint : attente puis refus à l'échéance (« timeout »)")

order = []
def worker(kid, prio, label):
    okk, _ = L.acquire_ex(kid, 0, 10, prio=prio, total=1, info={"who": kid, "model": "m:1b"})
    if okk:
        order.append(label); time.sleep(0.05); L.release(kid)
ths = []
for kid, prio, label in (("batch", 3, "basse"), ("normal", 2, "normale"), ("direction", 1, "haute"), ("batch2", 3, "basse2")):
    th = threading.Thread(target=worker, args=(kid, prio, label)); th.start(); ths.append(th); time.sleep(0.12)
wl = L.waiting_list()
ok([w["kid"] for w in wl] == ["direction", "normal", "batch", "batch2"], "file visible dans l'ordre de passage : haute, normale, puis basse (arrivée la plus ancienne d'abord)")
ok(wl[0]["model"] == "m:1b" and wl[0]["prio"] == 1 and wl[0]["waited"] > 0, "chaque ligne indique le client, le modèle, la priorité et l'attente")
L.release("hold")
for th in ths: th.join(5)
ok(order == ["haute", "normale", "basse", "basse2"], "à la libération, la priorité haute passe avant les basses arrivées plus tôt (%s)" % order)
ok(L.total_running() == 0 and L.snapshot() == {} and L.waiting_list() == [], "tout libéré : compteurs à zéro, file vide")
st = L.wait_stats()
ok(st["n"] >= 3 and st["max"] > 0 and "1" in st["by_prio"] and "3" in st["by_prio"], "statistiques d'attente par priorité sur la dernière heure")

# --- 2. une clé au plafond ne bloque pas les autres
L = limits.Limiter()
L.acquire_ex("A", 1, 1, total=5)
res = []
th = threading.Thread(target=lambda: res.append(L.acquire_ex("A", 1, 5, prio=1, total=5))); th.start(); time.sleep(0.15)
t0 = time.time(); r = L.acquire_ex("B", 0, 1, prio=3, total=5)
ok(r == (True, None) and time.time() - t0 < 0.3, "la clé A (priorité haute) attend son plafond sans empêcher la clé B (basse) de passer")
L.release("A"); th.join(3)
ok(res == [(True, None)], "la clé A repasse dès qu'une de ses requêtes se termine")
# --- 3. file pleine
L = limits.Limiter(); L.acquire_ex("h", 0, 1, total=1)
th = threading.Thread(target=lambda: L.acquire_ex("w", 0, 1, total=1)); th.start(); time.sleep(0.15)
ok(L.acquire_ex("z", 0, 5, total=1, max_queue=1) == (False, "full"), "taille de file atteinte : refus immédiat (« full »), sans attendre")
th.join(3)
# --- 4. vieillissement : une basse qui attend longtemps finit par passer avant une haute plus récente
limits.AGING = 0.3
L = limits.Limiter(); L.acquire_ex("h", 0, 1, total=1); out = []
def w(kid, prio):
    if L.acquire_ex(kid, 0, 10, prio=prio, total=1)[0]: out.append(kid); L.release(kid)
t1 = threading.Thread(target=w, args=("ancienne-basse", 3)); t1.start(); time.sleep(0.8)
t2 = threading.Thread(target=w, args=("nouvelle-haute", 1)); t2.start(); time.sleep(0.1)
ok(L.waiting_list()[0]["kid"] == "ancienne-basse" and L.waiting_list()[0]["eff"] == 1, "après quelque temps d'attente, la requête de priorité basse monte au niveau haut")
L.release("h"); t1.join(5); t2.join(5)
ok(out == ["ancienne-basse", "nouvelle-haute"], "vieillissement : aucune requête ne reste bloquée derrière de nouvelles requêtes prioritaires")
limits.AGING = 120
ok(limits.priority_of(1) == 1 and limits.priority_of("3") == 3 and limits.priority_of(None) == 2 and limits.priority_of(9) == 2 and limits.priority_of("x") == 2, "priorité inconnue ou absente : normale")
ok(limits.Limiter.gated("k", 0, 0) is False and limits.Limiter.gated("k", 2, 0) and limits.Limiter.gated("k", 0, 3) and not limits.Limiter.gated(None, 2, 2), "la requête passe par la file seulement si un plafond s'applique")

# --- 5. console : priorité d'une clé, réglages globaux, vue
ok(server.validate_limits({"priority": "1"}) == {"priority": 1, "max_concurrent": 0, "quota_day": 0, "quota_month": 0, "max_ctx": 0, "max_output": 0}, "priorité lue à la création de la clé")
ok(server.validate_limits({"priority": 3}, {"priority": 2}) == {"priority": 3}, "mise à jour partielle : seule la priorité change")
ok(raises(server.validate_limits, {"priority": 4}) and raises(server.validate_limits, {"priority": 0}) and raises(server.validate_limits, {"priority": "haute"}), "priorité hors 1 à 3 refusée")
server.QUEUE_CONF = os.path.join(tmp, "queue-admin.json"); server.ROUTER_LIMITS = os.path.join(tmp, "limits.json")
server.load_publication = lambda: {"keys": [{"id": "k1", "name": "Direction", "priority": 1}, {"id": "k2", "name": "Batch", "priority": 3, "max_concurrent": 1}]}
server.read_env = lambda: {"OLLAMA_NUM_PARALLEL": "4"}
ok(server.queue_settings() == {"max_active": 0, "max_queue": 0}, "par défaut : aucune limite globale")
ok(server.queue_save({"max_active": "4", "max_queue": 20}) == {"max_active": 4, "max_queue": 20} and server.queue_settings()["max_active"] == 4, "réglages enregistrés")
ok(oct(os.stat(server.QUEUE_CONF).st_mode & 0o777) == "0o644", "fichier lisible par le routeur (aucun secret)")
ok(server.queue_save({"max_queue": 5}) == {"max_active": 4, "max_queue": 5}, "mise à jour partielle")
ok(raises(server.queue_save, {"max_active": 999}) and raises(server.queue_save, {"max_queue": -1}) and raises(server.queue_save, {"max_active": "abc"}), "valeurs hors bornes refusées")
v = server.queue_view()
ok(not v["live"] and v["waiting"] == [] and v["parallel"] == 4 and [(k["name"], k["priority"]) for k in v["keys"]] == [("Direction", 1), ("Batch", 3)], "sans données du routeur : file vide, priorités des clés listées")
with open(server.ROUTER_LIMITS, "w") as f:
    json.dump({"t": int(time.time()), "active": 2, "waiting": [{"kid": "k2", "who": "Batch", "model": "m:1b", "prio": 3, "eff": 2, "waited": 41.5}], "waits": {"n": 1, "avg": 3, "max": 3, "by_prio": {}}, "queue": {}, "tokens": {}}, f)
v = server.queue_view()
ok(v["live"] and v["active"] == 2 and v["waiting"][0]["who"] == "Batch" and v["waiting"][0]["eff"] == 2, "file en direct relue depuis le routeur, nom de la clé résolu")
with open(server.ROUTER_LIMITS, "w") as f: json.dump({"t": int(time.time()) - 600, "active": 2, "waiting": [{"kid": "k2", "prio": 3}]}, f)
v = server.queue_view(); ok(not v["live"] and v["waiting"] == [] and v["active"] == 0, "données périmées (routeur arrêté) : on n'affiche pas une file fantôme")
ok(server.limits_view()["keys"][0]["priority"] == 1, "priorité exposée avec les limites de chaque clé")

# --- 6. routeur : vraies requêtes HTTP
hits = []
class Back(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        hits.append(body.get("prompt")); time.sleep(float(body.get("sleep") or 0))
        out = json.dumps({"response": "ok", "done": True}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    do_GET = do_POST
class S(http.server.ThreadingHTTPServer): daemon_threads = True
back = S(("127.0.0.1", 0), Back); threading.Thread(target=back.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % back.server_address[1]; router.QUEUE_WAIT = 4
router.fleet = lambda: {"local": {}, "servers": []}; router.local_models = lambda: {"names": set(), "tags": []}
KEYS = {"bg": {"id": "kb", "name": "Fond", "priority": 3}, "dir": {"id": "kd", "name": "Direction", "priority": 1}, "bat": {"id": "kt", "name": "Batch", "priority": 3}, "anon": None}
Handler = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
def rights(self):
    k = KEYS.get(self.headers.get("X-Who", ""))
    if not k: return None
    self._key = k
    return (k["name"], {"inference", "read"}, set(), k["id"], set())
Handler.rights = rights
httpd = router.make_server("127.0.0.1", 0, False, False); threading.Thread(target=httpd.serve_forever, daemon=True).start(); PORT = httpd.server_address[1]
def ask(who, prompt, sleep=0, store=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request("POST", "/api/generate", body=json.dumps({"model": "m:1b", "prompt": prompt, "sleep": sleep, "stream": False}), headers={"Content-Type": "application/json", "X-Who": who})
    r = c.getresponse(); body = r.read().decode(); c.close()
    if store is not None: store.append((prompt, r.status, body))
    return r.status, body
def write_conf(**c):
    with open(router.QUEUE_CONF, "w") as f: json.dump(c, f)
    os.utime(router.QUEUE_CONF, (time.time() + len(c) + n, time.time() + len(c) + n))

st, _ = ask("dir", "libre"); ok(st == 200 and hits == ["libre"], "sans plafond : la requête passe directement")
ok(router.queue_conf() == {"max_active": 0, "max_queue": 0}, "routeur : aucune limite globale par défaut")
write_conf(max_active=1, max_queue=1)
ok(router.queue_conf() == {"max_active": 1, "max_queue": 1}, "routeur : réglages de la console relus à chaud")
del hits[:]; res = []
t_bg = threading.Thread(target=ask, args=("bg", "occupe", 1.0, res)); t_bg.start(); time.sleep(0.3)
t_bat = threading.Thread(target=ask, args=("bat", "batch", 0.05, res)); t_bat.start(); time.sleep(0.2)
wl = router._limiter.waiting_list()
ok([(w["who"], w["prio"], w["model"]) for w in wl] == [("Batch", 3, "m:1b")], "routeur : la requête qui attend est visible avec son client, sa priorité et son modèle")
ok(router._limiter.total_running() == 1, "une seule requête en cours (plafond global de 1 respecté)")
st, body = ask("anon", "refusée")
ok(st == 429 and "file d'attente pleine" in body and "refusée" not in hits, "taille de file atteinte : refus 429 explicite, la requête n'atteint pas Ollama")
write_conf(max_active=1, max_queue=10)
t_dir = threading.Thread(target=ask, args=("dir", "direction", 0.05, res)); t_dir.start()
for t in (t_bg, t_bat, t_dir): t.join(10)
ok(hits == ["occupe", "direction", "batch"], "la clé « Direction » (haute) passe avant « Batch » (basse) arrivée plus tôt : %s" % hits)
ok(all(s == 200 for _, s, _ in res) and router._limiter.total_running() == 0 and router._limiter.snapshot() == {}, "toutes les requêtes réussissent, plus rien en cours ni en attente")
# délai d'attente dépassé
router.QUEUE_WAIT = 1; del hits[:]; res2 = []
t = threading.Thread(target=ask, args=("bg", "long", 2.0, res2)); t.start(); time.sleep(0.3)
st, body = ask("dir", "trop-tard")
ok(st == 429 and "attente de 1 s dépassée" in body and "trop-tard" not in hits, "attente trop longue : 429 avec le délai dans le message")
t.join(10)
ok(router._limiter.total_running() == 0, "le plafond est libéré après la fin de la requête longue")
# plafond par clé seul (sans plafond global)
write_conf(max_active=0, max_queue=0); KEYS["bat"]["max_concurrent"] = 1; router.QUEUE_WAIT = 4; del hits[:]
r3 = []; ta = threading.Thread(target=ask, args=("bat", "un", 0.6, r3)); ta.start(); time.sleep(0.2)
tb = threading.Thread(target=ask, args=("bat", "deux", 0, r3)); tb.start(); time.sleep(0.1)
st, _ = ask("dir", "autre-cle")
ok(st == 200 and "autre-cle" in hits and "deux" not in hits, "plafond d'une clé seul : cette clé attend, les autres passent librement")
ta.join(5); tb.join(5)
ok(hits[-1] == "deux" and "un" in hits, "la seconde requête de la clé repart quand la première est finie")
print("\n%d vérifications réussies." % n)
