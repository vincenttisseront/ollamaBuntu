#!/usr/bin/env python3
"""Redirection de modèles côté routeur : « les demandes pour X sont servies par Y » (serveur Ollama simulé qui renvoie le modèle reçu)."""
import http.client, http.server, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"), OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"), OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import router
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
FAIL = {}   # modèle -> code d'erreur renvoyé par le faux Ollama
class Hd(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        code = FAIL.get(str(d.get("model")))
        if code:
            out = json.dumps({"error": "boom %d" % code}).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out); return
        out = (json.dumps({"response": "modele=" + str(d.get("model")), "done": True}) + "\n").encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    do_GET = do_POST
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % srv.server_address[1]
router.fleet = lambda: {"servers": []}
router.local_models = lambda: {"names": set(), "tags": []}
Handler = next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates"))
Handler.rights = lambda self: None
httpd = router.make_server("127.0.0.1", 0, False, False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
PORT = httpd.server_address[1]
CONF = os.path.join(ETC, "redirects.json"); ver = [0]
def rules(*rs):
    open(CONF, "w").write(json.dumps({"rules": list(rs)})); ver[0] += 5; os.utime(CONF, (time.time() + ver[0], time.time() + ver[0]))
def ask(model, path="/api/generate", prompt="salut", **extra):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request("POST", path, body=json.dumps(dict({"model": model, "prompt": prompt, "stream": False}, **extra)), headers={"Content-Type": "application/json"})
    r = c.getresponse(); body = r.read().decode(); c.close()
    return r.status, body

st, b = ask("gemma4:12b")
ok(st == 200 and "modele=gemma4:12b" in b, "sans règle : le modèle demandé est servi tel quel")
rules({"from": "gemma4:12b", "to": "hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M", "percent": 100, "enabled": True})
st, b = ask("gemma4:12b")
ok(st == 200 and "modele=hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M" in b, "règle active : l'application demande gemma, Qwen3 répond (sans rien changer côté application)")
st, b = ask("GEMMA4:12B")
ok("Qwen3" in b, "le nom du modèle demandé est reconnu sans tenir compte de la casse")
st, b = ask("llama3.2:3b")
ok("modele=llama3.2:3b" in b, "un autre modèle n'est pas touché")
st, b = ask("gemma4:12b", "/v1/chat/completions")
ok("Qwen3" in b, "API compatible OpenAI (/v1/chat/completions) : redirigée aussi")
st, b = ask("gemma4:12b", "/api/show")
ok("modele=gemma4:12b" in b, "route de gestion (/api/show) : jamais redirigée")
rules({"from": "gemma4:12b", "to": "qwen3:14b", "percent": 100, "enabled": False})
st, b = ask("gemma4:12b")
ok("modele=gemma4:12b" in b, "règle désactivée : retour immédiat au modèle demandé (relue à chaud, sans redémarrage)")
rules({"from": "gemma4", "to": "qwen3:14b", "percent": 100, "enabled": True})
st, b = ask("gemma4:latest")
ok("modele=qwen3:14b" in b, "« gemma4 » et « gemma4:latest » sont le même modèle")
rules({"from": "a:1b", "to": "b:1b", "percent": 100, "enabled": True}, {"from": "b:1b", "to": "c:1b", "percent": 100, "enabled": True})
st, b = ask("a:1b")
ok("modele=b:1b" in b, "pas d'enchaînement : a -> b ne continue pas vers c")
rules({"from": "gemma4:12b", "to": "qwen3:14b", "percent": 30, "enabled": True})
hits = sum("qwen3" in ask("gemma4:12b")[1] for _ in range(200))
ok(40 <= hits <= 80, "30 %% : %d demandes sur 200 redirigées (essai sur une partie du trafic)" % hits)
body, asked, served = router.apply_redirect(b'{"model":"x:1b","prompt":"p"}', [(router.norm("x:1b"), "y:1b", 50)], rnd=lambda: 0.49)
ok(served == "y:1b" and asked == "x:1b" and json.loads(body)["model"] == "y:1b" and json.loads(body)["prompt"] == "p", "50 % et tirage 0,49 : redirigé, reste de la requête intact")
body, asked, served = router.apply_redirect(b'{"model":"x:1b"}', [(router.norm("x:1b"), "y:1b", 50)], rnd=lambda: 0.51)
ok(served is None and json.loads(body)["model"] == "x:1b", "50 % et tirage 0,51 : non redirigé")
ok(router.apply_redirect(b"pas du json", [("x:latest", "y", 100)])[1:] == (None, None), "corps illisible : laissé tel quel")
ok(router.apply_redirect(b'{"model":"x"}', [("x:latest", "x", 100)])[2] is None, "règle vers le même modèle : ignorée")
rules({"from": "gemma4:12b", "to": "qwen3:14b", "percent": 100, "enabled": True})
for _ in range(30):
    ask("gemma4:12b")
    try:
        lines = [json.loads(l) for l in open(os.path.join(tmp, "requests.jsonl")) if l.strip()]
    except OSError:
        lines = []
    if any(l.get("redirected_from") for l in lines): break
    time.sleep(0.1)
red = [l for l in lines if l.get("redirected_from")]
ok(red and red[-1]["model"] == "qwen3:14b" and red[-1]["redirected_from"] == "gemma4:12b", "journal des requêtes : modèle servi et modèle demandé (redirected_from)")

# --- cascade : conditions de la règle et repli sur le modèle demandé
N = router.norm
def red(d, rule): return router.apply_redirect_ex(json.dumps(d).encode(), [rule])
body, asked, served, fb = red({"model": "g:1b", "prompt": "court"}, (N("g:1b"), "p:1b", 100, {"short_chars": 20}, True))
ok(served == "p:1b" and asked == "g:1b" and fb is True and json.loads(body)["model"] == "p:1b", "demande courte : confiée au petit modèle, repli annoncé")
ok(red({"model": "g:1b", "prompt": "x" * 21}, (N("g:1b"), "p:1b", 100, {"short_chars": 20}, False))[2:] == (None, False), "demande plus longue que la limite : reste sur le modèle demandé")
ok(red({"model": "g:1b", "messages": [{"role": "system", "content": "a" * 15}, {"role": "user", "content": [{"type": "text", "text": "b" * 6}]}]}, (N("g:1b"), "p:1b", 100, {"short_chars": 20}, False))[2] is None, "la taille compte tous les messages, y compris les contenus en morceaux")
ok(red({"model": "g:1b", "prompt": "x", "tools": [{"type": "function"}]}, (N("g:1b"), "p:1b", 100, {"no_tools": True}, False))[2] is None and red({"model": "g:1b", "prompt": "x"}, (N("g:1b"), "p:1b", 100, {"no_tools": True}, False))[2] == "p:1b", "sans outils seulement : une demande avec outils n'est pas redirigée")
ok(red({"model": "g:1b", "messages": [{"role": "user", "content": "x", "images": ["AAAA"]}]}, (N("g:1b"), "p:1b", 100, {"no_images": True}, False))[2] is None and red({"model": "g:1b", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:..."}}]}]}, (N("g:1b"), "p:1b", 100, {"no_images": True}, False))[2] is None, "sans images seulement : images d'Ollama et d'OpenAI reconnues")
ok(router.apply_redirect(b'{"model":"g:1b","prompt":"x"}', [(N("g:1b"), "p:1b", 100)])[2] == "p:1b" and router.apply_redirect_ex(b'{"model":"g:1b"}', [(N("g:1b"), "p:1b", 100)])[3] is False, "anciennes règles (3 valeurs) : inchangées, sans repli")
rules({"from": "g:1b", "to": "p:1b", "percent": 100, "enabled": True, "short_chars": 30, "no_tools": True, "fallback": True})
ok(router.redirect_rules()[0][3] == {"short_chars": 30, "no_tools": True} and router.redirect_rules()[0][4] is True, "le routeur lit les conditions et le repli dans redirects.json")
st, b = ask("g:1b", prompt="court"); ok(st == 200 and "modele=p:1b" in b, "demande courte : servie par le petit modèle")
st, b = ask("g:1b", prompt="x" * 40); ok(st == 200 and "modele=g:1b" in b, "demande longue : servie par le modèle demandé")
st, b = ask("g:1b", prompt="court", tools=[{"type": "function"}]); ok(st == 200 and "modele=g:1b" in b, "demande avec outils : servie par le modèle demandé")
FAIL["p:1b"] = 404
st, b = ask("g:1b", prompt="court"); ok(st == 200 and "modele=g:1b" in b, "petit modèle absent (404) : la demande repart avec le modèle demandé, le client n'a rien vu")
FAIL["p:1b"] = 500
st, b = ask("g:1b", prompt="court"); ok(st == 200 and "modele=g:1b" in b, "petit modèle en erreur (500) : même repli")
ok(ask("g:1b", prompt="court", stream=False)[0] == 200, "…et sans nouvelle tentative inutile ensuite")
for _ in range(30):
    try: lines = [json.loads(l) for l in open(os.path.join(tmp, "requests.jsonl")) if l.strip()]
    except OSError: lines = []
    if any(l.get("escalated") for l in lines): break
    time.sleep(0.1)
esc = [l for l in lines if l.get("escalated")]
ok(esc and esc[-1]["model"] == "g:1b" and esc[-1]["escalated_from"] == "p:1b" and esc[-1]["escalated"] == "erreur 500" and not esc[-1].get("redirected_from") and esc[-1]["status"] == 200 and not esc[-1].get("retried"), "journal : modèle qui a répondu, modèle en échec, motif (la cascade n'est pas comptée comme une panne de serveur)")
FAIL["g:1b"] = 500
st, b = ask("g:1b", prompt="court"); ok(st == 500, "les deux modèles en erreur : une seule reprise, le client voit l'erreur (pas de boucle)")
FAIL.clear()
rules({"from": "g:1b", "to": "p:1b", "percent": 100, "enabled": True, "short_chars": 30})
FAIL["p:1b"] = 404
st, b = ask("g:1b", prompt="court"); ok(st == 404, "sans repli : l'erreur du modèle servi est transmise telle quelle")
FAIL.clear()
rules({"from": "g:1b", "to": "p:1b", "percent": 100, "enabled": True, "short_chars": "zéro", "no_tools": "oui", "fallback": "oui"})
ok(router.redirect_rules()[0][3] == {} and router.redirect_rules()[0][4] is False, "conditions illisibles ou non booléennes : ignorées (la règle reste une simple redirection)")

print("\n%d vérifications réussies" % n)
