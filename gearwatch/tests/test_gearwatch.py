import json
import shutil
from pathlib import Path

import pytest

from gw import alerts, config, db
from gw.classify import classify
from gw.extract import extract, parse_price
from gw.importer import import_file, reclassify
from gw.params import extract_params, parse_size
from gw.pricing import effective_price
from gw.query import parse_query, search
from gw.text import has_keyword, normalize

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cfg():
    return config.load()


@pytest.fixture
def con(tmp_path):
    return db.connect(tmp_path / "t.sqlite")


def _import_all(con, cfg, tmp_path):
    for f in FIX.glob("*.html"):
        dst = tmp_path / f.name
        shutil.copy(f, dst)
        import_file(con, cfg, dst, archive=False)
    reclassify(con, cfg)


# ------------------------------------------------------------------ tekst

def test_normalize_and_keywords():
    assert normalize("Śpiwór  Łódź Arc’teryx") == "spiwor lodz arcteryx"
    assert has_keyword("raki polautomatyczne", "polautomat*")
    assert not has_keyword("raki polautomatyczne", "automat*")
    assert has_keyword("raki pol-automatyczne", "pol automat*")
    assert has_keyword("palnik fire maple x1", "x1")
    assert not has_keyword("palnik fire maple x10", "x1")
    assert has_keyword("black diamond lite-wire", "lite wire")


def test_parse_price():
    assert parse_price("1 299,99 zł") == 1299.99
    assert parse_price("49.90") == 49.9
    assert parse_price("349 zł") == 349.0


# --------------------------------------------------------------- parametry

def test_params():
    p = extract_params("Śpiwór puchowy X", "Temperatura komfortu: -7°C, limit -14°C. Waga 1,2 kg")
    assert p["temp_komfortu_c"] == -7 and p["temp_limit_c"] == -14 and p["waga_g"] == 1200
    p = extract_params("Palnik Fire Maple X2 Pro", "", {"Waga": "540 g", "Czas gotowania 1 l wody": "2:30 min"})
    assert p["waga_g"] == 540 and p["czas_gotowania_min"] == 2.5
    p = extract_params("Plecak Osprey Talon 44", "")
    assert p["pojemnosc_l"] == 44
    p = extract_params("Karabinek X", "Wytrzymałość: 22 kN / 7 kN / 9 kN, waga 37 g")
    assert p["wytrzymalosc_kn"] == 22 and p["waga_g"] == 37
    p = extract_params("Raki Grivel G12 New-Matic", "12 zębów")
    assert p["liczba_zebow"] == 12
    p = extract_params("Karimata Therm-a-Rest NeoAir XTherm", "R-value: 7,3")
    assert p["r_value"] == 7.3


def test_parse_size():
    assert parse_size("46") == 46
    assert parse_size("EU 45,5") == 45.5
    assert parse_size("46 2/3") == pytest.approx(46.67, 0.01)


# ------------------------------------------------------------ klasyfikacja

@pytest.mark.parametrize("name,expected", [
    ("Karabinek Black Diamond LiteWire", ("karabinki", "ekspresowe")),
    ("Karabinek HMS Petzl Attache Screw-Lock", ("karabinki", "hms")),
    ("Karabinek Camp Nano 22", ("karabinki", "gorskie")),
    # nazwy z prawdziwego listingu Skalnika
    ("KARABINEK LITEWIRE", ("karabinki", "ekspresowe")),
    ("KARABINEK MINIWIRE", ("karabinki", "gorskie")),
    ("KARABINEK VERTIGO WIRE LOCK", ("karabinki", "hms")),
    ("KARABINEK ROCKLOCK", ("karabinki", "hms")),
    ("KARABINEK EAGLE HMS TRIPLEX", ("karabinki", "hms")),
    ("KARABINEK ATOM LOCK-BLACK", ("karabinki", "hms")),
    ("KARABINEK VERTIGO WIRE-LOCK M040AB00", ("karabinki", "hms")),
    ("KARABINEK ATTACHE M038AA01", ("karabinki", "hms")),
    ("KARABINEK OSPREY TWIST", ("karabinki", "hms")),
    ("KARABINEK ROCHA SCREW-ORANGE", ("karabinki", "hms")),
    ("KARABINEK LIME WG -ANTHRACITE-BLUE", ("karabinki", "gorskie")),
    ("KARABINEK ELECTRON STRAIGHT GATE", ("karabinki", "ekspresowe")),
    ("KARABINEK OVO PRO", ("karabinki", "inne")),
    ("Ekspres Petzl Spirit Express Sport 12 cm", ("ekspresy", "sportowe")),
    ("Ekspres alpinistyczny Black Diamond OZ Alpine 60 cm", ("ekspresy", "gorskie")),
    ("Kości Wild Country Rocks zestaw 1-10", ("kosci_mechaniki", "kosci")),
    ("Friend Black Diamond Camalot C4 #2", ("kosci_mechaniki", "friendy")),
    ("Mikrokam Black Diamond Camalot Z4 #0.3", ("kosci_mechaniki", "mikrokamy")),
    ("Czekan turystyczny Petzl Glacier", ("czekany", "turystyczne")),
    ("Czekan techniczny Petzl Nomic", ("czekany", "techniczne")),
    ("Raki półautomatyczne Petzl Vasak", ("raki", "polautomatyczne")),
    ("Raki automatyczne Grivel G14", ("raki", "automatyczne")),
    ("Palnik Fire Maple X1 Pro", ("palniki", "x1_pro")),
    ("Palnik Fire Maple X1", ("palniki", "x1")),
    ("Kuchenka Jetboil Flash", ("palniki", "inne")),
    ("Plecak Osprey Talon 44", ("plecaki", "talon")),
    ("Kurtka softshell Rab Torque", ("kurtki", "softshell")),
    ("Spodnie Mammut Nordwand Gore-Tex", ("spodnie", "hardshell")),
    ("Bluza Icebreaker Merino 260", ("bluzy", "merino")),
    ("Namiot 4-sezonowy MSR Access 2", ("namioty", "czterosezonowe")),
    ("Przewodnik wspinaczkowy Sokoliki", ("przewodniki", "sokoliki")),
    ("Crashpad Ocun Paddy", ("pozostale", "crashpad")),
    ("Czapka Arc'teryx Rho", ("pozostale", "czapka")),
    ("Buty wysokogórskie La Sportiva Nepal B2", ("buty", "b2")),
])
def test_classification(cfg, name, expected):
    r = classify(cfg, name)
    assert (r.category, r.subcategory) == expected, r


def test_accessory_carabiner_is_not_wishlist(cfg):
    assert classify(cfg, "KARABINEK SPRZĘTOWY MINO Z AKCESORIAMI").category is None


@pytest.mark.parametrize("ctx", ["Akcesoria wspinaczkowe > Karabinki", "Sprzęt wspinaczkowy > Karabinki",
                                 "Strona główna > Wspinaczka > Akcesoria > Karabinki i akcesoria"])
def test_context_does_not_trigger_exclusions(cfg, ctx):
    # regresja: exclude [akcesori*] w kontekście wycinał cały listing Skalnika
    r = classify(cfg, "KARABINEK LITEWIRE", ctx)
    assert (r.category, r.subcategory) == ("karabinki", "ekspresowe")


def test_excluded_brand(cfg):
    r = classify(cfg, "Kurtka Forclaz MT500 hardshell", brand="Forclaz")
    assert r.category != "kurtki"


def test_ambiguous_goes_to_unknown(cfg):
    # wykluczenie rozstrzyga: hardshell ma exclude [softshell*]
    r = classify(cfg, "Kurtka hybrydowa softshell z membraną Gore-Tex")
    assert (r.category, r.subcategory) == ("kurtki", "softshell")
    # bez wykluczeń: remis turystyczne (summit) vs techniczne (hybrid)
    r = classify(cfg, "Czekan Petzl Summit Evo hybrid")
    assert r.subcategory == "unknown" and r.reason.startswith("remis")


def test_sleeping_bag_by_param(cfg):
    r = classify(cfg, "Śpiwór puchowy Pajak Radical 4Z", params={"temp_komfortu_c": -12})
    assert r.subcategory == "zimowe"
    r = classify(cfg, "Śpiwór puchowy Cumulus X", params={"temp_komfortu_c": 0})
    assert r.subcategory == "trzysezonowe"


def test_gift_card_only_skalnik(cfg):
    assert classify(cfg, "Karta podarunkowa 200 zł", shop="skalnik").subcategory == "karta_podarunkowa"
    assert classify(cfg, "Karta podarunkowa 200 zł", shop="8a").category is None


def test_levis_requires_brand(cfg):
    assert classify(cfg, "Jeansy Levi's 527 Bootcut", brand="Levi's").subcategory == "bootcut_levis"
    assert classify(cfg, "Jeansy Wrangler bootcut").category is None


# --------------------------------------------------------------- ceny

def test_effective_price(cfg):
    assert effective_price(cfg, "skalnik", 49.9, 59.9) == 41.93
    assert effective_price(cfg, "skalnik", 30.0, 100.0) == 30.0
    assert effective_price(cfg, "skalnik", 100.0, None) == 70.0
    assert effective_price(cfg, "8a", 100.0, 150.0) == 100.0


# ---------------------------------------------------------- ekstrakcja

def test_extract_magento_listing():
    recs = extract({"html": (FIX / "magento_listing.html").read_text(), "url": "https://www.skalnik.pl/karabinki"})
    by_name = {r.name: r for r in recs}
    lw = by_name["Karabinek Black Diamond LiteWire"]
    assert (lw.price, lw.catalog_price) == (49.9, 59.9)
    assert lw.url == "https://www.skalnik.pl/karabinek-black-diamond-litewire.html"
    assert "Karabinki" in lw.context
    assert len(recs) == 4
    assert all("?" not in r.url for r in recs)


def test_extract_jsonld_product():
    recs = extract({"html": (FIX / "jsonld_product.html").read_text(), "url": "https://8a.pl/x?y=1"})
    (r,) = recs
    assert r.kind == "product" and r.price == 2299.0 and r.brand == "Arc'teryx"
    assert r.url == "https://8a.pl/kurtka-arcteryx-beta-ar-gore-tex"
    assert r.sizes == ["L", "XL"] and r.specs["Waga"] == "460 g"
    assert "Kurtki przeciwdeszczowe" in r.context


def test_extract_generic_listing():
    recs = extract({"html": (FIX / "generic_listing.html").read_text(), "url": "https://8a.pl/palniki"})
    by_url = {r.url: r for r in recs}
    x1 = by_url["https://8a.pl/palnik-fire-maple-x1"]
    assert (x1.price, x1.catalog_price) == (249.0, 299.0)
    assert len(recs) == 3


# ------------------------------------------------------- end-to-end

def test_end_to_end_search(con, cfg, tmp_path):
    _import_all(con, cfg, tmp_path)
    res, _ = search(con, cfg, parse_query("karabinki/ekspresowe", cfg))
    assert [x["row"]["name"] for x in res] == ["Karabinek Black Diamond LiteWire"]

    res, _ = search(con, cfg, parse_query("karabinki", cfg))
    assert "Karabinek HMS Petzl Attache Screw-Lock" not in [x["row"]["name"] for x in res]  # wanted: false
    prices = [x["row"]["effective"] for x in res]
    assert prices == sorted(prices)

    res, _ = search(con, cfg, parse_query("hardshell, -5", cfg))
    assert [x["row"]["shop"] for x in res] == ["8a"]
    res, _ = search(con, cfg, parse_query("hardshell, -40", cfg))
    assert res == []  # poza zakresem temp z wishlisty


def test_reimport_same_file_is_skipped(con, cfg, tmp_path):
    f = tmp_path / "a.html"
    shutil.copy(FIX / "magento_listing.html", f)
    assert import_file(con, cfg, f, archive=False)[0] == 4
    assert import_file(con, cfg, f, archive=False)[0] == 0


def test_bookmarklet_json_import(con, cfg, tmp_path):
    cap = {"v": 1, "url": "https://8a.pl/kurtka", "captured_at": "2026-11-01T10:00:00Z",
           "jsonld": [json.dumps({"@type": "Product", "name": "Plecak Osprey Talon 44",
                                  "brand": "Osprey", "offers": {"price": "499", "priceCurrency": "PLN"}})],
           "html": "<html><head><meta property='og:type' content='product'></head><body><h1>x</h1></body></html>"}
    f = tmp_path / "gearwatch-8a.pl-x.json"
    f.write_text(json.dumps(cap))
    assert import_file(con, cfg, f, archive=False)[0] == 1
    reclassify(con, cfg)
    row = con.execute("SELECT * FROM products").fetchone()
    assert (row["category"], row["subcategory"]) == ("plecaki", "talon")


def test_size_filter_and_alerts(con, cfg, tmp_path):
    def add(name, price, sizes):
        cap = {"url": "https://8a.pl/" + name.replace(" ", "-"), "captured_at": "2099-01-01T00:00:00Z",
               "jsonld": [json.dumps({"@type": "Product", "name": name, "offers": [
                   {"price": str(price), "size": s, "availability": "InStock"} for s in sizes]})],
               "html": "<html><head><meta property='og:type' content='product'></head></html>"}
        f = tmp_path / f"gearwatch-{abs(hash(name))}.json"
        f.write_text(json.dumps(cap))
        import_file(con, cfg, f, archive=False)

    add("Buty wysokogórskie Scarpa Mont Blanc B2", 999, ["44", "45", "46"])
    add("Buty wysokogórskie La Sportiva Nepal B2", 990, ["42", "43"])
    reclassify(con, cfg)
    con.execute("UPDATE prices SET day=date('now')")
    res, _ = search(con, cfg, parse_query("buty/b2", cfg))
    assert [x["row"]["name"] for x in res] == ["Buty wysokogórskie Scarpa Mont Blanc B2"]
    items = alerts.pending(con, cfg)
    assert [i["row"]["name"] for i in items] == ["Buty wysokogórskie Scarpa Mont Blanc B2"]


def test_badges_are_not_names_and_menu_is_not_context(cfg):
    recs = extract({"html": (FIX / "badge_listing.html").read_text(), "url": "https://www.skalnik.pl/karabinki"})
    names = {r.url.rsplit("/", 1)[-1]: r.name for r in recs}
    assert names["karabinek-ovo-light-tg-czerwony-1050416"] == "Karabinek Climbing Technology Ovo Light TG czerwony"
    assert names["karabinek-ovo-vi6-617013"] == "Karabinek ovo vi6"  # z adresu URL
    assert "Crashpady" not in recs[0].context
    for r in recs:
        assert classify(cfg, r.name, r.context).category == "karabinki"


def test_reimport_fixes_listing_names(con, cfg, tmp_path):
    f = tmp_path / "a.html"
    shutil.copy(FIX / "badge_listing.html", f)
    import_file(con, cfg, f, archive=False)
    con.execute("UPDATE products SET name='-27%'")
    import_file(con, cfg, f, archive=False, force=True)
    assert "-27%" not in [r["name"] for r in con.execute("SELECT name FROM products")]


def test_menu_like_context_is_ignored(cfg):
    # zaobserwowane na prawdziwym Skalniku: kontekst = fragment menu
    ctx = "Wspinaczka > Karabinki > Kości > Plecaki > Buty > Crashpady"
    r = classify(cfg, "KARABINEK OVO LIGHT TG-CZERWONY", ctx)
    assert r.category == "karabinki"


def test_nested_breadcrumb_menu_is_flattened():
    html = ("<html><body><div class='breadcrumbs'><ul><li><a>Strona główna</a></li>"
            "<li><a>Wspinaczka</a><ul><li>Crashpady</li><li>Plecaki</li></ul></li><li>Karabinki</li></ul></div>"
            "<h1>Karabinki</h1><li class='product-item'><a class='product-item-link' href='/k-1'>Karabinek Test Alfa</a>"
            "<span data-price-type='finalPrice' data-price-amount='10'></span></li></body></html>")
    (r,) = extract({"html": html, "url": "https://www.skalnik.pl/karabinki"})
    assert "Crashpady" not in r.context and "Karabinki" in r.context
