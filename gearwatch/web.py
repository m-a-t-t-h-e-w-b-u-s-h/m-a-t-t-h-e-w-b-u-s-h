#!/usr/bin/env python3
"""Lokalna strona gearwatch: wyszukiwarka, najlepsze oferty, historia cen.

  python web.py                 # http://localhost:8000 (tylko ten komputer)
  python web.py --lan           # dostępna też z telefonu w tym samym Wi-Fi
  python web.py --port 8080 --no-browser

Strona czyta bazę data/gearwatch.sqlite; nic nie wysyła do internetu
(zdjęcia produktów ładuje przeglądarka bezpośrednio ze sklepów).
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from gw import config, db, webapi

INDEX = Path(__file__).resolve().parent / "gw" / "web" / "index.html"

ROUTES = {
    "/api/search": webapi.api_search,
    "/api/deals": webapi.api_deals,
    "/api/unknown": webapi.api_unknown,
    "/api/coverage": webapi.api_coverage,
    "/api/history": webapi.api_history,
}


def make_handler(wishlist: str | None, db_path: str | None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # ciszej w konsoli
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data):
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            args = {k: v[-1] for k, v in parse_qs(u.query).items()}
            cfg = config.load(wishlist)  # świeże reguły po każdej zmianie wishlist.yaml
            if u.path == "/api/meta":
                return self._json(200, webapi.meta(cfg))
            fn = ROUTES.get(u.path)
            if not fn:
                return self._json(404, {"error": "nie ma takiej strony"})
            con = db.connect(db_path)
            try:
                return self._json(200, fn(con, cfg, args))
            except (ValueError, SystemExit) as e:
                return self._json(400, {"error": str(e)})
            finally:
                con.close()

    return Handler


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # nic nie jest wysyłane – tylko wybór interfejsu
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="udostępnij w sieci lokalnej (telefon w tym samym Wi-Fi)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--wishlist")
    ap.add_argument("--db")
    args = ap.parse_args(argv)

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), make_handler(args.wishlist, args.db))
    url = f"http://localhost:{args.port}"
    print(f"gearwatch: {url}")
    if args.lan:
        print(f"z telefonu (to samo Wi-Fi): http://{lan_ip()}:{args.port}")
        print("Windows może zapytać o zgodę zapory – zezwól tylko dla sieci prywatnych.")
    print("Zatrzymanie: Ctrl+C")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
