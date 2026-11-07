"""Przypisanie kategorii i podkategorii na podstawie reguł z wishlist.yaml."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from dataclasses import dataclass, field

from .config import Category, Config, Subcategory
from .text import matching_keywords, normalize

W_NAME, W_CONTEXT, W_DESC, W_BRAND, W_PARAM = 3, 2, 1, 1, 3
MIN_CATEGORY = 3   # np. jedno trafienie w nazwie
MIN_SUB = 1
MAX_CONTEXT_CATEGORIES = 3
UNKNOWN = "unknown"


@dataclass
class Texts:
    name: str
    context: str
    desc: str
    brand: str
    url: str = ""

    @classmethod
    def of(cls, name, context="", desc="", brand="", url=""):
        slug = re.sub(r"[/\-_.]+", " ", urlsplit(url).path) if url else ""
        return cls(normalize(name), normalize(context), normalize(desc), normalize(brand), normalize(slug))


@dataclass
class Result:
    category: str | None
    subcategory: str | None
    reason: str = ""
    category_scores: dict = field(default_factory=dict)
    sub_scores: dict = field(default_factory=dict)
    hits: dict = field(default_factory=dict)


def _brand_matches(t: Texts, brands) -> bool:
    for b in brands or []:
        nb = normalize(b)
        if nb and (nb == t.brand or t.brand.startswith(nb) or t.name.startswith(nb) or f" {nb} " in f" {t.name} "
                   or f" {nb} " in f" {t.url} "):
            return True
    return False


def _score(t: Texts, keywords, exclude, params: dict | None = None, param_range=None, brands=None):
    """Zwraca (punkty, trafienia) albo (None, powód) przy wykluczeniu."""
    # tylko nazwa: kontekst (breadcrumbs listingu) dotyczy całej strony, więc
    # wykluczenie w nim wycinałoby wszystkie produkty naraz
    excl = matching_keywords(t.name, exclude)
    if excl:
        return None, [f"wykluczenie: {', '.join(sorted(set(excl)))}"]
    score, hits = 0, []
    for field_text, weight, label in ((t.name, W_NAME, "nazwa"), (t.context, W_CONTEXT, "kontekst"), (t.desc, W_DESC, "opis")):
        found = matching_keywords(field_text, keywords)
        score += weight * len(found)
        hits += [f"{label}:{k}" for k in found]
    for pname, rng in (param_range or {}).items():
        v = (params or {}).get(pname)
        if rng is True:  # parametr ustawiony (np. znany model z modele.yaml)
            if v:
                score += W_PARAM
                hits.append(f"param:{pname}")
            continue
        if isinstance(v, (int, float)) and rng.get("min", float("-inf")) <= v <= rng.get("max", float("inf")):
            score += W_PARAM
            hits.append(f"param:{pname}={v}")
    if score and _brand_matches(t, brands):
        score += W_BRAND
        hits.append("marka")
    return score, hits


def _category_score(cat: Category, t: Texts, params, shop) -> tuple[int | None, list]:
    if cat.exclude_brands and _brand_matches(t, cat.exclude_brands):
        return None, ["wykluczona marka"]
    if cat.keywords:
        return _score(t, cat.keywords, cat.exclude)
    # kategoria bez słów kluczowych -> najlepsza podkategoria
    best, best_hits = 0, []
    for sub in cat.subcategories.values():
        s, h = _sub_score(sub, t, params, shop)
        if s is not None and s > best:
            best, best_hits = s, h
    return (best if best >= MIN_CATEGORY else 0), best_hits


def _sub_score(sub: Subcategory, t: Texts, params, shop):
    if sub.shops and shop not in sub.shops:
        return None, ["inny sklep"]
    if sub.require_brand and not _brand_matches(t, sub.brands):
        return None, ["brak wymaganej marki"]
    if sub.require_name and not matching_keywords(t.name, sub.keywords):
        return None, ["brak słowa kluczowego w nazwie"]
    return _score(t, sub.keywords, sub.exclude, params, sub.param_range, sub.brands)


def _name_beats(first, second) -> bool:
    """Remis rozstrzyga nazwa: wygrywa reguła trafiona w nazwie, gdy druga ma trafienia tylko z kontekstu/opisu."""
    named = lambda hits: any(h.startswith("nazwa:") for h in hits or [])
    return named(first) and not named(second)


def classify(cfg: Config, name: str, context: str = "", desc: str = "", brand: str = "",
             params: dict | None = None, shop: str | None = None, url: str = "") -> Result:
    t = Texts.of(name, context, desc, brand, url)
    # marki wykluczone globalnie (settings.exclude_brands) – sprawdzane też w adresie produktu
    if _brand_matches(t, cfg.settings.get("exclude_brands") or []):
        return Result(None, None, "wykluczona marka")
    # kontekst pasujący do wielu kategorii naraz to menu sklepu, nie informacja o produkcie
    if t.context:
        ctx_cats = [c for c in cfg.categories.values()
                    if any(matching_keywords(t.context, sub.keywords) for sub in c.subcategories.values())
                    or matching_keywords(t.context, c.keywords)]
        if len(ctx_cats) >= MAX_CONTEXT_CATEGORIES:
            t.context = ""
    cat_margin = cfg.settings.get("category_margin", 2)
    sub_margin = cfg.settings.get("subcategory_margin", 2)

    cat_scores, cat_hits = {}, {}
    for cname, cat in cfg.categories.items():
        s, h = _category_score(cat, t, params, shop)
        if s:
            cat_scores[cname], cat_hits[cname] = s, h
    ranked = sorted(cat_scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] < MIN_CATEGORY:
        return Result(None, None, "poza wishlistą", cat_scores)
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < cat_margin \
            and not _name_beats(cat_hits.get(ranked[0][0]), cat_hits.get(ranked[1][0])):
        return Result(UNKNOWN, UNKNOWN, f"remis kategorii: {ranked[0][0]} vs {ranked[1][0]}",
                      cat_scores, hits=cat_hits)

    cname = ranked[0][0]
    cat = cfg.categories[cname]
    sub_scores, sub_hits = {}, {}
    for sname, sub in cat.subcategories.items():
        if sname == cat.fallback:
            continue
        s, h = _sub_score(sub, t, params, shop)
        sub_hits[sname] = h
        if s:
            sub_scores[sname] = s
    sranked = sorted(sub_scores.items(), key=lambda kv: kv[1], reverse=True)
    hits = {"kategoria": cat_hits.get(cname, []), **{k: v for k, v in sub_hits.items() if v}}
    if not sranked or sranked[0][1] < MIN_SUB:
        if cat.fallback:
            return Result(cname, cat.fallback, "fallback", cat_scores, sub_scores, hits)
        return Result(cname, UNKNOWN, "brak dopasowania podkategorii", cat_scores, sub_scores, hits)
    if len(sranked) > 1 and sranked[0][1] - sranked[1][1] < sub_margin \
            and not _name_beats(sub_hits.get(sranked[0][0]), sub_hits.get(sranked[1][0])):
        return Result(cname, UNKNOWN, f"remis: {sranked[0][0]} vs {sranked[1][0]}", cat_scores, sub_scores, hits)
    return Result(cname, sranked[0][0], "ok", cat_scores, sub_scores, hits)
