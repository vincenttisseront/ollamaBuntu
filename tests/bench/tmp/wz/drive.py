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

# ------------------------------------------------------------ scénario
wait_for(r"Langue / Language"); ok("choix de la langue : « Français » par défaut"); key(ENTER)
wait_for(r"O L L A M A B U N T U"); shot("01-bienvenue"); ok("écran d'accueil + logo"); key(ENTER)
wait_for(r"Carte réseau utilisée"); shot("02-interface"); ok("choix de la carte réseau (" + ("eth0 listée" if "eth0" in text() else "?") + ")"); key(ENTER)
wait_for(r"Comment la carte"); key(DOWN); key(ENTER); ok("adressage : statique")
wait_for(r"format CIDR"); key("192.168.10.50", 0.3); key(ENTER)
wait_for(r"n'est pas une adresse IPv4 valide"); ok("adresse sans masque refusée"); key(ENTER)
wait_for(r"format CIDR"); clear_field(); key("192.168.10.50/24", 0.3); key(ENTER)
wait_for(r"Passerelle par défaut"); assert "192.168.10.1" in text(); ok("passerelle pré-remplie 192.168.10.1"); clear_field(); key("10.0.0.1"); key(ENTER)
wait_for(r"doit être une adresse du réseau 192.168.10.0/24"); ok("passerelle hors réseau refusée"); key(ENTER)
wait_for(r"Passerelle par défaut"); clear_field(); key("192.168.10.254"); key(ENTER)
wait_for(r"Serveurs DNS"); clear_field(); key("192.168.10.53, 1.1.1.1"); key(ENTER); ok("DNS saisis")
wait_for(r"Nom du serveur"); clear_field(); key("mauvais_nom!"); key(ENTER)
wait_for(r"n'est pas un nom de machine valide"); ok("nom de machine invalide refusé"); key(ENTER)
wait_for(r"Nom du serveur"); clear_field(); key("IA-Prod-01.ibanfirst.local"); key(ENTER)
wait_for(r"Identifiant \(console"); clear_field(); key("root"); key(ENTER)
wait_for(r"ne peut pas être utilisé"); ok("compte système « root » refusé"); key(ENTER)
wait_for(r"Identifiant \(console"); clear_field(); key("vti"); key(ENTER)
wait_for(r"Mot de passe de « vti »"); assert "Clavier actif : fr" in text(); shot("03-mot-de-passe"); ok("clavier affiché : fr"); key("court"); key(ENTER)
wait_for(r"au moins 8 caractères"); ok("mot de passe trop court refusé"); key(ENTER)
wait_for(r"Mot de passe de"); key("Ollama-2026!"); key(ENTER)
wait_for(r"Saisissez à nouveau"); key("Ollama-2026?"); key(ENTER)
wait_for(r"pas identiques"); ok("confirmation différente refusée"); key(ENTER)
wait_for(r"Mot de passe de"); key("Ollama-2026!"); key(ENTER)
wait_for(r"Saisissez à nouveau"); key("Ollama-2026!"); key(ENTER)
wait_for(r"Vérifiez la configuration"); shot("04-recapitulatif")
assert "ia-prod-01.ibanfirst.local" in text() and "192.168.10.50/24" in text(); ok("récapitulatif correct (nom converti en minuscules)")
key(ENTER, 1)
wait_for(r"OllamaBuntu est prêt", 60); shot("05-termine"); ok("configuration appliquée, écran final")
print("\n".join(l.rstrip() for l in screen.display if l.strip()))
key(ENTER, 1); child.expect(pexpect.EOF, timeout=10); child.close()
print("code de sortie de l'assistant :", child.exitstatus)
