#!/usr/bin/env python3
"""Catalogue « Recommandés » multi-registres : les modèles Hugging Face (hf.co/...) sont mélangés aux modèles Ollama dans une vue unique, avec leur source."""
import json, os, sys, tempfile
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp()
os.environ.update(OB_ETC=tmp + "/etc", OB_STATE=tmp + "/state", OB_MODELS=tmp + "/models")
LIB = os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, os.path.join(LIB, "admin")); sys.path.insert(0, LIB)
import server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
GIB = 1024 ** 3
ok(server.model_source("llama3.2:3b") == "Ollama" and server.model_source("hf.co/bartowski/phi-4-GGUF:Q4_K_M") == "Hugging Face"
   and server.model_source("registry.ollama.ai/library/x:1") == "Ollama" and server.model_source("reg.exemple.fr/ns/m:1") == "reg.exemple.fr", "source déduite du nom du modèle")
cat = json.load(open(os.path.join(LIB, "admin", "catalog.json"), encoding="utf-8"))["models"]
hf = [m for m in cat if m["name"].startswith("hf.co/")]
ok(len(hf) >= 8 and len({m["name"] for m in cat}) == len(cat), "catalogue : %d modèles Hugging Face, aucun doublon" % len(hf))
ok(all(__import__("re").match(r"^hf\.co/[\w.-]+/[\w.-]+:[A-Za-z0-9_]+$", m["name"]) and m["category"] and m["description"] and "Hugging Face" in m["description"] for m in hf), "noms au format hf.co/utilisateur/dépôt:quantification, avec catégorie et description")
# vue agrégée avec des registres simulés
server.capacity = lambda: {"vram": 24 * GIB, "ram_total": 64 * GIB, "ram_available": 40 * GIB, "gpus": ["Test"]}
server.ollama_version = lambda: "0.13.0"
server.ollama_json = lambda *a, **k: (200, {"models": [{"name": "hf.co/bartowski/phi-4-GGUF:Q4_K_M", "size": 9 * GIB, "details": {}}]})
server.load_catalog = lambda: cat
def manifest(name):
    if "Magistral" in name: return None                       # absent de Hugging Face : « indisponible »
    if "Mistral-Nemo" in name: raise OSError("registre HTTP 503")
    size = 40 * GIB if "32B" in name or "70b" in name or "120b" in name else 6 * GIB
    return {"cloud": False, "digest": "sha256:x", "layers": ["sha256:x"], "sizes": {"sha256:x": size}, "size": size, "vision": False, "draft": False, "params": "7B", "quant": "Q4_K_M", "family": "f", "requires": None}
server.registry_manifest = manifest
server.local_manifest = lambda name: (None, None)
d = server.model_insights()
by = {c["name"]: c for c in d["catalog"]}
ok({c["source"] for c in d["catalog"]} == {"Ollama", "Hugging Face"}, "les deux registres sont dans la même liste")
ok(by["hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M"]["available"] and by["hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M"]["fit"]["level"] == "gpu" and by["llama3.2:3b"]["fit"]["level"] == "gpu", "adéquation calculée de la même façon pour les deux sources")
ok(by["hf.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF:Q4_K_M"]["fit"]["level"] == "mixte" or by["hf.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF:Q4_K_M"]["fit"]["level"] == "trop", "gros modèle Hugging Face jugé trop gros pour la carte")
ok(by["hf.co/bartowski/phi-4-GGUF:Q4_K_M"]["installed"] and not by["hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M"]["installed"], "modèle Hugging Face déjà installé détecté")
ok(not by["hf.co/unsloth/Magistral-Small-2509-GGUF:Q4_K_M"]["available"] and not by["hf.co/bartowski/Mistral-Nemo-Instruct-2407-GGUF:Q4_K_M"]["available"], "dépôt absent ou registre en erreur : marqué indisponible sans casser la liste")
ok(d["installed"][0]["source"] == "Hugging Face", "modèle installé : source indiquée")
ok(d["sources"]["Hugging Face"]["total"] == len(hf) and d["sources"]["Hugging Face"]["available"] == len(hf) - 2 and d["sources"]["Ollama"]["total"] == len(cat) - len(hf), "compteurs par source")
order = {"gpu": 0, "cpu": 1, "mixte": 2, "trop": 3, "incompatible": 4, None: 5}
lv = [order[(c.get("fit") or {}).get("level")] for c in d["catalog"]]
ok(lv == sorted(lv), "tri unique du plus adapté au moins adapté, tous registres confondus")
print("\n%d vérifications réussies" % n)
