"""Dane dla strony web.py – te same funkcje co w find.py, zwracane jako JSON."""
from __future__ import annotations

from . import db
from .config import Config
from .query import Query, deals, format_params, parse_query, search


def _f(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def _b(v) -> bool:
    return str(v).lower() in ("1", "true", "on", "yes")


def build_query(cfg: Config, args: dict) -> Query:
    q = parse_query(args.get("q", ""), cfg)
    cat, sub = args.get("cat") or "", args.get("sub") or ""
    if cat:
        if cat not in cfg.categories:
            raise ValueError(f"nieznana kategoria {cat}")
        subs = [sub] if sub else list(cfg.categories[cat].subcategories)
        chosen = [(cat, s, bool(sub)) for s in subs]
        if q.selectors:
            keep = [x for x in q.selectors if x[0] == cat and (not sub or x[1] == sub)]
            q.selectors = keep or chosen
        else:
            q.selectors = chosen
    t = _f(args.get("temp"))
    if t is not None:
        q.temp = t
    return q


def _item(x: dict) -> dict:
    r, sub = x["row"], x["sub"]
    return {
        "id": r["id"], "name": r["name"], "shop": r["shop"], "url": r["url"], "image": r["image"],
        "effective": r["effective"], "price": r["price"], "catalog": r["catalog_price"], "day": r["day"],
        "available": r["available"], "path": sub.path, "wanted": sub.wanted,
        "params": format_params(sub, x["params"], x.get("size_unknown"), x.get("height_note", ""),
                                x.get("unknown_notes")),
        "plec": x["params"].get("plec", "u"),
        "alert_below": sub.alert_below,
        **{k: x[k] for k in ("discount", "promo", "drop", "lowest", "below_alert") if k in x},
    }


def meta(cfg: Config) -> dict:
    return {
        "categories": {cn: [{"name": sn, "wanted": s.wanted} for sn, s in c.subcategories.items()]
                       for cn, c in cfg.categories.items()},
        "shops": list(cfg.shops),
        "gender": cfg.settings.get("gender", "meskie"),
        "membranes": ["Gore-Tex Pro", "Gore-Tex Paclite", "Gore-Tex Active", "Gore-Tex ePE", "Gore-Tex", "eVent",
                      "Futurelight", "H2No", "DryVent", "Pertex Shield", "własna/inna"],
    }


def _shell_filters(args: dict) -> dict:
    return {"membrana": args.get("membrana") or None, "warstwy": args.get("warstwy") or None,
            "wodo_min": _f(args.get("wodo_min")), "strict": _b(args.get("strict"))}


def api_search(con, cfg: Config, args: dict) -> dict:
    q = build_query(cfg, args)
    results, unknown = search(
        con, cfg, q, shop=args.get("shop") or None, max_price=_f(args.get("max")),
        in_stock=_b(args.get("in_stock")), include_unwanted=_b(args.get("all")),
        include_stale=_b(args.get("stale")), gender=args.get("plec") or None, **_shell_filters(args))
    limit = int(_f(args.get("limit")) or 300)
    return {"items": [_item(x) for x in results[:limit]], "total": len(results), "unknown": unknown}


def api_deals(con, cfg: Config, args: dict) -> dict:
    q = build_query(cfg, args)
    items = deals(con, cfg, q, shop=args.get("shop") or None, min_discount=_f(args.get("min_discount")) or 0,
                  include_stale=_b(args.get("stale")), gender=args.get("plec") or None, **_shell_filters(args))
    if _b(args.get("per_sub")):
        best = {}
        for d in items:
            best.setdefault(d["sub"].path, d)
        items = list(best.values())
    limit = int(_f(args.get("limit")) or 300)
    return {"items": [_item(x) for x in items[:limit]], "total": len(items)}


def api_unknown(con, cfg: Config, args: dict) -> dict:
    rows = con.execute("SELECT * FROM products WHERE subcategory='unknown' ORDER BY category, name").fetchall()
    out = []
    for r in rows:
        d = db.loads(r["class_debug"], {})
        out.append({"id": r["id"], "name": r["name"], "shop": r["shop"], "url": r["url"], "category": r["category"],
                    "reason": r["class_reason"], "scores": d.get("podkategorie") or d.get("kategorie"),
                    "hits": {k: v for k, v in (d.get("trafienia") or {}).items() if v}})
    return {"items": out, "total": len(out)}


def api_coverage(con, cfg: Config, args: dict) -> dict:
    stats = {}
    for r in con.execute(
            """SELECT p.category, p.subcategory, p.shop, COUNT(DISTINCT p.id) AS n, MAX(pr.day) AS last
               FROM products p LEFT JOIN prices pr ON pr.product_id = p.id GROUP BY 1, 2, 3"""):
        stats[(r["category"], r["subcategory"], r["shop"])] = {"n": r["n"], "last": r["last"]}
    rows = []
    for cn, cat in cfg.categories.items():
        for sn, sub in cat.subcategories.items():
            if not sub.wanted:
                continue
            cells = {}
            for shop in cfg.shops:
                if sub.shops and shop not in sub.shops:
                    cells[shop] = None
                else:
                    cells[shop] = stats.get((cn, sn, shop), {"n": 0, "last": None})
            rows.append({"path": f"{cn}/{sn}", "shops": cells})
    return {"rows": rows, "shops": list(cfg.shops)}


def api_history(con, cfg: Config, args: dict) -> dict:
    pid = int(_f(args.get("id")) or 0)
    p = con.execute("SELECT id, name, shop, url, category, subcategory, image FROM products WHERE id=?",
                    (pid,)).fetchone()
    if not p:
        raise ValueError(f"brak produktu #{pid}")
    points = [dict(r) for r in con.execute(
        "SELECT day, effective, price, catalog_price FROM prices WHERE product_id=? ORDER BY day", (pid,))]
    return {"product": dict(p), "points": points}


def api_basket(con, cfg: Config, args: dict) -> dict:
    """Najtańszy pasujący produkt dla każdej pozycji wishlisty + suma (łącznie i w jednym sklepie)."""
    include_other = _b(args.get("include_other"))
    selectors = [(cn, sn, True) for cn, c in cfg.categories.items() for sn, sub in c.subcategories.items()
                 if sub.wanted and (include_other or not sub.fallback_of)]
    q = Query(selectors=selectors)
    results, _ = search(con, cfg, q, shop=None, in_stock=_b(args.get("in_stock")),
                        include_stale=_b(args.get("stale")), gender=args.get("plec") or None,
                        include_unwanted=False)
    shops = list(cfg.shops)
    items: dict[str, dict] = {}
    order = []
    for cn, c in cfg.categories.items():
        for sn, sub in c.subcategories.items():
            if not sub.wanted or (sub.fallback_of and not include_other):
                continue
            key = sub.group or sub.path
            if key not in items:
                items[key] = {"key": key, "label": sub.group or sub.path, "paths": [], "best": None,
                              "by_shop": {sh: None for sh in shops}, "count": 0}
                order.append(key)
            items[key]["paths"].append(sub.path)
    for x in results:
        key = x["sub"].group or x["sub"].path
        it = items.get(key)
        if it is None:
            continue
        it["count"] += 1
        d = _item(x)
        if it["best"] is None or d["effective"] < it["best"]["effective"]:
            it["best"] = d
        cur = it["by_shop"].get(d["shop"])
        if cur is None or d["effective"] < cur["effective"]:
            it["by_shop"][d["shop"]] = d
    rows = [items[k] for k in order]
    total = round(sum(r["best"]["effective"] for r in rows if r["best"]), 2)
    split = {sh: round(sum(r["best"]["effective"] for r in rows if r["best"] and r["best"]["shop"] == sh), 2)
             for sh in shops}
    one_shop = {sh: {"total": round(sum(r["by_shop"][sh]["effective"] for r in rows if r["by_shop"][sh]), 2),
                     "missing": [r["label"] for r in rows if r["by_shop"][sh] is None]} for sh in shops}
    return {"rows": rows, "total": total, "split": split, "one_shop": one_shop, "shops": shops,
            "missing": [r["label"] for r in rows if not r["best"]]}
