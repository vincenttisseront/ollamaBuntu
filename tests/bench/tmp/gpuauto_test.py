import json, os, shutil, subprocess
B = "/tmp/gpuauto"; n = 0
TG = "gfx1030 gfx1100 gfx1101 gfx1102 gfx1150 gfx1151 gfx1200 gfx1201 gfx908 gfx90a gfx942 gfx950".split()   # Ollama 0.40.15, relevé dans l'archive
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m)
    if not c: raise SystemExit(1)
def setup(cards, rocm=True):
    shutil.rmtree(B, ignore_errors=True)
    lib = B + "/lib/rocm_v7_2/rocblas/library"; os.makedirs(lib)
    if rocm:
        for t in TG: open(lib + "/TensileLibrary_lazy_%s.dat" % t, "w").close()
    else: shutil.rmtree(B + "/lib/rocm_v7_2")
    os.makedirs(B + "/kfd/0"); open(B + "/kfd/0/properties", "w").write("cpu_cores_count 16\nsimd_count 0\ngfx_target_version 0\n")
    for i, (gfx, vram_gb, bus) in enumerate(cards, 1):
        d = "%s/kfd/%d" % (B, i); os.makedirs(d + "/mem_banks/0")
        v = int(gfx[3:-2]) * 10000 + int(gfx[-2], 16) * 100 + int(gfx[-1], 16)
        open(d + "/properties", "w").write("cpu_cores_count 0\nsimd_count 120\ngfx_target_version %d\nlocation_id %d\ndomain 0\nunique_id %d\n" % (v, bus << 8, 0xabc0 + i))
        open(d + "/mem_banks/0/properties", "w").write("heap_type 1\nsize_in_bytes %d\n" % (vram_gb << 30))
def run(*args, etc=None):
    env = dict(os.environ, OB_KFD_ROOT=B + "/kfd", OB_OLLAMA_LIB=B + "/lib", OB_RUN=B + "/run", OB_ETC=etc or B + "/etc")
    subprocess.run(["python3", "/home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/gpu-auto.py"] + list(args), env=env, check=True)
    tag = "main" if not args or args[0] == "main" else "pool-" + args[0][5:]
    return open("%s/run/gpu-auto-%s.env" % (B, tag)).read(), json.load(open("%s/run/gpu-auto-%s.json" % (B, tag)))
setup([("gfx1101", 16, 0x03)]); env, r = run("main")
ok(env == "" and r["state"]["0000:03:00.0"] == "natif", "RX 7800 XT seule (gfx1101) : prise en charge native, aucun contournement")
setup([("gfx1036", 2, 0x0e), ("gfx1101", 16, 0x03)]); env, r = run("main")
ok(env == "ROCR_VISIBLE_DEVICES=1\n" and r["state"]["0000:0e:00.0"].startswith("écarté") and r["state"]["0000:03:00.0"] == "natif",
   "RX 7800 XT + GPU intégré Ryzen 7000 (gfx1036) : GPU intégré écarté (ROCR_VISIBLE_DEVICES=1), pas de contournement")
setup([("gfx1031", 12, 0x03)]); env, r = run("main")
ok(env == "HSA_OVERRIDE_GFX_VERSION=10.3.0\n" and r["state"]["0000:03:00.0"] == "contournement:10.3.0", "RX 6700 XT seule (gfx1031) : contournement 10.3.0")
setup([("gfx1100", 48, 0x03), ("gfx1103", 2, 0x0e)]); env, r = run("main")
ok(env == "ROCR_VISIBLE_DEVICES=0\n" and "GPU intégré" in r["state"]["0000:0e:00.0"], "W7800 (gfx1100) + GPU intégré même famille (gfx1103, 2 Go) : GPU intégré écarté, pas forcé")
setup([("gfx1030", 16, 0x03), ("gfx1031", 12, 0x04)]); env, r = run("main")
ok(env == "HSA_OVERRIDE_GFX_VERSION=10.3.0\n" and r["state"]["0000:04:00.0"] == "contournement:10.3.0", "RX 6800 (gfx1030) + RX 6700 XT (gfx1031, 12 Go) : contournement 10.3.0, les deux cartes utilisées")
setup([("gfx1031", 12, 0x03), ("gfx1101", 16, 0x04)]); env, r = run("main")
ok(env == "ROCR_VISIBLE_DEVICES=1\n" and "famille différente" in r["state"]["0000:03:00.0"], "RX 6700 XT + RX 7800 XT (familles différentes) : la carte native gardée, l'autre écartée avec la raison")
os.makedirs(B + "/etc/pools"); open(B + "/etc/pools/gros.env", "w").write("ROCR_VISIBLE_DEVICES=0\nOLLAMA_HOST=127.0.0.1:11500\n")
env, r = run("pool:gros")
ok(env == "HSA_OVERRIDE_GFX_VERSION=10.3.0\n", "groupe de GPU « gros » réservé à la RX 6700 XT : contournement appliqué au groupe seul")
setup([("gfx1101", 16, 0x03)], rocm=False); env, r = run("main")
ok(env == "" and r["state"]["0000:03:00.0"] == "rocm-absent", "module ROCm non installé : rien n'est écrit")
shutil.rmtree(B + "/kfd"); env, r = run("main"); ok(env == "", "aucun GPU AMD (topologie KFD absente) : rien n'est écrit, aucune erreur")
