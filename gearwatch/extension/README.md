# Rozszerzenie gearwatch (Chrome / Edge)

Automatycznie zapisuje zrzut każdej strony **kategorii lub produktu**, którą
sam otworzysz w skalnik.pl lub 8a.pl. Rozszerzenie:

- samo nie otwiera żadnych stron i nie wysyła niczego do sieci,
- zapisuje plik `gearwatch-<sklep>-<czas>.json` w Pobranych (tak jak bookmarklet),
- tę samą stronę zapisuje automatycznie najwyżej raz dziennie,
- pomija koszyk, konto, blog i ekran „Just a moment...” Cloudflare.

Na ikonie rozszerzenia pojawia się: `✓` zapisano, `=` już zapisane dziś,
`!` błąd zapisu, `?` strona nieobsługiwana (np. trzeba ją odświeżyć).
**Kliknięcie ikony** wymusza zapis bieżącej strony – przydatne po przewinięciu
długiej listy, która doładowuje produkty.

## Instalacja (raz)

1. Otwórz `chrome://extensions` (w Edge: `edge://extensions`).
2. Włącz **Tryb dewelopera** (przełącznik w prawym górnym rogu).
3. Kliknij **Załaduj rozpakowane** i wskaż folder `gearwatch\extension`.
4. Przypnij ikonę rozszerzenia (ikona puzzla → pinezka przy „gearwatch”).
5. Ustawienia Chrome → Pobrane: **wyłącz „Pytaj, gdzie zapisać każdy plik”**,
   inaczej każdy zrzut otworzy okno zapisu.

Po aktualizacji kodu: `chrome://extensions` → przy gearwatch ikona odświeżania.

## Folder zakładek „gearwatch”

```
python refresh.py --bookmarks
```

tworzy `data\gearwatch-zakladki.html` z adresami listingów, które już
zrzuciłeś (razem ze stronami 2, 3…). Zaimportuj go: Chrome → Zakładki →
Menedżer zakładek → ⋮ → **Importuj zakładki**. Potem dodawaj do folderu
kolejne kategorie przeciągając adresy z paska.

Raz na kilka dni: prawy przycisk na folderze → **Otwórz wszystkie**.
Rozszerzenie zapisze każdą kartę po ok. 4 sekundach. Przy kilkudziesięciu
kartach podziel folder na mniejsze (np. Skalnik / 8a), żeby nie otwierać
wszystkiego naraz.
