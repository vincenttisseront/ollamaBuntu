#!/usr/bin/env python3
"""Assemble le catalogue anglais de l'appliance à partir des fichiers cat_*.py de ce dossier.

Le français est la langue source ; chaque cat_*.py déclare E (phrases exactes) et P (modèles à variables {1}...).
Le résultat est le fichier src/rootfs/usr/local/lib/ollamabuntu/admin/web/i18n/en.json, utilisé par la console web,
l'assistant, le menu console, la bannière, le menu de démarrage et les messages de construction.

  python3 tools/i18n/build_catalog.py           régénère en.json
  python3 tools/i18n/build_catalog.py --check   échoue si en.json n'est pas à jour (contrôle avant de pousser)
"""
import glob, json, os, re, runpy, sys
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu", "admin", "web", "i18n", "en.json")
exact, patterns = {}, []
for f in sorted(glob.glob(os.path.join(HERE, "cat_*.py"))):
    ns = runpy.run_path(f)
    for k, v in ns.get("E", {}).items():
        if k in exact and exact[k] != v: raise SystemExit("traduction en double et différente : %r (%s)" % (k, f))
        exact[" ".join(k.split())] = v.lstrip(" ")
    for p, out in ns.get("P", []):
        p = re.sub(r" {2,}", " ", p).lstrip(" ")   # comme les textes, normalisés avant recherche
        re.compile("^" + p + "$"); patterns.append([p, out.lstrip(" ")])
text = json.dumps({"exact": exact, "patterns": patterns}, ensure_ascii=False, indent=0, sort_keys=True) + "\n"
if "--check" in sys.argv:
    cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
    if cur != text: raise SystemExit("en.json n'est pas à jour : lancez python3 tools/i18n/build_catalog.py")
    print("catalogue à jour : %d phrases, %d modèles" % (len(exact), len(patterns))); sys.exit(0)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write(text)
print("catalogue : %d phrases, %d modèles" % (len(exact), len(patterns)))
