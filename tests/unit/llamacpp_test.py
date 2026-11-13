#!/usr/bin/env python3
"""Moteur llama.cpp, parties pures : fichier du modèle, réglages, ligne de commande selon la version, traduction Ollama <-> OpenAI (JSON et flux), choix du binaire."""
import json, os, re, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import llamacpp as L
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a)
    except ValueError as e: return str(e)
    return None

# --- manifestes et fichiers
ok(L.parse_model_name("gemma4:12b") == ("registry.ollama.ai", "library", "gemma4", "12b") and L.parse_model_name("llama3") == ("registry.ollama.ai", "library", "llama3", "latest")
   and L.parse_model_name("hf.co/unsloth/Qwen3-14B-GGUF:Q4_K_M") == ("hf.co", "unsloth", "Qwen3-14B-GGUF", "Q4_K_M") and L.parse_model_name("jean/modele:x")[:2] == ("registry.ollama.ai", "jean"), "noms de modèles Ollama : bibliothèque, espace, hôte Hugging Face, étiquette")
cands = L.manifest_candidates("/m", "gemma4:12b")
ok(cands[0] == "/m/manifests-v2/registry.ollama.ai/library/gemma4/12b" and "/m/manifests/ollama.com/library/gemma4/12b" in cands and len(cands) == 4, "chemins de manifeste essayés (deux dispositions, ancien hôte)")
D = "a" * 64
MAN = {"layers": [{"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:" + "b" * 64}, {"mediaType": L.MODEL_MEDIA, "digest": "sha256:" + D}]}
ok(L.blob_of(MAN, "/m") == "/m/blobs/sha256-" + D and L.blob_of({"layers": []}, "/m") is None and L.blob_of({"layers": [{"mediaType": L.MODEL_MEDIA, "digest": "sha256:../../etc/passwd"}]}, "/m") is None, "blob du modèle ; empreinte piégée refusée")
files = {"/m/manifests/registry.ollama.ai/library/x/latest": json.dumps(MAN), "/m/manifests/registry.ollama.ai/library/vide/latest": json.dumps({"layers": []}), "/m/manifests/registry.ollama.ai/library/casse/latest": "{pas du json"}
rd = files.get
ok(L.find_gguf("/m", "x", rd) == ("/m/blobs/sha256-" + D, None), "find_gguf : modèle installé")
ok("non installé" in L.find_gguf("/m", "absent", rd)[1] and "ne contient pas" in L.find_gguf("/m", "vide", rd)[1] and "non installé" in L.find_gguf("/m", "casse", rd)[1], "modèle absent, sans poids, manifeste illisible : messages distincts")

# --- options supplémentaires
ok(L.extra_clean("") == "" and L.extra_clean("  --no-mmap  -ub 512 ") == "--no-mmap -ub 512" and L.extra_clean("--cache-reuse=256") == "--cache-reuse=256", "options supplémentaires : espaces normalisés")
for bad in ("--host 0.0.0.0", "--port 80", "-m /etc/passwd", "--api-key=x", "--hf-repo a/b", "--ssl-key-file k", "--lora x", "-hf a/b", "--model-url http://x", "--no-mmap; rm -rf /", "--x $(id)", "--tools all"):
    r = raises(L.extra_clean, bad)
    if r is None: ok(False, "option dangereuse acceptée : " + bad)
ok(True, "options dangereuses refusées (réseau, fichiers, autre modèle, séparateurs de commande)")
ok("guillemets" in raises(L.extra_clean, "--x 'abc") and "300" in raises(L.extra_clean, "a" * 301), "guillemets non fermés, texte trop long")

# --- réglages d'un moteur
c = L.config_clean({"id": "qwen", "model": "hf.co/unsloth/Qwen3-30B-A3B-GGUF:Q4_K_M", "n_cpu_moe": "11", "ctx": "16384", "port": 11600, "backend_port": 11700})
ok(c["id"] == "qwen" and c["n_cpu_moe"] == 11 and c["ctx"] == 16384 and c["kv"] == "q8_0" and c["flash"] and c["parallel"] == 1 and c["idle_min"] == 15 and c["unload_ollama"], "moteur valide : valeurs par défaut prudentes")
ok(L.config_clean({"n_cpu_moe": None}, c)["n_cpu_moe"] is None and L.config_clean({"ctx": 4096}, c)["id"] == "qwen" and L.config_clean({"n_cpu_moe": ""}, c)["n_cpu_moe"] is None, "champs absents conservés ; n_cpu_moe vide = aucun")
for bad, frag in (({"id": "Majuscule"}, "identifiant"), ({"id": "x" * 30}, "identifiant"), ({"model": "a b"}, "modèle"), ({"model": "../x"}, "modèle"), ({"ctx": 100}, "contexte"), ({"parallel": 9}, "parallèles"),
                  ({"n_cpu_moe": -1}, "experts"), ({"n_cpu_moe": "x"}, "experts"), ({"kv": "q5"}, "cache"), ({"idle_min": -1}, "inactivité"), ({"start_timeout": 5}, "délai"),
                  ({"threads": 999}, "fils"), ({"port": 80}, "port"), ({"port": "x"}, "port"), ({"flash": False}, "flash"), ({"extra": "--host 1.2.3.4"}, "interdite")):
    r = raises(L.config_clean, bad, c)
    if r is None or frag not in r: ok(False, "refus attendu %r : %r" % (bad, r))
ok(True, "réglages invalides refusés avec un message clair")
ok(raises(L.config_clean, {"model": "x"}) and raises(L.config_clean, {"id": "a"}), "identifiant et modèle obligatoires à la création")
ok(L.free_ports([]) == (11600, 11700) and L.free_ports([{"port": 11600, "backend_port": 11700}, {"port": 11601, "backend_port": 11701}]) == (11602, 11702), "ports libres attribués")

# --- ligne de commande selon la version
HELP_NEW = """-fa,   --flash-attn [on|off|auto]  set Flash Attention use (default: auto)
-c, --ctx-size N
-ngl, --n-gpu-layers N
-np, --parallel N
--n-cpu-moe N      keep the Mixture of Experts weights of the first N layers in the CPU
-ot, --override-tensor <tensor name pattern>=<buffer type>,...
--cache-type-k TYPE
--jinja
--no-webui
-t, --threads N
--cache-reuse N"""
HELP_OLD = "-fa, --flash-attn   enable Flash Attention (default: disabled)\n-c, --ctx-size N\n-ngl, --n-gpu-layers N\n-np, --parallel N\n-ot, --override-tensor <t>\n--cache-type-k TYPE\n--jinja\n-t, --threads N"
HELP_ANCIEN = "-c, --ctx-size N\n-ngl, --n-gpu-layers N\n--threads N"
cn, co, ca = L.detect_caps(HELP_NEW), L.detect_caps(HELP_OLD), L.detect_caps(HELP_ANCIEN)
ok(cn["n_cpu_moe"] and cn["flash_value"] and cn["jinja"] and cn["no_webui"] and co["flash"] and not co["flash_value"] and not co["n_cpu_moe"] and co["override_tensor"] and not ca["flash"] and not ca["jinja"] and L.detect_caps("")["ngl"] is False, "options reconnues d'après --help (flash attention avec ou sans valeur, n-cpu-moe, override-tensor)")
cfg = L.config_clean({"id": "q", "model": "m", "n_cpu_moe": 11, "ctx": 8192, "parallel": 2, "threads": 8, "extra": "--no-mmap", "port": 11600, "backend_port": 11700})
a, w = L.build_args(cfg, cn, "/b/llama-server", "/blobs/x")
ok(a[:7] == ["/b/llama-server", "-m", "/blobs/x", "--host", "127.0.0.1", "--port", "11700"] and a[a.index("-c") + 1] == "16384" and a[a.index("-np") + 1] == "2" and a[a.index("--n-cpu-moe") + 1] == "11"
   and a[a.index("--flash-attn") + 1] == "on" and a[a.index("--cache-type-k") + 1] == "q8_0" and "--jinja" in a and "--no-webui" in a and a[-1] == "--no-mmap" and a[a.index("-t") + 1] == "8" and not w,
   "version récente : contexte total = contexte × requêtes parallèles, experts, flash attention « on », cache q8_0, gabarit, sans interface web")
ok(a[a.index("--host") + 1] == "127.0.0.1", "llama-server n'écoute que sur la boucle locale")
a2, w2 = L.build_args(cfg, co, "/b/ls", "/g")
ok("--n-cpu-moe" not in a2 and a2[a2.index("--override-tensor") + 1] == r"blk\.(0|1|2|3|4|5|6|7|8|9|10)\.ffn_(up|down|gate)_exps\.=CPU" and "--flash-attn" in a2 and a2[a2.index("--flash-attn") + 1] != "on" and any("override-tensor" in x for x in w2),
   "version sans --n-cpu-moe : repli sur --override-tensor, signalé")
pat = L.moe_override(3).split("=")[0]
ok(re.search(pat, "blk.2.ffn_up_exps.weight") and re.search(pat, "blk.0.ffn_gate_exps.weight") and not re.search(pat, "blk.3.ffn_up_exps.weight") and not re.search(pat, "blk.12.ffn_down_exps.weight") and not re.search(pat, "blk.2.attn_q.weight"), "l'expression ne vise que les experts des N premières couches (pas l'attention, pas la couche 12 pour N = 3)")
a3, w3 = L.build_args(cfg, ca, "/b/ls", "/g")
ok("--n-cpu-moe" not in a3 and "--override-tensor" not in a3 and "--flash-attn" not in a3 and len(w3) >= 2 and any("experts" in x for x in w3), "version très ancienne : options inconnues retirées et signalées, jamais passées à llama-server")
a4, _ = L.build_args(L.config_clean({"n_cpu_moe": None, "kv": "f16", "flash": False, "parallel": 1}, cfg), cn, "/b/ls", "/g")
ok("--n-cpu-moe" not in a4 and "--cache-type-k" not in a4 and "--flash-attn" not in a4, "sans experts, cache f16, sans flash attention : options absentes")
ok(L.build_args(dict(cfg, n_cpu_moe=0), cn, "b", "g")[0].count("--n-cpu-moe") == 0, "0 couche : aucune option MoE")

# --- Ollama -> OpenAI
body, stream = L.chat_to_openai({"model": "m", "messages": [{"role": "system", "content": "sois bref"}, {"role": "user", "content": "salut"}],
                                  "options": {"temperature": 0.2, "top_k": 40, "num_predict": 100, "stop": "FIN", "num_ctx": 99999, "num_gpu": 3, "bad": 1, "seed": 7}, "keep_alive": 0})
ok(stream is True and body["stream"] is True and body["stream_options"] == {"include_usage": True} and body["temperature"] == 0.2 and body["top_k"] == 40 and body["max_tokens"] == 100 and body["stop"] == ["FIN"] and body["seed"] == 7, "chat : flux actif par défaut (comme Ollama), options d'échantillonnage traduites")
ok("num_ctx" not in body and "num_gpu" not in body and "bad" not in body and "keep_alive" not in body and "model" not in body, "contexte, placement et champs inconnus ne sont pas transmis (c'est le moteur qui décide)")
b2, s2 = L.chat_to_openai({"messages": [{"role": "user", "content": "x"}], "stream": False, "format": "json", "think": False})
ok(s2 is False and b2["stream"] is False and "stream_options" not in b2 and b2["response_format"] == {"type": "json_object"} and b2["chat_template_kwargs"] == {"enable_thinking": False}, "stream:false ; format json ; think:false -> enable_thinking")
b3, _ = L.chat_to_openai({"messages": [{"role": "user", "content": "x"}], "format": {"type": "object", "properties": {"a": {"type": "string"}}}})
ok(b3["response_format"]["type"] == "json_schema" and b3["response_format"]["json_schema"]["schema"]["type"] == "object", "format : schéma JSON")
TOOLS = [{"type": "function", "function": {"name": "meteo", "description": "d", "parameters": {"type": "object"}}}]
b4, _ = L.chat_to_openai({"messages": [{"role": "user", "content": "meteo ?"}, {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "meteo", "arguments": {"ville": "Troyes"}}}]},
                                       {"role": "tool", "content": "12 degrés", "tool_name": "meteo"}], "tools": TOOLS})
tc = b4["messages"][1]["tool_calls"][0]
ok(b4["tools"] == TOOLS and tc["id"] == "call_1" and tc["type"] == "function" and json.loads(tc["function"]["arguments"]) == {"ville": "Troyes"} and b4["messages"][2]["tool_call_id"] == "call_1", "outils : arguments objet -> texte JSON, résultat relié à son appel")
for bad, frag in (({"messages": []}, "obligatoire"), ({}, "obligatoire"), ({"messages": [{"role": "robot", "content": "x"}]}, "rôle"), ({"messages": [{"role": "user", "content": "x", "images": ["AAAA"]}]}, "images"),
                  ({"messages": [{"role": "user", "content": ["x"]}]}, "texte"), ({"messages": [{"role": "user", "content": "x"}], "format": "xml"}, "format")):
    r = raises(L.chat_to_openai, bad)
    if r is None or frag not in r: ok(False, "refus attendu %r : %r" % (bad, r))
ok(True, "demandes inacceptables refusées clairement (messages, rôle, images, contenu non textuel, format)")
g, gs = L.generate_to_openai({"model": "m", "prompt": "salut", "system": "bref", "options": {"temperature": 0}, "stream": False})
ok(g["messages"] == [{"role": "system", "content": "bref"}, {"role": "user", "content": "salut"}] and gs is False and g["temperature"] == 0, "generate : consigne système + prompt en conversation")
for bad in ({"prompt": "x", "raw": True}, {"prompt": "x", "suffix": "y"}, {"prompt": "x", "context": [1]}, {"prompt": "x", "images": ["a"]}, {"prompt": 3}, {}):
    if raises(L.generate_to_openai, bad) is None: ok(False, "generate accepté à tort : %r" % bad)
ok(True, "generate : mode brut, suffixe, contexte, images, prompt absent refusés")

# --- OpenAI -> Ollama (réponse complète)
RESP = {"choices": [{"message": {"role": "assistant", "content": "Bonjour", "reasoning_content": "je réfléchis"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        "timings": {"prompt_n": 12, "prompt_ms": 80.0, "predicted_n": 3, "predicted_ms": 40.0}}
o = L.response_to_ollama("chat", "m", RESP, 100.0, 100.5, load_s=0.2)
ok(o["message"] == {"role": "assistant", "content": "Bonjour", "thinking": "je réfléchis"} and o["done"] is True and o["done_reason"] == "stop" and o["prompt_eval_count"] == 12 and o["eval_count"] == 3
   and o["eval_duration"] == 40_000_000 and o["prompt_eval_duration"] == 80_000_000 and o["load_duration"] == 200_000_000 and o["total_duration"] == 500_000_000 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{9}Z", o["created_at"]),
   "réponse chat : contenu, raisonnement, décomptes et durées de llama-server")
g = L.response_to_ollama("generate", "m", dict(RESP, choices=[{"message": {"content": "Salut"}, "finish_reason": "length"}]), 0, 1)
ok(g["response"] == "Salut" and "message" not in g and g["done_reason"] == "length", "réponse generate : champ « response », arrêt « length »")
TCR = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "meteo", "arguments": "{\"ville\": \"Troyes\"}"}}, {"function": {"name": "x", "arguments": "pas du json"}}]}, "finish_reason": "tool_calls"}]}
t = L.response_to_ollama("chat", "m", TCR, 0, 2)
ok(t["message"]["tool_calls"] == [{"function": {"name": "meteo", "arguments": {"ville": "Troyes"}}}, {"function": {"name": "x", "arguments": {}}}] and t["message"]["content"] == "" and t["eval_count"] == 0 and t["eval_duration"] == 2_000_000_000, "appels d'outils : arguments texte -> objet (illisible : vide) ; sans mesures : horloge")

# --- flux SSE -> lignes Ollama
def sse(o): return b"data: " + json.dumps(o).encode() + b"\n"
tick = iter([100.0, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7, 100.8])
ST = L.StreamTranslator("chat", "m", t0=100.0, clock=lambda: next(tick))
lines = []
for raw in (b": keep-alive\n", b"\n", sse({"choices": [{"delta": {"role": "assistant", "content": ""}}]}), sse({"choices": [{"delta": {"content": "Bon"}}]}), sse({"choices": [{"delta": {"reasoning_content": "hmm"}}]}),
            sse({"choices": [{"delta": {"content": "jour"}, "finish_reason": None}]}), sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            sse({"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}, "timings": {"prompt_n": 5, "prompt_ms": 10.0, "predicted_n": 2, "predicted_ms": 20.0}}), b"data: [DONE]\n", b"data: {pas du json\n"):
    lines += ST.feed(raw)
lines += ST.close()
objs = [json.loads(x) for x in lines]
ok(len(objs) == 4 and [o.get("message", {}).get("content") for o in objs[:3]] == ["Bon", "", "jour"] and objs[1]["message"].get("thinking") == "hmm" and all(x.endswith(b"\n") for x in lines), "flux : un objet par morceau de texte (le raisonnement à part), commentaires SSE et lignes illisibles ignorés")
f = objs[-1]
ok(f["done"] is True and f["done_reason"] == "stop" and f["prompt_eval_count"] == 5 and f["eval_count"] == 2 and f["eval_duration"] == 20_000_000 and f["message"]["content"] == "" and all(not o["done"] for o in objs[:-1]), "objet final : décomptes et durées mesurés par llama-server")
ok(ST.close() == [], "close() ne produit l'objet final qu'une seule fois")
ST2 = L.StreamTranslator("generate", "m", t0=0.0, clock=iter([1, 2, 3, 4]).__next__)
l2 = ST2.feed(sse({"choices": [{"delta": {"content": "a"}}]})) + ST2.feed(sse({"choices": [{"delta": {"content": "b"}, "finish_reason": "length"}]})) + ST2.close()
o2 = [json.loads(x) for x in l2]
ok([o.get("response") for o in o2] == ["a", "b", ""] and o2[-1]["eval_count"] == 2 and o2[-1]["done_reason"] == "length" and o2[-1]["eval_duration"] > 0, "flux generate : champ « response » ; sans décomptes du serveur, le nombre de morceaux sert de repli")
ST3 = L.StreamTranslator("chat", "m", t0=0.0, clock=lambda: 5.0)
for frag in ({"index": 0, "function": {"name": "mét", "arguments": "{\"vi"}}, {"index": 0, "function": {"name": "éo", "arguments": "lle\": \"T\"}"}}):
    ST3.feed(sse({"choices": [{"delta": {"tool_calls": [frag]}}]}))
ST3.feed(sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))
o3 = [json.loads(x) for x in ST3.close()]
ok(o3[0]["message"]["tool_calls"] == [{"function": {"name": "météo", "arguments": {"ville": "T"}}}] and o3[-1]["done"] is True, "flux : appels d'outils reconstitués à partir de fragments, émis avant l'objet final")
ok(L.StreamTranslator("chat", "m", t0=0).close()[0] and json.loads(L.StreamTranslator("chat", "m", t0=0).close()[0])["done"] is True, "flux vide : objet final quand même (le client n'attend pas indéfiniment)")

# --- choix du fichier à installer
A = lambda *names: [{"name": x, "digest": "sha256:" + "c" * 64, "size": 5} for x in names]
assets = A("llama-b7001-bin-macos-arm64.zip", "llama-b7001-bin-ubuntu-x64.zip", "llama-b7001-bin-ubuntu-vulkan-x64.zip", "llama-b7001-bin-ubuntu-rocm-7.0-x64.zip", "llama-b7001-bin-ubuntu-s390x.zip",
           "llama-b7001-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip", "llama-b7001-xcframework.zip", "llama-b7001-bin-ubuntu-arm64.zip", "llama-b7001-bin-ubuntu-openvino-x64.zip")
ok(L.pick_asset(assets, "vulkan")["name"] == "llama-b7001-bin-ubuntu-vulkan-x64.zip" and L.pick_asset(assets, "rocm")["name"].endswith("rocm-7.0-x64.zip") and L.pick_asset(assets, "cpu")["name"] == "llama-b7001-bin-ubuntu-x64.zip", "bon fichier selon le moteur de calcul : Vulkan, ROCm, processeur seul")
ok(L.pick_asset(assets, "cuda") is None and L.pick_asset([], "vulkan") is None and L.pick_asset(assets, "inconnu") is None and L.pick_asset(A("llama-b1-bin-win-x64.zip"), "cpu") is None, "pas de fichier Ubuntu pour ce moteur : None (jamais celui d'un autre système)")
ok(L.pick_asset(A("llama-b8000-bin-ubuntu-vulkan-x64.tar.gz"), "vulkan")["name"].endswith(".tar.gz") and L.pick_asset(A("llama-b8000-bin-ubuntu-vulkan-x64.exe"), "vulkan") is None, "archives .zip et .tar.gz acceptées, pas les exécutables")
ok(L.digest_sha256({"digest": "sha256:" + "A" * 64}) == "a" * 64 and L.digest_sha256({"digest": "md5:abc"}) is None and L.digest_sha256({}) is None and L.digest_sha256({"digest": "sha256:zz"}) is None, "somme SHA-256 publiée : lue ou absente")
ok(L.server_in_listing(["build/bin/libggml.so", "build/bin/llama-server", "x/llama-server-old", "build/llama-server"]) == "build/llama-server" and L.server_in_listing(["a/b"]) is None and L.server_in_listing(["dir/llama-server/"]) is None, "llama-server repéré dans une archive")
# --- noms réels de la version b12360 (13/11/2026) et version « v1.0.0 » sans binaires désignée « dernière » par GitHub
REAL = A("cudart-llama-b12360-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-b12360-bin-ubuntu-cuda-13.5-x64.tar.gz", "llama-b12360-bin-ubuntu-cuda-12.8-x64.tar.gz", "llama-b12360-bin-ubuntu-cuda-13.5-x64.tar.gz",
         "llama-b12360-bin-ubuntu-rocm-10.0-x64.tar.gz", "llama-b12360-bin-ubuntu-vulkan-x64.tar.gz", "llama-b12360-bin-ubuntu-vulkan-arm64.tar.gz", "llama-b12360-bin-ubuntu-x64.tar.gz",
         "llama-b12360-bin-ubuntu-arm64.tar.gz", "llama-b12360-bin-ubuntu-openvino-2026.4.1-x64.tar.gz", "llama-b12360-bin-ubuntu-sycl-fp16-x64.tar.gz", "llama-b12360-bin-ubuntu-zdnn-s390x.tar.gz",
         "llama-b12360-bin-ubuntu-26.04-s390x.tar.gz", "llama-b12360-ui.tar.gz", "llama-b12360-bin-win-rocm-10.0-x64.zip")
ok([L.pick_asset(REAL, b)["name"] for b in ("vulkan", "rocm", "cpu", "cuda")] == ["llama-b12360-bin-ubuntu-vulkan-x64.tar.gz", "llama-b12360-bin-ubuntu-rocm-10.0-x64.tar.gz", "llama-b12360-bin-ubuntu-x64.tar.gz", "llama-b12360-bin-ubuntu-cuda-12.8-x64.tar.gz"],
   "noms réels : Vulkan, ROCm, processeur et CUDA (jamais le « cudart » seul, ni l'ARM, ni le Windows)")
STUB = {"tag_name": "v1.0.0", "prerelease": False, "assets": A("nightly-tag.txt")}
BUILD = {"tag_name": "b12360", "prerelease": True, "assets": REAL}
rel, asset, why = L.pick_release([STUB, BUILD], "rocm")
ok(rel["tag_name"] == "b12360" and asset["name"].endswith("rocm-10.0-x64.tar.gz") and why is None, "version sans binaires désignée « dernière » : ignorée, la première version qui a le fichier est prise (échec du 13/11/2026)")
ok(L.pick_release([STUB, {"tag_name": "b12361", "assets": A("llama-b12361-bin-ubuntu-vulkan-x64.tar.gz")[:0]}, BUILD], "vulkan")[0]["tag_name"] == "b12360", "version en cours de publication (sans fichier) : sautée")
ok(L.pick_release([dict(BUILD, draft=True)], "vulkan") == (None, None, "nofile") and L.pick_release([STUB], "vulkan") == (None, None, "nofile") and L.pick_release([], "vulkan") == (None, None, "nofile") and L.pick_release(None, "vulkan")[2] == "nofile", "brouillon, version sans binaires, liste vide : « nofile »")
NOSUM = {"tag_name": "b12362", "assets": [{"name": "llama-b12362-bin-ubuntu-vulkan-x64.tar.gz", "size": 5}]}
ok(L.pick_release([NOSUM, BUILD], "vulkan")[0]["tag_name"] == "b12360", "fichier sans somme SHA-256 publiée (envoi en cours) : on prend la version précédente, vérifiable")
ok(L.pick_release([NOSUM], "vulkan") == (None, None, "nosum:b12362") and L.pick_release(["x", 3, None], "vulkan")[2] == "nofile", "aucune version vérifiable : « nosum », éléments illisibles ignorés")
print("\n%d vérifications réussies" % n)
