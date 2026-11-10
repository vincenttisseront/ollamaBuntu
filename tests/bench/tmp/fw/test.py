import importlib.util, json, os, socket, subprocess, sys, tempfile, time, threading
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: cleanup(); sys.exit(1)
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True)
def cleanup(): sh("ip netns del obsrv"); sh("ip link del obh0")
cleanup()
for c in ["ip netns add obsrv", "ip link add obh0 type veth peer name obn0", "ip link set obn0 netns obsrv", "ip addr add 10.99.0.1/30 dev obh0", "ip link set obh0 up",
          "ip netns exec obsrv ip addr add 10.99.0.2/30 dev obn0", "ip netns exec obsrv ip link set obn0 up", "ip netns exec obsrv ip link set lo up"]:
    r = sh(c); assert r.returncode == 0, (c, r.stderr)
E = tempfile.mkdtemp(); os.makedirs(E + "/tls")
open("/tmp/fw/nft-ns", "w").write('#!/bin/sh\nexec ip netns exec obsrv /usr/sbin/nft "$@"\n'); os.chmod("/tmp/fw/nft-ns", 0o755)
os.environ.update(OB_ETC=E, OB_NFT="/tmp/fw/nft-ns", OB_FW_RULES=E + "/firewall.nft", OB_STATE=E, OB_OLLAMA_LOG_DIR=E)
spec = importlib.util.spec_from_file_location("srv", "/home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/admin/server.py"); srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)
srv.run = lambda *a, **k: subprocess.run(a[0], capture_output=True, text=True).stdout if a[0][0] != "systemctl" else ""
PORTS = [22, 80, 443, 3000, 8443, 11400, 11434, 11443, 11500]
listener = subprocess.Popen(["ip", "netns", "exec", "obsrv", sys.executable, "-c", """
import socket, threading
def serve(p):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("0.0.0.0", p)); s.listen(64)
    while True:
        c, _ = s.accept(); c.sendall(b"ok"); c.close()
for p in %r: threading.Thread(target=serve, args=(p,), daemon=True).start()
threading.Event().wait()""" % PORTS])
time.sleep(0.8)
def reach(port, timeout=0.6):
    try:
        s = socket.create_connection(("10.99.0.2", port), timeout=timeout); s.close(); return True
    except OSError: return False
def scan(): return {p: reach(p) for p in PORTS}
try:
    ok(scan() == {p: True for p in PORTS}, "sans pare-feu : les 9 ports de test sont joignables depuis le réseau")
    sh("ip netns exec obsrv nft add table ip docker_sim; ip netns exec obsrv nft add chain ip docker_sim DOCKER")
    r = srv.apply_firewall(force=True); ok(r[0], "règles générées et chargées : %s" % r[1])
    s = scan(); ok([p for p in PORTS if s[p]] == [22, 80, 443], "par défaut, seuls SSH, 80 et 443 sont ouverts ; fermés : %s" % [p for p in PORTS if not s[p]])
    ok(sh("ip netns exec obsrv nft list table ip docker_sim").returncode == 0, "table de Docker conservée (aucun « flush ruleset »)")
    import struct
    def icmp(typ):
        """Envoie un paquet ICMP (type donné) et attend une réponse « echo-reply »."""
        def csum(b):
            b += b"\0" * (len(b) % 2); t = sum(struct.unpack("!%dH" % (len(b) // 2), b)); t = (t >> 16) + (t & 0xFFFF); return ~(t + (t >> 16)) & 0xFFFF
        pkt = struct.pack("!BBHHH", typ, 0, 0, 0x4242, 1) + b"ollamabuntu"
        pkt = pkt[:2] + struct.pack("!H", csum(pkt)) + pkt[4:]
        so = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP); so.settimeout(1); so.sendto(pkt, ("10.99.0.2", 0))
        try:
            while True:
                d, a = so.recvfrom(2048)
                if a[0] == "10.99.0.2" and d[20] == 0: return True
        except OSError: return False
    ok(icmp(8), "ping (ICMP echo, débit limité) : réponse reçue")
    ok(not icmp(13), "contre-épreuve : ICMP « timestamp » (type non autorisé) bloqué")
    hs = socket.socket(); hs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); hs.bind(("10.99.0.1", 9999)); hs.listen(5)
    threading.Thread(target=lambda: [hs.accept()[0].sendall(b"pong")], daemon=True).start()
    out = sh("ip netns exec obsrv python3 -c \"import socket; s=socket.create_connection(('10.99.0.1', 9999), timeout=2); print(s.recv(4).decode())\"").stdout.strip()
    ok(out == "pong", "connexions sortantes et leurs réponses autorisées (mises à jour, registre, Docker)")
    open(E + "/open-webui.env", "w").write("x=1\n")
    json.dump({"enabled": True, "port": 11443, "tls": True, "auth": True, "allow": ["10.99.0.0/30"], "anonymous": {"perms": [], "models": []}, "keys": []}, open(E + "/publication.json", "w"))
    srv.apply_firewall(); s = scan()
    ok([p for p in PORTS if s[p]] == [22, 80, 443, 8443, 11443], "Open WebUI déployé + API publiée : 8443 et 11443 ouverts en plus (3000 en clair toujours fermé)")
    pub = json.load(open(E + "/publication.json")); pub["allow"] = ["192.168.0.0/16"]; json.dump(pub, open(E + "/publication.json", "w"))
    srv.apply_firewall(); ok(not reach(11443) and reach(8443), "API publiée réservée à 192.168.0.0/16 : port 11443 fermé pour 10.99.0.1")
    try: srv.set_firewall({"admin_allow": ["192.168.0.0/16"]}, "10.99.0.1"); locked = False
    except ValueError as e: locked = True; msg = str(e)
    ok(locked and reach(22), "protection anti-verrouillage : réglage refusé (« %s »)" % msg[:80])
    srv.set_firewall({"admin_allow": ["192.168.0.0/16"]}, "192.168.1.5"); s = scan()
    ok(not s[22] and not s[443] and not s[80] and s[8443], "administration réservée à 192.168.0.0/16 : SSH et console fermés pour 10.99.0.1, Open WebUI inchangé")
    srv.set_firewall({"admin_allow": ["10.99.0.0/24", "2001:db8::/32"]}, "10.99.0.1"); s = scan()
    ok(s[22] and s[443], "administration réservée à 10.99.0.0/24 (+ un réseau IPv6) : accès rétabli")
    fails = sum(not reach(22, 0.4) for _ in range(35))
    ok(fails >= 10, "SSH : limitation de débit par adresse (35 connexions rapides : %d refusées au-delà de la rafale)" % fails)
    st = srv.firewall_status(); ok(st["active"] and st["drops"] and st["drops"] > 0, "état : pare-feu actif, %d paquets refusés comptés" % st["drops"])
    before = sh("ip netns exec obsrv nft -s list table inet ollamabuntu").stdout
    srv.render_firewall = lambda cfg=None: "table inet ollamabuntu { chain input { type filter hook input priority filter; policy drop; tcp dport syntaxe-invalide accept } }\n"
    r = srv.apply_firewall(force=True)
    ok(not r[0] and sh("ip netns exec obsrv nft -s list table inet ollamabuntu").stdout == before and reach(443), "règles invalides : refusées par « nft -c », règles en place conservées (« %s »)" % r[1][:60])
    spec.loader.exec_module(srv); srv.run = lambda *a, **k: subprocess.run(a[0], capture_output=True, text=True).stdout if a[0][0] != "systemctl" else ""
    srv.set_firewall({"enabled": False}, "10.99.0.1")
    ok(reach(3000) and sh("ip netns exec obsrv nft list table inet ollamabuntu").returncode != 0, "pare-feu désactivé depuis la console : table retirée")
finally:
    listener.terminate(); cleanup()
