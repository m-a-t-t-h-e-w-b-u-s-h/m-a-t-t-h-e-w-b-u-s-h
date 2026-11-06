"""Import zrzutów stron do bazy + przeliczenie klasyfikacji."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from . import db
from .classify import classify
from .config import ROOT, Config
from .extract import Record, extract
from .params import body_fit_params, detect_gender, extract_params, layers, mat_r_value, membrane
from .pricing import effective_price

ARCHIVE = ROOT / "data" / "archive"


def inbox_files(cfg: Config) -> list[Path]:
    files: list[Path] = []
    for entry in cfg.settings.get("inbox") or ["./inbox"]:
        d = Path(entry).expanduser()
        if not d.is_absolute():
            d = ROOT / d
        if not d.is_dir():
            continue
        files += d.glob("gearwatch-*.json")
        files += d.glob("gearwatch-*.html")
        if d.resolve() == (ROOT / "inbox").resolve():
            files += [p for p in d.glob("*.htm*") if not p.name.startswith("gearwatch-")]
    return sorted(set(files))


def load_capture(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        cap = json.loads(raw)
    else:  # strona zapisana z przeglądarki (Ctrl+S)
        soup = BeautifulSoup(raw, "html.parser")
        canon = soup.select_one("link[rel=canonical]") or soup.select_one("meta[property='og:url']")
        url = (canon.get("href") or canon.get("content")) if canon else ""
        cap = {"url": url, "html": raw}
    if not cap.get("captured_at"):
        ts = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        cap["captured_at"] = ts.isoformat(timespec="seconds")
    return cap


def _upsert(con, cfg: Config, shop: str, rec: Record, captured_at: str, source: str) -> int:
    row = con.execute("SELECT * FROM products WHERE shop=? AND url=?", (shop, rec.url)).fetchone()
    if row is None:
        cur = con.execute(
            "INSERT INTO products (shop,url,name,brand,context,description,specs,sizes,method,first_seen,last_seen,image)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (shop, rec.url, rec.name, rec.brand, rec.context, rec.description, db.dumps(rec.specs),
             db.dumps(rec.sizes), rec.method, captured_at, captured_at, rec.image or None))
        pid = cur.lastrowid
    else:
        pid = row["id"]
        detail = rec.kind == "product"
        con.execute(
            "UPDATE products SET name=?, brand=COALESCE(?,brand), context=?, description=?, specs=?, sizes=?,"
            " method=?, last_seen=MAX(last_seen, ?) WHERE id=?",
            (rec.name if detail or not row["name"] or row["specs"] in (None, "", "{}") else row["name"],
             rec.brand,
             rec.context if (detail or not row["context"] or row["specs"] in (None, "", "{}")) and rec.context
             else row["context"],
             rec.description if detail else row["description"],
             db.dumps(rec.specs) if detail else row["specs"],
             db.dumps(rec.sizes) if detail or rec.sizes else row["sizes"],
             rec.method if detail else row["method"],
             captured_at, pid))
        if rec.image:
            con.execute("UPDATE products SET image=? WHERE id=? AND (image IS NULL OR ?)",
                        (rec.image, pid, int(detail)))
    if rec.price is not None:
        day = captured_at[:10]
        prev = con.execute("SELECT captured_at FROM prices WHERE product_id=? AND day=?", (pid, day)).fetchone()
        if prev is None or prev["captured_at"] <= captured_at:
            con.execute(
                "INSERT OR REPLACE INTO prices (product_id,day,captured_at,price,catalog_price,effective,available,source)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (pid, day, captured_at, rec.price, rec.catalog_price,
                 effective_price(cfg, shop, rec.price, rec.catalog_price),
                 None if rec.available is None else int(rec.available), source))
    return pid


def archived_files() -> list[Path]:
    return sorted(ARCHIVE.glob("*/*.json")) + sorted(ARCHIVE.glob("*/*.htm*"))


def import_file(con, cfg: Config, path: Path, archive: bool = True, force: bool = False) -> tuple[int, str]:
    """Zwraca (liczba rekordów, komunikat)."""
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if not force and con.execute("SELECT 1 FROM imported_files WHERE sha256=?", (sha,)).fetchone():
        msg = "już zaimportowany"
        count = 0
    else:
        cap = load_capture(path)
        shop = cfg.shop_for_url(cap.get("url") or "")
        if not shop:
            if archive:
                _archive(path)
            return 0, f"nieznany sklep ({cap.get('url') or 'brak URL'}) – pominięty"
        records = extract(cap)
        for rec in records:
            rec_shop = cfg.shop_for_url(rec.url) or shop
            _upsert(con, cfg, rec_shop, rec, cap["captured_at"], path.name)
        con.execute("INSERT OR REPLACE INTO imported_files VALUES (?,?,?)",
                    (sha, path.name, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        methods = sorted({r.method for r in records})
        count = len(records)
        msg = f"{shop}: {count} produktów ({', '.join(methods) or '—'})"
        if not records:
            msg += "  ⚠ nic nie wyciągnięto – selektory wymagają poprawki"
    if archive:
        _archive(path)
    con.commit()
    return count, msg


def _archive(path: Path) -> None:
    dest = ARCHIVE / datetime.now().strftime("%Y-%m-%d")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest / path.name))


def reclassify(con, cfg: Config) -> dict:
    """Przelicza parametry, kategorie i ceny efektywne dla wszystkich produktów."""
    stats: dict[str, int] = {}
    for row in con.execute("SELECT * FROM products").fetchall():
        specs = db.loads(row["specs"], {})
        sizes = db.loads(row["sizes"], [])
        params = extract_params(row["name"], row["description"] or "", specs, sizes)
        params["plec"] = detect_gender(row["name"], row["context"] or "", specs)
        params.update(body_fit_params(row["name"], row["description"] or "", specs, sizes))
        if "r_value" not in params:
            r = mat_r_value(row["name"])
            if r:
                params["r_value"] = r
        mem = membrane(row["name"], row["description"] or "", specs)
        if mem:
            params["membrana"] = mem
        lay = layers(row["name"], row["description"] or "", specs, mem)
        if lay:
            params["warstwy"] = lay
        res = classify(cfg, row["name"], row["context"] or "", " ".join([row["description"] or "", *map(str, specs.values())]),
                       row["brand"] or "", params, row["shop"])
        debug = {"kategorie": res.category_scores, "podkategorie": res.sub_scores, "trafienia": res.hits}
        con.execute("UPDATE products SET params=?, category=?, subcategory=?, class_reason=?, class_debug=? WHERE id=?",
                    (db.dumps(params), res.category, res.subcategory, res.reason, db.dumps(debug), row["id"]))
        key = res.reason if res.subcategory == "unknown" or res.category is None else "ok"
        stats[key.split(":")[0]] = stats.get(key.split(":")[0], 0) + 1
    for p in con.execute("SELECT p.rowid AS rid, p.price, p.catalog_price, pr.shop FROM prices p"
                         " JOIN products pr ON pr.id=p.product_id").fetchall():
        con.execute("UPDATE prices SET effective=? WHERE rowid=?",
                    (effective_price(cfg, p["shop"], p["price"], p["catalog_price"]), p["rid"]))
    con.commit()
    return stats
