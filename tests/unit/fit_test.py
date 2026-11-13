#!/usr/bin/env python3
"""Ajustement d'un modèle à la mémoire : forme du modèle, mémoire du cache, scénarios (contexte, cache quantifié, experts en RAM, couches), vitesse estimée."""
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin"))
import fit
GIB = fit.GIB
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)

# --- cartes
ok(fit.gpu_bandwidth("AMD Radeon RX 7800 XT") == 624 and fit.gpu_bandwidth("Quadro RTX 4000") == 416 and fit.gpu_bandwidth("NVIDIA GeForce RTX 4070 Ti SUPER") == 672, "bande passante : noms de cartes courantes reconnus")
ok(fit.gpu_bandwidth("AMD Radeon RX 7900 XTX") == 960 and fit.gpu_bandwidth("RX 7900 XT") == 800 and fit.gpu_bandwidth("RTX A4000") == 448, "le motif le plus précis l'emporte (XTX avant XT, A4000 avant 4000)")
ok(fit.gpu_bandwidth("Carte inconnue") is None and fit.gpu_bandwidth("") is None and fit.gpu_bandwidth(None) is None, "carte inconnue : None (pas d'invention)")

# --- modèle à experts ?
ok(fit.looks_moe("qwen3:30b-a3b") is True and fit.looks_moe("mixtral:8x7b") is True and fit.looks_moe("gpt-oss:20b") is True and fit.looks_moe("x", "qwen3moe") is True, "à experts d'après le nom ou l'architecture")
ok(fit.looks_moe("llama3.2:3b", "llama") is False and fit.looks_moe("gemma4:12b") is None and fit.looks_moe("x", "", ["moe"]) is True, "dense connu / inconnu / étiquette")

# --- forme d'un modèle (cas réel : Qwen3-30B-A3B, quantification Q4_K_M ≈ 17,3 Gio)
QWEN = {"general.architecture": "qwen3moe", "general.parameter_count": 30532122624, "qwen3moe.block_count": 48, "qwen3moe.embedding_length": 2048,
        "qwen3moe.attention.head_count": 32, "qwen3moe.attention.head_count_kv": 4, "qwen3moe.attention.key_length": 128, "qwen3moe.attention.value_length": 128,
        "qwen3moe.context_length": 40960, "qwen3moe.expert_count": 128, "qwen3moe.expert_used_count": 8, "qwen3moe.expert_feed_forward_length": 768}
qsize = int(17.3 * GIB)
q = fit.model_from_show("qwen3:30b-a3b", qsize, QWEN)
ok(q["moe"] and q["experts"] == 128 and q["used"] == 8 and q["layers"] == 48 and q["max_ctx"] == 40960 and q["kv_elems"] == 48 * 4 * 256, "forme : couches, têtes du cache, experts lus dans model_info")
ok(0.90 * qsize < q["expert_bytes"] <= 0.97 * qsize, "octets d'experts : ≈ 95 %% des poids (%.1f Gio)" % (q["expert_bytes"] / GIB))
GEMMA = {"general.architecture": "gemma3", "general.parameter_count": 12e9, "gemma3.block_count": 48, "gemma3.embedding_length": 3840,
         "gemma3.attention.head_count": 16, "gemma3.attention.head_count_kv": 8, "gemma3.attention.key_length": 256, "gemma3.context_length": 131072}
g = fit.model_from_show("gemma4:12b", int(8.1 * GIB), GEMMA)
ok(not g["moe"] and g["expert_bytes"] == 0 and g["experts"] is None and g["kv_elems"] == 48 * 8 * 512, "modèle dense : pas d'experts ; longueur de valeur = longueur de clé par défaut")
ok(fit.model_from_show("x", 0, GEMMA) is None and fit.model_from_show("x", 5 * GIB, {})["kv_elems"] is None, "poids inconnus : None ; forme inconnue : cache non calculable")
KVL = dict(GEMMA, **{"gemma3.attention.head_count_kv": [8, 8, 4, 4]})
ok(fit.model_from_show("x", GIB, dict(KVL, **{"gemma3.block_count": 4}))["kv_elems"] == (8 + 8 + 4 + 4) * 512, "têtes du cache variables selon les couches : sommées")

# --- mémoire du cache
ok(fit.kv_bytes(g, 8192, "f16") == int(48 * 8 * 512 * 2.0 * 8192) and fit.kv_bytes(g, 8192, "q8_0") < fit.kv_bytes(g, 8192, "f16") * 0.54 and fit.kv_bytes(g, 8192, "q4_0") < fit.kv_bytes(g, 8192, "f16") * 0.3, "cache : f16 = 2 octets/élément, q8_0 ≈ moitié, q4_0 ≈ un quart")
ok(fit.kv_bytes(g, 4096, "f16", parallel=3) == 3 * fit.kv_bytes(g, 4096, "f16") and fit.kv_bytes({"kv_elems": None}, 4096, "f16") is None, "le cache se multiplie par le nombre de requêtes parallèles ; forme inconnue : None")

# --- fenêtre glissante (Gemma 3 : une couche sur 6 lit tout le contexte, les autres 1024 jetons)
GSWA = dict(GEMMA, **{"gemma3.attention.sliding_window": 1024})
gs = fit.model_from_show("gemma3:12b", int(8.1 * GIB), GSWA)
ok(gs["swa"] == 1024 and abs(gs["swa_global"] - 1 / 6.0) < 1e-9 and fit.kv_bytes(gs, 16384, "f16") < fit.kv_bytes(g, 16384, "f16") * 0.25, "fenêtre glissante : le cache à 16k est ~5 fois plus petit que le calcul prudent")
ok(fit.kv_bytes(gs, 512, "f16") == fit.kv_bytes(g, 512, "f16") and fit.model_from_show("x", GIB, GEMMA)["swa"] is None and fit.model_from_show("x", GIB, dict(GSWA, **{"gemma3.attention.sliding_window_pattern": 4}))["swa_global"] == 0.25, "contexte plus court que la fenêtre : calcul inchangé ; sans fenêtre déclarée : prudent ; motif lu quand le modèle le donne")

# --- matériel : Radeon RX 7800 XT 16 Go, 15,4 Go de RAM (celui de l'utilisateur)
HW0 = {"vram": 16 * GIB, "ram_avail": int(13.8 * GIB), "ram_total": int(15.4 * GIB), "gpus": ["AMD Radeon RX 7800 XT"]}
hw = fit.resolve_hw(HW0)
ok(hw["gpu_theory"] == 624 and abs(hw["gpu_eff"] - 624 * fit.EFF_GPU) < 1e-6 and not hw["calibrated"] and hw["ram_eff"] == fit.RAM_GBPS_DEFAULT * fit.EFF_RAM and not hw["ram_measured"], "matériel : bande passante carte et mémoire déduites (ni mesure ni calibrage)")
hwc = fit.resolve_hw(HW0, {"ram_gbps": 50, "calib": {"gpu_gbps": 380.0}})
ok(hwc["gpu_eff"] == 380.0 and hwc["calibrated"] and hwc["ram_measured"] and hwc["ram_eff"] == 50 * fit.EFF_RAM, "une mesure réelle remplace l'estimation (calibrage de la carte, mémoire mesurée)")
ok(fit.resolve_hw({"vram": 8 * GIB, "gpus": ["Carte X"]})["gpu_eff"] is None, "carte inconnue et non calibrée : pas de débit estimé")
ok(fit.calibrate(76.0, int(8.1 * GIB)) == round(76.0 * 8.1 * GIB / 1e9, 1) and fit.calibrate(None, 5) is None and fit.calibrate(0, 5) is None, "calibrage : débit mesuré × octets lus par jeton")

# --- vitesse
T = fit.tps(int(8.1 * GIB), 0, hw)
ok(T is not None and 40 < T < 60, "dense 12B (8,1 Gio) en mémoire vidéo : %.1f jetons/s (carte à 624 Go/s × 0,65)" % T)
T2 = fit.tps(int(4 * GIB), int(4 * GIB), hw)
ok(T2 < T / 2, "moitié des poids en mémoire système : beaucoup plus lent (%.1f jetons/s)" % T2)
ok(fit.tps(1000, 0, fit.resolve_hw({"vram": GIB, "gpus": ["inconnue"]})) is None and fit.tps(0, 0, hw) is None, "carte inconnue : None ; rien à lire : None")
ok([fit.speed_label(x) for x in (None, 80, 20, 6, 1)] == ["non estimée", "rapide", "confortable", "lente", "très lente"], "étiquettes de vitesse")

# --- scénarios : un modèle dense qui tient
p = fit.plan(g, hw, want_ctx=8192)
ok(p["verdict"] == "gpu" and p["recommended"] == "s1" and p["scenarios"][0]["fits_vram"] and p["scenarios"][0]["kv"] == "f16" and p["scenarios"][0]["ctx"] == 8192, "gemma 12B à 8k : tient en mémoire vidéo sans rien changer")
ok(p["scenarios"][0]["vram"] < 16 * GIB * fit.VRAM_USABLE and p["scenarios"][0]["tps"] and 30 < p["scenarios"][0]["tps"] < 70, "mémoire vidéo nécessaire et vitesse estimée affichées")

# --- tient seulement avec un cache quantifié ou un contexte réduit
big = fit.model_from_show("dense", int(13.3 * GIB), dict(GEMMA, **{"gemma3.attention.head_count_kv": 16, "gemma3.block_count": 60}))
pq = fit.plan(big, hw, want_ctx=16384)
sc = pq["scenarios"][-1]
ok(pq["verdict"] == "ajuste" and sc["fits_vram"] and (sc["kv"] != "f16" or sc["ctx"] < 16384), "modèle plus gros : tient après ajustement (%s, contexte %d)" % (sc["kv"], sc["ctx"]))
ok(any("cache de contexte" in x or "contexte est réduit" in x for x in pq["notes"]), "…et le dit en clair")
first = pq["scenarios"][0]
ok(first["ctx"] == 16384 and first["kv"] == "f16" and not first["fits_vram"] or sc["ctx"] <= 16384, "le plus fidèle est essayé d'abord (contexte et précision d'origine)")

# --- modèle dense trop gros : débordement par couches
dense30 = fit.model_from_show("dense30", int(22 * GIB), dict(GEMMA, **{"gemma3.block_count": 60}))
pd = fit.plan(dense30, hw, want_ctx=8192)
s = pd["scenarios"][-1]
ok(pd["verdict"] == "couches" and s["mode"] == "layers" and 0.5 < s["gpu_frac"] < 0.8 and s["ngl"] is not None and s["tps"] and s["tps"] < 20, "dense de 22 Gio sur 16 Gio : débordement par couches, %d %% en mémoire vidéo, %.1f jetons/s" % (s["gpu_frac"] * 100, s["tps"]))
ok(s["ram"] > 0 and s["fits_ram"] and any("pas à experts" in x for x in pd["notes"]), "la part en mémoire système tient en RAM et la note déconseille ce chemin pour un modèle dense")

# --- modèle à experts trop gros : experts en mémoire système
pm = fit.plan(q, hw, want_ctx=8192)
m = next(x for x in pm["scenarios"] if x["mode"] == "moe")
ok(pm["verdict"] == "moe" and m["mode"] == "moe" and m["n_cpu_moe"] is not None and 5 <= m["n_cpu_moe"] <= 20, "Qwen3-30B-A3B sur 16 Gio : experts de %s couche(s) sur 48 en mémoire système" % m["n_cpu_moe"])
ok(m["fits_vram"] and m["fits_ram"] and m["ram"] < 8 * GIB and m["kv"] == "q8_0", "le reste tient en mémoire vidéo, la part débordée tient en RAM, cache en q8_0")
dense_equiv = next(x for x in pm["scenarios"] if x["mode"] == "layers")
ok(pm["recommended"] == m["id"] and dense_equiv["label"].startswith("Pour comparaison") and m["tps"] > 1.2 * dense_equiv["tps"] and 25 < m["tps"] < 120,
   "experts en RAM : %.1f jetons/s ; pour comparaison, débordement par couches : %.1f (l'attention et le cache restent sur la carte)" % (m["tps"], dense_equiv["tps"]))
ok(any("Ollama ne sait pas" in x for x in pm["notes"]) and any("traitement du prompt" in x for x in pm["notes"]), "notes : besoin du moteur llama.cpp, lenteur de la lecture du prompt")
ok(fit.solve_moe(q, hw, 8192, "q8_0") == m["n_cpu_moe"] and fit.solve_moe(g, hw, 8192, "f16") is None, "solve_moe : même valeur ; None pour un modèle dense")
small = fit.model_from_show("moe-petit", 4 * GIB, dict(QWEN, **{"general.parameter_count": 6e9, "qwen3moe.expert_feed_forward_length": 256}))
ok(fit.solve_moe(small, hw, 8192, "q8_0") == 0, "modèle à experts qui tient : 0 couche en mémoire système")
more = fit.solve_moe(q, hw, 32768, "q8_0")
ok(more is not None and more > fit.solve_moe(q, hw, 8192, "q8_0"), "un plus grand contexte demande plus d'experts en mémoire système")

# --- trop gros même avec la mémoire système
huge = fit.model_from_show("enorme", int(60 * GIB), dict(QWEN, **{"general.parameter_count": 90e9, "qwen3moe.expert_feed_forward_length": 2048}))
ph = fit.plan(huge, hw, want_ctx=8192)
ok(ph["verdict"] == "trop" and ph["recommended"] is None and any("ne tient pas" in x for x in ph["notes"]), "60 Gio sur 16 Gio de mémoire vidéo + 13,8 Gio de RAM : ne tient pas")
ok(fit.plan(huge, dict(hw, ram_avail=int(64 * GIB)), want_ctx=8192)["verdict"] == "moe", "…mais tient avec 64 Gio de RAM (experts en mémoire système)")

# --- sans GPU, réglages actuels, contexte plafonné au maximum du modèle
pn = fit.plan(g, fit.resolve_hw({"vram": 0, "ram_avail": 8 * GIB}), want_ctx=8192)
ok(pn["verdict"] == "sans-gpu" and pn["recommended"] == "cpu" and any("processeur" in x for x in pn["notes"]), "sans mémoire vidéo : processeur")
pc = fit.plan(g, hw, want_ctx=8192, current={"ctx": 65536, "kv": "f16", "parallel": 4})
ok(pc["scenarios"][0]["label"] == "Réglages actuels" and pc["current_fits"] is False and pc["scenarios"][0]["parallel"] == 4, "réglages actuels chiffrés en premier (65 536 jetons × 4 requêtes ne tiennent pas)")
short = fit.model_from_show("court", 2 * GIB, dict(GEMMA, **{"gemma3.context_length": 4096}))
ok(max(s["ctx"] for s in fit.plan(short, hw, want_ctx=32768)["scenarios"]) == 4096, "contexte souhaité plafonné au maximum du modèle")
ok(fit.ctx_ladder(8192, None) == [8192, 4096, 2048] and fit.ctx_ladder(1024, None) == [1024], "échelle de contextes : on divise par deux jusqu'à 2048")

# --- débit mesuré
now = 1_000_000.0
rows = [{"model": "m", "ts": now - 100, "tps": t, "out_tok": 100, "status": 200} for t in (70, 80, 75)] + [{"model": "m", "ts": now - 10, "tps": 5, "out_tok": 3, "status": 200}, {"model": "m", "ts": now - 10 ** 7, "tps": 1, "out_tok": 100, "status": 200}, {"model": "autre", "ts": now - 5, "tps": 99, "out_tok": 100, "status": 200}]
ok(fit.measured_tps(rows, "m", now) == 75 and fit.measured_tps(rows, "autre", now) is None and fit.measured_tps([], "m", now) is None, "débit mesuré : médiane des requêtes récentes de 30 jetons ou plus ; moins de 3 requêtes : None")

# --- modèle Hugging Face (non installé)
c = fit.candidate_from_hf("unsloth/Qwen3-30B-A3B-GGUF", int(17.3 * GIB))
ok(c["moe"] and c["guess"] and c["expert_bytes"] > 0 and fit.plan(c, hw, 8192)["verdict"] == "moe", "candidat Hugging Face à experts : verdict sur hypothèse")
cd = fit.candidate_from_hf("TheBloke/Llama-2-13B-GGUF", int(7.4 * GIB), arch="llama")
ok(not cd["moe"] and fit.plan(cd, hw, 4096)["verdict"] in ("gpu", "ajuste"), "candidat dense")
print("\n%d vérifications réussies" % n)
