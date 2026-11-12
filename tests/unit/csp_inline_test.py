"""Garde-fou CSP : la console sert « style-src 'self' », donc aucun attribut style="" ne doit
exister (HTML, chaînes JS) ; le style dynamique passe par le CSSOM (element.style)."""
import re, sys, pathlib
W = pathlib.Path(__file__).resolve().parents[2] / "src/rootfs/usr/local/lib/ollamabuntu/admin/web"
ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name)
    ok = ok and cond
html = (W / "index.html").read_text(encoding="utf-8")
js = (W / "app.js").read_text(encoding="utf-8")
check("index.html : aucun attribut style=", not re.search(r'\sstyle\s*=', html))
check("index.html : aucun <style> intégré", "<style" not in html)
check("app.js : aucun style= dans une chaîne", not re.search(r'style\s*=\s*[\\"\'`]', js))
check("app.js : pas de setAttribute('style')", not re.search(r"setAttribute\(\s*['\"]style", js))
check("app.js : el() applique style via cssText", "k === 'style') e.style.cssText" in js)
sys.exit(0 if ok else 1)
