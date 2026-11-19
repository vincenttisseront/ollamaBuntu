#!/usr/bin/env python3
"""Détection GPU : un nouveau « discovering available GPUs » sans résultat ne doit pas masquer la dernière détection réussie."""
import os, sys
sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu")
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, "admin"))
import server
A = 'time=x level=INFO source=runner.go:60 msg="discovering available GPUs..."'
U = 'time=x msg="inference compute" id=0 library=CUDA name=CUDA0 pci_id=0000:03:00.0 total="7.6 GiB"'
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
u, d = server.parse_discovery("\n".join([A, U, "x", A, "y"]))
ok(len(u) == 1 and u[0]["pci_id"] == "0000:03:00.0", "dernier bloc vide : la détection précédente est conservée")
u, d = server.parse_discovery("\n".join([A, U, A, U.replace("0000:03", "0000:04")]))
ok(u[0]["pci_id"] == "0000:04:00.0", "deux blocs avec résultat : le plus récent")
ok(server.parse_discovery("rien") == ([], []) and server.parse_discovery("") == ([], []), "journal sans détection : listes vides")
u, d = server.parse_discovery(U)
ok(len(u) == 1, "résultat sans ligne de début : lu quand même")
u, d = server.parse_discovery("\n".join([A, 'x msg="dropping integrated GPU" id=1 library=Vulkan', U]))
ok(len(u) == 1 and len(d) == 1, "GPU intégré écarté signalé dans le même bloc")
print("%d contrôles réussis" % n)
