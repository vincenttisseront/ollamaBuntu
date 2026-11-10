#!/usr/bin/env python3
"""OllamaBuntu - traduction des textes affichés hors console web (assistant, menu,
bannière, menu de démarrage). Même catalogue et même méthode que la console web :
phrase exacte, puis modèle à variables ({1}...), puis phrase par phrase ; ligne par
ligne pour les textes multi-lignes (retours réels ou « \\n » interprétés par whiptail).

  i18n.py LANGUE ARGUMENT...      arguments traduits, séparés par des octets nuls
  i18n.py --file LANGUE FICHIER   fichier traduit ligne par ligne (bannière /etc/issue)
  i18n.py --grub LANGUE FICHIER   titres des « menuentry » traduits (grub.cfg)
"""
import json
import os
import re
import sys

DIR = os.environ.get("OB_I18N_DIR", "/usr/local/lib/ollamabuntu/admin/web/i18n")
SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ý«(])")


class Catalog:
    def __init__(self, lang):
        self.exact, self.patterns = {}, []
        if lang == "fr":
            return
        try:
            with open(os.path.join(DIR, lang + ".json"), encoding="utf-8") as f:
                cat = json.load(f)
        except (OSError, ValueError):
            return
        self.exact = cat.get("exact", {})
        self.patterns = [(re.compile("^" + p + "$"), out) for p, out in cat.get("patterns", [])]

    def lookup(self, k):
        if k in self.exact:
            return self.exact[k]
        for rx, out in self.patterns:
            m = rx.match(k)
            if m:
                def val(g):
                    v = m.group(int(g.group(1))) or ""
                    t = self.lookup(v) if v and v != k else None   # valeur traduite si elle est connue
                    return t if t is not None else v
                return re.sub(r"\{(\d)\}", val, out)
        return None

    def line(self, s):
        key = " ".join(s.split())
        if not key or not re.search(r"[A-Za-zÀ-ÿ]", key):
            return s
        raw = s.strip()
        out = self.lookup(raw) if raw != key else None   # texte tel quel d'abord : l'alignement capturé est conservé
        if out is None:
            out = self.lookup(key)
        if out is None:
            parts = SPLIT.split(key)
            if len(parts) > 1:
                tp = [self.lookup(p) for p in parts]
                if any(x is not None for x in tp):
                    out = " ".join(t if t is not None else p for p, t in zip(parts, tp))
        if out is None:
            return s
        return re.match(r"^\s*", s).group(0) + out + re.search(r"\s*$", s).group(0)

    def text(self, s, literal_newlines=True):
        if not self.exact:
            return s
        # sépare sur les retours réels et, pour whiptail, les « \n » littéraux (séparateurs conservés) ;
        # dans un fichier (bannière agetty), « \n » est un code d'agetty et non un retour à la ligne
        pieces = re.split(r"(\n|\\n)" if literal_newlines else r"(\n)", s)
        return "".join(p if p in ("\n", "\\n") else self.line(p) for p in pieces)


def main(argv):
    if len(argv) >= 3 and argv[0] in ("--file", "--grub"):
        cat = Catalog(argv[1])
        with open(argv[2], encoding="utf-8") as f:
            src = f.read()
        if argv[0] == "--file":
            sys.stdout.write(cat.text(src, literal_newlines=False))
        else:
            sys.stdout.write(re.sub(r'(menuentry ")([^"]*)(")', lambda m: m.group(1) + cat.line(m.group(2)) + m.group(3), src))
        return 0
    if not argv:
        print(__doc__)
        return 2
    cat = Catalog(argv[0])
    sys.stdout.write("\0".join(cat.text(a) for a in argv[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
