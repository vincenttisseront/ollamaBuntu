#!/usr/bin/env python3
"""OllamaBuntu - réglage automatique des GPU AMD (ROCm), exécuté avant chaque démarrage d'Ollama.

Chaque GPU AMD est comparé aux cibles GFX réellement compilées dans le module ROCm installé :
  - cible présente (ex. RX 7800 XT, gfx1101) : rien à faire ;
  - cible absente mais famille présente (ex. RX 6700 XT, gfx1031 -> gfx1030) :
    contournement HSA_OVERRIDE_GFX_VERSION (ex. 10.3.0) ;
  - GPU inutilisable à côté d'un GPU utilisable (ex. GPU intégré d'un Ryzen 7000, gfx1036) :
    écarté avec ROCR_VISIBLE_DEVICES, car il peut faire échouer l'initialisation de ROCm.
Une valeur des paramètres avancés (ollama.env, lu après ce fichier) l'emporte toujours.

  gpu-auto.py main          réglage de l'instance principale
  gpu-auto.py pool:<nom>    réglage d'un groupe de GPU (ses cartes seulement)
  gpu-auto.py --report      diagnostic (JSON), sans rien écrire
"""
import glob
import json
import os
import re
import sys

KFD = os.environ.get("OB_KFD_ROOT", "/sys/class/kfd/kfd/topology/nodes")
LIB = os.environ.get("OB_OLLAMA_LIB", "/usr/local/lib/ollama")
RUN = os.environ.get("OB_RUN", "/run/ollamabuntu")
ETC = os.environ.get("OB_ETC", "/etc/ollamabuntu")
FAMILY = (("gfx103", "gfx1030", "10.3.0"), ("gfx110", "gfx1100", "11.0.0"), ("gfx115", "gfx1150", "11.5.0"), ("gfx120", "gfx1200", "12.0.0"))


def props(path):
    out = {}
    try:
        with open(path) as f:
            for line in f:
                k, _, v = line.strip().partition(" ")
                if v.strip().lstrip("-").isdigit():
                    out[k] = int(v)
    except OSError:
        pass
    return out


def targets():
    """Cibles GFX compilées dans le module ROCm d'Ollama (noms des bibliothèques rocBLAS)."""
    found = set()
    for f in glob.glob(os.path.join(LIB, "rocm*", "rocblas", "library", "*gfx*")):
        found.update(m for m in re.findall(r"gfx[0-9a-f]+", os.path.basename(f)))
    return found


def gfx_name(v):
    return "gfx%d%x%x" % (v // 10000, (v // 100) % 100, v % 100)


def devices():
    """GPU AMD vus par ROCm, dans l'ordre de ses numéros (nœuds de la topologie KFD sans CPU seul)."""
    nodes = sorted((d for d in glob.glob(os.path.join(KFD, "*")) if os.path.basename(d).isdigit()), key=lambda d: int(os.path.basename(d)))
    out = []
    for d in nodes:
        p = props(os.path.join(d, "properties"))
        if not p.get("gfx_target_version") or not p.get("simd_count"):
            continue
        vram = max([props(b).get("size_in_bytes", 0) for b in glob.glob(os.path.join(d, "mem_banks", "*", "properties"))] or [0])
        loc = p.get("location_id", 0)
        out.append({"index": len(out), "gfx": gfx_name(p["gfx_target_version"]), "vram": vram,
                    "pci": "%04x:%02x:%02x.%x" % (p.get("domain", 0), loc >> 8, (loc >> 3) & 0x1f, loc & 7),
                    "uuid": "GPU-%016x" % p["unique_id"] if p.get("unique_id") else None})
    return out


def family(gfx, tg):
    for prefix, target, version in FAMILY:
        if gfx.startswith(prefix) and target in tg:
            return prefix, version
    return None, None


def decide(devs, tg, restrict_visible=True):
    """Réglage pour un ensemble de GPU : variables d'environnement + état de chaque carte."""
    env, state = {}, {}
    if not devs or not tg:
        return env, {d["pci"]: ("rocm-absent" if not tg else "") for d in devs}
    native = [d for d in devs if d["gfx"] in tg]
    fixable = [d for d in devs if d["gfx"] not in tg and family(d["gfx"], tg)[0]]
    small = [d for d in fixable if d["vram"] < 4 << 30]   # moins de 4 Go : GPU intégré (mémoire partagée)
    if native:   # une carte native suffit : un GPU intégré n'est pas forcé, il ralentirait les modèles répartis
        fixable = [d for d in fixable if d not in small]
    keep = list(native)
    if fixable:
        fams = {family(d["gfx"], tg)[0] or d["gfx"][:6] for d in native + fixable}
        if len(fams) == 1:   # une seule famille : le contournement ne gêne aucune carte
            keep += fixable
            env["HSA_OVERRIDE_GFX_VERSION"] = family(fixable[0]["gfx"], tg)[1]
        elif not native:     # familles différentes, aucune carte native : la famille qui a le plus de mémoire vidéo
            best = {}
            for d in fixable:
                best[family(d["gfx"], tg)[0]] = best.get(family(d["gfx"], tg)[0], 0) + d["vram"]
            fam = max(best, key=best.get)
            keep = [d for d in fixable if family(d["gfx"], tg)[0] == fam]
            env["HSA_OVERRIDE_GFX_VERSION"] = family(keep[0]["gfx"], tg)[1]
    for d in devs:
        if d in native:
            state[d["pci"]] = "natif"
        elif d in keep:
            state[d["pci"]] = "contournement:" + env["HSA_OVERRIDE_GFX_VERSION"]
        elif keep:
            state[d["pci"]] = "écarté:" + ("GPU intégré ou à faible mémoire vidéo" if d in small else
                                           "famille différente des autres cartes" if d in fixable else "cible non prise en charge par ROCm")
        else:
            state[d["pci"]] = "non-pris-en-charge"
    if restrict_visible and keep and len(keep) < len(devs):
        env["ROCR_VISIBLE_DEVICES"] = ",".join(str(d["index"]) for d in keep)
    return env, state


def pool_devices(devs, name):
    """Cartes d'un groupe de GPU, d'après les identifiants ROCm de sa configuration (numéros ou GPU-<uuid>)."""
    ids = ""
    try:
        with open(os.path.join(ETC, "pools", name + ".env")) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k in ("ROCR_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES"):
                    ids = v.strip().strip('"')
    except OSError:
        return devs
    wanted = [x for x in ids.split(",") if x and x != "-1"]
    return [d for d in devs if str(d["index"]) in wanted or (d["uuid"] and d["uuid"] in wanted)]


def main(argv):
    tg, devs = targets(), devices()
    if argv[:1] == ["--report"]:
        env, state = decide(devs, tg)
        print(json.dumps({"targets": sorted(tg), "devices": devs, "state": state, "env": env}, ensure_ascii=False))
        return 0
    inst = argv[0] if argv else "main"
    if inst.startswith("pool:"):
        name = re.sub(r"[^A-Za-z0-9_.-]", "", inst[5:])
        env, state = decide(pool_devices(devs, name), tg, restrict_visible=False)   # le groupe choisit déjà ses cartes
        tag = "pool-" + name
    else:
        env, state = decide(devs, tg)
        tag = "main"
    os.makedirs(RUN, exist_ok=True)
    with open(os.path.join(RUN, "gpu-auto-%s.env" % tag), "w") as f:
        f.write("".join("%s=%s\n" % kv for kv in sorted(env.items())))
    with open(os.path.join(RUN, "gpu-auto-%s.json" % tag), "w") as f:
        json.dump({"targets": sorted(tg), "devices": devs, "state": state, "env": env}, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:   # jamais bloquant : Ollama démarre quand même, sans réglage automatique
        sys.stderr.write("gpu-auto : %s\n" % e)
        sys.exit(0)
