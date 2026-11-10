import http.client, json, os, subprocess, sys, time
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m)
    if not c: sys.exit(1)
def req(method, path, body=None, headers=None, raw=False):
    c = http.client.HTTPConnection("127.0.0.1", 18434, timeout=30)
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    c.request(method, path, body=data, headers=headers or {}); r = c.getresponse()
    if raw: return r
    out = r.read(); return r.status, (json.loads(out.splitlines()[0]) if out.strip() else {}), r
pools = {"pools": [{"id": "g1", "name": "Gros modèles", "port": 11500, "models": ["llama3.1:70b", "qwen3:32b", "mistral"]}]}
json.dump(pools, open("/tmp/rt/etc/pools.json", "w"))
ups = [subprocess.Popen([sys.executable, "/tmp/rt/upstream.py", str(p)]) for p in (11400, 11500)]
rt = subprocess.Popen([sys.executable, "/home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/router.py"], env=dict(os.environ, OB_ETC="/tmp/rt/etc", OB_ROUTER_LISTEN="127.0.0.1:18434"))
time.sleep(1.2)
try:
    s, d, _ = req("POST", "/api/chat", {"model": "llama3.1:70b", "messages": []}); ok(d["served_by"] == 11500, "chat llama3.1:70b (modèle du groupe) -> instance du groupe :11500")
    s, d, _ = req("POST", "/api/chat", {"model": "registry.ollama.ai/library/llama3.1:70b"}); ok(d["served_by"] == 11500, "nom complet registry.ollama.ai/library/llama3.1:70b -> groupe")
    s, d, _ = req("POST", "/api/chat", {"model": "mistral:latest"}); ok(d["served_by"] == 11500, "« mistral:latest » reconnu comme « mistral » (tag implicite) -> groupe")
    s, d, _ = req("POST", "/api/chat", {"model": "llama3.2:3b"}); ok(d["served_by"] == 11400, "chat llama3.2:3b (hors groupe) -> instance principale :11400")
    s, d, _ = req("POST", "/v1/chat/completions", {"model": "qwen3:32b", "messages": []}); ok(d["served_by"] == 11500, "API compatible OpenAI /v1/chat/completions qwen3:32b -> groupe")
    s, d, _ = req("POST", "/api/generate", {"model": "QWEN3:32B"}); ok(d["served_by"] == 11500, "nom en majuscules -> groupe")
    s, d, _ = req("POST", "/api/pull", {"model": "llama3.1:70b"}); ok(d["served_by"] == 11400, "téléchargement (/api/pull) d'un modèle du groupe -> toujours l'instance principale")
    s, d, _ = req("DELETE", "/api/delete", {"model": "llama3.1:70b"}); ok(d["served_by"] == 11400, "suppression -> instance principale")
    s, d, _ = req("GET", "/api/tags"); ok(d["served_by"] == 11400, "liste des modèles /api/tags -> instance principale")
    r = req("HEAD", "/", raw=True); ok(r.status == 200, "HEAD / (test de vie utilisé par les clients) -> 200")
    c = http.client.HTTPConnection("127.0.0.1", 18434); c.request("GET", "/api/ps"); ps = json.loads(c.getresponse().read())
    ok(sorted(m["name"] for m in ps["models"]) == ["charge-sur-11400", "charge-sur-11500"], "/api/ps : modèles chargés des deux instances fusionnés")
    r = req("POST", "/api/chat", {"model": "llama3.1:70b"}, raw=True); t0 = time.time(); first = r.readline(); t1 = time.time() - t0; rest = r.read().splitlines()
    ok(t1 < 0.25 and len(rest) == 4, "diffusion en flux : 1er morceau reçu après %.2f s (réponse complète 1,5 s), 5 morceaux" % t1)
    ok(r.getheader("X-OllamaBuntu-Instance") == "127.0.0.1:11500", "en-tête X-OllamaBuntu-Instance indique l'instance qui a répondu")
    big = json.dumps({"model": "llama3.1:70b", "images": ["A" * 30_000_000]}).encode()
    s, d, _ = req("POST", "/api/embed", big); ok(d["received"] == len(big) and d["served_by"] == 11500, "requête de 30 Mo (image) transmise intégralement (%d octets)" % d["received"])
    c = http.client.HTTPConnection("127.0.0.1", 18434); c.putrequest("POST", "/api/embed"); c.putheader("Transfer-Encoding", "chunked"); c.endheaders()
    payload = json.dumps({"model": "qwen3:32b", "input": "x"}).encode()
    for part in (payload[:10], payload[10:]): c.send(b"%x\r\n%s\r\n" % (len(part), part))
    c.send(b"0\r\n\r\n"); d = json.loads(c.getresponse().read()); ok(d["served_by"] == 11500 and d["received"] == len(payload), "corps de requête « chunked » reconstitué et routé")
    pools["pools"][0]["models"] = ["llama3.2:3b"]; time.sleep(0.05); json.dump(pools, open("/tmp/rt/etc/pools.json", "w")); os.utime("/tmp/rt/etc/pools.json", (time.time() + 5, time.time() + 5))
    s, d, _ = req("POST", "/api/chat", {"model": "llama3.2:3b"}); s2, d2, _ = req("POST", "/api/chat", {"model": "llama3.1:70b"})
    ok(d["served_by"] == 11500 and d2["served_by"] == 11400, "réaffectation prise en compte à chaud, sans redémarrer le routeur")
    ups[1].terminate(); ups[1].wait(); time.sleep(0.3)
    s, d, _ = req("POST", "/api/chat", {"model": "llama3.2:3b"}); ok(s == 502 and "injoignable" in d["error"], "instance du groupe arrêtée : erreur 502 explicite « %s »" % d["error"][:60])
finally:
    rt.terminate(); [u.terminate() for u in ups]
