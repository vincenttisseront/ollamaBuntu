#!/usr/bin/env python3
"""Console : ajustement des modèles (verdicts, détail, calibrage, mesure mémoire, application) et moteur llama.cpp (création, états, actions, installation vérifiée du binaire,
routes HTTP, droits, audit, sauvegarde)."""
import hashlib, http.client, http.server, io, json, os, stat, sys, tempfile, threading, time, zipfile
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_STATE=os.path.join(tmp, "state"), OB_MODELS=os.path.join(tmp, "models"))
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import fit, llamacpp, server, updater, backup
GIB = fit.GIB
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a, **k):
    try: f(*a, **k)
    except (ValueError, updater.UpdateError) as e: return str(e)
    return None
os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
server.AUDIT_FILE = os.path.join(tmp, "audit.jsonl")
server.FIT_FILE = os.path.join(ETC, "fit.json"); server.ENGINES_FILE = os.path.join(ETC, "engines.json"); server.LLAMA_GLOBAL = os.path.join(ETC, "llama.json")
server.LLAMA_ROOT = os.path.join(tmp, "state", "llama"); server.MODELS_DIR = os.path.join(tmp, "models"); server.CONTEXT_FILE = os.path.join(ETC, "model-context.json")
server.save_users({"admin": dict(server.hash_password("Secret-123"), role="admin", linux=False, rev="r0", created=1, updated=1),
                   "jean": dict(server.hash_password("Secret-456"), role="utilisateur", linux=False, rev="r1", created=1, updated=1)})

# --- matériel et modèles simulés : Radeon RX 7800 XT 16 Go, 15,4 Go de RAM
server.gpu_inventory = lambda: [{"description": "AMD Radeon RX 7800 XT", "total": "16.0 GiB", "library": "ROCm", "key": "k"}]
server.meminfo = lambda: {"MemTotal": int(15.4 * GIB), "MemAvailable": int(13.8 * GIB)}
ENV = {}
UPD = []
server.read_env = lambda: dict(ENV)
server.update_env = lambda ch, restart=True: (UPD.append(dict(ch)), ENV.update({k: v for k, v in ch.items()}))
RUN = []
server.run = lambda cmd, timeout=10, **kw: (RUN.append(list(cmd)), "active\n" if cmd[:2] == ["systemctl", "is-active"] else "")[1]
QWEN = {"general.architecture": "qwen3moe", "general.parameter_count": 30532122624, "qwen3moe.block_count": 48, "qwen3moe.embedding_length": 2048, "qwen3moe.attention.head_count": 32, "qwen3moe.attention.head_count_kv": 4,
        "qwen3moe.attention.key_length": 128, "qwen3moe.attention.value_length": 128, "qwen3moe.context_length": 40960, "qwen3moe.expert_count": 128, "qwen3moe.expert_used_count": 8, "qwen3moe.expert_feed_forward_length": 768}
GEMMA = {"general.architecture": "gemma3", "general.parameter_count": 12e9, "gemma3.block_count": 48, "gemma3.embedding_length": 3840, "gemma3.attention.head_count": 16, "gemma3.attention.head_count_kv": 8, "gemma3.attention.key_length": 256, "gemma3.context_length": 131072}
DENSE = dict(GEMMA, **{"gemma3.block_count": 60})
INFO = {"gemma4:12b": GEMMA, "qwen3:30b-a3b": QWEN, "dense30:latest": DENSE}
TAGS = [{"name": "gemma4:12b", "size": int(8.1 * GIB), "digest": "g"}, {"name": "qwen3:30b-a3b", "size": int(17.3 * GIB), "digest": "q"}, {"name": "dense30:latest", "size": int(22 * GIB), "digest": "d"},
        {"name": "gemma4:12b-gpu1", "size": 1, "digest": "x"}, {"name": "gpt-oss:120b-cloud", "size": 1, "digest": "c"}]
ENGINE_STATE = {}
CALLS = []
def fake_ollama_json(method, path, body=None, timeout=15, addr=None):
    if addr and path.startswith("/engine/"):
        CALLS.append((method, path, addr))
        port = int(addr.rsplit(":", 1)[1])
        if path == "/engine/status":
            if port in ENGINE_STATE: return 200, ENGINE_STATE[port]
            raise OSError("refusé")
        return 200, {"ok": True}
    if path == "/api/tags": return 200, {"models": TAGS}
    if path == "/api/show": return 200, {"model_info": INFO.get(body["model"], {})}
    raise OSError("inattendu : " + path)
server.ollama_json = fake_ollama_json
NOW = time.time()
LOG = []
server.read_requests = lambda n=5000: LOG
def rq(model, tps, tok=100, status=200, dt=60): return {"model": model, "ts": NOW - dt, "tps": tps, "out_tok": tok, "status": status}
def install_model(name, digest):
    host, ns, mod, tag = llamacpp.parse_model_name(name)
    p = os.path.join(server.MODELS_DIR, "manifests", host, ns, mod); os.makedirs(p, exist_ok=True); os.makedirs(os.path.join(server.MODELS_DIR, "blobs"), exist_ok=True)
    json.dump({"layers": [{"mediaType": llamacpp.MODEL_MEDIA, "digest": "sha256:" + digest}]}, open(os.path.join(p, tag), "w")); open(os.path.join(server.MODELS_DIR, "blobs", "sha256-" + digest), "wb").write(b"G" * 100)

# ---------------------------------------------------------------- AJUSTEMENT
v = server.fit_view()
rows = {r["name"]: r for r in v["models"]}
ok(sorted(rows) == ["dense30:latest", "gemma4:12b", "qwen3:30b-a3b"], "modèles étudiés : les installés (copies « -gpuN » et modèles cloud écartés)")
ok(v["hw"]["vram"] == 16 * GIB and v["hw"]["gpu_theory"] == 624 and not v["hw"]["calibrated"] and v["hw"]["ram_avail"] == int(13.8 * GIB), "matériel : 16 Gio de mémoire vidéo, carte reconnue (624 Go/s), pas calibrée")
ok(rows["gemma4:12b"]["verdict"] == "gpu" and rows["gemma4:12b"]["label"] == "Tient en mémoire vidéo" and not rows["gemma4:12b"]["moe"] and rows["gemma4:12b"]["tps"] and 30 < rows["gemma4:12b"]["tps"] < 70, "gemma 12B : tient en mémoire vidéo, vitesse estimée")
q = rows["qwen3:30b-a3b"]
ok(q["verdict"] == "moe" and q["moe"] and q["experts"] == 128 and q["used"] == 8 and 5 <= q["n_cpu_moe"] <= 20 and q["tps"] > 25, "Qwen3-30B-A3B : experts en mémoire système, %s couche(s) sur 48, %.0f jetons/s estimés" % (q["n_cpu_moe"], q["tps"]))
ok(rows["dense30:latest"]["verdict"] == "couches" and rows["dense30:latest"]["tps"] < 5 and rows["dense30:latest"]["n_cpu_moe"] is None, "dense de 22 Gio : débordement par couches, lent, pas de moteur MoE")
ok(v["detail"] is None and v["settings"] == {"ctx": None, "parallel": 1, "kv": "f16"}, "sans modèle demandé : pas de détail ; réglages actuels d'Ollama")
d = server.fit_view("qwen3:30b-a3b")["detail"]
ok(d["verdict"] == "moe" and any(s["mode"] == "moe" for s in d["scenarios"]) and any(s["label"].startswith("Pour comparaison") for s in d["scenarios"]) and d["row"]["name"] == "qwen3:30b-a3b", "détail : scénarios dont la comparaison avec le débordement par couches")
LOG[:] = [rq("gemma4:12b", t) for t in (70, 76, 74)] + [rq("gemma4:12b", 5, tok=5), rq("qwen3:30b-a3b", 90, status=500)]
ok(server.fit_view()["models"][1]["measured"] == 74 if server.fit_view()["models"][1]["name"] == "gemma4:12b" else True, "débit mesuré d'après le journal des requêtes")
rows = {r["name"]: r for r in server.fit_view()["models"]}
ok(rows["gemma4:12b"]["measured"] == 74 and rows["qwen3:30b-a3b"]["measured"] is None, "gemma : médiane de 74 jetons/s (requêtes courtes ou en erreur ignorées) ; Qwen sans mesure")
server.CONTEXT_FILE and json.dump({"models": {"gemma4:12b": 131072}}, open(server.CONTEXT_FILE, "w"))
cur = server.fit_view("gemma4:12b")["detail"]
ok(cur["scenarios"][0]["label"] == "Réglages actuels" and cur["current_fits"] is False and cur["verdict"] in ("ajuste",), "contexte de 131 072 jetons configuré : ne tient pas tel quel, un réglage est proposé")
os.remove(server.CONTEXT_FILE)

# --- calibrage d'après un débit mesuré
r = server.fit_calibrate("gemma4:12b")
ok(r["tps"] == 74 and 500 < r["gpu_gbps"] < 900 and server.fit_conf()["calib"]["model"] == "gemma4:12b", "calibrage : bande passante effective de la carte déduite du débit mesuré (%.0f Go/s ; le débit des vraies mesures de l'utilisateur inclut le décodage spéculatif)" % r["gpu_gbps"])
v2 = server.fit_view()
ok(v2["hw"]["calibrated"] and abs(v2["hw"]["gpu_eff"] - r["gpu_gbps"]) < 0.01, "la vue utilise désormais la bande passante calibrée")
g2 = {x["name"]: x for x in v2["models"]}["gemma4:12b"]
ok(abs(g2["tps"] - 74) < 4, "…et l'estimation de gemma rejoint la mesure (%.0f contre 74)" % g2["tps"])
saved_log = list(LOG); LOG.clear()
ok("pas assez" in (raises(server.fit_calibrate, "gemma4:12b") or ""), "calibrage sans mesures récentes : refusé avec la marche à suivre")
LOG[:] = saved_log
ok("déborde" in (raises(server.fit_calibrate, "qwen3:30b-a3b") or ""), "calibrage avec un modèle à experts qui déborde : refusé")
LOG.extend(rq("dense30:latest", 4) for _ in range(5))
ok("déborde" in (raises(server.fit_calibrate, "dense30:latest") or ""), "calibrage avec un modèle qui déborde de la mémoire vidéo : refusé (il ne mesure pas la carte)")
ok(raises(server.fit_calibrate, "inconnu:1b") == "modèle introuvable", "modèle inconnu")
server.fit_save_conf({"clear_calibration": True}); ok("calib" not in server.fit_conf(), "calibrage effaçable")

# --- réglages et mesure de la mémoire
c = server.fit_save_conf({"ram_gbps": "45,5", "gpu_gbps": 500})
ok(c["ram_gbps"] == 45.5 and c["gpu_gbps"] == 500.0 and oct(os.stat(server.FIT_FILE).st_mode & 0o777) == "0o644", "débits saisis à la main (virgule décimale acceptée)")
ok(server.fit_view()["hw"]["ram_measured"] and server.fit_view()["hw"]["gpu_theory"] == 500.0, "…repris par le calcul")
ok(all(raises(server.fit_save_conf, x) for x in ({"ram_gbps": 0}, {"ram_gbps": "x"}, {"gpu_gbps": 99999})), "débits hors limites ou illisibles : refusés")
server.fit_save_conf({"ram_gbps": None, "gpu_gbps": ""}); ok("ram_gbps" not in server.fit_conf() and "gpu_gbps" not in server.fit_conf(), "valeurs effaçables")
t0 = time.time(); g = server.fit_measure_ram(seconds=0.3, mb=8)
ok(g > 0.5 and time.time() - t0 < 5 and server.fit_conf()["ram_gbps"] == g, "mesure de la mémoire : %.1f Go/s mesurés et enregistrés" % g)
server.fit_save_conf({"ram_gbps": None})

# --- application d'un réglage
UPD.clear(); r = server.fit_apply({"model": "gemma4:12b", "ctx": 8192, "kv": "q8_0"})
ok(r == {"ctx": 8192, "kv": "q8_0"} and json.load(open(server.CONTEXT_FILE))["models"]["gemma4:12b"] == 8192, "contexte du modèle enregistré")
ok(UPD == [{"OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_FLASH_ATTENTION": "1"}], "cache en q8_0 : la flash attention est activée avec lui (sinon Ollama l'ignorerait)")
UPD.clear(); server.fit_apply({"model": "gemma4:12b", "ctx": 8192, "kv": "q8_0"}); ok(UPD == [], "cache déjà à la bonne valeur : Ollama n'est pas redémarré pour rien")
UPD.clear(); server.fit_apply({"model": "gemma4:12b", "ctx": 8192, "kv": "f16"}); ok(UPD and UPD[0]["OLLAMA_KV_CACHE_TYPE"] == "", "retour au cache f16")
ok(raises(server.fit_apply, {"model": "../x", "ctx": 4096}) and raises(server.fit_apply, {"model": "gemma4:12b", "ctx": 4096, "kv": "q5"}) and raises(server.fit_apply, {"model": "gemma4:12b", "ctx": 10}), "nom invalide, cache inconnu, contexte hors limites : refusés")

# --- modèle Hugging Face
server.hf_files = lambda repo: {"id": repo, "uncensored": False, "arch": "qwen3moe", "ctx": 40960, "tags": [], "quants": [{"quant": "Q2_K", "size": int(11 * GIB), "files": 1}, {"quant": "Q4_K_M", "size": int(17.3 * GIB), "files": 1}, {"quant": "Q8_0", "size": int(32 * GIB), "files": 1}]}
h = server.fit_hf("unsloth/Qwen3-30B-A3B-GGUF")
byq = {x["quant"]: x for x in h["quants"]}
ok(h["moe"] and byq["Q2_K"]["verdict"] in ("gpu", "ajuste") and byq["Q4_K_M"]["verdict"] == "moe" and byq["Q4_K_M"]["n_cpu_moe"] and byq["Q8_0"]["verdict"] in ("moe", "trop"), "dépôt Hugging Face à experts : verdict par quantification (léger : tient ; Q4 : experts en mémoire système)")
server.hf_files = lambda repo: {"id": repo, "uncensored": False, "arch": "llama", "ctx": None, "tags": [], "quants": [{"quant": "Q4_K_M", "size": int(7.4 * GIB), "files": 1}]}
ok(not server.fit_hf("TheBloke/Llama-2-13B-GGUF")["moe"] and server.fit_hf("TheBloke/Llama-2-13B-GGUF")["quants"][0]["verdict"] in ("gpu", "ajuste"), "dépôt dense")

# ---------------------------------------------------------------- MOTEUR LLAMA.CPP
install_model("qwen3:30b-a3b", "a" * 64); install_model("gemma4:12b", "b" * 64)
ok(server.engines_load() == ([], True) and server.llama_binary()["installed"] is False, "au départ : aucun moteur, binaire absent")
ok("n'est pas installé" in (raises(server.engine_action, "x", "start") or "") or raises(server.engine_action, "x", "start") == "moteur introuvable", "action sur un moteur inconnu : refusée")
ok(raises(server.engine_save, {"model": "inconnu:1b"}) and "non installé" in raises(server.engine_save, {"model": "inconnu:1b"}), "moteur pour un modèle non installé dans Ollama : refusé")
ok(raises(server.engine_save, {"model": "../x"}) == "nom de modèle invalide", "nom invalide : refusé")
RUN.clear()
e = server.engine_save({"model": "qwen3:30b-a3b"})
ok(e["id"] == "qwen3-30b-a3b" and e["model"] == "qwen3:30b-a3b" and e["port"] == 11600 and e["backend_port"] == 11700 and 5 <= e["n_cpu_moe"] <= 20 and e["kv"] == "q8_0" and e["ctx"] >= 2048 and e["cpu_bytes"] > 0, "création : réglages proposés par le calcul d'ajustement (%s couches d'experts en RAM), ports attribués" % e["n_cpu_moe"])
ok(["systemctl", "enable", "--now", "ollamabuntu-llama@qwen3-30b-a3b.service"] in RUN, "unité systemd du moteur activée et démarrée")
d = json.load(open(server.ENGINES_FILE))
ok(d["exclusive"] is True and d["engines"][0]["id"] == "qwen3-30b-a3b" and oct(os.stat(server.ENGINES_FILE).st_mode & 0o777) == "0o644" and "token" not in json.dumps(d), "engines.json : une seule source pour le routeur et le démon, lisible par eux (0644), aucun secret")
ok("déjà un moteur" in (raises(server.engine_save, {"model": "qwen3:30b-a3b"}) or ""), "un modèle ne peut avoir qu'un moteur")
e2 = server.engine_save({"model": "gemma4:12b", "n_cpu_moe": "", "ctx": 4096})
ok(e2["port"] == 11601 and e2["backend_port"] == 11701 and e2["n_cpu_moe"] is None and e2["ctx"] == 4096 and e2["id"] == "gemma4-12b", "deuxième moteur : ports suivants, aucun expert déplacé quand on le demande")
RUN.clear(); e3 = server.engine_save({"id": "qwen3-30b-a3b", "ctx": 16384, "idle_min": 5})
ok(e3["ctx"] == 16384 and e3["idle_min"] == 5 and e3["model"] == "qwen3:30b-a3b" and e3["n_cpu_moe"] == e["n_cpu_moe"] and e3["port"] == 11600 and ["systemctl", "restart", "ollamabuntu-llama@qwen3-30b-a3b.service"] in RUN, "modification : champs absents conservés, démon redémarré pour relire ses réglages")
ok(raises(server.engine_save, {"id": "qwen3-30b-a3b", "ctx": 10}) and raises(server.engine_save, {"id": "qwen3-30b-a3b", "extra": "--host 0.0.0.0"}) and len(server.engines_load()[0]) == 2, "réglage invalide ou option dangereuse : refusé, rien n'est écrit")
e4 = server.engine_save({"id": "qwen3-30b-a3b", "n_cpu_moe": 14}); ok(e4["n_cpu_moe"] == 14 and e4["cpu_bytes"] > e["cpu_bytes"], "plus de couches d'experts en RAM : octets en mémoire système recalculés")

# --- états et actions
ENGINE_STATE[11600] = {"state": "ready", "pid": 42, "inflight": 1, "requests": 7, "tail": ["x"], "error": ""}
st = server.engine_status(e)
ok(st["state"] == "ready" and st["service"] == "active" and st["pid"] == 42, "état lu auprès du démon")
st = server.engine_status(e2); ok(st["state"] == "service arrêté" or st["service"] in ("active", "inactive"), "démon injoignable : état du service systemd")
lv = server.llama_view()
ok([x["id"] for x in lv["engines"]] == ["qwen3-30b-a3b", "gemma4-12b"] and lv["engines"][0]["status"]["state"] == "ready" and lv["candidates"] == [] and lv["repo"] == "ggml-org/llama.cpp" and "dense30:latest" in lv["all_models"], "vue d'ensemble : moteurs et états ; plus de candidat MoE (le seul a son moteur)")
server.engine_delete("gemma4-12b")
lv = server.llama_view()
ok([x["id"] for x in lv["engines"]] == ["qwen3-30b-a3b"] and ["systemctl", "disable", "--now", "ollamabuntu-llama@gemma4-12b.service"] in RUN, "suppression : retiré de la table, unité arrêtée")
ok(raises(server.engine_delete, "gemma4-12b") == "moteur introuvable", "suppression d'un moteur inconnu : refusée")
json.dump({"exclusive": True, "engines": []}, open(server.ENGINES_FILE, "w"))
ok([c["name"] for c in server.llama_view()["candidates"]] == ["qwen3:30b-a3b"], "modèle MoE sans moteur : proposé comme candidat")
server.engine_save({"model": "qwen3:30b-a3b"}); CALLS.clear()
ok("n'est pas installé" in (raises(server.engine_action, "qwen3-30b-a3b", "start") or ""), "démarrage sans binaire installé : refusé")

# --- installation du binaire depuis GitHub (faux serveur, somme SHA-256 publiée vérifiée)
def make_zip(server_script=b"#!/bin/sh\ncase \"$1\" in --help) echo '--ctx-size N'; echo '--n-cpu-moe N';; esac\nexit 0\n", extra=()):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        zi = zipfile.ZipInfo("build/bin/llama-server"); zi.external_attr = 0o755 << 16; z.writestr(zi, server_script)
        zi = zipfile.ZipInfo("build/bin/libggml.so.1"); zi.external_attr = 0o644 << 16; z.writestr(zi, b"lib")
        zl = zipfile.ZipInfo("build/bin/libggml.so"); zl.external_attr = (0o120000 | 0o777) << 16; z.writestr(zl, "libggml.so.1")
        for name, data in extra:
            zi = zipfile.ZipInfo(name); zi.external_attr = 0o644 << 16; z.writestr(zi, data)
    return b.getvalue()
STATE = {"zip": make_zip(), "digest": True, "assets": None, "fail_release": False, "truncate": 0}
class GH(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0].endswith("/releases"):
            if STATE["fail_release"]: self.send_response(404); self.end_headers(); return
            zb = STATE["zip"]; base = "http://127.0.0.1:%d" % gh.server_address[1]
            a = lambda name: dict(name=name, size=len(zb), browser_download_url=base + "/dl/" + name, **({"digest": "sha256:" + hashlib.sha256(zb).hexdigest()} if STATE["digest"] else {}))
            # comme GitHub le 13/11/2026 : la « dernière » version (v1.0.0) n'a qu'un fichier texte, les vraies compilations sont des pré-versions plus bas ou plus haut
            stub = {"tag_name": "v1.0.0", "prerelease": False, "assets": [{"name": "nightly-tag.txt", "size": 7, "digest": "sha256:" + "e" * 64, "browser_download_url": base + "/dl/nightly-tag.txt"}]}
            build = {"tag_name": "b7001", "prerelease": True, "assets": STATE["assets"] or [a("llama-b7001-bin-ubuntu-vulkan-x64.zip"), a("llama-b7001-bin-ubuntu-x64.zip"), a("llama-b7001-bin-win-cuda-12.4-x64.zip")]}
            body = json.dumps([stub, {"tag_name": "b7002", "prerelease": True, "draft": True, "assets": [a("llama-b7002-bin-ubuntu-vulkan-x64.zip")]}, {"tag_name": "b7003", "prerelease": True, "assets": []}, build]).encode()
        elif self.path.startswith("/dl/"):
            body = STATE["zip"]
        else:
            self.send_response(404); self.end_headers(); return
        if STATE["truncate"] and self.path.split("?")[0].endswith("/releases"):   # connexion coupée avant la fin du corps (IncompleteRead, qui n'est pas une OSError)
            STATE["truncate"] -= 1
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body[:len(body) // 2]); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
gh = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GH); threading.Thread(target=gh.serve_forever, daemon=True).start()
updater.API = "http://127.0.0.1:%d" % gh.server_address[1]
def install(backend):
    server.llama_install(backend)
    t0 = time.time()
    while server._llama_inst["state"] == "running" and time.time() - t0 < 30: time.sleep(0.05)
    return server._llama_inst
ok("vulkan, rocm ou cpu" in (raises(server.llama_install, "cuda") or ""), "moteur de calcul inconnu : refusé")
i = install("vulkan")
b = server.llama_binary()
ok(i["state"] == "done" and b["installed"] and b["tag"] == "b7001" and b["backend"] == "vulkan" and b["asset"].endswith("ubuntu-vulkan-x64.zip") and b["path"].endswith("build/bin/llama-server") and len(b["sha256"]) == 64, "installation : bon fichier Ubuntu/Vulkan choisi, binaire vérifié et en place (%s)" % b["tag"])
ok(os.access(b["path"], os.X_OK) and os.path.islink(os.path.join(os.path.dirname(b["path"]), "libggml.so")) and os.readlink(os.path.join(os.path.dirname(b["path"]), "libggml.so")) == "libggml.so.1", "droits d'exécution, lien de bibliothèque relatif recréé")
ok(any("SHA-256 vérifiée" in x for x in i["log"]) and any("--n-cpu-moe : oui" in x for x in i["log"]), "journal d'installation : somme vérifiée, options reconnues")
ok(oct(os.stat(server.LLAMA_GLOBAL).st_mode & 0o777) == "0o644" and ("POST", "/engine/stop", "127.0.0.1:11600") in CALLS, "binaire enregistré ; les moteurs en marche sont arrêtés pour reprendre le nouveau à la demande")
CALLS.clear(); server.engine_action("qwen3-30b-a3b", "start"); time.sleep(0.3)
ok(("POST", "/engine/start", "127.0.0.1:11600") in CALLS and any(c[:2] == ["systemctl", "is-active"] for c in RUN), "démarrage demandé : le démon est appelé en arrière-plan")
CALLS.clear(); server.engine_action("qwen3-30b-a3b", "stop"); ok(("POST", "/engine/stop", "127.0.0.1:11600") in CALLS, "arrêt demandé : appel direct")
ok(raises(server.engine_action, "qwen3-30b-a3b", "explose") == "action inconnue", "action inconnue refusée")
# refus
STATE["digest"] = False; i = install("vulkan")
ok(i["state"] == "error" and "SHA-256" in i["error"] and "ne pourrait pas être vérifiée" in i["error"], "fichier publié sans somme SHA-256 : installation refusée")
STATE["digest"] = True; good = STATE["zip"]
STATE["assets"] = [dict(name="llama-b7001-bin-ubuntu-vulkan-x64.zip", size=5, browser_download_url=updater.API + "/dl/x.zip", digest="sha256:" + "0" * 64)]
i = install("vulkan"); ok(i["state"] == "error" and "SHA-256 incorrecte" in i["error"], "somme différente de celle publiée : téléchargement refusé")
ok(not os.path.exists(os.path.join(server.LLAMA_ROOT, "download.part.zip")), "…et supprimé")
STATE["assets"] = None; i = install("rocm"); ok(i["state"] == "error" and "aucun fichier Ubuntu" in i["error"], "pas de fichier pour ce moteur de calcul : message clair")
STATE["zip"] = make_zip(extra=[("../evil", b"x")]); i = install("vulkan"); ok(i["state"] == "error" and "chemin suspect" in i["error"], "archive avec chemin remontant : refusée")
ok(not os.path.exists(os.path.join(tmp, "state", "evil")) and not os.path.exists(os.path.join(server.LLAMA_ROOT, "evil")), "…rien n'est écrit hors du dossier")
bz = io.BytesIO()
with zipfile.ZipFile(bz, "w") as z:
    zi = zipfile.ZipInfo("build/bin/llama-server"); zi.external_attr = 0o755 << 16; z.writestr(zi, b"#!/bin/sh\nexit 0\n")
    zl = zipfile.ZipInfo("build/bin/passwd"); zl.external_attr = (0o120000 | 0o777) << 16; z.writestr(zl, "../../../../../../etc/passwd")
STATE["zip"] = bz.getvalue(); i = install("vulkan"); ok(i["state"] == "error" and "lien suspect" in i["error"], "lien symbolique qui sort du dossier : archive refusée")
STATE["zip"] = make_zip(b"#!/bin/sh\necho 'no such flag' >&2\nexit 2\n"); i = install("vulkan"); ok(i["state"] == "error" and "ne démarre pas" in i["error"], "binaire qui ne démarre pas sur ce serveur : refusé avant d'être installé")
ok(server.llama_binary()["path"] == b["path"] and os.access(b["path"], os.X_OK), "…l'installation précédente reste en place après chaque échec")
# bibliothèque système manquante : détectée, paquet Ubuntu installé, essai relancé
MARK = os.path.join(tmp, "libgomp-ok")
def lib_script(lib): return ("#!/bin/sh\n[ -e %s ] || { echo \"$0: error while loading shared libraries: %s: cannot open shared object file: No such file or directory\" >&2; exit 127; }\n"
                             "case \"$1\" in --help) echo '--ctx-size N'; echo '--n-cpu-moe N';; esac\nexit 0\n" % (MARK, lib)).encode()
APT = []
def fake_apt(cands, ok=True):
    APT.append(list(cands))
    if ok: open(MARK, "w").close()
    return ok, cands[0]
_real_apt = server._apt_install
server._apt_install = fake_apt
STATE["zip"] = make_zip(lib_script("libgomp.so.1")); i = install("vulkan")
ok(i["state"] == "done" and APT == [["libgomp1"]] and any("libgomp.so.1 : installation du paquet libgomp1" in x for x in i["log"]) and any("Paquet libgomp1 installé." in x for x in i["log"]), "libgomp.so.1 absente (Ubuntu minimale) : paquet libgomp1 installé automatiquement, puis l'installation aboutit")
os.remove(MARK); APT.clear(); server._apt_install = lambda c: fake_apt(c, ok=False)
i = install("vulkan"); ok(i["state"] == "error" and "sudo apt install -y libgomp1" in i["error"] and "libgomp.so.1" in i["error"], "paquet impossible à installer : la commande à lancer à la main est donnée")
APT.clear(); server._apt_install = fake_apt
STATE["zip"] = make_zip(lib_script("libamdhip64.so.7")); STATE["assets"] = [dict(name="llama-b7001-bin-ubuntu-rocm-7.0-x64.zip", size=5, browser_download_url=updater.API + "/dl/r.zip", digest="sha256:" + hashlib.sha256(STATE["zip"]).hexdigest())]; i = install("rocm")
ok(i["state"] == "error" and APT == [] and "libamdhip64.so.7" in i["error"] and "Vulkan" in i["error"], "bibliothèque ROCm absente : rien n'est installé à l'aveugle, le moteur Vulkan est proposé")
STATE["assets"] = None; i = install("vulkan"); ok(i["state"] == "error" and "libamdhip64.so.7" in i["error"] and "Vulkan" not in i["error"].split("absentes")[-1], "…mais sans suggérer Vulkan quand c'est déjà le moteur choisi")
server._apt_install = _real_apt; STATE["zip"] = good
server._llama_inst.update(state="running", log=["Version b1"]); server._llama_progress("Téléchargement : 10 % (5 / 50 Mo)"); server._llama_progress("Téléchargement : 40 % (20 / 50 Mo)")
ok(server._llama_inst["log"] == ["Version b1", "Téléchargement : 40 % (20 / 50 Mo)"], "progression du téléchargement : une seule ligne mise à jour")
server._llama_inst.update(state="idle")
STATE["zip"] = good; STATE["fail_release"] = True; i = install("vulkan"); ok(i["state"] == "error" and "introuvable" in i["error"], "GitHub sans réponse : message clair"); STATE["fail_release"] = False
STATE["zip"] = good; STATE["truncate"] = 1; i = install("vulkan")
ok(i["state"] == "done" and any("nouvel essai (2 sur 3)" in x for x in i["log"]) and any("versions récentes lues" in x for x in i["log"]), "liste des versions coupée en cours de route : nouvel essai, puis installation (avant : l'état restait « en cours » pour toujours)")
STATE["truncate"] = 9; i = install("vulkan")
ok(i["state"] == "error" and "interrompue" in i["error"] and any(x.startswith("Échec") for x in i["log"]), "coupée à chaque fois : échec clair après 3 essais, pas de blocage"); STATE["truncate"] = 0
_orig = server.llamacpp.pick_release
def _boom(*a, **k): raise KeyError("inattendu")
server.llamacpp.pick_release = _boom; i = install("vulkan"); server.llamacpp.pick_release = _orig
ok(i["state"] == "error" and "KeyError" in i["error"], "exception imprévue : l'installation passe en erreur au lieu de rester « en cours »")
server._llama_inst.update(state="running", t=time.time()); ok("déjà en cours" in (raises(server.llama_install, "vulkan") or ""), "installation récente en cours : une seconde est refusée")
server._llama_inst.update(state="running", t=time.time() - 4000); i = install("vulkan"); ok(i["state"] == "done", "installation « en cours » depuis plus de 30 minutes (thread perdu) : une nouvelle est acceptée")
tgz = io.BytesIO()
import tarfile
with tarfile.open(fileobj=tgz, mode="w:gz") as t:
    data = b"#!/bin/sh\ncase \"$1\" in --help) echo '--ctx-size N'; echo '--override-tensor X';; esac\nexit 0\n"; ti = tarfile.TarInfo("llama-b7002/llama-server"); ti.size = len(data); ti.mode = 0o755; t.addfile(ti, io.BytesIO(data))
STATE["zip"] = tgz.getvalue(); STATE["assets"] = [dict(name="llama-b7002-bin-ubuntu-x64.tar.gz", size=len(STATE["zip"]), browser_download_url=updater.API + "/dl/a.tgz", digest="sha256:" + hashlib.sha256(STATE["zip"]).hexdigest())]
i = install("cpu"); ok(i["state"] == "done" and server.llama_binary()["backend"] == "cpu" and server.llama_binary()["path"].endswith("llama-b7002/llama-server") and any("repli sur --override-tensor" in x for x in i["log"]), "archive .tar.gz et moteur « cpu » : installés ; version sans --n-cpu-moe signalée")
STATE["assets"] = None; STATE["zip"] = good

# ---------------------------------------------------------------- ROUTES HTTP
httpd = server.make_server(0, server.Handler); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
def req(method, path, cookie="", body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
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
st, _, d = req("GET", "/api/fit", adm); ok(st == 200 and len(d["models"]) == 3 and d["hw"]["vram"] == 16 * GIB, "GET /api/fit")
st, _, d = req("GET", "/api/fit?model=qwen3:30b-a3b", adm); ok(st == 200 and d["detail"]["verdict"] == "moe", "GET /api/fit?model=")
st, _, d = req("GET", "/api/fit/hf?repo=a/b", adm); ok(st == 200 and "quants" in d, "GET /api/fit/hf")
server.hf_files = lambda repo: (_ for _ in ()).throw(ValueError("dépôt introuvable sur Hugging Face"))
st, _, d = req("GET", "/api/fit/hf?repo=a/b", adm); ok(st == 400 and "introuvable" in d["error"], "dépôt introuvable : 400")
st, _, d = req("GET", "/api/llama", adm); ok(st == 200 and d["binary"]["installed"] and d["engines"][0]["id"] == "qwen3-30b-a3b" and "install" in d, "GET /api/llama")
st, _, d = req("GET", "/api/llama/logs?id=qwen3-30b-a3b", adm); ok(st == 200 and "text" in d and req("GET", "/api/llama/logs?id=zzz", adm)[0] == 400, "journal d'un moteur ; moteur inconnu : 400")
for path in ("/api/fit", "/api/fit/hf?repo=a/b", "/api/llama", "/api/llama/logs?id=x"):
    if req("GET", path, usr)[0] != 403 or req("GET", path)[0] != 401: ok(False, "droits : " + path)
ok(True, "lectures réservées aux administrateurs (403 / 401)")
for path, body in (("/api/fit/config", {"ram_gbps": 40}), ("/api/fit/measure-ram", {}), ("/api/fit/calibrate", {"model": "gemma4:12b"}), ("/api/fit/apply", {"model": "gemma4:12b", "ctx": 4096}), ("/api/llama/install", {"backend": "cpu"}),
                   ("/api/llama/save", {"model": "gemma4:12b"}), ("/api/llama/action", {"id": "x", "action": "stop"}), ("/api/llama/delete", {"id": "x"})):
    if req("POST", path, usr, body)[0] != 403: ok(False, "droits : " + path)
ok(True, "actions réservées aux administrateurs")
st, _, d = req("POST", "/api/fit/config", adm, {"ram_gbps": 40}); ok(st == 200 and d["conf"]["ram_gbps"] == 40.0, "POST /api/fit/config")
ok(req("POST", "/api/fit/config", adm, {"ram_gbps": 0})[0] == 400, "valeur invalide : 400")
st, _, d = req("POST", "/api/fit/apply", adm, {"model": "gemma4:12b", "ctx": 4096, "kv": "f16"}); ok(st == 200 and d["ctx"] == 4096, "POST /api/fit/apply")
st, _, d = req("POST", "/api/fit/calibrate", adm, {"model": "gemma4:12b"}); ok(st == 200 and d["tps"] == 74, "POST /api/fit/calibrate")
st, _, d = req("POST", "/api/llama/save", adm, {"model": "gemma4:12b", "n_cpu_moe": ""}); ok(st == 200 and d["engine"]["id"] == "gemma4-12b", "POST /api/llama/save")
ok(req("POST", "/api/llama/save", adm, {"model": "absent:1b"})[0] == 400, "modèle absent : 400")
ok(req("POST", "/api/llama/action", adm, {"id": "gemma4-12b", "action": "stop"})[0] == 200 and req("POST", "/api/llama/action", adm, {"id": "zzz", "action": "stop"})[0] == 400, "POST /api/llama/action ; moteur inconnu : 400")
ok(req("POST", "/api/llama/delete", adm, {"id": "gemma4-12b"})[0] == 200, "POST /api/llama/delete")
st, _, d = req("POST", "/api/llama/install", adm, {"backend": "cuda"}); ok(st == 400, "moteur de calcul inconnu : 400")
st, _, d = req("POST", "/api/llama/install", adm, {"backend": "vulkan"}); ok(st == 200, "POST /api/llama/install")
t0 = time.time()
while server._llama_inst["state"] == "running" and time.time() - t0 < 30: time.sleep(0.05)
audit = open(server.AUDIT_FILE).read()
ok("Installation du moteur llama.cpp" in audit and "Moteur MoE (réglages)" in audit and "Calibrage de la carte" in audit and "Réglages de l'ajustement" in audit, "actions consignées au journal d'audit")
ok(all(f in backup.FILES for f in ("engines.json", "llama.json", "fit.json")), "réglages inclus dans la sauvegarde de la configuration")
print("\n%d vérifications réussies" % n)
os._exit(0)
