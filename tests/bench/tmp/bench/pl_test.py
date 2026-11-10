import json, ssl, http.client, os, sys, time, subprocess
T = "/tmp/target"; U = T + "/tmp/gpufake/units"; n = 0
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
cookie = {}
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
def api(method, path, body=None):
    c = http.client.HTTPSConnection("127.0.0.1", 18443, context=ctx, timeout=120)
    h = {"X-OB": "1", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = "; ".join("%s=%s" % kv for kv in cookie.items())
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h); r = c.getresponse(); raw = r.read()
    for k, v in r.getheaders():
        if k.lower() == "set-cookie": kv = v.split(";")[0].split("=", 1); cookie[kv[0]] = kv[1]
    return r.status, json.loads(raw or b"{}")
def ollama(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", 11434, timeout=60); c.request(method, path, body=json.dumps(body) if body else None); r = c.getresponse(); return r.status, json.loads(r.read() or b"{}")
def calls(): return open(T + "/tmp/systemctl-calls.log").read() if os.path.exists(T + "/tmp/systemctl-calls.log") else ""
def reset_calls(): open(T + "/tmp/systemctl-calls.log", "w").close()
def gpu_line(i, lib, name, desc, pci, total="44.5 GiB"):
    return 'time=2026-11-04T10:00:02Z level=INFO source=types.go:50 msg="inference compute" id=%s library=%s compute=8.9 name=%s description="%s" libdirs=ollama driver=13.0 pci_id=%s type=discrete total="%s" available="%s"\n' % (i, lib, name, desc, pci, total, total)
api("POST", "/api/login", {"user": "vti", "password": "Ollama-2026!"})
s, d = api("GET", "/api/gpu/placement")
inv = {g["pci_id"]: g for g in d["inventory"]}
ok(s == 200 and len(inv) == 3 and inv["0000:04:00.0"]["ordinal"] == 0 and d["pools"] == [], "inventaire : 3 GPU (2 x L40S CUDA, Arc Vulkan n°0), aucun groupe")
ok([g["index"] for g in d["main_gpus"]] == [0, 1, 2], "épinglage : l'instance principale voit les GPU 0, 1, 2 (ordre de détection d'Ollama)")
# --- épinglage : variante réelle créée par Ollama
s, d = api("POST", "/api/models/pin", {"name": "ob-tiny", "index": 1})
ok(s == 200 and d["variant"] == "ob-tiny:latest-gpu1", "variante créée par l'API d'Ollama : %s" % d.get("variant", d))
s2, show = ollama("POST", "/api/show", {"model": "ob-tiny:latest-gpu1"})
ok("main_gpu" in show.get("parameters", "") and "1" in show.get("parameters", ""), "Ollama confirme le paramètre de la variante : « %s »" % show.get("parameters", "").strip())
tags = {m["name"]: m for m in ollama("GET", "/api/tags")[1]["models"]}
import glob
def layers(tag):
    f = os.path.realpath(glob.glob(T + "/usr/share/ollama/.ollama/models/manifests*/*/library/ob-tiny/" + tag)[0])
    return {l["mediaType"].split(".")[-1]: l for l in json.load(open(f))["layers"]}
lb, lv = layers("latest"), layers("latest-gpu1")
ok(lb["model"]["digest"] == lv["model"]["digest"] and lv["params"]["size"] < 100, "même fichier de poids partagé (%s), la variante n'ajoute que %d octets de paramètres" % (lb["model"]["digest"][7:19], lv["params"]["size"]))
s, d = api("GET", "/api/gpu/placement"); p = d["pins"][0]
ok(p["ok"] and p["description"] == "NVIDIA L40S" and p["pci"] == "0000:42:00.0", "épinglage enregistré : GPU 1 = L40S en 0000:42:00.0, état correct")
ok(api("POST", "/api/models/pin", {"name": "ob-tiny", "index": 7})[0] == 400, "GPU 7 inexistant : refusé")
ok(api("POST", "/api/models/pin", {"name": "ob-tiny:latest-gpu1", "index": 0})[0] == 400, "épingler une variante déjà épinglée : refusé")
# --- groupe de GPU
open(T + "/etc/ollamabuntu/ollama.env", "w").write("OLLAMA_HOST=127.0.0.1:11434\nOLLAMA_KEEP_ALIVE=2h\n")
reset_calls()
s, d = api("POST", "/api/gpu/pools/create", {"name": "Gros modèles", "gpus": ["0000:41:00.0", "0000:04:00.0"], "models": ["llama3.2:3b"]})
ok(s == 200 and d["id"] == "g1", "groupe « Gros modèles » créé (L40S n°1 + Arc, modèle llama3.2:3b)")
g1 = open(T + "/etc/ollamabuntu/pools/g1.env").read()
ok("OLLAMA_HOST=127.0.0.1:11500" in g1 and "CUDA_VISIBLE_DEVICES=GPU-5f1a\n" in g1 and "GGML_VK_VISIBLE_DEVICES=0\n" in g1 and "ROCR_VISIBLE_DEVICES=-1" in g1 and "OLLAMA_NOPRUNE=1" in g1,
   "instance du groupe : port 11500, CUDA=GPU-5f1a (UUID), Vulkan=0, ROCm=-1, sans nettoyage du magasin")
ok("OLLAMA_KEEP_ALIVE=2h" in g1 and "OLLAMA_MODELS=/usr/share/ollama/.ollama/models" in g1, "réglages de l'administrateur repris (KEEP_ALIVE=2h) et magasin de modèles partagé")
main = open(T + "/etc/ollamabuntu/ollama-main.env").read()
ok("CUDA_VISIBLE_DEVICES=GPU-77c2\n" in main and "GGML_VK_VISIBLE_DEVICES=-1" in main and "OLLAMA_HOST=127.0.0.1:" in main, "instance principale : limitée à la L40S n°2 (GPU-77c2), Arc retirée, port interne")
c = calls()
ok(all(x in c for x in ["restart ollama.service", "enable ollama-pool@g1.service", "restart ollama-pool@g1.service"]) and "restart ollamabuntu-router" not in c,
   "services : Ollama redémarré, instance g1 activée ; routeur non redémarré (relecture à chaud)")
ok(json.load(open(T + "/etc/ollamabuntu/pools.json"))["pools"][0]["models"] == ["llama3.2:3b"], "pools.json (lu par le routeur) à jour")
for body, why in [({"name": "Autre", "gpus": ["0000:41:00.0"], "models": []}, "GPU déjà dans un groupe"), ({"name": "Autre", "gpus": ["0000:42:00.0"], "models": ["llama3.2:3b"]}, "modèle déjà affecté"),
                  ({"name": "Vide", "gpus": [], "models": []}, "aucun GPU"), ({"name": "<b>x</b>", "gpus": ["0000:42:00.0"]}, "nom invalide"), ({"name": "X", "gpus": ["0000:99:00.0"]}, "GPU inconnu")]:
    s, d = api("POST", "/api/gpu/pools/create", body); ok(s == 400, "refus : %s -> « %s »" % (why, d.get("error")))
# --- après redémarrage des instances : chacune ne voit que ses cartes
open(U + "/ollama.service.log", "w").write('msg="discovering available GPUs..."\n' + gpu_line("GPU-77c2", "CUDA", "CUDA0", "NVIDIA L40S", "0000:42:00.0"))
open(U + "/ollama-pool@g1.service.log", "w").write('msg="discovering available GPUs..."\n' + gpu_line("GPU-5f1a", "CUDA", "CUDA0", "NVIDIA L40S", "0000:41:00.0") + gpu_line("00000000-0400", "Vulkan", "Vulkan0", "Intel(R) Arc(tm) A770 Graphics (DG2)", "0000:04:00.0", "15.9 GiB"))
s, d = api("GET", "/api/gpu/placement"); pool = d["pools"][0]
ok(all(g["seen"] for g in pool["gpu_details"]) and pool["state"] == "active", "le groupe voit bien ses 2 cartes (détection de son instance)")
ok([g["pci_id"] for g in d["main_free"]] == ["0000:42:00.0"] and len(d["inventory"]) == 3 and {g["pci_id"]: g for g in d["inventory"]}["0000:04:00.0"]["ordinal"] == 0, "inventaire complet conservé (3 GPU, n° Vulkan intact) ; reste à l'instance principale : L40S n°2")
pin = d["pins"][0]
ok(not pin["ok"] and pin["current"] is None, "épinglage signalé « à revoir » : la principale ne voit plus qu'un GPU, le n°1 n'existe plus pour elle")
s, g = api("GET", "/api/gpu"); dev = {x["slot"]: x for x in g["devices"]}.get("0000:41:00.0")
ok(dev and "Réservé au groupe « Gros modèles »" in dev["message"] and dev["state"] == "ok", "onglet GPU : L40S n°1 « %s »" % (dev or {}).get("message"))
# --- modification, propagation des réglages, suppression
reset_calls(); s, d = api("POST", "/api/gpu/pools/update", {"id": "g1", "name": "Gros modèles", "gpus": ["0000:41:00.0", "0000:04:00.0"], "models": ["llama3.2:3b", "qwen3.5:2b"]})
ok(s == 200 and json.load(open(T + "/etc/ollamabuntu/pools.json"))["pools"][0]["models"] == ["llama3.2:3b", "qwen3.5:2b"], "modification : qwen3.5:2b ajouté au groupe")
reset_calls(); s, d = api("POST", "/api/ollama-env", {"values": {"OLLAMA_KEEP_ALIVE": "30m"}})
ok(s == 200 and "OLLAMA_KEEP_ALIVE=30m" in open(T + "/etc/ollamabuntu/pools/g1.env").read() and "restart ollama-pool@g1.service" in calls(), "paramètre avancé modifié : propagé au groupe, instance du groupe redémarrée")
s, envd = api("GET", "/api/ollama-env")
ok(any(k["key"] == "OLLAMA_SCHED_SPREAD" for k in envd["settings"]), "paramètre OLLAMA_SCHED_SPREAD proposé dans les paramètres avancés")
reset_calls(); s, d = api("POST", "/api/gpu/pools/delete", {"id": "g1"})
ok(s == 200 and not os.path.exists(T + "/etc/ollamabuntu/pools/g1.env") and "CUDA_VISIBLE" not in open(T + "/etc/ollamabuntu/ollama-main.env").read(), "suppression : configuration du groupe retirée, instance principale sans restriction")
c = calls(); ok("disable --now ollama-pool@g1.service" in c and "ollamabuntu-router" not in c, "suppression : instance g1 arrêtée et désactivée ; routeur conservé (accès local et publication)")
s, d = api("POST", "/api/models/unpin", {"variant": "ob-tiny:latest-gpu1"})
ok(s == 200 and "ob-tiny:latest-gpu1" not in {m["name"] for m in ollama("GET", "/api/tags")[1]["models"]} and "ob-tiny:latest" in {m["name"] for m in ollama("GET", "/api/tags")[1]["models"]}, "variante supprimée, modèle d'origine conservé")
