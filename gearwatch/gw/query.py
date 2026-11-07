"""Zapytania do bazy: wyszukiwanie, filtry, formatowanie."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import db
from .config import Config, Subcategory
from .params import parse_size
from .text import has_keyword, normalize

LABELS = {
    "waga_g": ("waga", lambda v: f"{v:g} g" if v < 1000 else f"{v / 1000:.2f} kg".replace(".", ",")),
    "wytrzymalosc_kn": ("wytrz.", lambda v: f"{v:g} kN"),
    "typ_zamka": ("zamek", str),
    "dlugosc_cm": ("dł.", lambda v: f"{v:g} cm"),
    "pojemnosc_l": ("poj.", lambda v: f"{v:g} l"),
    "czas_gotowania_min": ("1 l wody", lambda v: f"{int(v)}:{round((v % 1) * 60):02d} min"),
    "temp_komfortu_c": ("komfort", lambda v: f"{v:g}°C"),
    "r_value": ("R", lambda v: f"{v:g}"),
    "wodoodpornosc_mm": ("wodoodp.", lambda v: f"{v:,} mm".replace(",", " ")),
    "liczba_zebow": ("zęby", str),
    "ksztalt_rekojesci": ("rękojeść", str),
    "sezon": ("sezon", str),
    "membrana": ("membrana", str),
    "warstwy": ("", str),
    "zakres_mm": ("zakres", str),
    "rozmiar": ("rozm.", str),
    "rozmiary": ("rozmiary", str),
}


@dataclass
class Query:
    selectors: list[tuple[str, str | None, bool]] = field(default_factory=list)  # (kat, podkat, jawnie)
    temp: float | None = None
    text: list[str] = field(default_factory=list)


def parse_query(q: str, cfg: Config) -> Query:
    out = Query()
    for raw in (q or "").split(","):
        tok = raw.strip()
        if not tok:
            continue
        m = re.fullmatch(r"([+\-−]?\d+(?:[.,]\d+)?)\s*(?:°\s*c|c)?", tok, re.I)
        if m:
            out.temp = float(m.group(1).replace("−", "-").replace(",", "."))
            continue
        nt = normalize(tok)
        if "/" in nt:
            c, _, s = nt.partition("/")
            cats = [n for n in cfg.categories if _name_match(n, c)]
            if not cats:
                raise SystemExit(f"Nieznana kategoria: {c!r}. Dostępne: {', '.join(cfg.categories)}")
            for cn in cats:
                subs = [sn for sn in cfg.categories[cn].subcategories if not s or s == "*" or _name_match(sn, s)]
                if s and s != "*" and not subs:
                    raise SystemExit(f"Nieznana podkategoria {s!r} w {cn}. Dostępne: "
                                     f"{', '.join(cfg.categories[cn].subcategories)}")
                out.selectors += [(cn, sn, bool(s) and s != "*") for sn in subs]
            continue
        hit = False
        for cn, cat in cfg.categories.items():
            if _name_match(cn, nt) or any(has_keyword(nt, k) for k in cat.keywords):
                out.selectors += [(cn, sn, False) for sn in cat.subcategories]
                hit = True
            for sn in cat.subcategories:
                if _name_match(sn, nt):
                    out.selectors.append((cn, sn, True))
                    hit = True
        if not hit:
            out.text.append(nt)
    return out


def _name_match(name: str, tok: str) -> bool:
    n = normalize(name).replace("_", " ")
    tok = tok.replace("_", " ")
    return n == tok or (len(tok) >= 4 and (n.startswith(tok) or tok.startswith(n[:-1]) and len(n) > 4))


def size_ok(sub: Subcategory, sizes: list[str]) -> bool | None:
    """True/False, albo None gdy rozmiary nieznane."""
    if not sub.size:
        return True
    labels = {str(x).upper() for x in sub.size.get("labels", [])}
    if labels:  # rozmiary literowe, np. M, L ("S/M" pasuje do M)
        toks = [t for s in sizes for t in re.split(r"[\s/\-,;|]+", str(s).upper()) if t]
        if not toks:
            return None
        return any(t in labels for t in toks)
    vals = [v for v in (parse_size(s) for s in sizes) if v is not None]
    if not vals:
        return None
    lo, hi = sub.size.get("min", 0), sub.size.get("max", 99)
    return any(lo - 1e-6 <= v <= hi + 1e-6 for v in vals)


def height_ok(cfg: Config, sub: Subcategory, params: dict) -> tuple[bool | None, str]:
    """Czy śpiwór/karimata pasuje na settings.height_cm. Zwraca (wynik, opis); None = nie wiadomo."""
    if not sub.height_fit:
        return True, ""
    h = float(cfg.settings.get("height_cm", 0) or 0)
    if not h:
        return True, ""
    if params.get("wzrost_max_cm"):
        ok = params["wzrost_max_cm"] >= h
        return ok, f"maks. wzrost {params['wzrost_max_cm']} cm"
    if params.get("dlugosc_spec_cm"):
        need = h + 20 if sub.height_fit == "spiwor" else h  # śpiwór: ok. 20 cm zapasu
        ok = params["dlugosc_spec_cm"] >= need
        return ok, f"długość {params['dlugosc_spec_cm']:g} cm"
    classes = params.get("dlugosci") or []
    if "long" in classes:
        return True, "long"
    if "regular" in classes:
        # Regular zwykle pasuje do ok. 180–185 cm; przy wyższym wzroście – niepewne
        return (True if h <= 180 else None), "regular (zwykle do 180–185 cm)"
    if classes == ["short"]:
        return False, "short"
    return None, ""


def filters_ok(sub: Subcategory, params: dict) -> bool:
    for pname, rng in (sub.filters or {}).items():
        v = params.get(pname)
        if isinstance(v, (int, float)) and not (rng.get("min", float("-inf")) <= v <= rng.get("max", float("inf"))):
            return False
    return True


def required_r(t: float) -> float:
    """Orientacyjne minimalne R-value maty dla temperatury nocy (°C)."""
    if t >= 10:
        return 1.0
    if t >= 0:
        return 2.0
    if t >= -10:
        return 4.0
    if t >= -20:
        return 5.0
    return 6.0


def temp_ok(sub: Subcategory, params: dict, t: float | None) -> bool:
    if t is None:
        return True
    if sub.temp and not (sub.temp[0] <= t <= sub.temp[1]):
        return False
    comfort = params.get("temp_komfortu_c")
    if sub.temp_param == "temp_komfortu_c":
        # przy wpisanej temperaturze pokazujemy tylko śpiwory ze ZNANĄ temperaturą komfortu
        return isinstance(comfort, (int, float)) and comfort <= t
    if sub.temp_param == "r_value":
        r = params.get("r_value")
        return isinstance(r, (int, float)) and r >= required_r(t)
    return not (isinstance(comfort, (int, float)) and comfort > t)


GENDERS = {"meskie": {"m", "u"}, "damskie": {"k", "u"}, "dzieciece": {"d"}, "wszystkie": {"m", "k", "d", "u"}}


def gender_ok(cfg: Config, params: dict, gender: str | None = None) -> bool:
    """Domyślnie settings.gender z wishlist.yaml (meskie = męskie + unisex)."""
    allowed = GENDERS.get(gender or cfg.settings.get("gender", "meskie"), GENDERS["meskie"])
    return params.get("plec", "u") in allowed


def latest_rows(con, cfg: Config, include_stale: bool = False):
    stale_days = cfg.settings.get("stale_days", 30)
    since = "0000" if include_stale else (date.today() - timedelta(days=stale_days)).isoformat()
    return con.execute(
        """SELECT p.*, pr.day, pr.price, pr.catalog_price, pr.effective, pr.available
           FROM products p
           JOIN prices pr ON pr.product_id = p.id
           WHERE pr.day = (SELECT MAX(day) FROM prices WHERE product_id = p.id) AND pr.day >= ?
             AND p.id NOT IN (SELECT product_id FROM hidden)""",
        (since,)).fetchall()


def shell_ok(params: dict, membrana=None, warstwy=None, wodo_min=None, strict=False) -> tuple[bool, list[str]]:
    """Filtry membrany / warstw / wodoodporności.

    Membrana i warstwy: wybór konkretnej wartości pokazuje TYLKO produkty, przy których jest potwierdzona.
    Wodoodporność: nieznana wartość przechodzi z '?' (chyba że strict)."""
    unknown = []
    if membrana:
        v = params.get("membrana")
        if v is None:
            return False, []
        elif membrana == "gore-tex" and not v.startswith("Gore-Tex"):
            return False, []
        elif membrana != "gore-tex" and v.lower() != membrana.lower():
            return False, []
    if warstwy:
        v = params.get("warstwy")
        if v is None:
            return False, []
        elif v.replace(".", ",").upper() != warstwy.replace(".", ",").upper():
            return False, []
    if wodo_min:
        v = params.get("wodoodpornosc_mm")
        if v is None:
            unknown.append("wodoodp. ?")
        elif v < wodo_min:
            return False, []
    if strict and unknown:
        return False, []
    return True, unknown


def search(con, cfg: Config, q: Query, *, shop=None, max_price=None, in_stock=False,
           include_unwanted=False, include_stale=False, gender=None,
           membrana=None, warstwy=None, wodo_min=None, strict=False):
    wanted_paths = {(c, s): explicit for c, s, explicit in q.selectors}
    results, unknown_count = [], 0
    for r in latest_rows(con, cfg, include_stale):
        if not r["category"]:
            continue
        key = (r["category"], r["subcategory"])
        if q.selectors and r["subcategory"] == "unknown":
            if any(c == r["category"] for c, _ in wanted_paths):
                unknown_count += 1
            continue
        sub = cfg.subcategory(f"{key[0]}/{key[1]}")
        if sub is None:
            continue
        if q.selectors:
            if key not in wanted_paths:
                continue
            if not sub.wanted and not wanted_paths[key] and not include_unwanted:
                continue
        elif not sub.wanted and not include_unwanted:
            continue
        params = db.loads(r["params"], {})
        name_n = normalize(r["name"])
        if any(t not in name_n for t in q.text):
            continue
        if shop and r["shop"] != shop:
            continue
        if sub.shops and r["shop"] not in sub.shops:
            continue
        if in_stock and r["available"] == 0:
            continue
        if not r["effective"] or r["effective"] <= 0 or (max_price and r["effective"] > max_price):
            continue
        if not gender_ok(cfg, params, gender):
            continue
        if not temp_ok(sub, params, q.temp) or not filters_ok(sub, params):
            continue
        sz = size_ok(sub, db.loads(r["sizes"], []))
        if sz is False:
            continue
        hf, hnote = height_ok(cfg, sub, params)
        if hf is False:
            continue
        shok, shunk = shell_ok(params, membrana, warstwy, wodo_min, strict)
        if not shok:
            continue
        results.append({"row": r, "sub": sub, "params": params, "size_unknown": sz is None,
                        "height_note": (f"{'✓' if hf else '?'} {int(cfg.settings.get('height_cm', 0))} cm"
                                        + (f": {hnote}" if hnote else ": długość nieznana")) if sub.height_fit else "",
                        "unknown_notes": shunk})
    results.sort(key=lambda x: x["row"]["effective"])
    return results, unknown_count


def money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " zł"


def format_params(sub: Subcategory, params: dict, size_unknown=False, height_note: str = "", unknown_notes=()) -> str:
    parts = []
    for p in sub.params:
        if p in params:
            label, fmt = LABELS.get(p, (p, str))
            try:
                parts.append(f"{label} {fmt(params[p])}".strip())
            except (TypeError, ValueError):
                parts.append(f"{label} {params[p]}")
    if sub.season and "sezon" not in params:
        parts.append(f"sezon {sub.season}")
    if height_note:
        parts.append(height_note)
    parts += [n for n in unknown_notes or [] if n.split()[0] not in " ".join(parts)]
    if size_unknown:
        parts.append("rozmiar ? (brak wariantów – otwórz stronę produktu)")
    return " · ".join(parts)


def deals(con, cfg: Config, q: Query, *, shop=None, min_discount=0.0, include_stale=False, gender=None, **filters):
    """Najlepsze oferty z wishlisty.

    rabat   = 1 - cena_efektywna / cena_katalogowa (katalogowa = przekreślona, a gdy jej brak – aktualna;
              dla Skalnika to zawiera Twoje 30%)
    spadek  = 1 - cena_efektywna / najwyższa cena efektywna z ostatnich 30 dni (z historii w bazie)
    promo   = promocja samego sklepu: 1 - cena_aktualna / cena_przekreślona (bez Twoich 30%)
    min     = cena efektywna jest najniższa w całej historii produktu
    """
    found, _ = search(con, cfg, q, shop=shop, include_stale=include_stale, gender=gender, **filters)
    out = []
    for x in found:
        r = x["row"]
        eff = r["effective"]
        base = r["catalog_price"] if r["catalog_price"] and r["catalog_price"] > (r["price"] or 0) else r["price"]
        discount = 1 - eff / base if base else 0.0
        hist = con.execute(
            "SELECT MAX(effective) AS hi, MIN(effective) AS lo, COUNT(*) AS n FROM prices"
            " WHERE product_id=? AND day < ? AND day >= date(?, '-30 day')", (r["id"], r["day"], r["day"])).fetchone()
        all_lo = con.execute("SELECT MIN(effective) AS lo, COUNT(*) AS n FROM prices WHERE product_id=?",
                             (r["id"],)).fetchone()
        drop = 1 - eff / hist["hi"] if hist["n"] and hist["hi"] else None
        promo = 1 - r["price"] / r["catalog_price"] if r["catalog_price"] and r["catalog_price"] > r["price"] else 0.0
        x.update(discount=discount, drop=drop, promo=promo,
                 lowest=all_lo["n"] > 1 and eff <= all_lo["lo"] + 0.01,
                 below_alert=x["sub"].alert_below is not None and eff < x["sub"].alert_below)
        if (discount > 0 and discount * 100 >= min_discount) or (drop and drop > 0):
            out.append(x)
    out.sort(key=lambda d: (d["below_alert"], max(d["discount"], d["drop"] or 0), d["promo"]), reverse=True)
    return out
