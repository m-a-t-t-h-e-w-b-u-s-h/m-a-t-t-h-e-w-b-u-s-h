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
    vals = [v for v in (parse_size(s) for s in sizes) if v is not None]
    if not vals:
        return None
    lo, hi = sub.size.get("min", 0), sub.size.get("max", 99)
    return any(lo - 1e-6 <= v <= hi + 1e-6 for v in vals)


def filters_ok(sub: Subcategory, params: dict) -> bool:
    for pname, rng in (sub.filters or {}).items():
        v = params.get(pname)
        if isinstance(v, (int, float)) and not (rng.get("min", float("-inf")) <= v <= rng.get("max", float("inf"))):
            return False
    return True


def temp_ok(sub: Subcategory, params: dict, t: float | None) -> bool:
    if t is None:
        return True
    if sub.temp and not (sub.temp[0] <= t <= sub.temp[1]):
        return False
    comfort = params.get("temp_komfortu_c")
    return not (isinstance(comfort, (int, float)) and comfort > t)


def latest_rows(con, cfg: Config, include_stale: bool = False):
    stale_days = cfg.settings.get("stale_days", 30)
    since = "0000" if include_stale else (date.today() - timedelta(days=stale_days)).isoformat()
    return con.execute(
        """SELECT p.*, pr.day, pr.price, pr.catalog_price, pr.effective, pr.available
           FROM products p
           JOIN prices pr ON pr.product_id = p.id
           WHERE pr.day = (SELECT MAX(day) FROM prices WHERE product_id = p.id) AND pr.day >= ?""",
        (since,)).fetchall()


def search(con, cfg: Config, q: Query, *, shop=None, max_price=None, in_stock=False,
           include_unwanted=False, include_stale=False):
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
        if r["effective"] is None or (max_price and r["effective"] > max_price):
            continue
        if not temp_ok(sub, params, q.temp) or not filters_ok(sub, params):
            continue
        sz = size_ok(sub, db.loads(r["sizes"], []))
        if sz is False:
            continue
        results.append({"row": r, "sub": sub, "params": params, "size_unknown": sz is None})
    results.sort(key=lambda x: x["row"]["effective"])
    return results, unknown_count


def money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " zł"


def format_params(sub: Subcategory, params: dict, size_unknown=False) -> str:
    parts = []
    for p in sub.params:
        if p in params:
            label, fmt = LABELS.get(p, (p, str))
            try:
                parts.append(f"{label} {fmt(params[p])}")
            except (TypeError, ValueError):
                parts.append(f"{label} {params[p]}")
    if sub.season and "sezon" not in params:
        parts.append(f"sezon {sub.season}")
    if size_unknown:
        parts.append("rozmiar ? (brak wariantów – otwórz stronę produktu)")
    return " · ".join(parts)
