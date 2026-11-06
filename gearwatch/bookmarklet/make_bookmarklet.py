#!/usr/bin/env python3
"""Generuje bookmarklet.html z linkiem do przeciągnięcia na pasek zakładek."""
import html
import re
from pathlib import Path
from urllib.parse import quote

here = Path(__file__).resolve().parent
js = (here / "capture.js").read_text(encoding="utf-8")
js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
js = " ".join(line.strip() for line in js.splitlines() if line.strip())
href = "javascript:" + quote(js, safe="(){}[];,.:=+-*/!?'_<>&|$^~")

page = f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>gearwatch – bookmarklet</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px}}
a.bm{{display:inline-block;padding:10px 16px;background:#1b5e20;color:#fff;border-radius:6px;text-decoration:none}}</style>
</head><body>
<h1>gearwatch – zrzut strony</h1>
<p>Przeciągnij ten przycisk na pasek zakładek:</p>
<p><a class="bm" href="{html.escape(href, quote=True)}">📥 gearwatch</a></p>
<ol>
<li>Otwórz stronę kategorii (np. karabinki) albo produktu w Skalniku lub 8a.</li>
<li>Przewiń do końca listy, żeby doładowały się wszystkie produkty.</li>
<li>Kliknij zakładkę <b>gearwatch</b> – w Pobranych pojawi się plik <code>gearwatch-….json</code>.</li>
<li>Uruchom <code>python refresh.py</code> (albo poczekaj na zaplanowane zadanie).</li>
</ol>
<p>Strony produktów dają więcej parametrów (waga, rozmiary, specyfikacja) niż listingi.</p>
</body></html>
"""
(here / "bookmarklet.html").write_text(page, encoding="utf-8")
print(f"Zapisano {here / 'bookmarklet.html'} ({len(href)} znaków w linku)")
