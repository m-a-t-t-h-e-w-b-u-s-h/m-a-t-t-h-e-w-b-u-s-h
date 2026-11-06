# gearwatch – wishlista sprzętu ze Skalnika i 8a

Narzędzie CLI, które zbiera ceny produktów ze **skalnik.pl** i **8a.pl**,
przypisuje je do kategorii i podkategorii z `wishlist.yaml`, trzyma historię cen
w SQLite i wysyła alert na Telegram, gdy coś spadnie poniżej progu.

## Skąd biorą się dane (i dlaczego nie ma scrapera)

Oba sklepy stoją za ochroną antybotową Cloudflare: każde zapytanie spoza
przeglądarki (curl, `requests`) dostaje `403` i stronę „Just a moment...”,
także z domowego łącza. Publicznego feedu produktowego też nie znalazłem
(Skalnik ma program partnerski dla wydawców, 8a – brak informacji).
Narzędzie **nie obchodzi tej ochrony**. Dane zbierasz sam w swojej
przeglądarce, a resztę robi automat:

1. **Bookmarklet** (`bookmarklet/bookmarklet.html`) – na stronie kategorii lub
   produktu klikasz zakładkę, a w Pobranych pojawia się plik
   `gearwatch-<sklep>-<czas>.json`. Bookmarklet niczego nie wysyła do sieci.
   Zamiast niego możesz też zapisać stronę (Ctrl+S, „tylko HTML”) do `inbox/`.
2. **`refresh.py`** (codziennie, z harmonogramu) importuje nowe pliki z
   `~/Downloads` i `./inbox`, wyciąga produkty, klasyfikuje je, zapisuje ceny
   i wysyła alerty. Zaimportowane pliki przenosi do `data/archive/`.
3. **`find.py`** przeszukuje bazę (bez dostępu do sieci).

Dane ze strony wyciągane są w kolejności: JSON-LD (schema.org) → znaczniki
Magento (`data-price-type="finalPrice"/"oldPrice"`) → ogólna heurystyka
„kafelek z ceną i linkiem”. **Selektory nie były sprawdzone na prawdziwych
stronach sklepów** (testy działają na syntetycznych fixturach). Jeśli import
napisze `⚠ nic nie wyciągnięto`, ten plik JSON jest materiałem do poprawki
ekstraktora (`gw/extract.py`).

## Instalacja

```
cd gearwatch
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell)
source .venv/bin/activate          # Linux / macOS
pip install -r requirements.txt
python bookmarklet/make_bookmarklet.py
```

Otwórz `bookmarklet/bookmarklet.html` w przeglądarce i przeciągnij zielony
przycisk na pasek zakładek.

## Zbieranie danych

- Otwórz stronę kategorii (np. karabinki), przewiń do końca, kliknij zakładkę.
  Przy stronicowaniu – na każdej stronie.
- Strona **produktu** daje więcej: specyfikację (waga, kN, R-value, temp.
  komfortu…), dostępne rozmiary i opis. Warto ją zrzucić dla produktów, które
  Cię interesują – zwłaszcza butów B2 (filtr rozmiaru 45.5–46.5 sprawdza
  dostępne warianty; bez nich wynik ma dopisek „rozmiar ?”).

## Wyszukiwanie

```
python find.py "hardshell, -5"          # kurtki i spodnie hardshell, zakres temp. obejmuje -5°C
python find.py "karabinki/ekspresowe"   # kategoria/podkategoria
python find.py "karabinki"              # cała kategoria (bez kubełków wanted: false)
python find.py "karabinki/hms"          # kubełek wanted: false – pokazany, bo podany wprost
python find.py "spiwory, -10" --shop 8a --max 1500 --in-stock
python find.py "plecaki, talon 44"      # dodatkowe słowa filtrują po nazwie
python find.py --categories             # drzewo kategorii z liczbą produktów
python find.py --history 42             # historia cen produktu #42
```

Wynik jest posortowany od najtańszej ceny efektywnej. Dla każdego produktu
widać: cenę efektywną (i aktualną, jeśli się różni), sklep, nazwę,
parametry zależne od podkategorii i link.

**Cena efektywna:** Skalnik `min(aktualna, katalogowa × 0.7)` – gdy sklep nie
pokazuje ceny przekreślonej, katalogowa = aktualna; 8a – cena aktualna.
Współczynnik ustawiasz w `wishlist.yaml` → `shops`.

**Zapytanie** to lista po przecinkach: liczba = temperatura (filtruje po zakresie
`temp` podkategorii i po temperaturze komfortu śpiworów), `kat/podkat`,
nazwa kategorii/podkategorii (bez polskich znaków też działa) albo dowolne
słowo, które musi wystąpić w nazwie produktu.

## Kategorie, podkategorie i raport `unknown`

Reguły są w `wishlist.yaml` (opis składni na początku pliku). Każdy produkt
dostaje kategorię i podkategorię na podstawie nazwy (3 pkt za słowo kluczowe),
breadcrumbs/tytułu listingu (2 pkt), opisu i specyfikacji (1 pkt), marki (+1)
i parametrów (`param_range`, +3 – np. śpiwory po temperaturze komfortu,
karimaty po R-value). `exclude` (sprawdzane tylko w nazwie) dyskwalifikuje regułę.

Gdy dwie podkategorie mają podobny wynik (różnica < `subcategory_margin`) albo
żadna nie pasuje, produkt dostaje `subcategory: unknown`:

```
python find.py --unknown                # z punktacją i trafionymi słowami
python find.py --unknown --csv unknown.csv
```

Po poprawieniu reguł: `python refresh.py --reclassify` (przelicza wszystko
z bazy, bez nowych plików). Kategorie z `fallback: inne` (palniki, plecaki,
kurtki…) wrzucają produkty bez żadnego dopasowania do kubełka `inne`
(`wanted: false`) zamiast do `unknown`, żeby raport pokazywał tylko
przypadki naprawdę niejednoznaczne. Usuń `fallback`, jeśli chcesz widzieć
wszystko.

## Codzienne odświeżanie

`refresh.py` sprawdza alerty najwyżej raz dziennie (kolejny przebieg tego samego
dnia tylko importuje; `--force` wymusza alerty, `--dry-run` pokazuje je na ekranie).

**Windows** (Harmonogram zadań, codziennie o 20:37):

```
schtasks /Create /SC DAILY /ST 20:37 /TN gearwatch /TR "C:\ścieżka\do\gearwatch\.venv\Scripts\python.exe C:\ścieżka\do\gearwatch\refresh.py"
```

**Linux / macOS** (`crontab -e`):

```
37 20 * * * cd /ścieżka/do/gearwatch && .venv/bin/python refresh.py >> data/refresh.log 2>&1
```

## Alerty Telegram (opcjonalnie)

1. Utwórz bota u [@BotFather](https://t.me/BotFather) i skopiuj token.
2. Napisz cokolwiek do bota, potem otwórz
   `https://api.telegram.org/bot<TOKEN>/getUpdates` i odczytaj `chat.id`.
3. Ustaw zmienne środowiskowe:
   - Windows: `setx TELEGRAM_BOT_TOKEN "…"` i `setx TELEGRAM_CHAT_ID "…"` (nowe okno terminala)
   - Linux: `export TELEGRAM_BOT_TOKEN=… TELEGRAM_CHAT_ID=…` (np. w crontabie)
4. Progi to `alert_below` w podkategoriach `wishlist.yaml`. Alert przychodzi,
   gdy cena efektywna jest poniżej progu, produkt nie jest oznaczony jako
   niedostępny i spełnia filtry (rozmiar, pojemność). Ten sam produkt dostaje
   kolejny alert tylko przy jeszcze niższej cenie.

Bez zmiennych alerty są tylko wypisywane na ekran.

## Testy

```
pip install -r requirements-dev.txt
python -m pytest -q
```

## Struktura

```
find.py, refresh.py        CLI
wishlist.yaml              wishlista + reguły klasyfikacji
bookmarklet/               capture.js, generator bookmarklet.html
gw/extract.py              JSON-LD / Magento / heurystyka -> rekordy
gw/params.py               waga, kN, litry, czas gotowania, temp. komfortu, R-value…
gw/classify.py             punktacja kategorii i podkategorii
gw/importer.py             import plików, upsert, historia cen, reklasyfikacja
gw/query.py, gw/alerts.py  wyszukiwanie, filtry, Telegram
data/gearwatch.sqlite      baza (tworzona automatycznie, poza gitem)
```
