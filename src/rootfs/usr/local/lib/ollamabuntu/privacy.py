#!/usr/bin/env python3
"""OllamaBuntu - confidentialité des demandes : détection et masquage des données sensibles, termes interdits.
Fonctions pures (aucun accès disque ni réseau) : utilisées par le routeur (à chaque demande) et par la console (validation, essai).

- Catégories détectées : secrets (jetons, clés d'API, « mot de passe : ... »), IBAN, numéros longs (cartes bancaires...), numéro de sécurité sociale,
  téléphone, e-mail, adresse IP. Les secrets sont TOUJOURS masqués dans les extraits enregistrés ; les autres catégories se règlent.
- Trois usages : (1) extraits enregistrés dans le journal (déjà possibles, désormais réglables), (2) « anonymiser » : la demande est réécrite AVANT
  d'être envoyée au modèle (le modèle, ou un autre serveur du parc, ne voit jamais la donnée), (3) termes interdits, globaux et par clé : refus ou masquage.
- La détection est à base d'expressions régulières : elle attrape les formats usuels, pas toutes les données personnelles (noms, adresses postales...)."""
import json
import re
import unicodedata

CATEGORIES = ("secret", "iban", "nir", "number", "phone", "email", "ip")
DEFAULT_ON = ("secret", "iban", "nir", "number", "phone", "email")   # l'adresse IP est courante dans les demandes techniques : à activer au besoin
MAX_SCAN = 200000          # caractères examinés par demande (au-delà : le reste n'est pas examiné)
MAX_WORDS, MAX_KEY_WORDS, WORD_MIN, WORD_MAX = 200, 50, 2, 60
BLOCK_MARK = "▮▮▮"

# L'ordre compte : un motif plus précis passe avant un motif plus large (le numéro de sécurité sociale avant « numéro long »).
PATTERNS = (
    ("secret", re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), "[jeton]"),
    ("secret", re.compile(r"\b(?:sk|pk|obf|obr|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}"), "[clé]"),
    ("secret", re.compile(r"(?i)\b(?:mot de passe|password|passwd|pwd|mdp)\s*(?:est|is)?\s*[:=]\s*\S{3,}"), "[secret]"),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"), "[IBAN]"),
    ("nir", re.compile(r"(?<![\d])[12] ?\d{2} ?(?:0[1-9]|1[0-2]|[2-9]\d) ?(?:\d{2}|2[AB]) ?\d{3} ?\d{3}(?: ?\d{2})?(?![\d])"), "[n° sécu]"),
    ("number", re.compile(r"\b(?:\d[ -]?){12,19}\b"), "[numéro]"),
    ("phone", re.compile(r"(?<![\w+])(?:(?:\+|00)33[ .-]?|0)[1-9](?:[ .-]?\d{2}){4}(?!\d)|(?<![\w+])\+\d{1,3}[ .-]?\d(?:[ .-]?\d){7,12}(?!\d)"), "[téléphone]"),
    ("email", re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}"), "[e-mail]"),   # bornes et « pas au milieu d'un mot » : pas de temps quadratique sur un texte sans @
    ("ip", re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"), "[IP]"),
)
TEXT_KEYS = ("prompt", "system", "input", "content", "text")      # champs de texte d'une demande (Ollama, compatible OpenAI, Anthropic)
CONTAINER_KEYS = ("messages", "parts")


def config_clean(data, cur=None):
    """Valide les réglages (ValueError si invalides) ; les champs absents gardent leur valeur actuelle."""
    out = json.loads(json.dumps(cur or default_config()))
    data = data if isinstance(data, dict) else {}
    if isinstance(data.get("categories"), dict):
        for c in CATEGORIES:
            if c in data["categories"]:
                out["categories"][c] = bool(data["categories"][c])
    out["categories"]["secret"] = True     # jamais désactivable
    for k in ("anonymize", "detect"):
        if k in data:
            out[k] = bool(data[k])
    if "words_action" in data:
        if data["words_action"] not in ("block", "mask"):
            raise ValueError("action sur un terme interdit : refuser ou masquer")
        out["words_action"] = data["words_action"]
    if "words" in data:
        out["words"] = words_clean(data["words"], MAX_WORDS)
    return out


def default_config():
    return {"categories": {c: c in DEFAULT_ON for c in CATEGORIES}, "anonymize": False, "detect": True, "words": [], "words_action": "block"}


def words_clean(v, limit):
    """Liste de termes interdits : texte (un par ligne ou séparés par des virgules / points-virgules) ou liste. ValueError si invalide."""
    if v is None or v == "":
        return []
    items = re.split(r"[\n;,]", v) if isinstance(v, str) else v
    if not isinstance(items, list):
        raise ValueError("termes interdits : une liste est attendue")
    out, seen = [], set()
    for w in items:
        w = " ".join(str(w).split())
        if not w:
            continue
        if not WORD_MIN <= len(w) <= WORD_MAX or re.search(r"[\x00-\x1f<>\"]", w):
            raise ValueError("terme interdit « %s » : %d à %d caractères, sans < > \"" % (w[:20], WORD_MIN, WORD_MAX))
        f = fold(w)
        if f not in seen:
            seen.add(f)
            out.append(w)
    if len(out) > limit:
        raise ValueError("au plus %d termes interdits" % limit)
    return out


def fold(text):
    """Minuscules sans accents, MÊME LONGUEUR que le texte d'origine (pour retrouver les positions)."""
    text = str(text)
    if text.isascii():
        return text.lower()
    out = []
    for ch in text:
        low = ch.lower()
        base = unicodedata.normalize("NFD", low)[:1] if len(low) == 1 else low[:1]
        out.append(base or ch)
    return "".join(out)


def words_regex(words):
    """Expression qui reconnaît n'importe lequel des termes, sur du texte « plié » (fold) : mots entiers, espaces quelconques dans une expression."""
    parts = []
    for w in sorted({fold(w) for w in words if w}, key=len, reverse=True):
        parts.append(r"\s+".join(re.escape(p) for p in w.split()))
    if not parts:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)")


def mask_text(text, cats):
    """Remplace les données sensibles des catégories actives (« secret » toujours). Retourne (texte, catégories trouvées)."""
    found, active = set(), set(cats or ()) | {"secret"}
    for cat, rx, label in PATTERNS:
        if cat in active:
            text, n = rx.subn(label, text)
            if n:
                found.add(cat)
    return text, found


def scan(text, cats):
    """Catégories présentes dans le texte, sans le modifier."""
    return mask_text(text, cats)[1]


def active_cats(conf):
    return [c for c in CATEGORIES if (conf.get("categories") or {}).get(c, c in DEFAULT_ON)] if conf else list(DEFAULT_ON)


class Result:
    def __init__(self):
        self.cats, self.hits, self.changed, self.truncated = set(), [], False, False


def _text(s, conf_cats, anonymize, wrx, action, res, budget):
    if budget[0] <= 0:
        res.truncated = True
        return s
    part = s[: budget[0]]
    rest = s[len(part):]
    budget[0] -= len(part)
    if rest:
        res.truncated = True
    new = part
    if wrx is not None:
        f = fold(part)
        spans = [(m.start(), m.end(), part[m.start():m.end()]) for m in wrx.finditer(f)]
        for a, b, w in spans:
            if w not in res.hits:
                res.hits.append(w)
        if spans and action == "mask":
            for a, b, w in reversed(spans):
                new = new[:a] + BLOCK_MARK + new[b:]
    masked, found = mask_text(new, conf_cats)
    res.cats |= found
    if anonymize and masked != new:
        new = masked
    if new != part:
        res.changed = True
    return new + rest


def _walk(obj, fn, depth=0):
    if depth > 12:
        return obj
    if isinstance(obj, dict):
        out = dict(obj)
        for k in TEXT_KEYS:
            v = out.get(k)
            if isinstance(v, str):
                out[k] = fn(v)
            elif isinstance(v, list):
                out[k] = [fn(x) if isinstance(x, str) else _walk(x, fn, depth + 1) for x in v]
            elif isinstance(v, dict):
                out[k] = _walk(v, fn, depth + 1)
        for k in CONTAINER_KEYS:
            if isinstance(out.get(k), list):
                out[k] = [fn(x) if isinstance(x, str) else _walk(x, fn, depth + 1) for x in out[k]]
        return out
    if isinstance(obj, list):
        return [fn(x) if isinstance(x, str) else _walk(x, fn, depth + 1) for x in obj]
    return obj


def process(body, conf, words):
    """Examine (et au besoin réécrit) le corps JSON d'une demande d'inférence.
    conf : réglages (config_clean) ; words : termes interdits applicables (globaux + clé).
    Retourne (corps, Result). Le corps n'est réécrit que si « anonymize » ou une action « mask » l'exige ; un corps illisible est laissé tel quel."""
    res = Result()
    try:
        d = json.loads(body)
    except (ValueError, TypeError):
        return body, res
    if not isinstance(d, dict):
        return body, res
    cats = active_cats(conf)
    wrx = words_regex(words)
    if not (conf.get("detect", True) or conf.get("anonymize") or wrx):
        return body, res
    budget = [MAX_SCAN]
    new = _walk(d, lambda s: _text(s, cats, bool(conf.get("anonymize")), wrx, conf.get("words_action", "block"), res, budget))
    if res.changed:
        return json.dumps(new, ensure_ascii=False).encode(), res
    return body, res


def excerpt_text(text, conf_cats, chars):
    """Extrait enregistré : espaces normalisés, masqué AVANT la coupe (un secret coupé en deux échapperait aux motifs), coupé à `chars`."""
    text = " ".join(str(text)[: chars * 4].split())
    text, _ = mask_text(text, conf_cats)
    return text if len(text) <= chars else text[: chars - 1].rstrip() + "…"


def stats(reqs, now, span, name=lambda m: m):
    """Synthèse des demandes de la période d'après le journal (métadonnées seulement : catégories détectées, masquages, refus).
    Retourne {n, with_pii, masked, blocked, by_cat: {catégorie: nombre}, clients: [{client, n, pii, masked, blocked}]}."""
    out = {"n": 0, "with_pii": 0, "masked": 0, "blocked": 0, "by_cat": {}, "clients": []}
    per = {}
    for r in reqs:
        if r.get("ts", 0) < now - span:
            continue
        out["n"] += 1
        c = per.setdefault(str(r.get("client") or "?"), {"client": str(r.get("client") or "?"), "n": 0, "pii": 0, "masked": 0, "blocked": 0})
        c["n"] += 1
        cats = [x for x in (r.get("pii") or []) if x in CATEGORIES] if isinstance(r.get("pii"), list) else []
        if cats:
            out["with_pii"] += 1
            c["pii"] += 1
            for x in cats:
                out["by_cat"][x] = out["by_cat"].get(x, 0) + 1
        if r.get("masked") is True:
            out["masked"] += 1
            c["masked"] += 1
        if r.get("blocked") is True:
            out["blocked"] += 1
            c["blocked"] += 1
    out["clients"] = sorted((c for c in per.values() if c["pii"] or c["masked"] or c["blocked"]), key=lambda c: (-c["blocked"], -c["pii"], c["client"]))
    return out
