#!/usr/bin/env python3
"""Wyszukiwanie w wishliście.

Przykłady:
  python find.py "hardshell, -5"
  python find.py "karabinki/ekspresowe"
  python find.py "spiwory, -10" --shop 8a --max 1500
  python find.py "karabinki/hms"            # kubełek z wanted: false, bo podany jawnie
  python find.py "kurtki" --plec damskie    # jednorazowo damskie (domyślnie męskie + unisex)
  python find.py --unknown                  # raport produktów bez jednoznacznej podkategorii
  python find.py "karabinki/inne" --short --limit 200   # jedna linia na produkt
  python find.py --unknown --short          # j.w. dla raportu unknown
  python find.py --unknown --csv unknown.csv
  python find.py --history 42
  python find.py --categories               # lista kategorii/podkategorii
  python find.py --coverage                 # co już zebrano (podkategorie × sklepy)
  python find.py --deals                    # najlepsze oferty (rabat / spadek ceny / próg alertu)
  python find.py --deals "kurtki" --min-discount 30 --short
  python find.py --deals --per-sub          # najlepsza oferta w każdej podkategorii
"""
from __future__ import annotations

import argparse
import csv
import sys

from gw import config, db
from gw.query import deals, format_params, money, parse_query, search


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def cmd_search(con, cfg, args):
    q = parse_query(args.query or "", cfg)
    results, unknown = search(con, cfg, q, shop=args.shop, max_price=args.max, in_stock=args.in_stock,
                              include_unwanted=args.all, include_stale=args.stale, gender=args.plec)
    multi = len({x["sub"].path for x in results}) > 1
    if args.short:
        for x in results[: args.limit]:
            r = x["row"]
            print(f"{money(r['effective']):>12}  {r['shop']:<8} #{r['id']:<5} {r['name'][:80]}"
                  + (f"  [{x['sub'].path}]" if multi else ""))
    for x in ([] if args.short else results[: args.limit]):
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
    if args.short:
        for r in rows:
            reason = (r["class_reason"] or "").replace("brak dopasowania podkategorii", "brak")
            print(f"#{r['id']:<5} {r['category'] or '-':<16} {reason[:28]:<28} {r['name'][:70]}")
        print(f"Razem: {len(rows)}")
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


def cmd_deals(con, cfg, args):
    q = parse_query(args.query or "", cfg)
    items = deals(con, cfg, q, shop=args.shop, min_discount=args.min_discount, include_stale=args.stale,
                  gender=args.plec)
    if args.per_sub:  # najlepsza oferta w każdej podkategorii
        best = {}
        for d in items:
            best.setdefault(d["sub"].path, d)
        items = list(best.values())
    if not items:
        print("Brak ofert spełniających kryteria.")
        return
    print(f"{'rabat':>6} {'promo':>6} {'spadek':>7} {'cena ef.':>12} {'katalogowa':>12}  sklep    nazwa")
    for d in items[: args.limit]:
        r = d["row"]
        base = r["catalog_price"] if r["catalog_price"] and r["catalog_price"] > (r["price"] or 0) else r["price"]
        flags = (" 🔔" if d["below_alert"] else "") + (" ⬇min" if d["lowest"] else "")
        drop = f"{-d['drop'] * 100:+.0f}%" if d["drop"] else "—"
        promo = f"{d['promo'] * 100:.0f}%" if d["promo"] else "—"
        print(f"{d['discount'] * 100:>5.0f}% {promo:>6} {drop:>7} {money(r['effective']):>12} {money(base):>12}  "
              f"{r['shop']:<8} {r['name'][:60]}  [{d['sub'].path}]{flags}")
        if not args.short:
            print(f"{'':>49}{r['url']}   #{r['id']}")
    print("\nrabat = względem ceny katalogowej (Skalnik: z Twoim -30%), promo = przecena samego sklepu,"
          "\nspadek = względem najwyższej ceny z 30 dni,"
          "\n🔔 = poniżej progu alertu, ⬇min = najniższa cena w historii")


def cmd_coverage(con, cfg, args):
    """Które podkategorie mają już produkty z których sklepów – puste = strona do odwiedzenia."""
    stats = {}
    for r in con.execute(
            """SELECT p.category, p.subcategory, p.shop, COUNT(DISTINCT p.id) AS n, MAX(pr.day) AS last
               FROM products p LEFT JOIN prices pr ON pr.product_id = p.id
               GROUP BY 1, 2, 3"""):
        stats[(r["category"], r["subcategory"], r["shop"])] = (r["n"], r["last"])
    shops = list(cfg.shops)
    print(f"{'podkategoria':<34}" + "".join(f"{s:>22}" for s in shops))
    missing = []
    for cn, cat in cfg.categories.items():
        for sn, sub in cat.subcategories.items():
            if not sub.wanted:
                continue
            cells = []
            for shop in shops:
                if sub.shops and shop not in sub.shops:
                    cells.append(f"{'n/d':>22}")
                    continue
                n, last = stats.get((cn, sn, shop), (0, None))
                cells.append(f"{(f'{n} prod. ({last})' if n else '— brak'):>22}")
                if not n:
                    missing.append(f"{cn}/{sn} @ {shop}")
            print(f"{cn + '/' + sn:<34}" + "".join(cells))
    print(f"\nBrakuje {len(missing)} par podkategoria/sklep. „— brak” oznacza: tej strony jeszcze nie odwiedziłeś"
          " albo sklep nie ma takich produktów (albo reguły ich nie łapią – wtedy pomoże --unknown).")


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", help='np. "hardshell, -5" albo "karabinki/ekspresowe"')
    ap.add_argument("--shop", choices=None, help="skalnik | 8a")
    ap.add_argument("--max", type=float, help="maksymalna cena efektywna")
    ap.add_argument("--in-stock", action="store_true", help="tylko dostępne")
    ap.add_argument("--plec", choices=["meskie", "damskie", "dzieciece", "wszystkie"],
                    help="nadpisuje settings.gender z wishlist.yaml (domyślnie: meskie = męskie + unisex)")
    ap.add_argument("--all", action="store_true", help="pokaż też podkategorie z wanted: false")
    ap.add_argument("--stale", action="store_true", help="pokaż też ceny starsze niż stale_days")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--unknown", action="store_true", help="raport subcategory: unknown")
    ap.add_argument("--csv", help="z --unknown: zapisz raport do CSV")
    ap.add_argument("--short", action="store_true", help="jedna linia na produkt (wyniki i --unknown)")
    ap.add_argument("--history", type=int, metavar="ID", help="historia cen produktu")
    ap.add_argument("--categories", action="store_true", help="lista kategorii z liczbą produktów")
    ap.add_argument("--coverage", action="store_true", help="co już zebrano: podkategorie × sklepy")
    ap.add_argument("--deals", action="store_true", help="najlepsze oferty (rabat, spadek ceny, próg alertu)")
    ap.add_argument("--min-discount", type=float, default=0, metavar="PROC", help="z --deals: minimalny rabat w %%")
    ap.add_argument("--per-sub", action="store_true", help="z --deals: najlepsza oferta w każdej podkategorii")
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
    elif args.coverage:
        cmd_coverage(con, cfg, args)
    elif args.deals:
        cmd_deals(con, cfg, args)
    else:
        cmd_search(con, cfg, args)


if __name__ == "__main__":
    main()
