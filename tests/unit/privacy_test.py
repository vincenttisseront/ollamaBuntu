#!/usr/bin/env python3
"""Confidentialité : détection et masquage des données sensibles, anonymisation avant le modèle, termes interdits (globaux et par clé),
de bout en bout avec un faux Ollama. Données de test synthétiques (aucun vrai numéro)."""
import http.client, http.server, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
tmp = tempfile.mkdtemp()
os.environ.update(OB_ETC=tmp, OB_ROUTER_USAGE=os.path.join(tmp, "usage.json"), OB_ROUTER_LIMITS=os.path.join(tmp, "limits.json"), OB_ROUTER_REQLOG=os.path.join(tmp, "requests.jsonl"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "rootfs", "usr", "local", "lib", "ollamabuntu"))
import privacy, router
n = 0
def ok(c, m):
    global n; n += 1; print("[%02d] %s - %s" % (n, "OK  " if c else "ÉCHEC", m))
    if not c: sys.exit(1)
def raises(f, *a):
    try: f(*a)
    except ValueError: return True
    return False

# ------------------------------------------------------------------ détection
M = lambda t, cats=privacy.DEFAULT_ON: privacy.mask_text(t, cats)
t, c = M("Mon IBAN FR76 3000 6000 0112 3456 7890 189 et ma carte 4970 1012 3456 7890")
ok("[IBAN]" in t and "[numéro]" in t and "FR76" not in t and "4970" not in t and c == {"iban", "number"}, "IBAN et numéro de carte masqués, catégories signalées")
t, c = M("Ma sécu : 1 85 05 78 006 084 36, appelez le 06 12 34 56 78 ou le +33 6 12 34 56 78 ou +1 415 555 0100")
ok(t.count("[n° sécu]") == 1 and t.count("[téléphone]") == 3 and c == {"nir", "phone"}, "numéro de sécurité sociale et téléphones (France et international) masqués")
t, c = M("écrire à marie.dupont@exemple.fr, serveur 192.168.1.20")
ok("[e-mail]" in t and "192.168.1.20" in t and c == {"email"}, "e-mail masqué ; l'adresse IP ne l'est pas par défaut")
t, c = M("écrire à marie.dupont@exemple.fr, serveur 192.168.1.20", privacy.DEFAULT_ON + ("ip",))
ok("[IP]" in t and "192.168.1.20" not in t, "adresse IP masquée quand la catégorie est activée")
ok(M("version 1.2.3.4.5 et 999.1.1.1")[0] == "version 1.2.3.4.5 et 999.1.1.1", "numéros de version et adresses impossibles non pris pour des IP")
t, c = M("Authorization: Bearer abcdefghijklmnop12345 et la clé sk-abcdefghijklmnopqrstuv, mot de passe : Zx9!vq2L")
ok(t.count("[jeton]") == 1 and "[clé]" in t and "[secret]" in t and "Zx9" not in t and c == {"secret"}, "jeton, clé d'API et mot de passe annoncé masqués")
t, c = privacy.mask_text("a@b.fr 06 12 34 56 78 FR76 3000 6000 0112 3456 7890 189", ())
ok(t == "a@b.fr 06 12 34 56 78 FR76 3000 6000 0112 3456 7890 189" and c == set(), "catégories vides : rien n'est masqué hors secrets")
t, c = privacy.mask_text("a@b.fr 06 12 34 56 78 sk-abcdefghijklmnopqrstuv", ())
ok(t == "a@b.fr 06 12 34 56 78 [clé]" and c == {"secret"}, "les secrets ne peuvent pas être désactivés")
ok(M("Rendez-vous le 12/03/2026 à 14h30, facture 2026-0042, 3 chats")[0] == "Rendez-vous le 12/03/2026 à 14h30, facture 2026-0042, 3 chats", "dates, numéros de facture courts et chiffres usuels non masqués")

# ------------------------------------------------------------------ extraits
ex = privacy.excerpt_text("Bonjour,   voici mon e-mail jean@exemple.fr et mon IBAN FR7630006000011234567890189, merci beaucoup de votre aide précieuse", privacy.DEFAULT_ON, 60)
ok(ex.endswith("…") and "@" not in ex and "FR76" not in ex and len(ex) <= 60 and "  " not in ex, "extrait : normalisé, masqué avant la coupe, borné")
ex = privacy.excerpt_text("mon e-mail jean@exemple.fr", [c for c in privacy.DEFAULT_ON if c != "email"], 80)
ok("jean@exemple.fr" in ex, "catégorie désactivée : l'extrait garde l'adresse")
ok(privacy.excerpt_text("sk-abcdefghijklmnopqrstuv", [], 80) == "[clé]", "…mais jamais un secret")

# ------------------------------------------------------------------ réglages
d = privacy.default_config()
ok(d["categories"]["secret"] and d["categories"]["email"] and not d["categories"]["ip"] and d["anonymize"] is False and d["detect"] and d["words"] == [] and d["words_action"] == "block", "valeurs par défaut prudentes")
c = privacy.config_clean({"categories": {"secret": False, "ip": True, "email": False}, "anonymize": True, "words": "Projet Orion\nsalaire; Salaire , confidentiel", "words_action": "mask"})
ok(c["categories"]["secret"] is True and c["categories"]["ip"] and not c["categories"]["email"] and c["anonymize"] and c["words"] == ["Projet Orion", "salaire", "confidentiel"] and c["words_action"] == "mask", "validation : secret non désactivable, termes dédoublonnés (casse), action")
ok(privacy.config_clean({}, c) == c and privacy.config_clean({"anonymize": False}, c)["words"] == c["words"], "champs absents : valeurs actuelles conservées")
ok(raises(privacy.config_clean, {"words_action": "effacer"}) and raises(privacy.config_clean, {"words": ["x"]}) and raises(privacy.config_clean, {"words": ["a" * 61]}) and raises(privacy.config_clean, {"words": ["a<b"]}), "termes trop courts, trop longs ou avec < > : refusés")
ok(raises(privacy.config_clean, {"words": ["mot%03d" % i for i in range(201)]}) and not raises(privacy.config_clean, {"words": ["mot%03d" % i for i in range(200)]}), "200 termes au plus")
ok(privacy.config_clean({"categories": "oui", "anonymize": "x"})["anonymize"] is True and raises(privacy.words_clean, 5, 10), "types inattendus ne font pas planter (booléens), liste invalide refusée")

# ------------------------------------------------------------------ termes interdits
w = privacy.words_regex(["Projet Orion", "salaire", "café"])
f = lambda s: [m.group(0) for m in w.finditer(privacy.fold(s))]
ok(f("Le projet   ORION avance") == ["projet   orion"] and f("votre SALAIRE") == ["salaire"] and f("un CAFÉ et un cafe") == ["café".replace("é", "e"), "cafe"], "casse, accents et espaces multiples ignorés")
ok(f("les salaires augmentent") == [] and f("salarié") == [] and f("anti-salaire") == ["salaire"], "mot entier uniquement (« salaires », « salarié » ne correspondent pas)")
ok(len(privacy.fold("œuvre ÉCOLE ß")) == len("œuvre ÉCOLE ß"), "le pliage garde la longueur du texte (positions fiables)")
ok(privacy.words_regex([]) is None, "aucun terme : aucune expression")
body = json.dumps({"model": "m", "messages": [{"role": "system", "content": "tu es gentil"}, {"role": "user", "content": [{"type": "text", "text": "Quel est le salaire de Marie ? marie@exemple.fr"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}], "tools": [{"name": "salaire"}], "stream": False}).encode()
conf = privacy.config_clean({"anonymize": True, "words": ["salaire"], "words_action": "mask"})
nb, res = privacy.process(body, conf, conf["words"])
dd = json.loads(nb)
ok("▮▮▮" in dd["messages"][1]["content"][0]["text"] and "[e-mail]" in dd["messages"][1]["content"][0]["text"] and res.hits == ["salaire"] and res.cats == {"email"} and res.changed, "texte multi-parties : terme masqué, e-mail anonymisé, seulement dans le texte")
ok(dd["messages"][1]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}} and dd["tools"] == [{"name": "salaire"}] and dd["model"] == "m" and dd["stream"] is False, "images, outils et paramètres intacts")
nb, res = privacy.process(body, privacy.config_clean({"words": ["salaire"]}), ["salaire"])
ok(nb == body and res.hits == ["salaire"] and res.cats == {"email"} and not res.changed, "détection seule : corps inchangé octet pour octet, résultats signalés")
nb, res = privacy.process(b"pas du json", conf, ["x"]); ok(nb == b"pas du json" and not res.hits, "corps illisible : laissé tel quel")
nb, res = privacy.process(b"[1,2]", conf, ["x"]); ok(nb == b"[1,2]", "corps JSON qui n'est pas un objet : laissé tel quel")
for path, b, key in (("/api/generate", {"model": "m", "prompt": "mon IBAN FR7630006000011234567890189", "system": "salaire"}, "prompt"),
                     ("/api/embed", {"model": "m", "input": ["bonjour a@b.fr", "autre"]}, "input"),
                     ("/v1/completions", {"model": "m", "prompt": ["a@b.fr"]}, "prompt")):
    nb, res = privacy.process(json.dumps(b).encode(), conf, conf["words"])
    ok(res.cats and "@" not in json.dumps(json.loads(nb)[key]) and "FR76" not in nb.decode(), "format %s : texte anonymisé" % path)
big = json.dumps({"model": "m", "prompt": "x" * (privacy.MAX_SCAN + 10) + " a@b.fr"}).encode()
nb, res = privacy.process(big, conf, []); ok(res.truncated and b"a@b.fr" in nb, "demande énorme : examen borné (le reste n'est pas examiné)")
deep = {"model": "m", "messages": [{"content": "ok"}]}
cur = deep["messages"][0]
for _ in range(30): cur["content"] = [{"content": "a@b.fr"}]; cur = cur["content"][0]
nb, res = privacy.process(json.dumps(deep).encode(), conf, []); ok(nb, "imbrication excessive : pas d'erreur")

# ------------------------------------------------------------------ routeur de bout en bout
SEEN = []
class Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_POST(self):
        SEEN.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        raw = json.dumps({"response": "ok", "done": True, "prompt_eval_count": 5, "eval_count": 6, "eval_duration": 1000000000}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=up.serve_forever, daemon=True).start()
router.MAIN = "127.0.0.1:%d" % up.server_address[1]
KEY = {"id": "k1", "name": "RH", "words": []}
WHO = ["key"]
def fake_rights(self):
    if WHO[0] == "local": self._key = None; return None
    self._key = KEY; return ("RH", {"inference", "read"}, set(), "k1", set())
next(v for v in vars(router).values() if isinstance(v, type) and hasattr(v, "candidates")).rights = fake_rights
srv = router.make_server("127.0.0.1", 0, False, False); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
def call(prompt, path="/api/generate"):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    c.request("POST", path, json.dumps({"model": "m", "prompt": prompt, "stream": False}), {"Content-Type": "application/json"})
    r = c.getresponse(); body = r.read(); c.close(); return r.status, json.loads(body or b"{}")
def conf_write(d): open(os.path.join(tmp, "privacy.json"), "w").write(json.dumps(d)); os.utime(os.path.join(tmp, "privacy.json"), (time.time() + len(SEEN) + n, time.time() + len(SEEN) + n))
def logs():
    try: return [json.loads(l) for l in open(os.environ["OB_ROUTER_REQLOG"], encoding="utf-8")]
    except OSError: return []
P = "écris à marie@exemple.fr au sujet du salaire"
st, _ = call(P)
ok(st == 200 and json.loads(SEEN[-1])["prompt"] == P, "réglages par défaut : la demande part inchangée vers le modèle")
last = logs()[-1]
ok(last["pii"] == ["email"] and "masked" not in last and "prompt" not in last, "…mais le journal retient les catégories détectées (jamais le contenu) : pii=[email]")
st, _ = call("rien de sensible"); ok("pii" not in logs()[-1], "aucune donnée sensible : pas de champ « pii »")
conf_write({"detect": False}); st, _ = call(P)
ok(st == 200 and "pii" not in logs()[-1], "détection désactivée : aucune analyse, aucun champ")
conf_write({"anonymize": True}); st, _ = call(P)
sent = json.loads(SEEN[-1])["prompt"]
ok(st == 200 and sent == "écris à [e-mail] au sujet du salaire" and logs()[-1]["masked"] is True, "anonymisation : le modèle reçoit « [e-mail] », pas l'adresse")
conf_write({"anonymize": True, "categories": {"email": False}}); call(P)
ok(json.loads(SEEN[-1])["prompt"] == P, "catégorie e-mail désactivée : adresse conservée")
conf_write({"words": ["salaire"]}); n0 = len(SEEN); st, d = call(P)
ok(st == 403 and "terme interdit" in d["error"] and "« salaire »" in d["error"] and "RH" in d["error"] and len(SEEN) == n0, "terme interdit global : 403 explicite, le modèle n'est jamais appelé")
e = logs()[-1]
ok(e["blocked"] is True and e["status"] == 403 and e["client"] == "RH" and "salaire" not in json.dumps(e) and e["model"] == "m", "refus journalisé (client, modèle) sans reprendre le texte de la demande")
conf_write({"words": ["salaire"], "words_action": "mask"}); st, _ = call(P)
ok(st == 200 and json.loads(SEEN[-1])["prompt"] == "écris à marie@exemple.fr au sujet du ▮▮▮", "action « masquer » : le terme est remplacé, la demande continue")
conf_write({}); KEY["words"] = ["orion"]; n0 = len(SEEN)
st, d = call("point sur le projet Orion"); ok(st == 403 and "« Orion »" in d["error"] and len(SEEN) == n0, "terme propre à la clé : refusé pour cette clé")
st, _ = call(P); ok(st == 200, "…sans toucher aux autres demandes de la clé")
WHO[0] = "local"; st, _ = call("point sur le projet Orion"); ok(st == 200, "le terme d'une clé ne s'applique pas à l'accès local")
conf_write({"words": ["salaire"]}); st, d = call(P); ok(st == 403 and "« salaire »" in d["error"] and "local" in d["error"], "…mais les termes globaux s'appliquent à tous, accès local compris")
WHO[0] = "key"; KEY["words"] = []
conf_write({"words": ["salaire"]}); n0 = len(SEEN)
st, d = call("votre café", "/api/embed"); ok(st == 200, "demande sans terme interdit sur un autre point d'accès")
c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10); c.request("GET", "/api/tags"); r = c.getresponse(); r.read(); c.close()
ok(r.status != 403, "les demandes de consultation (hors inférence) ne sont pas examinées")
open(os.path.join(tmp, "privacy.json"), "w").write("{pas du json"); os.utime(os.path.join(tmp, "privacy.json"), (time.time() + 999, time.time() + 999))
ok(router.privacy_conf() == privacy.default_config(), "fichier de réglages corrompu : réglages par défaut (pas d'arrêt du routeur)")
open(os.path.join(tmp, "privacy.json"), "w").write(json.dumps({"words_action": "effacer"})); os.utime(os.path.join(tmp, "privacy.json"), (time.time() + 1999, time.time() + 1999))
ok(router.privacy_conf() == privacy.default_config(), "réglages invalides : réglages par défaut")
conf_write({"prompt_excerpt": True}); open(os.path.join(tmp, "request-log.json"), "w").write(json.dumps({"prompt_excerpt": True, "chars": 80}))
conf_write({"categories": {"email": False}}); st, _ = call("contact marie@exemple.fr clé sk-abcdefghijklmnopqrstuv")
ok(logs()[-1]["prompt"] == "contact marie@exemple.fr clé [clé]", "extrait enregistré : suit les catégories choisies, le secret reste masqué")
print("\n%d vérifications réussies." % n)
