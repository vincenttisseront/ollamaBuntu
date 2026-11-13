#!/usr/bin/env python3
"""Base de documents plus rapide : recherche grossière puis exacte, classement hybride (mots de la question), embeddings sur processeur,
mémoire des questions, reprise des vecteurs déjà calculés, mesure de ce que la recherche rapide perd."""
import http.server, json, os, random, shutil, sys, tempfile, threading, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import rag
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m), flush=True)
    if not c: sys.exit(1)
tmp = tempfile.mkdtemp()
rnd = random.Random(7)

# ------------------------------------------------------------------ réglages
c = rag.config_clean({})
ok(c["hybrid"] is False and c["fast"] is False and c["embed_cpu"] is False, "options désactivées par défaut (le comportement d'avant ne change pas)")
c2 = rag.config_clean({"hybrid": True, "fast": True, "embed_cpu": True, "top_k": 3}, c)
ok(c2["hybrid"] is True and c2["fast"] is True and c2["embed_cpu"] is True and c2["top_k"] == 3 and rag.config_clean({"fast": "oui"}, c2)["fast"] is False, "options validées : seul « vrai » active")
old = {k: v for k, v in rag.DEFAULTS.items() if k not in ("hybrid", "fast", "embed_cpu")}
ok(rag.config_clean({}, old)["fast"] is False, "ancien fichier de réglages sans les nouvelles clés : valeurs par défaut")

# ------------------------------------------------------------------ mots de la question
ok(rag.query_terms("Quelle est la procédure de congés payés ?") == ["proce", "conge", "payes"], "mots utiles : sans mots vides ni accents, réduits à 5 lettres")
ok(rag.query_terms("The VPN-client for the 2FA") == ["vpn-c", "2fa"], "mots anglais et sigles")
tx = ["La procédure des congés payés est décrite ici.", "Le règlement intérieur de la société.", "Congés : voir la procédure.", ""]
ls = rag.lexical_scores("procédure congés payés", tx)
ok(ls[0] == max(ls) and ls[0] > ls[2] > ls[1] == 0 and ls[3] == 0, "part des mots retrouvés : le texte qui les contient tous passe devant")
ok(rag.lexical_scores("", tx) == [0.0] * 4 and rag.lexical_scores("le la les", tx) == [0.0] * 4 and rag.lexical_scores("congés", []) == [], "question vide ou sans mot utile : aucun effet")
rare = rag.lexical_scores("alpha beta", ["alpha beta", "alpha", "beta", "alpha x", "alpha y", "alpha z"])
ok(rare[2] > rare[1], "un mot rare pèse plus qu'un mot qu'on retrouve partout")
ok(rag.coarse_dims(768) == 128 and rag.coarse_dims(1024) == 168 and rag.coarse_dims(200) == 0 and rag.coarse_dims(384) == 64, "longueur du premier tri : un sixième des valeurs, au moins 64 ; aucun tri grossier sous 256 valeurs")

# ------------------------------------------------------------------ jeu de vecteurs : début du vecteur informatif (comme les modèles « matriochka ») ou non
DIM = 384
def unit(v):
    nn = sum(x * x for x in v) ** 0.5
    return [x / nn for x in v]
def make_store(root, structured, count=900, docs=3, model="nomic-embed-text", texts=None):
    s = rag.Store(root); vecs_all = []
    per = count // docs
    for d in range(docs):
        chunks, vecs = [], []
        for i in range(per):
            scale = [1.0 / (1 + j / 16.0) ** 2 for j in range(DIM)] if structured else [1.0] * DIM
            v = unit([rnd.gauss(0, 1) * scale[j] for j in range(DIM)])
            vecs.append(v); chunks.append({"t": (texts[d * per + i] if texts else "texte %d-%d" % (d, i)), "p": i // 10 + 1, "h": ""})
        s.save({"id": "%012x" % (d + 1), "name": "doc%d.txt" % d, "collection": "RH" if d % 2 == 0 else "IT", "model": model, "dim": DIM, "chunks": per, "size": 1, "sha": "x", "added": d}, chunks, vecs)
        vecs_all += vecs
    return s, vecs_all
good, gv = make_store(os.path.join(tmp, "good"), True)
bad, bv = make_store(os.path.join(tmp, "bad"), False)
def brute(vecs, q, k):
    sc = sorted(((sum(a * b for a, b in zip(q, v)), i) for i, v in enumerate(vecs)), reverse=True)
    return [i for _, i in sc[:k]]
def where(hit): return (int(hit["doc"], 16) - 1) * 300 + hit["chunk"]
q = unit([x + rnd.gauss(0, 0.05) * 0 for x in gv[123]])
st = {}
hits, stale = good.search(q, [], 5, 0.0, "nomic-embed-text", stats=st)
ok([where(h) for h in hits] == brute(gv, q, 5) and stale == 0 and st["mode"] == "exact" and st["chunks"] == 900 and st["coarse_dims"] == 0, "recherche exacte : mêmes résultats qu'un calcul direct, statistiques du mode")
ok(hits[0]["chunk"] == 123 % 300 and abs(hits[0]["score"] - 1.0) < 1e-3, "l'extrait cherché arrive premier avec un score de 1")
st = {}
fh, _ = good.search(q, [], 5, 0.0, "nomic-embed-text", fast=True, stats=st)
ok(st["mode"] == "rapide" and st["coarse_dims"] == 64 and st["chunks"] == 900 and st["candidates"] <= 200 and [where(h) for h in fh][0] == 123, "recherche rapide : premier tri sur 64 valeurs, au plus 200 candidats recalculés")
# rappel sur des vecteurs structurés : on garde presque tous les bons résultats ; sur des vecteurs sans structure, on en perd
def recall(store, vecs, trials=25):
    got = tot = 0
    for t in range(trials):
        qv = unit([x + rnd.gauss(0, 0.002) for x in vecs[rnd.randrange(len(vecs))]])
        ex = {where(h) for h in store.search(qv, [], 5, 0.0, "nomic-embed-text")[0]}
        fa = {where(h) for h in store.search(qv, [], 5, 0.0, "nomic-embed-text", fast=True)[0]}
        got, tot = got + len(ex & fa), tot + len(ex)
    return got / tot
rg, rb = recall(good, gv), recall(bad, bv)
ok(rg >= 0.9 and rb < rg, "rappel de la recherche rapide : élevé quand le début du vecteur est informatif (%.2f), plus faible sinon (%.2f)" % (rg, rb))
# filtre de score minimal et de bases, comme avant
q2 = unit([rnd.gauss(0, 1) for _ in range(DIM)])
ok(good.search(q2, [], 5, 0.95, "nomic-embed-text")[0] == [] and good.search(q2, [], 5, 0.95, "nomic-embed-text", fast=True)[0] == [], "score minimal : rien en dessous, en exact comme en rapide")
only_rh = good.search(q, ["RH"], 50, 0.0, "nomic-embed-text", fast=True)[0]
ok(only_rh and all(h["collection"] == "RH" for h in only_rh) and good.search(q, [], 3, 0.0, "autre-modele")[1] == 3, "bases demandées respectées ; documents d'un autre modèle ignorés et comptés")
ok(len(good.search(q, ["IT"], 5, 0.0, "nomic-embed-text", allowed=["RH"], fast=True)[0]) == 0, "droits d'accès : une base non autorisée n'est jamais parcourue")

# ------------------------------------------------------------------ mesure de ce que la recherche rapide perd
r = good.recall_check("nomic-embed-text", samples=6)
ok(r["ok"] and r["recall"] >= 0.8 and r["samples"] == 6 and r["chunks"] == 900 and r["coarse_dims"] == 64 and r["exact_ms"] >= 0 and r["fast_ms"] >= 0, "mesure du rappel : %s %% sur %d questions (exact %d ms, rapide %d ms)" % (round(100 * r["recall"]), r["samples"], r["exact_ms"], r["fast_ms"]))
rb2 = bad.recall_check("nomic-embed-text", samples=6)
ok(rb2["ok"] and rb2["recall"] < r["recall"], "base à vecteurs sans structure : rappel plus faible, donc le conseil de ne pas activer est chiffré")
small, _ = make_store(os.path.join(tmp, "small"), True, count=90, docs=3)
ok(small.recall_check("nomic-embed-text")["ok"] is False and "moins de 200" in small.recall_check("nomic-embed-text")["reason"] and good.recall_check("absent")["ok"] is False, "base trop petite ou modèle sans document : pas de mesure, raison claire")
clock = iter(x * 30.0 for x in range(100))
r3 = good.recall_check("nomic-embed-text", samples=10, budget=20.0, clock=lambda: next(clock))
ok(r3["ok"] and r3["samples"] == 1, "temps limité : la mesure s'arrête, au moins une question est traitée")

# ------------------------------------------------------------------ classement hybride
words = ["congés payés procédure", "règlement intérieur société", "factures fournisseurs comptabilité", "sauvegarde serveur nuit"]
texts = [words[i % 4] + " numéro %d" % i for i in range(300)]
hy, hv = make_store(os.path.join(tmp, "hyb"), True, count=300, docs=1, texts=texts)
base = hv[0]
qv = unit([x + rnd.gauss(0, 0.001) for x in hv[10]])
no_h = hy.search(qv, [], 5, 0.0, "nomic-embed-text")[0]
yes_h = hy.search(qv, [], 5, 0.0, "nomic-embed-text", question="procédure congés payés", hybrid=True)[0]
ok(len(yes_h) == 5 and "lex" in yes_h[0] and yes_h[0]["score"] <= 1.0 and all("lex" not in h for h in no_h), "hybride : champ « lex » ajouté, score affiché inchangé (cosinus), sans option rien ne change")
# la requête vectorielle est exactement équidistante des extraits 40 et 41 (moyenne de deux vecteurs unitaires) ; les mots de la question tranchent
tie = unit([a + b for a, b in zip(hv[40], hv[41])])
t = hy._load("000000000001")["chunks"]
ok("congés" in t[40]["t"] and "règlement" in t[41]["t"], "jeu de textes : l'extrait 40 parle de congés, le 41 du règlement")
def order(question):
    r = [h["chunk"] for h in hy.search(tie, [], 12, 0.0, "nomic-embed-text", question=question, hybrid=True)[0]]
    return r.index(40) < r.index(41)
ok(order("procédure congés payés") is True and order("règlement intérieur société") is False, "à cosinus égal (40 et 41), l'extrait qui contient les mots de la question passe devant, dans les deux sens")
ok(len({h["score"] for h in hy.search(tie, [], 12, 0.0, "nomic-embed-text", question="règlement intérieur société", hybrid=True)[0] if h["chunk"] in (40, 41)}) == 1, "…et les scores affichés restent ceux du cosinus")
ok(hy.search(qv, [], 5, 0.0, "nomic-embed-text", question="", hybrid=True)[0] == no_h, "question vide : le classement hybride ne change rien")

# ------------------------------------------------------------------ embeddings : processeur, mémoire des questions
BODIES = []
class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        BODIES.append(d)
        out = json.dumps({"embeddings": [[1.0 + len(t) % 3, 2.0, 2.0] for t in d["input"]]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
addr = "127.0.0.1:%d" % srv.server_address[1]
rag.embed(addr, "nomic-embed-text", ["a"]); rag.embed(addr, "nomic-embed-text", ["a"], cpu=True)
ok("options" not in BODIES[0] and BODIES[1]["options"] == {"num_gpu": 0}, "embeddings sur le processeur : num_gpu 0 transmis, sinon rien de plus qu'avant")
BODIES.clear(); rag._qcache.clear()
v1 = rag.embed_query(addr, "nomic-embed-text", "ma question")
v2 = rag.embed_query(addr, "nomic-embed-text", "ma question")
ok(v1 == v2 and len(BODIES) == 1 and abs(sum(x * x for x in v1) - 1) < 1e-6, "même question reposée : un seul calcul, vecteur normalisé")
rag.embed_query(addr, "nomic-embed-text", "ma question", cpu=True); rag.embed_query(addr, "autre-modele", "ma question"); rag.embed_query(addr, "nomic-embed-text", "autre question")
ok(len(BODIES) == 4, "le cache distingue processeur/carte, modèle et texte")
rag.embed_query(addr, "nomic-embed-text", "ma question", now=time.time() + rag.QCACHE_TTL + 5)
ok(len(BODIES) == 5, "au bout de 10 minutes la question est recalculée")
v1[0] = 99.0
ok(rag.embed_query(addr, "nomic-embed-text", "autre question")[0] != 99.0 and len(BODIES) == 5, "le vecteur rendu est une copie : le modifier n'abîme pas la mémoire")
for i in range(rag.QCACHE_MAX + 10): rag.embed_query(addr, "nomic-embed-text", "q%d" % i)
ok(len(rag._qcache) <= rag.QCACHE_MAX, "mémoire des questions bornée")

# ------------------------------------------------------------------ reprise de vecteurs déjà calculés
rs, rv = make_store(os.path.join(tmp, "reuse"), True, count=60, docs=2, texts=["extrait %d" % i for i in range(60)])
got = rs.reusable("nomic-embed-text", ["extrait 3", "extrait 45", "tout neuf", "extrait 3"])
ok(got[0] is not None and len(got[0]) == DIM and got[1] is not None and got[2] is None and got[3] == got[0], "textes identiques : vecteur repris ; texte nouveau : à calculer")
ok(all(abs(a - b) < 1e-6 for a, b in zip(got[0], rv[3])) and all(abs(a - b) < 1e-6 for a, b in zip(got[1], rv[45])), "…et c'est bien le vecteur de l'extrait d'origine")
ok(rs.reusable("autre-modele", ["extrait 3"]) == [None] and rs.reusable("nomic-embed-text", []) == [], "autre modèle d'embeddings : rien n'est repris")

shutil.rmtree(tmp, ignore_errors=True)
print("\n%d vérifications réussies" % n)
