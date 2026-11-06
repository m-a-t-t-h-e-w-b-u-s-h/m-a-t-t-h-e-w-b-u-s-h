"""SQLite: produkty, historia cen, uruchomienia, wysłane alerty."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import ROOT

DEFAULT_DB = ROOT / "data" / "gearwatch.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY,
    shop          TEXT NOT NULL,
    url           TEXT NOT NULL,
    name          TEXT NOT NULL,
    brand         TEXT,
    context       TEXT,
    description   TEXT,
    specs         TEXT,            -- JSON
    sizes         TEXT,            -- JSON lista dostępnych rozmiarów
    params        TEXT,            -- JSON
    category      TEXT,
    subcategory   TEXT,
    class_reason  TEXT,
    class_debug   TEXT,            -- JSON z punktacją (raport unknown)
    method        TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (shop, url)
);
CREATE TABLE IF NOT EXISTS prices (
    product_id    INTEGER NOT NULL REFERENCES products(id),
    day           TEXT NOT NULL,   -- YYYY-MM-DD
    captured_at   TEXT NOT NULL,
    price         REAL,
    catalog_price REAL,
    effective     REAL,
    available     INTEGER,
    source        TEXT,
    PRIMARY KEY (product_id, day)
);
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    files         INTEGER,
    records       INTEGER,
    alerts        INTEGER
);
CREATE TABLE IF NOT EXISTS alerts_sent (
    product_id    INTEGER NOT NULL,
    effective     REAL NOT NULL,
    sent_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden (
    product_id    INTEGER PRIMARY KEY,   -- produkty ukryte ręcznie ("Ukryj" na stronie / find.py --hide)
    hidden_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imported_files (
    sha256        TEXT PRIMARY KEY,
    name          TEXT,
    imported_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category, subcategory);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    if "image" not in cols:  # migracja starszych baz
        con.execute("ALTER TABLE products ADD COLUMN image TEXT")
    return con


def loads(v, default):
    try:
        return json.loads(v) if v else default
    except json.JSONDecodeError:
        return default


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)
