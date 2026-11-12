#!/usr/bin/env python3
"""Détection du GPU utilisé par Ollama : la phrase de démarrage ne doit pas se perdre dans un long journal (journalctl simulé)."""
import os, stat, sys, tempfile
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp(); ETC = os.path.join(tmp, "etc"); os.makedirs(ETC)
os.environ.update(OB_ETC=ETC, OB_STATE=os.path.join(tmp, "state"))
os.environ.pop("OB_OLLAMA_LOG_DIR", None)
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import server
server.LOG_CACHE_TTL = 0
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)

START = 'time=2026-11-12T08:00:00 level=INFO source=runner.go msg="discovering available GPUs"'
USED = 'time=2026-11-12T08:00:02 level=INFO source=types.go msg="inference compute" id=0 library=ROCm compute=gfx1101 name=ROCm0 description="AMD Radeon RX 7700 XT" pci_id=0000:06:00.0 total="12.0 GiB" available="11.5 GiB"'
GIN = '[GIN] 2026/11/12 - 09:00:00 | 200 |  1.2s |  127.0.0.1 | POST "/api/chat"'
journal = os.path.join(tmp, "journal.txt")
bindir = os.path.join(tmp, "bin"); os.makedirs(bindir)
FAKE = r'''#!/usr/bin/env python3
import re, sys
a = sys.argv[1:]
lines = open(%r).read().splitlines()
if "-g" in a:
    if %r:
        sys.exit(1)
    rx = re.compile(a[a.index("-g") + 1], re.I); lines = [l for l in lines if rx.search(l)]
n = int(a[a.index("-n") + 1]) if "-n" in a else len(lines)
print("\n".join(lines[-n:]))
'''
def fake(nogrep=False):
    p = os.path.join(bindir, "journalctl"); open(p, "w").write(FAKE % (journal, nogrep)); os.chmod(p, 0o755)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
def write(lines): open(journal, "w").write("\n".join(lines) + "\n")

fake(); write([START, USED] + [GIN] * 30)
used, dropped = server.ollama_discovery()
ok(len(used) == 1 and used[0]["library"] == "ROCm" and used[0]["description"] == "AMD Radeon RX 7700 XT", "journal court : le GPU AMD est trouvé")
write([START, USED] + [GIN] * 30000)
used, dropped = server.ollama_discovery()
ok(len(used) == 1 and used[0]["compute"] == "gfx1101", "journal de 30 000 lignes (Ollama en service depuis longtemps) : le GPU est toujours trouvé")
old = server.run(["journalctl", "-u", "ollama.service", "-b", "-n", "5000", "--no-pager", "-o", "cat"])
ok("discovering available GPUs" not in old, "(l'ancienne lecture des 5000 dernières lignes ne voyait plus la phrase de démarrage : c'était le défaut)")
fake(nogrep=True); write([START, USED] + [GIN] * 100)
used, dropped = server.ollama_discovery()
ok(len(used) == 1, "journalctl sans option -g : repli sur la lecture simple, GPU trouvé")
fake(); write([START, USED, START, 'time=x level=INFO msg="inference compute" id=0 library=cpu description="cpu"'] + [GIN] * 50000)
used, dropped = server.ollama_discovery()
ok(len(used) == 1 and used[0]["library"] == "cpu", "Ollama redémarré : seule la dernière détection compte")
write([GIN] * 100); used, dropped = server.ollama_discovery()
ok(used == [] and dropped == [], "aucune détection dans le journal : liste vide")
write([START, 'time=y level=WARN msg="amdgpu is supported but kfd denied" gpu=0'] + [GIN] * 40000 + ['time=z level=WARN msg="x"'])
ok("kfd denied" in (server.rocm_hint(server.ollama_log_text()) or ""), "message ROCm de la détection retrouvé dans un long journal")

# --- mémorisation : le journal perd la phrase de démarrage (rotation) mais c'est la même instance Ollama
SD = os.path.join(bindir, "systemctl")
def instance(pid, mono, restarts=0):
    open(SD, "w").write("#!/bin/sh\necho MainPID=%s\necho ActiveEnterTimestampMonotonic=%s\necho ActiveEnterTimestamp=Thu 2026-11-12 08:00:00 CET\necho NRestarts=%s\necho ActiveState=active\n" % (pid, mono, restarts)); os.chmod(SD, 0o755)
instance(4242, 111); write([START, USED] + [GIN] * 50)
used, _ = server.ollama_discovery()
ok(len(used) == 1, "instance 4242 : détection lue et mémorisée")
write([GIN] * 5000)
used, _ = server.ollama_discovery()
ok(len(used) == 1 and used[0]["library"] == "ROCm", "journal tourné (phrase perdue), même instance : le GPU mémorisé est conservé")
instance(5151, 222); used, _ = server.ollama_discovery()
ok(used == [], "Ollama redémarré (autre PID) et journal sans détection : la mémoire de l'ancienne instance n'est PAS réutilisée")
instance(0, 0); used, _ = server.ollama_discovery()
ok(used == [], "service arrêté : rien n'est inventé")
info = server.ollama_service_info()
ok(info["id"] == "" and info["restarts"] == 0, "service arrêté : identité vide")
instance(7, 9, restarts=4); info = server.ollama_service_info()
ok(info["id"] == "7:9" and info["restarts"] == 4 and info["state"] == "active", "identité, redémarrages et état lus")
server.LOG_CACHE_TTL = 20; server._LOG_CACHE.clear()
calls = os.path.join(tmp, "calls"); open(calls, "w").close()
jp = os.path.join(bindir, "journalctl"); body = open(jp).read()
open(jp, "w").write(body.replace("import re, sys", "import re, sys\nopen(%r, 'a').write('x')" % calls)); os.chmod(jp, 0o755)
instance(1, 1); write([START, USED] + [GIN] * 10)
for _ in range(5): server.ollama_discovery(); server.ollama_log_text()
ok(len(open(calls).read()) == 1, "5 affichages d'affilée : le journal n'est lu qu'une fois (mémoire de 20 s)")
print("\n%d vérifications réussies" % n)
