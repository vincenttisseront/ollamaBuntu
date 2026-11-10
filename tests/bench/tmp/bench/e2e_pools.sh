#!/bin/bash
T=/tmp/target; M=$T/usr/share/ollama/.ollama/models
for d in dev dev/pts proc sys run; do mountpoint -q $T/$d || mount --bind /$d $T/$d; done
ps aux | grep -E "admin/server[.]py|ollama[ ]serve|router[.]py" | awk '{print $2}' | xargs -r kill 2>/dev/null; sleep 1
mkdir -p $T/tmp/e2e-etc && printf '{"pools": [{"id": "g1", "name": "Groupe test", "port": 11500, "gpus": [], "models": ["ob-tiny"]}]}' > $T/tmp/e2e-etc/pools.json && chmod -R a+rX $T/tmp/e2e-etc
blobs_before=$(ls $M/blobs | wc -l)
OL() { chroot --userspec=ollama:ollama $T /usr/bin/env -i HOME=/usr/share/ollama PATH=/usr/local/bin:/usr/bin:/bin "$@"; }
OL OLLAMA_HOST=127.0.0.1:11400 /usr/local/bin/ollama serve > /tmp/e2e-main.log 2>&1 &
OL OLLAMA_HOST=127.0.0.1:11500 OLLAMA_NOPRUNE=1 OLLAMA_MODELS=/usr/share/ollama/.ollama/models /usr/local/bin/ollama serve > /tmp/e2e-pool.log 2>&1 &
OL OB_ETC=/tmp/e2e-etc OB_MAIN=127.0.0.1:11400 OB_ROUTER_LISTEN=127.0.0.1:11434 python3 /usr/local/lib/ollamabuntu/router.py > /tmp/e2e-router.log 2>&1 &
for i in $(seq 1 30); do curl -s http://127.0.0.1:11400/api/version >/dev/null && curl -s http://127.0.0.1:11500/api/version >/dev/null && curl -s http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
python3 - "$blobs_before" <<'PY'
import http.client, json, sys, time, os
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
def gen(model):
    c = http.client.HTTPConnection("127.0.0.1", 11434, timeout=300)
    c.request("POST", "/api/generate", json.dumps({"model": model, "prompt": "Bonjour", "stream": True, "options": {"num_predict": 24}}))
    r = c.getresponse(); t0 = time.time(); first = None; text = ""; lines = 0
    while True:
        line = r.readline()
        if not line: break
        d = json.loads(line); lines += 1; text += d.get("response", "")
        if first is None and d.get("response"): first = time.time() - t0
        if d.get("done"): break
    return r.getheader("X-OllamaBuntu-Instance"), lines, text, first, time.time() - t0
inst, lines, text, first, total = gen("ob-tiny")
ok(inst == "127.0.0.1:11500" and lines > 2, "génération réelle ob-tiny (modèle du groupe) servie par l'instance du groupe :11500 (%d morceaux)" % lines)
ok(first is not None and first < total, "flux réel à travers le routeur : 1er jeton à %.2f s, fin à %.2f s" % (first or -1, total))
inst2, lines2, _, _, _ = gen("qwen3.5:2b")
ok(inst2 == "127.0.0.1:11400" and lines2 > 2, "génération réelle qwen3.5:2b (hors groupe) servie par l'instance principale :11400")
c = http.client.HTTPConnection("127.0.0.1", 11434); c.request("GET", "/api/ps"); ps = sorted(m["name"] for m in json.loads(c.getresponse().read())["models"])
ok(ps == ["ob-tiny:latest", "qwen3.5:2b"], "/api/ps via le routeur : les deux modèles chargés, chacun dans son instance (%s)" % ", ".join(ps))
for port, want in ((11500, "ob-tiny:latest"), (11400, "qwen3.5:2b")):
    c = http.client.HTTPConnection("127.0.0.1", port); c.request("GET", "/api/ps"); names = [m["name"] for m in json.loads(c.getresponse().read())["models"]]
    ok(names == [want], "instance :%d n'a chargé que %s" % (port, want))
c = http.client.HTTPConnection("127.0.0.1", 11434); c.request("GET", "/api/tags"); tags = {m["name"] for m in json.loads(c.getresponse().read())["models"]}
ok({"ob-tiny:latest", "qwen3.5:2b", "llama3.2:3b"} <= tags, "liste des modèles via le routeur : magasin partagé complet (%d modèles)" % len(tags))
after = len(os.listdir("/tmp/target/usr/share/ollama/.ollama/models/blobs"))
ok(after == int(sys.argv[1]), "magasin de modèles intact après démarrage des 2 instances (%d fichiers avant et après, OLLAMA_NOPRUNE)" % after)
PY
ps aux | grep -E "ollama[ ]serve|router[.]py" | awk '{print $2}' | xargs -r kill 2>/dev/null
