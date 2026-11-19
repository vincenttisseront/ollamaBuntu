#!/usr/bin/env python3
"""Détection GPU : journal noyé par llama-server (filtre large sans résultat) -> requête ciblée de secours."""
import os, sys, stat, tempfile
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import server
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
tmp = tempfile.mkdtemp()
A = 'time=x msg="discovering available GPUs..."'
U = 'time=x msg="inference compute" id=0 library=CUDA name=CUDA0 pci_id=0000:03:00.0 total="7.6 GiB"'
fake = os.path.join(tmp, "journalctl")
def script(broad, narrow, plain):
    open(fake, "w").write('''#!/bin/bash
for a in "$@"; do
  case "$a" in
    *"hsa"*) printf '%%s\\n' %s; exit 0 ;;
    *"inference compute|dropping"*) printf '%%s\\n' %s; exit 0 ;;
  esac
done
printf '%%s\\n' %s
''' % (broad, narrow, plain))
    os.chmod(fake, 0o755)
os.environ["PATH"] = tmp + ":" + os.environ["PATH"]
server.OLLAMA_LOG_DIR = server.OLLAMA_LOG_FILE = None
def q(t): return "'" + t.replace("'", "'\\''") + "'"
server._LOG_CACHE.clear()
script(q("junk\n" + A + "\njunk"), q(A + "\n" + U), q("junk"))
u, d = server.parse_discovery(server._ollama_log_text())
ok(len(u) == 1 and u[0]["pci_id"] == "0000:03:00.0", "filtre large : discovering sans résultat -> le résultat vient de la requête ciblée")
script(q("junk"), q(A + "\n" + U), q("junk"))
u, d = server.parse_discovery(server._ollama_log_text())
ok(len(u) == 1, "filtre large sans aucune détection : requête ciblée")
script(q(A + "\n" + U), q("autre"), q("junk"))
t = server._ollama_log_text()
ok("autre" not in t and len(server.parse_discovery(t)[0]) == 1, "filtre large complet : la requête ciblée n'est pas utilisée")
script(q("junk"), q("rien"), q("junk"))
ok(server.parse_discovery(server._ollama_log_text()) == ([], []), "aucune détection nulle part : listes vides")
# journalctl -g -n renvoie du plus récent au plus ancien : la détection retenue doit être la plus récente
OLD = 'time=2026-11-13T09:54:12.240Z msg="inference compute" id=cpu library=cpu pci_id='
NEW = 'time=2026-11-19T11:29:47.609Z msg="inference compute" id=0 library=CUDA pci_id=0000:03:00.0'
A1 = 'time=2026-11-13T09:54:02.955Z msg="discovering available GPUs..."'
A2 = 'time=2026-11-19T11:29:45.181Z msg="discovering available GPUs..."'
script(q("\n".join([NEW, A2, OLD, A1])), q("rien"), q("junk"))
u, d = server.parse_discovery(server._ollama_log_text())
ok(len(u) == 1 and u[0]["library"] == "CUDA", "journal renvoyé du plus récent au plus ancien : la détection récente est retenue (pas le vieux « cpu »)")
script(q("\n".join([A1, OLD, A2, NEW])), q("rien"), q("junk"))
u, d = server.parse_discovery(server._ollama_log_text())
ok(len(u) == 1 and u[0]["library"] == "CUDA", "journal déjà chronologique : inchangé")
ok(server.chronological("") == "" and server.chronological("sans horodatage\nautre") == "sans horodatage\nautre", "texte sans horodatage : laissé tel quel")
print("%d contrôles réussis" % n)
