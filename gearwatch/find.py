#!/usr/bin/env python3
"""Wyszukiwanie w wishliście.

Przykłady:
  python find.py "hardshell, -5"
  python find.py "karabinki/ekspresowe"
  python find.py "spiwory, -10" --shop 8a --max 1500
  python find.py "karabinki/hms"            # kubełek z wanted: false, bo podany jawnie
  python find.py --unknown                  # raport produktów bez jednoznacznej podkategorii
  python find.py --unknown --csv unknown.csv
  python find.py --history 42
  python find.py --categories               # lista kategorii/podkategorii
"""
from __future__ import annotations

import argparse
import csv
import sys

from gw import config, db
from gw.query import format_params, money, parse_query, search


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def cmd_search(con, cfg, args):
    q = parse_query(args.query or "", cfg)
    results, unknown = search(con, cfg, q, shop=args.shop, max_price=args.max, in_stock=args.in_stock,
                              include_unwanted=args.all, include_stale=args.stale)
    multi = len({x["sub"].path for x in results}) > 1
    for x in results[: args.limit]:
        r, sub = x["row"], x["sub"]
        price = money(r["effective"])
        extra = f" (cena {money(r['price'])})" if r["price"] != r["effective"] else ""
        cat = f"  [{sub.path}]" if multi else ""
        print(f"{price:>13}  {r['shop']:<8} {r['name']}{cat}{extra}")
        info = format_params(sub, x["params"], x["size_unknown"])
        if info:
            print(f"{'':>13}  {'':<8} {info}")
        print(f"{'':>13}  {'':<8} {r['url']}   #{r['id']} · {r['day']}")
    if not results:
        print("Brak dopasowań.")
    elif len(results) > args.limit:
        print(f"… i {len(results) - args.limit} więcej (--limit)")
    if unknown:
        print(f"\nℹ {unknown} produktów z tej kategorii ma subcategory: unknown → python find.py --unknown")


def cmd_unknown(con, cfg, args):
    rows = con.execute(
        "SELECT * FROM products WHERE subcategory='unknown' ORDER BY category, class_reason, name").fetchall()
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["id", "sklep", "kategoria", "powód", "nazwa", "punkty_kategorii", "punkty_podkategorii",
                        "trafienia", "url"])
            for r in rows:
                d = db.loads(r["class_debug"], {})
                w.writerow([r["id"], r["shop"], r["category"], r["class_reason"], r["name"], d.get("kategorie"),
                            d.get("podkategorie"), d.get("trafienia"), r["url"]])
        print(f"Zapisano {len(rows)} wierszy do {args.csv}")
        return
    if not rows:
        print("Brak produktów z subcategory: unknown 🎉")
        return
    current = None
    for r in rows:
        if r["category"] != current:
            current = r["category"]
            print(f"\n== {current}")
        d = db.loads(r["class_debug"], {})
        print(f"#{r['id']:<5} {r['shop']:<8} {r['name']}")
        print(f"       powód: {r['class_reason']}")
        if d.get("podkategorie"):
            print(f"       punkty: {d['podkategorie']}")
        hits = {k: v for k, v in (d.get("trafienia") or {}).items() if v}
        if hits:
            print(f"       trafienia: {hits}")
        print(f"       {r['url']}")
    print(f"\nRazem: {len(rows)}. Popraw reguły w wishlist.yaml i uruchom: python refresh.py --reclassify")


def cmd_history(con, cfg, args):
    p = con.execute("SELECT * FROM products WHERE id=?", (args.history,)).fetchone()
    if not p:
        raise SystemExit(f"Brak produktu #{args.history}")
    print(f"{p['name']}  [{p['category']}/{p['subcategory']}]  {p['shop']}\n{p['url']}\n")
    for r in con.execute("SELECT * FROM prices WHERE product_id=? ORDER BY day", (args.history,)):
        cat = f"  katalogowa {money(r['catalog_price'])}" if r["catalog_price"] else ""
        print(f"{r['day']}  efektywna {money(r['effective']):>12}  aktualna {money(r['price']):>12}{cat}")


def cmd_categories(con, cfg, args):
    counts = {(r[0], r[1]): r[2] for r in con.execute(
        "SELECT category, subcategory, COUNT(*) FROM products GROUP BY 1, 2")}
    for cn, cat in cfg.categories.items():
        print(cn)
        for sn, sub in cat.subcategories.items():
            flag = "" if sub.wanted else "  (wanted: false)"
            alert = f"  alert < {money(sub.alert_below)}" if sub.alert_below else ""
            print(f"  {cn + '/' + sn:<36} {counts.get((cn, sn), 0):>4} prod.{flag}{alert}")
        if counts.get((cn, "unknown")):
            print(f"  {cn + '/unknown':<36} {counts[(cn, 'unknown')]:>4} prod.")


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", help='np. "hardshell, -5" albo "karabinki/ekspresowe"')
    ap.add_argument("--shop", choices=None, help="skalnik | 8a")
    ap.add_argument("--max", type=float, help="maksymalna cena efektywna")
    ap.add_argument("--in-stock", action="store_true", help="tylko dostępne")
    ap.add_argument("--all", action="store_true", help="pokaż też podkategorie z wanted: false")
    ap.add_argument("--stale", action="store_true", help="pokaż też ceny starsze niż stale_days")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--unknown", action="store_true", help="raport subcategory: unknown")
    ap.add_argument("--csv", help="z --unknown: zapisz raport do CSV")
    ap.add_argument("--history", type=int, metavar="ID", help="historia cen produktu")
    ap.add_argument("--categories", action="store_true", help="lista kategorii z liczbą produktów")
    ap.add_argument("--wishlist", help="ścieżka do wishlist.yaml")
    ap.add_argument("--db", help="ścieżka do bazy SQLite")
    args = ap.parse_args(argv)

    cfg = config.load(args.wishlist)
    con = db.connect(args.db)
    if args.unknown:
        cmd_unknown(con, cfg, args)
    elif args.history:
        cmd_history(con, cfg, args)
    elif args.categories:
        cmd_categories(con, cfg, args)
    else:
        cmd_search(con, cfg, args)


if __name__ == "__main__":
    main()
