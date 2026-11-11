#!/usr/bin/env python3
"""OllamaBuntu - laboratoire : comparateur de modèles et jeux de tests de non-régression.
Fonctions pures (aucun accès disque, réseau ni commande) : testables hors de la console."""
import json
import re
import time

COMPARE_PROMPTS = [
    "Explique en cinq phrases la différence entre un disque SSD et un disque dur, pour un lecteur non spécialiste.",
    "Un train part à 8 h 15 et roule à 120 km/h pendant 2 h 30, puis s'arrête 20 minutes et repart à 90 km/h pendant 1 h. Quelle distance a-t-il parcourue et à quelle heure arrive-t-il ? Détaille le calcul.",
    "Écris une fonction Python qui renvoie les nombres premiers inférieurs à n (crible d'Ératosthène), avec une courte explication.",
]
MAX_MODELS, MAX_PROMPTS, MAX_PROMPT_CHARS, MAX_RESPONSE_CHARS = 3, 5, 2000, 4000
MAX_CASES, MAX_SUITES, MAX_REGEX = 20, 20, 200

_STOP_FR = {"le", "la", "les", "des", "une", "un", "est", "et", "que", "pour", "dans", "avec", "sur", "pas", "qui", "au", "du", "ce", "il", "elle", "sont", "ne", "en", "plus"}
_STOP_EN = {"the", "and", "is", "are", "of", "to", "in", "that", "for", "with", "on", "it", "this", "as", "be", "not", "was", "you", "have", "an"}


def compare_clean(models, prompts, num_predict):
    """Valide une demande de comparaison. Retourne (models, prompts, num_predict) ; lève ValueError."""
    if not isinstance(models, list) or not 2 <= len(models) <= MAX_MODELS:
        raise ValueError("choisissez 2 ou 3 modèles")
    models = [str(m or "").strip() for m in models]
    if any(not m for m in models) or len(set(models)) != len(models):
        raise ValueError("les modèles doivent être différents")
    if prompts in (None, "", []):
        prompts = COMPARE_PROMPTS[:2]
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= MAX_PROMPTS:
        raise ValueError("1 à %d questions" % MAX_PROMPTS)
    prompts = [str(p or "").strip() for p in prompts]
    if any(not p for p in prompts):
        raise ValueError("une question est vide")
    if any(len(p) > MAX_PROMPT_CHARS for p in prompts):
        raise ValueError("une question dépasse %d caractères" % MAX_PROMPT_CHARS)
    try:
        num_predict = int(num_predict or 200)
    except (TypeError, ValueError):
        raise ValueError("longueur de réponse invalide")
    if not 32 <= num_predict <= 512:
        raise ValueError("longueur de réponse : 32 à 512 jetons")
    return models, prompts, num_predict


def words(text):
    return set(re.findall(r"[a-zà-ÿ0-9']{3,}", str(text or "").lower()))


def similarity(a, b):
    """Recouvrement des mots (0 à 100) : repère un remplaçant qui répond à côté, sans prétendre mesurer la qualité."""
    wa, wb = words(a), words(b)
    if not wa and not wb:
        return 100
    return round(100.0 * len(wa & wb) / len(wa | wb))


def compare_row(model, prompt_index, gen, ps_entry=None, now=None):
    """Une génération « stream: false » d'Ollama : texte et mesures."""
    ev, evd = int(gen.get("eval_count") or 0), int(gen.get("eval_duration") or 0)
    ped, load = int(gen.get("prompt_eval_duration") or 0), int(gen.get("load_duration") or 0)
    size, vram = int((ps_entry or {}).get("size") or 0), int((ps_entry or {}).get("size_vram") or 0)
    text = str(gen.get("response") or "")
    return {"model": model, "prompt": prompt_index, "response": text[:MAX_RESPONSE_CHARS], "truncated": len(text) > MAX_RESPONSE_CHARS,
            "tokens": ev, "tps": round(ev * 1e9 / evd, 1) if ev and evd else None, "ttft_ms": round((load + ped) / 1e6), "load_ms": round(load / 1e6),
            "total_ms": round(int(gen.get("total_duration") or 0) / 1e6), "size": size or None,
            "vram_pct": round(100.0 * vram / size) if size else None, "t": int(now if now is not None else time.time())}


def _med(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def compare_summary(models, rows):
    """Résumé par modèle (médianes) et recouvrement des réponses avec le 1er modèle (référence)."""
    out = []
    ref = models[0] if models else None
    for m in models:
        mine = [r for r in rows if r["model"] == m]
        sims = []
        if m != ref:
            for r in mine:
                base = next((x for x in rows if x["model"] == ref and x["prompt"] == r["prompt"]), None)
                if base:
                    sims.append(similarity(base["response"], r["response"]))
        out.append({"model": m, "tps": _med([r["tps"] for r in mine]),
                    # le délai de la 1re question comprend le chargement du modèle : on retient la médiane des suivantes quand il y en a
                    "ttft_ms": _med([r["ttft_ms"] for r in (mine[1:] or mine)]), "load_ms": max([r.get("load_ms") or 0 for r in mine] or [0]),
                    "size": next((r["size"] for r in reversed(mine) if r.get("size")), None), "vram_pct": next((r["vram_pct"] for r in reversed(mine) if r.get("vram_pct") is not None), None),
                    "chars": round(sum(len(r["response"]) for r in mine) / len(mine)) if mine else 0, "similarity": round(sum(sims) / len(sims)) if sims else None,
                    "errors": sum(1 for r in mine if r.get("error"))})
    ok = [s for s in out if s["tps"]]
    best = {"tps": max(ok, key=lambda s: s["tps"])["model"] if ok else None,
            "ttft": min([s for s in out if s["ttft_ms"] is not None], key=lambda s: s["ttft_ms"])["model"] if any(s["ttft_ms"] is not None for s in out) else None}
    return {"models": out, "best": best, "reference": ref}


# ------------------------------------------------------------- tests de non-régression ---
def _language(text):
    ws = re.findall(r"[a-zà-ÿ']+", str(text or "").lower())
    if len(ws) < 6:
        return None
    fr, en = sum(1 for w in ws if w in _STOP_FR), sum(1 for w in ws if w in _STOP_EN)
    return "fr" if fr > en else "en" if en > fr else None


def _json_ok(text):
    t = str(text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        json.loads(t)
        return True
    except ValueError:
        return False


def expect_clean(e):
    """Critères d'un cas : contains / not_contains (listes de textes), regex, json (bool), min_chars / max_chars, language (fr|en)."""
    if not isinstance(e, dict):
        raise ValueError("critères invalides")
    out = {}
    for k in ("contains", "not_contains"):
        v = e.get(k) or []
        if isinstance(v, str):
            v = [x for x in (s.strip() for s in v.split("\n")) if x]
        if not isinstance(v, list) or len(v) > 10 or any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in v):
            raise ValueError("« %s » : 10 textes de 200 caractères au plus" % k)
        if v:
            out[k] = [x.strip() for x in v]
    rx = str(e.get("regex") or "").strip()
    if rx:
        if len(rx) > MAX_REGEX:
            raise ValueError("expression régulière trop longue")
        try:
            re.compile(rx)
        except re.error as err:
            raise ValueError("expression régulière invalide : %s" % err)
        out["regex"] = rx
    if e.get("json"):
        out["json"] = True
    for k in ("min_chars", "max_chars"):
        if e.get(k) not in (None, "", 0):
            try:
                n = int(e[k])
            except (TypeError, ValueError):
                raise ValueError("« %s » : nombre attendu" % k)
            if not 1 <= n <= 100000:
                raise ValueError("« %s » : 1 à 100000" % k)
            out[k] = n
    if e.get("language"):
        if e["language"] not in ("fr", "en"):
            raise ValueError("langue : fr ou en")
        out["language"] = e["language"]
    return out


def check_expect(text, expect):
    """Retourne (ok, [raisons d'échec])."""
    text = str(text or "")
    low, why = text.lower(), []
    for s in expect.get("contains", []):
        if s.lower() not in low:
            why.append("« %s » absent" % s)
    for s in expect.get("not_contains", []):
        if s.lower() in low:
            why.append("« %s » présent" % s)
    if expect.get("regex") and not re.search(expect["regex"], text[:20000], re.I | re.S):
        why.append("l'expression régulière ne correspond pas")
    if expect.get("json") and not _json_ok(text):
        why.append("ce n'est pas du JSON valide")
    if expect.get("min_chars") and len(text.strip()) < expect["min_chars"]:
        why.append("réponse trop courte (%d caractères)" % len(text.strip()))
    if expect.get("max_chars") and len(text.strip()) > expect["max_chars"]:
        why.append("réponse trop longue (%d caractères)" % len(text.strip()))
    if expect.get("language"):
        lg = _language(text)
        if lg != expect["language"]:
            why.append("langue détectée : %s" % (lg or "indéterminée"))
    return (not why), why


def suite_clean(s):
    """Valide un jeu de tests : {id, name, model, auto, cases: [{name, prompt, expect}]}."""
    if not isinstance(s, dict):
        raise ValueError("jeu de tests invalide")
    name = str(s.get("name") or "").strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("nom du jeu : 1 à 60 caractères")
    cases = s.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError("1 à %d cas de test" % MAX_CASES)
    out = []
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            raise ValueError("cas %d invalide" % (i + 1))
        prompt = str(c.get("prompt") or "").strip()
        if not prompt or len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError("cas %d : question de 1 à %d caractères" % (i + 1, MAX_PROMPT_CHARS))
        expect = expect_clean(c.get("expect") or {})
        if not expect:
            raise ValueError("cas %d : indiquez au moins un critère" % (i + 1))
        out.append({"name": (str(c.get("name") or "").strip() or "Cas %d" % (i + 1))[:60], "prompt": prompt, "expect": expect})
    return {"id": str(s.get("id") or ""), "name": name, "model": str(s.get("model") or "").strip(), "auto": bool(s.get("auto")), "cases": out}


def case_result(case, gen, now=None):
    row = compare_row("", 0, gen, None, now)
    ok, why = check_expect(row["response"], case["expect"])
    return {"name": case["name"], "ok": ok, "why": why, "response": row["response"], "tps": row["tps"], "ttft_ms": row["ttft_ms"], "tokens": row["tokens"]}


def run_summary(results):
    done = [r for r in results if not r.get("error")]
    return {"total": len(results), "passed": sum(1 for r in results if r.get("ok")), "errors": sum(1 for r in results if r.get("error")),
            "tps": _med([r.get("tps") for r in done]), "ttft_ms": _med([r.get("ttft_ms") for r in done])}


def compare_runs(prev, cur, tps_drop_pct=30):
    """Écart entre deux exécutions du même jeu et du même modèle : cas devenus faux, cas réparés, variation du débit."""
    if not prev:
        return None
    pm = {r["name"]: r for r in prev.get("results", [])}
    reg, fixed = [], []
    for r in cur.get("results", []):
        p = pm.get(r["name"])
        if p is None:
            continue
        if p.get("ok") and not r.get("ok"):
            reg.append(r["name"])
        elif not p.get("ok") and r.get("ok"):
            fixed.append(r["name"])
    pt, ct = (prev.get("summary") or {}).get("tps"), (cur.get("summary") or {}).get("tps")
    tps_pct = round(100.0 * (ct - pt) / pt, 1) if pt and ct else None
    return {"regressions": reg, "fixed": fixed, "tps_pct": tps_pct, "previous": prev.get("t"),
            "degraded": bool(reg) or (tps_pct is not None and tps_pct <= -tps_drop_pct)}
