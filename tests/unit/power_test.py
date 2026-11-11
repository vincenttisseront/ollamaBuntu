#!/usr/bin/env python3
"""Réveil (Wake-on-LAN) et mise en veille du parc : paquet magique, validations, décisions (module pur), cartes réseau."""
import os, socket, sys, tempfile, threading
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import power
n = 0
def ok(c, m):
    global n; n += 1; print(("[%02d] OK   - " if c else "[%02d] ÉCHEC - ") % n + m, flush=True)
    if not c: sys.exit(1)
def raises(fn, *a):
    try: fn(*a)
    except ValueError: return True
    return False

# --- adresses
ok(power.mac_clean("3C-EC-EF-12-34-56") == "3c:ec:ef:12:34:56" and power.mac_clean("3cec.ef12.3456") == "3c:ec:ef:12:34:56" and power.mac_clean("3cecef123456") == "3c:ec:ef:12:34:56" and power.mac_clean("") == "", "MAC : séparateurs usuels acceptés, forme normalisée")
ok(all(raises(power.mac_clean, x) for x in ("3c:ec:ef:12:34", "zz:ec:ef:12:34:56", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "3c:ec:ef:12:34:56:78")), "MAC : trop courte, non hexadécimale, nulle ou de diffusion refusées")
ok(power.broadcast_clean("192.168.1.255") == "192.168.1.255" and power.broadcast_clean("") == "" and all(raises(power.broadcast_clean, x) for x in ("192.168.1", "300.1.1.1", "a.b.c.d", "192.168.01.255", "192.168.1.255/24")), "adresse de diffusion : IPv4 stricte")
pk = power.magic_packet("3c:ec:ef:12:34:56")
ok(len(pk) == 102 and pk[:6] == b"\xff" * 6 and pk[6:] == bytes.fromhex("3cecef123456") * 16, "paquet magique : 6 × 0xFF puis 16 fois la MAC (102 octets)")
ok(raises(power.magic_packet, ""), "paquet magique : MAC vide refusée")

# --- envoi réel en UDP sur la boucle locale (aucun réseau extérieur)
srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); srv.bind(("127.0.0.1", 0)); srv.settimeout(5)
port = srv.getsockname()[1]
sent = power.send_wol("3c:ec:ef:12:34:56", "127.0.0.1", port)
data, _ = srv.recvfrom(2048)
ok(sent == 102 and data == pk, "envoi UDP : le paquet reçu est identique au paquet magique")
srv.close()

# --- réglages généraux
c = power.config_clean({})
ok(c == power.DEFAULTS and c["enabled"] is False, "réglages : valeurs par défaut, automatisme désactivé")
c = power.config_clean({"enabled": True, "wake_waiting": "3", "keep_awake": 1}, c)
ok(c["enabled"] and c["wake_waiting"] == 3 and c["keep_awake"] == 1 and c["wake_after_s"] == 20, "réglages : champs absents conservés")
ok(all(raises(power.config_clean, {k: v}) for k, v in (("wake_after_s", 1), ("wake_busy_pct", 101), ("cooldown_s", "x"), ("keep_awake", -1), ("settle_s", 10 ** 7))), "réglages : valeurs hors bornes refusées")

# --- réglages d'un serveur
s = power.server_clean({"mac": "3C:EC:EF:12:34:56", "wake": True, "sleep": "suspend", "idle_min": 15})
ok(s["mac"] == "3c:ec:ef:12:34:56" and s["wake"] and s["sleep"] == "suspend" and s["idle_min"] == 15 and s["broadcast"] == "", "serveur : réglages valides")
ok(raises(power.server_clean, {"wake": True}) and raises(power.server_clean, {"sleep": "suspend"}), "serveur : réveil ou veille automatiques sans MAC refusés (il ne pourrait pas être réveillé)")
ok(raises(power.server_clean, {"mac": "3c:ec:ef:12:34:56", "sleep": "hibernate"}) and raises(power.server_clean, {"idle_min": 2}) and raises(power.server_clean, {"idle_min": "x"}), "serveur : mode inconnu ou inactivité hors bornes refusés")
ok(power.server_clean({"wake": False}, s)["mac"] == s["mac"], "serveur : champs absents conservés")
ok(power.member_clean({"allow": "suspend"}) == {"allow": "suspend"} and power.member_clean({}) == {"allow": ""} and raises(power.member_clean, {"allow": "reboot"}), "serveur géré : autorisation « suspend », « poweroff » ou refus")
ok(power.allowed("suspend", "suspend") and power.allowed("poweroff", "suspend") and power.allowed("poweroff", "poweroff") and not power.allowed("suspend", "poweroff") and not power.allowed("", "suspend") and not power.allowed("poweroff", ""), "autorisation : l'extinction autorise aussi la veille, jamais l'inverse")

# --- modèles servis
ok(power.requestable(["a", "b"], {"c": "a", "*": "b", "d": "zz"}) == {"a", "b", "c", "*"}, "modèles servis : modèles de remplacement compris")
ok(power.serves([], {"x"}) and power.serves(["a"], {"a"}) and not power.serves(["a"], {"b"}) and power.serves(["*"], {"b"}), "serveur sans liste connue : non exclu ; sinon il faut un modèle commun")

# --- états et repos
T = 1000000
ok(power.state_of(True, None, None, T, 240) == "awake" and power.state_of(False, T - 10, None, T, 240) == "waking" and power.state_of(False, T - 500, T - 900, T, 240) == "offline"
   and power.state_of(False, None, T - 900, T, 240) == "asleep" and power.state_of(False, T - 1000, T - 600, T, 240) == "asleep" and power.state_of(False, None, None, T, 240) == "offline", "états : éveillé, en réveil, endormi (par la console), injoignable")
ok(power.is_idle(2.0, [], None, T) and not power.is_idle(40.0, [], None, T) and not power.is_idle(2.0, [{"id": 1}], None, T) and not power.is_idle(2.0, [], T - 30, T) and power.is_idle(2.0, [], T - 500, T) and not power.is_idle(None, [], None, T), "repos : charge faible, aucune tâche, aucune requête récente")
m = power.track_idle({}, True, T); m = power.track_idle(m, True, T + 60)
ok(m["idle_since"] == T and power.track_idle(m, False, T + 90)["idle_since"] is None and power.track_idle(m, True, T + 120)["idle_since"] == T + 120, "repos : début conservé tant qu'il dure, remis à zéro dès que le serveur travaille")
ok(power.track_busy(None, True, T) == T and power.track_busy(T, True, T + 30) == T and power.track_busy(T, False, T + 30) is None, "saturation : début conservé tant qu'elle dure")
ok(power.saturated([90, 95], 85) and not power.saturated([90, 20], 85) and not power.saturated([], 85) and not power.saturated([99], 0) and not power.saturated([None], 85), "saturation : tous les serveurs éveillés au-dessus du seuil")

# --- décisions
CONF = power.config_clean({"enabled": True})
def srv(i, state="awake", models=("m",), wake=True, sleep="suspend", idle_since=None, idle_min=30, woke_at=None, wake_sent=None, mac="3c:ec:ef:00:00:0%d"):
    return {"id": i, "name": "Srv" + i, "state": state, "models": list(models), "idle_since": idle_since, "woke_at": woke_at, "wake_sent": wake_sent,
            "power": {"mac": (mac % int(i)) if "%d" in mac else mac, "wake": wake, "sleep": sleep, "idle_min": idle_min}}
def kinds(acts): return [(a["action"], a["id"]) for a in acts]
off = dict(CONF, enabled=False)
ok(power.decide(T, off, [srv("1", "asleep")], [{"model": "m", "waited": 99}], {}, None) == [], "automatisme désactivé : aucune action")
ok(kinds(power.decide(T, CONF, [srv("1"), srv("2", "asleep")], [{"model": "m", "waited": 25}], {}, None)) == [("wake", "2")], "file d'attente depuis plus de 20 s : le serveur endormi est réveillé")
ok(power.decide(T, CONF, [srv("1"), srv("2", "asleep")], [{"model": "m", "waited": 10}], {}, None) == [], "file d'attente trop récente : pas encore de réveil")
ok(power.decide(T, CONF, [srv("2", "asleep")], [], {}, None) == [], "aucune demande : un serveur endormi le reste")
ok(power.decide(T, dict(CONF, wake_waiting=0), [srv("2", "asleep")], [{"model": "m", "waited": 99}], {}, None) == [], "réveil selon la file désactivé (0)")
ok(power.decide(T, dict(CONF, wake_waiting=3), [srv("2", "asleep")], [{"model": "m", "waited": 99}] * 2, {}, None) == [], "seuil de 3 demandes : 2 ne suffisent pas")
a = power.decide(T, CONF, [srv("1", "asleep", models=("autre",)), srv("2", "asleep", models=("m",))], [{"model": "m", "waited": 30}], {}, None)
ok(kinds(a) == [("wake", "2")] and "30 s" in a[0]["why"], "le serveur qui possède le modèle attendu est réveillé (pas un autre), motif en clair")
ok(power.decide(T, CONF, [srv("1", "asleep", models=("autre",))], [{"model": "m", "waited": 30}], {}, None) == [], "aucun serveur endormi ne sert le modèle attendu : pas de réveil inutile")
ok(kinds(power.decide(T, CONF, [srv("1", "asleep", models=())], [{"model": "m", "waited": 30}], {}, None)) == [("wake", "1")], "liste de modèles inconnue : réveil tenté")
ok(power.decide(T, CONF, [srv("1", "asleep", wake=False)], [{"model": "m", "waited": 30}], {}, None) == [] and power.decide(T, CONF, [srv("1", "asleep", mac="")], [{"model": "m", "waited": 30}], {}, None) == [], "réveil automatique désactivé ou sans MAC : jamais")
ok(power.decide(T, CONF, [srv("1", "waking", wake_sent=T - 30), srv("2", "asleep")], [{"model": "m", "waited": 30}], {}, None) == [], "un réveil est déjà en cours : on attend avant d'en lancer un autre")
ok(power.decide(T, CONF, [srv("1", "offline", wake_sent=T - 100)], [{"model": "m", "waited": 30}], {}, None) == [], "réveil sans effet : pas de nouvel essai avant le délai de 300 s")
ok(kinds(power.decide(T, CONF, [srv("1", "offline", wake_sent=T - 400)], [{"model": "m", "waited": 30}], {}, None)) == [("wake", "1")], "…puis nouvel essai")
ok(kinds(power.decide(T, CONF, [srv("1", "offline"), srv("2", "asleep")], [{"model": "m", "waited": 30}], {}, None)) == [("wake", "2")], "à égalité, un serveur mis en veille par la console passe avant un serveur injoignable")
# signal « modèle absent »
ok(kinds(power.decide(T, CONF, [srv("1", "asleep", models=("rare",)), srv("2", "asleep", models=("m",))], [], {"rare": T - 20}, None)) == [("wake", "1")], "modèle demandé que seul un serveur endormi possède : ce serveur est réveillé")
ok(power.decide(T, CONF, [srv("1", "asleep", models=("rare",))], [], {"rare": T - 500}, None) == [], "signal trop ancien (3 min) : ignoré")
ok(power.decide(T, CONF, [srv("1", "asleep", models=("autre",))], [], {"rare": T - 20}, None) == [], "signal : seul un serveur qui possède ce modèle est réveillé")
# saturation
ok(kinds(power.decide(T, CONF, [srv("1", "asleep")], [], {}, T - 90)) == [("wake", "1")], "parc saturé depuis plus de 60 s : réveil")
ok(power.decide(T, CONF, [srv("1", "asleep")], [], {}, T - 30) == [] and power.decide(T, CONF, [srv("1", "asleep")], [], {}, None) == [], "saturation trop récente ou absente : rien")
# mise en veille
IDLE = T - 3600
ok(kinds(power.decide(T, CONF, [srv("1", idle_since=IDLE), srv("2", idle_since=T - 100)], [], {}, None)) == [("sleep", "1")], "inactif depuis plus de 30 min : mis en veille ; l'autre (inactif depuis 100 s) reste éveillé")
a = power.decide(T, CONF, [srv("1", idle_since=IDLE)], [], {}, None)
ok(a[0]["mode"] == "suspend" and "60 min" in a[0]["why"], "motif en clair et mode demandé")
ok(power.decide(T, CONF, [srv("1", idle_since=IDLE, sleep="")], [], {}, None) == [] and power.decide(T, CONF, [srv("1", idle_since=IDLE, mac="", sleep="suspend")], [], {}, None) == [], "pas de mise en veille sans mode, ni sans MAC")
ok(power.decide(T, CONF, [srv("1", idle_since=None)], [], {}, None) == [], "serveur occupé : jamais mis en veille")
ok(power.decide(T, CONF, [srv("1", idle_since=IDLE, woke_at=T - 100)], [], {}, None) == [] and kinds(power.decide(T, CONF, [srv("1", idle_since=IDLE, woke_at=T - 900)], [], {}, None)) == [("sleep", "1")], "après un réveil, 10 min d'éveil minimum")
r = power.decide(T, dict(CONF, keep_awake=1), [srv("1", idle_since=IDLE), srv("2", idle_since=IDLE - 5)], [], {}, None)
ok(len(r) == 1 and r[0]["action"] == "sleep", "serveurs toujours éveillés : un seul reste, l'autre peut dormir (un par passage)")
ok(power.decide(T, dict(CONF, keep_awake=1), [srv("1", idle_since=IDLE)], [], {}, None) == [], "un seul serveur éveillé et « toujours éveillé » = 1 : il reste")
ok(len(power.decide(T, CONF, [srv("1", idle_since=IDLE), srv("2", idle_since=IDLE), srv("3", idle_since=IDLE)], [], {}, None)) == 1, "au plus une mise en veille par passage")
ok(power.decide(T, CONF, [srv("1", idle_since=IDLE)], [{"model": "m", "waited": 5}], {}, None) == [] and power.decide(T, CONF, [srv("1", idle_since=IDLE)], [{"model": "m", "waited": 90}], {}, None) == [], "jamais de mise en veille tant qu'une demande attend")
ok(power.decide(T, CONF, [srv("1", idle_since=IDLE), srv("2", "waking", wake_sent=T - 10)], [], {}, None) == [], "jamais de mise en veille pendant un réveil")
ok(power.decide(T, CONF, [srv("1", idle_since=IDLE)], [], {"m": T - 10}, None) == [], "ni quand un signal de modèle absent est récent")

# --- cartes réseau (arborescence /sys simulée)
tmp = tempfile.mkdtemp(); root = os.path.join(tmp, "net")
def nic(name, mac, device=True, wireless=False, state="up"):
    d = os.path.join(root, name); os.makedirs(d)
    open(os.path.join(d, "address"), "w").write(mac + "\n"); open(os.path.join(d, "operstate"), "w").write(state + "\n")
    if device: os.makedirs(os.path.join(d, "device"))
    if wireless: os.makedirs(os.path.join(d, "wireless"))
nic("lo", "00:00:00:00:00:00", device=False); nic("enp3s0", "3C:EC:EF:12:34:56"); nic("docker0", "02:42:ac:11:00:01", device=False); nic("wlp2s0", "aa:bb:cc:dd:ee:01", wireless=True); nic("enp4s0", "3c:ec:ef:12:34:57", state="down")
ETH = "Settings for enp3s0:\n\tSupports Wake-on: pumbg\n\tWake-on: d\n"
nics = power.list_nics(root, lambda i: ETH if i == "enp3s0" else "Settings for x:\n\tSupports Wake-on: d\n\tWake-on: d\n")
ok([x["iface"] for x in nics] == ["enp3s0", "enp4s0"], "cartes réseau : seules les cartes filaires physiques (ni boucle locale, ni Docker, ni Wi-Fi)")
ok(nics[0]["mac"] == "3c:ec:ef:12:34:56" and nics[0]["wol"] == "off" and nics[0]["supported"] is True and nics[1]["supported"] is False and nics[1]["link"] == "down", "cartes réseau : MAC normalisée, réveil désactivé mais pris en charge / non pris en charge")
ok(power.parse_ethtool("Supports Wake-on: pg\n\tWake-on: g\n") == ("magic", True) and power.parse_ethtool("") == ("?", None) and power.parse_ethtool("Link detected: yes") == ("?", None), "ethtool : lecture de l'état du réveil")
ok(power.list_nics(os.path.join(tmp, "absent")) == [] and power.list_nics(root)[0]["wol"] == "?", "dossier absent ou ethtool indisponible : liste vide / état inconnu")
print("\n%d vérifications réussies" % n)
