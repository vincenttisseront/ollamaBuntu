import gzip, hashlib, os, re, subprocess, sys
dest, mirror, code, keyring, wanted = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3], sys.argv[4], sys.argv[5:]
def get(url, path):
    r = subprocess.run(["curl", "-fsSL", "--retry", "4", "--connect-timeout", "20", "-o", path, url])
    if r.returncode: sys.exit("téléchargement impossible : %s (code curl %d)" % (url, r.returncode))
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()
def vercmp(a, b):
    """Comparaison de versions Debian (même algorithme que dpkg --compare-versions)."""
    def split(v):
        ep, _, rest = v.partition(":") if ":" in v else ("0", "", v)
        up, rev = rest.rsplit("-", 1) if "-" in rest else (rest, "0")
        return int(ep or 0), up, rev
    def order(c):
        return 0 if c.isdigit() else ord(c) if c.isalpha() else -1 if c == "~" else ord(c) + 256
    def part(x, y):
        while x or y:
            nx, ny = re.match(r"\D*", x).group(), re.match(r"\D*", y).group()
            for i in range(max(len(nx), len(ny))):
                cx, cy = (order(nx[i]) if i < len(nx) else 0), (order(ny[i]) if i < len(ny) else 0)
                if cx != cy:
                    return (cx > cy) - (cx < cy)
            x, y = x[len(nx):], y[len(ny):]
            dx, dy = re.match(r"\d*", x).group(), re.match(r"\d*", y).group()
            if int(dx or 0) != int(dy or 0):
                return (int(dx or 0) > int(dy or 0)) - (int(dx or 0) < int(dy or 0))
            x, y = x[len(dx):], y[len(dy):]
        return 0
    ea, ua, ra = split(a); eb, ub, rb = split(b)
    return (ea > eb) - (ea < eb) or part(ua, ub) or part(ra, rb)
found = {}
comps = os.environ.get("OB_COMPONENTS", "main").split()
for pocket in (code, code + "-updates", code + "-security"):
    rel = os.path.join(dest, pocket + ".InRelease"); get("%s/dists/%s/InRelease" % (mirror, pocket), rel)
    v = subprocess.run(["gpgv", "--keyring", keyring, rel], capture_output=True, text=True)
    if v.returncode: sys.exit("signature InRelease invalide pour %s : %s" % (pocket, v.stderr.strip()[:200]))
    text = open(rel, encoding="utf-8", errors="replace").read()
    for comp in comps:
        m = re.search(r"^ ([0-9a-f]{64})\s+\d+\s+%s/binary-amd64/Packages\.gz$" % comp, text.split("SHA256:", 1)[1], re.M)
        if not m: sys.exit("index %s/binary-amd64 absent de %s" % (comp, pocket))
        pk = os.path.join(dest, "%s.%s.Packages.gz" % (pocket, comp)); get("%s/dists/%s/%s/binary-amd64/Packages.gz" % (mirror, pocket, comp), pk)
        if sha256(pk) != m.group(1): sys.exit("empreinte de l'index incorrecte pour %s/%s" % (pocket, comp))
        for block in gzip.open(pk, "rt", encoding="utf-8", errors="replace").read().split("\n\n"):
            f = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", block, re.M))
            if f.get("Package") in wanted and f.get("Architecture") in ("amd64", "all"):
                if f["Package"] not in found or vercmp(f["Version"], found[f["Package"]]["Version"]) > 0:
                    found[f["Package"]] = f   # version la plus récente toutes poches confondues
missing = [w for w in wanted if w not in found]
if missing: sys.exit("paquets introuvables : %s" % " ".join(missing))
keep = []
for name, f in found.items():
    path = os.path.join(dest, os.path.basename(f["Filename"]))
    keep.append(os.path.basename(path))
    if not (os.path.exists(path) and sha256(path) == f["SHA256"]):
        get("%s/%s" % (mirror, f["Filename"]), path + ".part")
        if sha256(path + ".part") != f["SHA256"]: sys.exit("empreinte incorrecte : %s" % name)
        os.replace(path + ".part", path)
    print("    %-22s %s" % (name, f["Version"]))
for old in os.listdir(dest):   # versions périmées d'un build précédent
    if old.endswith(".deb") and old not in keep:
        os.remove(os.path.join(dest, old))
open(os.path.join(dest, "selection.txt"), "w").write("\n".join(sorted(keep)) + "\n")
