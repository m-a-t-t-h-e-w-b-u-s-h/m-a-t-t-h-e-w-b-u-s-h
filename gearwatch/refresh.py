#!/usr/bin/env python3
"""Codzienne odświeżenie: import zrzutów z inboxa -> klasyfikacja -> alerty.

  python refresh.py                 # import + klasyfikacja + alerty (alerty max raz dziennie)
  python refresh.py --reclassify    # tylko przelicz kategorie po zmianie wishlist.yaml
  python refresh.py --dry-run       # alerty tylko na ekran
  python refresh.py --force         # alerty nawet jeśli dziś już był przebieg
  python refresh.py plik.json ...   # import wskazanych plików
  python refresh.py --reimport      # ponownie przetwórz wszystkie pliki z data/archive (po poprawce ekstraktora)
  python refresh.py --inspect plik  # pokaż, co ekstraktor widzi w pliku (do diagnozy)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from gw import alerts, config, db
from gw.importer import archived_files, import_file, inbox_files, load_capture, reclassify


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--reclassify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-archive", action="store_true", help="nie przenoś plików do data/archive")
    ap.add_argument("--reimport", action="store_true", help="przetwórz ponownie pliki z data/archive")
    ap.add_argument("--inspect", type=Path, metavar="PLIK", help="diagnostyka ekstrakcji jednego pliku")
    ap.add_argument("--wishlist")
    ap.add_argument("--db")
    args = ap.parse_args(argv)

    cfg = config.load(args.wishlist)
    if args.inspect:
        inspect(args.inspect)
        return
    con = db.connect(args.db)

    n_files = n_records = 0
    if not args.reclassify:
        reimport = args.reimport and not args.files
        files = args.files or (archived_files() if reimport else inbox_files(cfg))
        for f in files:
            try:
                count, msg = import_file(con, cfg, f, archive=not (args.no_archive or reimport), force=reimport)
            except Exception as e:  # zły plik nie może zatrzymać całego przebiegu
                count, msg = 0, f"błąd: {e}"
            print(f"{f.name}: {msg}")
            n_files += 1
            n_records += count
        if not files:
            print("Inbox pusty – brak nowych zrzutów.")

    stats = reclassify(con, cfg)
    print("Klasyfikacja:", ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())) or "brak produktów")
    if stats.get("remis") or stats.get("brak dopasowania podkategorii") or stats.get("remis kategorii"):
        print("→ python find.py --unknown")

    if args.reclassify:
        return
    today = date.today().isoformat()
    already = con.execute("SELECT 1 FROM runs WHERE substr(started_at,1,10)=? AND alerts IS NOT NULL",
                          (today,)).fetchone()
    sent = None
    if already and not args.force and not args.dry_run:
        print("Alerty: dziś już sprawdzone (użyj --force).")
    else:
        sent = alerts.send(con, cfg, dry_run=args.dry_run)
        print(f"Alerty: {sent}")
    con.execute("INSERT INTO runs (started_at, files, records, alerts) VALUES (?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), n_files, n_records,
                 None if args.dry_run else sent))
    con.commit()


def inspect(path: Path):
    from bs4 import BeautifulSoup

    from gw.extract import extract
    cap = load_capture(path)
    print("URL:", cap.get("url"))
    recs = extract(cap)
    print(f"Rekordów: {len(recs)}")
    for r in recs[:5]:
        print(f"  [{r.method}] {r.name!r}  cena={r.price} katalogowa={r.catalog_price}\n    {r.url}")
    if recs:
        print("Kontekst:", recs[0].context[:300])
    soup = BeautifulSoup(cap.get("html") or "", "html.parser")
    tile = soup.select_one("li.product-item, .product-item-info, div.product-item")
    if tile:
        html = str(tile)
        print("\nPierwszy kafelek (HTML, skrócony):\n" + html[:2500])


if __name__ == "__main__":
    main()
