import importlib.util, json, os, subprocess, sys, tempfile, time
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True)
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
def cleanup(): sh("ip netns del obsrv"); sh("ip link del obh0")
cleanup()
for c in ["ip netns add obsrv", "ip link add obh0 type veth peer name obn0", "ip link set obn0 netns obsrv", "ip addr add 10.99.0.1/30 dev obh0", "ip addr add 203.0.113.1/32 dev obh0", "ip link set obh0 up",
          "ip netns exec obsrv ip addr add 10.99.0.2/30 dev obn0", "ip netns exec obsrv ip link set obn0 up", "ip netns exec obsrv ip link set lo up", "ip netns exec obsrv ip route add 203.0.113.0/24 via 10.99.0.1"]:
    assert sh(c).returncode == 0, c
srv = subprocess.Popen([sys.executable, "-c", "import socket,threading\ndef s(a):\n k=socket.socket();k.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);k.bind((a,9443));k.listen(9)\n while True: c,_=k.accept();c.close()\nfor a in ('10.99.0.1','203.0.113.1'): threading.Thread(target=s,args=(a,),daemon=True).start()\nthreading.Event().wait()"])
E = tempfile.mkdtemp(); os.environ.update(OB_ETC=E, OB_NFT="/tmp/fw/nft-ns", OB_FW_RULES=E + "/firewall.nft", OB_STATE=E, OB_OLLAMA_LOG_DIR=E)
spec = importlib.util.spec_from_file_location("srv", "/home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/admin/server.py"); srv_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv_mod)
srv_mod.run = lambda *a, **k: subprocess.run(a[0], capture_output=True, text=True).stdout if a[0][0] != "systemctl" else ""
time.sleep(0.5)
def conn(user, ip):
    r = sh("ip netns exec obsrv setpriv --reuid=%s --regid=%s --clear-groups python3 -c \"import socket; socket.create_connection(('%s', 9443), timeout=1.5)\"" % (user, user, ip))
    return r.returncode == 0
try:
    json.dump({"ollama_internet": False}, open(E + "/ai-policy.json", "w")); open(E + "/ollama.env", "w").write("OLLAMA_NO_CLOUD=1\n")
    r = srv_mod.apply_firewall(force=True); ok(r[0], "règles avec blocage de sortie d'Ollama chargées dans le noyau (%s)" % r[1])
    ok(not conn("ollama", "203.0.113.1"), "compte ollama -> adresse publique 203.0.113.1 : bloqué")
    ok(conn("ollama", "10.99.0.1"), "compte ollama -> réseau privé 10.99.0.1 : autorisé (réseau local)")
    ok(conn("root", "203.0.113.1"), "autres comptes (mises à jour système...) -> adresse publique : autorisé")
    with srv_mod.egress_window():
        ok(conn("ollama", "203.0.113.1"), "pendant un téléchargement lancé depuis la console : compte ollama -> Internet autorisé")
    ok(not conn("ollama", "203.0.113.1"), "téléchargement terminé : de nouveau bloqué")
    json.dump({"ollama_internet": True}, open(E + "/ai-policy.json", "w")); srv_mod.apply_firewall(force=True)
    ok(conn("ollama", "203.0.113.1"), "politique « accès Internet autorisé » : compte ollama -> Internet autorisé")
finally:
    srv.terminate(); cleanup()
