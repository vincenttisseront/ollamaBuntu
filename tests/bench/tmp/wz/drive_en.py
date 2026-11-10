#!/usr/bin/env python3
"""Pilote l'assistant OllamaBuntu au clavier et vérifie chaque écran."""
import pexpect, pyte, time, sys, re
from PIL import Image, ImageDraw, ImageFont
COLS, ROWS = 80, 25
screen = pyte.Screen(COLS, ROWS); stream = pyte.ByteStream(screen)
cmd = ("chroot /tmp/target /usr/bin/env -i TERM=linux LANG=C.UTF-8 OB_DRYRUN=1 "
       "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
       + " ".join(sys.argv[1:]))
child = pexpect.spawn("/bin/bash", ["-c", cmd], dimensions=(ROWS, COLS), timeout=5)
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 15)
PAL = {"black": (0,0,0), "red": (170,0,0), "green": (0,170,0), "brown": (170,85,0), "blue": (0,0,170),
       "magenta": (170,0,170), "cyan": (0,170,170), "white": (170,170,170), "default": None}
BRIGHT = {"black": (85,85,85), "red": (255,85,85), "white": (255,255,255), "brown": (255,255,85)}
ACS = {"q": "─", "x": "│", "l": "┌", "k": "┐", "m": "└", "j": "┘", "a": "▒", "t": "├", "u": "┤", "w": "┬", "v": "┴", "n": "┼"}
def pump(t=0.6):
    end = time.time() + t
    while time.time() < end:
        try: stream.feed(child.read_nonblocking(65536, timeout=0.15))
        except pexpect.TIMEOUT: pass
        except pexpect.EOF: return False
    return True
def text(): return "\n".join(screen.display)
def wait_for(pattern, t=20):
    end = time.time() + t
    while time.time() < end:
        alive = pump(0.4)
        if re.search(pattern, text()): return True
        if not alive: break
    print("!!! ÉCRAN ATTENDU NON TROUVÉ :", pattern); print(text()); sys.exit(1)
def shot(name):
    img = Image.new("RGB", (COLS * 9, ROWS * 18), (0, 0, 0)); d = ImageDraw.Draw(img)
    for y in range(ROWS):
        for x in range(COLS):
            c = screen.buffer[y][x]
            fg = (BRIGHT.get(c.fg) if c.bold else None) or PAL.get(c.fg) or (170,170,170)
            bg = PAL.get(c.bg) or (0,0,0)
            if c.reverse: fg, bg = bg, fg
            d.rectangle([x*9, y*18, x*9+8, y*18+17], fill=bg)
            ch = c.data
            d.text((x*9, y*18), ch, font=FONT, fill=fg)
    img.save(f"/tmp/wz/{name}.png")
def key(k, settle=0.5): child.send(k); pump(settle)
ENTER, DOWN, BS = "\r", "\x1b[B", "\x7f"
def clear_field(n=40): key(BS * n, 0.3)
step = 0
def ok(msg):
    global step; step += 1; print(f"[{step:02d}] OK - {msg}")

# ------------------------------------------------------------ scénario (anglais)
FR = re.compile(r"[éèêàçùâîôû«»]|\b(le|la|les|des|du|une|est|pour|avec|votre|vous|adresse|serveur|réseau|carte|Suivant|Retour|Oui|Non)\b")
def no_french(where):
    t = text(); bad = [l.strip() for l in t.splitlines() if FR.search(l) and "Langue" not in l and "Français" not in l]
    assert not bad, "français restant (%s) : %s" % (where, bad[:3]); ok("aucun texte français : " + where)
wait_for(r"Langue / Language"); shot("en-00-langue"); ok("premier écran : choix de la langue (Français / English)")
key("\t"); key(ENTER)
wait_for(r"O L L A M A B U N T U"); assert "Welcome" in text() and "Just four settings left" in text(); shot("en-01-welcome"); ok("accueil en anglais"); no_french("accueil"); key(ENTER)
wait_for(r"Network card used to administer"); no_french("carte réseau"); key(ENTER)
wait_for(r"How does card"); no_french("adressage"); key(DOWN); key(ENTER)
wait_for(r"CIDR format"); key("192.168.10.50", 0.3); key(ENTER)
wait_for(r"is not a valid IPv4 address"); ok("adresse invalide : « is not a valid IPv4 address in CIDR format »"); no_french("erreur d'adresse"); key(ENTER)
wait_for(r"CIDR format"); clear_field(); key("192.168.10.50/24", 0.3); key(ENTER)
wait_for(r"Default gateway"); assert "192.168.10.1" in text(); clear_field(); key("10.0.0.1"); key(ENTER)
wait_for(r"must be an address on network 192.168.10.0/24"); ok("passerelle hors réseau refusée (anglais)"); key(ENTER)
wait_for(r"Default gateway"); clear_field(); key("192.168.10.254"); key(ENTER)
wait_for(r"DNS servers"); clear_field(); key("192.168.10.53, 1.1.1.1"); key(ENTER)
wait_for(r"Server name"); no_french("nom du serveur"); clear_field(); key("bad_name!"); key(ENTER)
wait_for(r"is not a valid hostname"); no_french("nom invalide"); key(ENTER)
wait_for(r"Server name"); clear_field(); key("ai-prod-01"); key(ENTER)
wait_for(r"Username \(console"); clear_field(); key("root"); key(ENTER)
wait_for(r"cannot be used"); no_french("compte refusé"); key(ENTER)
wait_for(r"Username \(console"); clear_field(); key("vti"); key(ENTER)
wait_for(r"Password for .vti."); assert "Active keyboard: fr" in text(); shot("en-02-password"); no_french("mot de passe"); key("short"); key(ENTER)
wait_for(r"at least 8 characters"); key(ENTER)
wait_for(r"Password for"); key("Ollama-2026!"); key(ENTER)
wait_for(r"Enter the password again"); key("Ollama-2026?"); key(ENTER)
wait_for(r"do not match"); ok("confirmation différente : « The two entries do not match. »"); key(ENTER)
wait_for(r"Password for"); key("Ollama-2026!"); key(ENTER)
wait_for(r"Enter the password again"); key("Ollama-2026!"); key(ENTER)
wait_for(r"Check the configuration before applying it"); shot("en-03-summary"); assert "192.168.10.50/24" in text() and "Username     : vti" in text(); no_french("récapitulatif"); key(ENTER, 1)
wait_for(r"OllamaBuntu is ready", 60); shot("en-04-ready"); assert "Web administration : https://" in text(); no_french("écran final"); ok("configuration appliquée, écran final en anglais")
key(ENTER, 1); child.expect(pexpect.EOF, timeout=10); child.close()
