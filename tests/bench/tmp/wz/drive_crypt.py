#!/usr/bin/env python3
"""Pilote l'assistant OllamaBuntu au clavier et vérifie chaque écran."""
import pexpect, pyte, time, sys, re
from PIL import Image, ImageDraw, ImageFont
COLS, ROWS = 80, 25
screen = pyte.Screen(COLS, ROWS); stream = pyte.ByteStream(screen)
cmd = ("chroot /tmp/target /usr/bin/env -i TERM=linux LANG=C.UTF-8 OB_DRYRUN=1 OB_CRYPT_DEV=/tmp/crypt/disk.img OB_CRYPT_STATE=/tmp/crypt/state OB_CRYPT_LOG=/tmp/crypt/c.log OB_CRYPT_NO_INITRAMFS=1 OB_CRYPT_PBKDF_ARGS=\"--pbkdf pbkdf2 --pbkdf-force-iterations 1000\" "
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

# ------------------------------------------------------------ scénario : disque chiffré, sans TPM
import subprocess, os
NEWP = "phrase de demarrage 2026"; KEYRE = re.compile(r"([A-Z2-7]{6}-){8}[A-Z2-7]{4}")
def opens(secret): return subprocess.run(["cryptsetup", "open", "--test-passphrase", "--key-file=-", "/tmp/target/tmp/crypt/disk.img"], input=secret.encode(), capture_output=True).returncode == 0
wait_for(r"Langue / Language"); key(ENTER)
wait_for(r"O L L A M A B U N T U"); key(ENTER)
wait_for(r"Disque chiffré"); wait_for(r"pas de TPM utilisable"); shot("c-01-phrase"); ok("sans TPM : l'assistant explique que la phrase de passe sera demandée à chaque démarrage"); key(ENTER)
wait_for(r"Nouvelle phrase de passe"); key("court"); key(ENTER); wait_for(r"Saisissez-la à nouveau"); key("court"); key(ENTER)
wait_for(r"Phrase trop courte"); ok("phrase de moins de 12 caractères refusée"); key(ENTER)
wait_for(r"Nouvelle phrase de passe"); key(NEWP); key(ENTER); wait_for(r"Saisissez-la à nouveau"); key("une autre phrase longue"); key(ENTER)
wait_for(r"pas identiques"); ok("deux saisies différentes refusées"); key(ENTER)
wait_for(r"Nouvelle phrase de passe"); key(NEWP); key(ENTER); wait_for(r"Saisissez-la à nouveau"); key(NEWP); key(ENTER)
wait_for(r"Clé de récupération du disque"); wait_for(r"HORS de ce serveur"); t = text(); REC = KEYRE.search(t).group(0); shot("c-02-cle"); ok("clé de récupération affichée : %s" % REC); key(ENTER)
wait_for(r"Avez-vous enregistré cette clé"); key("\t"); key(ENTER)
wait_for(r"Clé de récupération du disque"); REC2 = KEYRE.search(text()).group(0); assert REC2 == REC, "clé différente"; ok("« Non, la réafficher » : la même clé est présentée de nouveau"); key(ENTER)
wait_for(r"Avez-vous enregistré cette clé"); key(ENTER)
wait_for(r"Carte réseau utilisée"); ok("après confirmation, l'assistant continue (réseau)")
assert opens(NEWP) and opens(REC) and not opens("TEMP-installation-ISO-9fK2"); ok("sur le volume : la phrase choisie et la clé de récupération ouvrent ; la phrase provisoire de l'ISO est morte")
assert not os.path.exists("/tmp/target/tmp/crypt/state/recovery.key"); ok("copie locale de la clé de récupération effacée après confirmation")
child.terminate(force=True)
