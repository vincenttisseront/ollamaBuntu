#!/usr/bin/env python3
"""Recherche et quantifications Hugging Face contre un faux serveur local (aucun accès Internet)."""
import http.server, json, os, sys, threading
sys.dont_write_bytecode = True
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
LIST = [{"id": "bart/Llama-3.2-3B-GGUF", "downloads": 900, "likes": 3, "tags": ["gguf"]},
        {"id": "x/Llama-3.2-3B-abliterated-GGUF", "downloads": 500, "likes": 1, "tags": ["gguf"]},
        {"id": "y/Llama-3.2-Uncensored-GGUF", "downloads": 100, "likes": 0, "tags": ["gguf"]},
        {"id": "z/gated-Llama", "downloads": 50, "gated": "auto", "tags": []}]
INFO = {"id": "bart/Llama-3.2-3B-GGUF", "tags": ["gguf"], "siblings": [
    {"rfilename": "Llama-3.2-3B-Q4_K_M.gguf", "size": 2000}, {"rfilename": "Llama-3.2-3B-Q8_0.gguf", "size": 3400},
    {"rfilename": "Llama-3.2-3B-IQ3_XS.gguf", "size": 1300}, {"rfilename": "mmproj-F16.gguf", "size": 5}, {"rfilename": "README.md", "size": 1},
    {"rfilename": "big-Q6_K-00001-of-00002.gguf", "size": 10}, {"rfilename": "big-Q6_K-00002-of-00002.gguf", "size": 7}]}
ST = {"id": "Org/Llama-3.2-3B", "tags": ["safetensors"], "siblings": [{"rfilename": "model-00001-of-00002.safetensors", "size": 4000}, {"rfilename": "config.json", "size": 1}]}
EMPTY = {"id": "Org/Zzz-Modele", "tags": [], "siblings": [{"rfilename": "README.md", "size": 1}]}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/api/models?"): body, code = LIST, 200
        elif self.path.startswith("/api/models/bart/Llama-3.2-3B-GGUF"): body, code = INFO, 200
        elif self.path.startswith("/api/models/Org/Llama-3.2-3B"): body, code = ST, 200
        elif self.path.startswith("/api/models/Org/Zzz-Modele"): body, code = EMPTY, 200
        else: body, code = {}, 404
        raw = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OB_HF"] = "http://127.0.0.1:%d" % srv.server_port
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import server
ids = lambda r: [m["id"] for m in r["models"]]
r = server.hf_search("llama", "standard"); ok(ids(r) == ["bart/Llama-3.2-3B-GGUF"], "standard : versions sans censure et dépôts à accès restreint masqués")
r = server.hf_search("llama", "all"); ok(len(ids(r)) == 3 and [m["uncensored"] for m in r["models"]] == [False, True, True], "toutes : les versions sans censure apparaissent, signalées")
r = server.hf_search("llama", "uncensored"); ok(sorted(ids(r)) == ["x/Llama-3.2-3B-abliterated-GGUF", "y/Llama-3.2-Uncensored-GGUF"], "sans censure seulement")
try: server.hf_search("a;rm -rf", "standard"); ok(False, "recherche invalide refusée")
except ValueError: ok(True, "recherche avec caractères interdits refusée")
f = server.hf_files("bart/Llama-3.2-3B-GGUF"); q = {x["quant"]: x for x in f["quants"]}
ok(sorted(q) == ["IQ3_XS", "Q4_K_M", "Q6_K", "Q8_0"], "quantifications détectées, mmproj et README ignorés")
ok(q["Q6_K"]["size"] == 17 and q["Q6_K"]["files"] == 2, "fichier en plusieurs parties : tailles additionnées")
ok([x["size"] for x in f["quants"]] == sorted(x["size"] for x in f["quants"]), "triées par taille")
for bad in ("../etc/passwd", "a/b/c", "x", ""):
    try: server.hf_files(bad); ok(False, "nom invalide refusé : %r" % bad)
    except ValueError: ok(True, "nom invalide refusé : %r" % bad)
f = server.hf_files("Org/Llama-3.2-3B")
ok(f["quants"] == [] and f["safetensors"] is True and [a["id"] for a in f["alternatives"]] == ["bart/Llama-3.2-3B-GGUF"] and f["alternatives"][0]["downloads"] == 900, "dépôt d'origine (safetensors) sans GGUF : signalé, avec les versions GGUF du même modèle proposées")
f = server.hf_files("Org/Zzz-Modele"); ok(f["quants"] == [] and f["safetensors"] is False and f["alternatives"] == [], "dépôt sans GGUF ni poids reconnus : aucune proposition inventée")
ok("alternatives" not in server.hf_files("bart/Llama-3.2-3B-GGUF"), "dépôt GGUF : pas de proposition")
ok(server.hf_gguf_alternatives("bart/Llama-3.2-3B-GGUF") == [] and server.hf_gguf_alternatives("o/ab") == [], "le dépôt lui-même n'est jamais proposé ; nom trop court : rien")
try: server.hf_files("nobody/none"); ok(False, "dépôt inconnu")
except ValueError as e: ok("introuvable" in str(e), "dépôt inconnu : message clair")
