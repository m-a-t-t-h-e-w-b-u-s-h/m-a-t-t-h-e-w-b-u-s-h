"""Alerty Telegram, gdy cena efektywna spadnie poniżej progu z wishlist.yaml."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from . import db
from .config import Config
from .query import filters_ok, latest_rows, money, size_ok


def pending(con, cfg: Config) -> list[dict]:
    out = []
    for r in latest_rows(con, cfg):
        sub = cfg.subcategory(f"{r['category']}/{r['subcategory']}") if r["category"] else None
        if not sub or sub.alert_below is None or r["effective"] is None:
            continue
        if r["effective"] >= sub.alert_below or r["available"] == 0:
            continue
        if sub.shops and r["shop"] not in sub.shops:
            continue
        params = db.loads(r["params"], {})
        sz = size_ok(sub, db.loads(r["sizes"], []))
        if not filters_ok(sub, params) or sz is False:
            continue
        last = con.execute("SELECT MIN(effective) AS m FROM alerts_sent WHERE product_id=?", (r["id"],)).fetchone()["m"]
        if last is not None and r["effective"] >= last - 0.01:
            continue  # już powiadomiono o tej lub niższej cenie
        out.append({"row": r, "sub": sub, "size_unknown": sz is None})
    return out


def message(item: dict) -> str:
    r, sub = item["row"], item["sub"]
    txt = (f"⬇ {r['name']}\n{money(r['effective'])} (próg {money(sub.alert_below)}) · {r['shop']} · {sub.path}\n"
           f"{r['url']}")
    if item["size_unknown"]:
        txt += "\n(rozmiar niezweryfikowany)"
    return txt


def send(con, cfg: Config, dry_run: bool = False) -> int:
    items = pending(con, cfg)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not items:
        return 0
    if dry_run or not (token and chat):
        if not dry_run:
            print("ℹ Brak TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID – alerty tylko na ekranie.")
        for it in items:
            print("ALERT:", message(it).replace("\n", " | "))
        return len(items)
    sent = 0
    for it in items:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             data={"chat_id": chat, "text": message(it), "disable_web_page_preview": "true"},
                             timeout=20)
        if resp.ok:
            con.execute("INSERT INTO alerts_sent VALUES (?,?,?)",
                        (it["row"]["id"], it["row"]["effective"], datetime.now(timezone.utc).isoformat(timespec="seconds")))
            sent += 1
        else:
            print(f"⚠ Telegram {resp.status_code}: {resp.text[:200]}")
    con.commit()
    return sent
