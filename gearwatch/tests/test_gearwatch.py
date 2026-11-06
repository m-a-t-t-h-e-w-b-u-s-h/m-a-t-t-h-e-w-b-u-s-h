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
    ("KARABINEK LIME SG -SILVER", ("karabinki", "ekspresowe")),
    ("KARABINEK LIME B -SILVER", ("karabinki", "ekspresowe")),
    ("KARABINEK LIME W -SILVER", ("karabinki", "gorskie")),
    ("KARABINEK SPIRIT GIĘTY-BLUE", ("karabinki", "ekspresowe")),
    ("KARABINEK ORBIT PROSTY-TITANIUM", ("karabinki", "ekspresowe")),
    ("KARABINEK LEGER SG -GREY-ORANGE", ("karabinki", "ekspresowe")),
    ("KARABINEK NINETEEN G", ("karabinki", "gorskie")),
    ("KARABINEK FLY-WEIGHT EVO-VIOLET", ("karabinki", "gorskie")),
    ("KARABINEK WILDWIRE-GREEN", ("karabinki", "gorskie")),
    ("ZESTAW KARABINKÓW NINETEEN G SIXPACK", ("karabinki", "gorskie")),
    ("KARABINEK TONDO SGL HC-HARD COATED-ORANGE", ("karabinki", "hms")),
    ("KARABINEK OVAL XL 3LOCK-BLUE", ("karabinki", "hms")),
    ("KARABINEK OVO LIGHT TG-CZERWONY", ("karabinki", "hms")),
    ("KARABINEK PASSO-TRI", ("karabinki", "hms")),
    ("KARABINEK GYM SAFE", ("karabinki", "hms")),
    ("KARABINEK CARITOOL S", ("karabinki", "inne")),
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


def test_name_beats_context_on_ties(cfg):
    # z prawdziwego raportu unknown (Skalnik)
    r = classify(cfg, "Bluza glacier fleece women-summit navy", "Odzież > Kurtki")
    assert r.category == "bluzy"
    r = classify(cfg, "Kurtka fineline stretch-basalt", "Kurtki > Kurtki hardshell")
    assert (r.category, r.subcategory) == ("kurtki", "hardshell")


@pytest.mark.parametrize("name,expected", [
    ("Plecak Osprey Talon 44", "duze"),
    ("Plecak Deuter Aircontact Core 45+10", "duze"),
    ("Plecak trekkingowy Mammut Trion 50 l", "duze"),
    ("Plecak Osprey Talon 22", "inne"),
    ("Plecak damski Osprey Tempest 40", "duze"),  # odfiltrowany płcią, nie klasyfikacją
    ("Plecak Black Diamond Speed", "inne"),  # pojemność nieznana
])
def test_backpacks_by_capacity(cfg, name, expected):
    r = classify(cfg, name, params=extract_params(name))
    assert (r.category, r.subcategory) == ("plecaki", expected)


def test_other_stoves_are_wanted(cfg):
    r = classify(cfg, "Kuchenka Jetboil Flash")
    assert r.subcategory == "inne" and cfg.subcategory("palniki/inne").wanted


@pytest.mark.parametrize("name,ctx,expected", [
    # z prawdziwych zrzutów Skalnika
    ("Kość mechaniczna friend 0.75", "Kości i mechaniki", ("kosci_mechaniki", "friendy")),
    ("Zestaw kości mechanicznych friend set 0.4, 0.5, 0.75", "", ("kosci_mechaniki", "friendy")),
    ("Kość mechaniczna zero friend 0.2", "", ("kosci_mechaniki", "mikrokamy")),
    ("Zestaw kości mechanicznych zero friend set 0.1-0.3", "", ("kosci_mechaniki", "mikrokamy")),
    ("Kości superlight offset rocks 5-10", "", ("kosci_mechaniki", "kosci")),
    ("Zestaw kości stopper set classic #5-11", "", ("kosci_mechaniki", "kosci")),
    ("Klucz do kości nut key", "", (None, None)),
    ("Spodnie rago-dark grey-light grey", "Spodnie softshell", ("spodnie", "inne")),
    ("Spodnie quest softshell-tnf black", "Spodnie softshell", ("spodnie", "softshell")),
])
def test_real_skalnik_names(cfg, name, ctx, expected):
    r = classify(cfg, name, ctx)
    assert (r.category, r.subcategory) == expected, r


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


def test_removed_items_are_not_wishlist(cfg):
    for name in ["Jeansy Levi's 527 Bootcut", "Perfumy Azzaro The Most Wanted", "Ścianka wspinaczkowa home wall",
                 "Karta podarunkowa 200 zł", "Dehydrator do żywności"]:
        r = classify(cfg, name, brand="Levi's" if "Levi" in name else "")
        assert r.subcategory not in ("bootcut_levis", "perfumy", "home_wall", "karta_podarunkowa", "dehydrator")


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
    assert (row["category"], row["subcategory"]) == ("plecaki", "duze")


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


def test_deals_discount_and_drop(con, cfg, tmp_path):
    _import_all(con, cfg, tmp_path)
    con.execute("UPDATE prices SET day=date('now')")
    # sztuczna historia: wczoraj LiteWire był droższy
    pid = con.execute("SELECT id FROM products WHERE name LIKE '%LiteWire%'").fetchone()["id"]
    con.execute("INSERT INTO prices VALUES (?, date('now','-1 day'), 'x', 59.9, 59.9, 50.0, 1, 't')", (pid,))
    from gw.query import deals
    items = deals(con, cfg, parse_query("karabinki", cfg))
    lw = next(d for d in items if d["row"]["id"] == pid)
    assert lw["discount"] == pytest.approx(1 - 41.93 / 59.9, abs=1e-3)
    assert lw["drop"] == pytest.approx(1 - 41.93 / 50.0, abs=1e-3)
    assert lw["lowest"] is True
    assert deals(con, cfg, parse_query("karabinki", cfg), min_discount=99) == [] or \
        all(d["drop"] for d in deals(con, cfg, parse_query("karabinki", cfg), min_discount=99))


def test_clothing_size_labels(cfg):
    from gw.query import size_ok
    sub = cfg.subcategory("kurtki/hardshell")
    assert size_ok(sub, ["L"]) is True
    assert size_ok(sub, ["S", "XL", "XXL"]) is False
    assert size_ok(sub, ["S/M"]) is True
    assert size_ok(sub, []) is None


@pytest.mark.parametrize("name,ctx,specs,expected", [
    ("Kurtka Arc'teryx Beta Jacket Men's", "", {}, "m"),
    ("Kurtka damska Rab Kinetic", "", {}, "k"),
    ("Bluza glacier fleece women-summit navy", "", {}, "k"),
    ("Kurtka Patagonia W's Torrentshell", "", {}, "k"),
    ("Spodnie Mammut Nordwand", "Odzież > Spodnie damskie", {}, "k"),
    ("Spodnie Mammut Nordwand", "Odzież > Spodnie męskie", {}, "m"),
    ("Kurtka Rab Downpour", "", {"Płeć": "Mężczyzna"}, "m"),
    ("Kurtka Rab Downpour", "", {"Płeć": "Kobieta"}, "k"),
    ("Kurtka dziecięca Reima", "", {}, "d"),
    ("Spodnie rise woman-wine red-baton rouge", "", {}, "k"),
    ("Plecak Osprey Talon 44", "", {}, "u"),
    ("Kurtka X", "Menu > Damskie > Męskie > Dziecięce", {}, "u"),
])
def test_detect_gender(name, ctx, specs, expected):
    from gw.params import detect_gender
    assert detect_gender(name, ctx, specs) == expected


def test_gender_filter_default_men(cfg):
    from gw.query import gender_ok
    assert gender_ok(cfg, {"plec": "m"}) and gender_ok(cfg, {"plec": "u"})
    assert not gender_ok(cfg, {"plec": "k"}) and not gender_ok(cfg, {"plec": "d"})
    assert gender_ok(cfg, {"plec": "k"}, "damskie")



@pytest.mark.parametrize("name,expected", [
    # druga partia nazw z prawdziwego raportu unknown (Skalnik)
    ("Czekan g zero-adriatic blue", "czekany/turystyczne"),
    ("Czekan x monster hammer", "czekany/techniczne"),
    ("Czekan asgard", "czekany/inne"),
    ("Osłona do czekana axe guard-yellow", "None/None"),
    ("Ekspres djinn axess 12 cm-blue", "ekspresy/sportowe"),
    ("Ekspres hotwire 12cm-desert sky", "ekspresy/gorskie"),
    ("Zestaw ekspresów orbit wire ks 12cm 6 pack", "ekspresy/gorskie"),
    ("Zestaw ekspresów photon ks 12cm 6 pack", "ekspresy/sportowe"),
    ("Taśma do ekspresów quickdraw bio-dyn 11mm 10cm-red", "None/None"),
    ("Materac ultralight mummy standard r 3.5 cnh22dz018-black", "karimaty/trzysezonowe"),
    ("Materac tuye r 5.8 cnh22dz016 square-carbon silver", "karimaty/zimowe"),
    ("Mata samopompująca classic light km3595-dark green", "karimaty/inne"),
    ("Kość mechaniczna dragonfly cam 3", "kosci_mechaniki/mikrokamy"),
    ("Raki g12 lt dual-matic evo-yellow", "raki/polautomatyczne"),
    ("Raki rupal semi -grey-orange", "raki/polautomatyczne"),
    ("Raki g12 lt new-matic evo-yellow", "raki/automatyczne"),
    ("Raki shark auto ii-night-oasis", "raki/automatyczne"),
    ("Raki g12 lt new-classic evo-black-yellow", "raki/koszykowe"),
    ("Buty ms rapace gtx-night black-kamille męskie pod raki", "buty/b2"),
    ("Śpiwór puez rds down -12-gold", "spiwory/zimowe"),
    ("Śpiwór puez rds down -1-gold", "spiwory/trzysezonowe"),
    ("Śpiwór radical 4z regular-red-red", "spiwory/inne"),
    ("Wkładka do śpiwora thermolite emt5-navy", "None/None"),
    ("Śpiwór dla psa moon pillar kks2102-blue", "None/None"),
])
def test_real_skalnik_names_batch2(cfg, name, expected):
    r = classify(cfg, name, params=extract_params(name))
    assert f"{r.category}/{r.subcategory}" == expected, r



@pytest.mark.parametrize("name,expected", [
    ("Materac neoair topo luxe regular-balsam", "karimaty"),
    ("Kurtka neutrino pro hoody women-tempest blue na zimę w góry", "kurtki"),
    ("Puchowa kurtka ciepła neutrino pro hoody women-black", "kurtki"),
    ("Przewodnik wspinaczkowy Sokoliki", "przewodniki"),
])
def test_real_skalnik_names_batch3(cfg, name, expected):
    assert classify(cfg, name, params=extract_params(name)).category == expected



def test_webapi(con, cfg, tmp_path):
    from gw import webapi
    _import_all(con, cfg, tmp_path)
    con.execute("UPDATE prices SET day=date('now')")
    d = webapi.api_search(con, cfg, {"cat": "karabinki", "sub": "ekspresowe"})
    assert [i["name"] for i in d["items"]] == ["Karabinek Black Diamond LiteWire"]
    d = webapi.api_search(con, cfg, {"q": "hardshell", "plec": "wszystkie"})
    assert d["items"] and all(i["path"].endswith("hardshell") for i in d["items"])
    assert webapi.api_deals(con, cfg, {"cat": "karabinki"})["items"][0]["discount"] > 0
    cov = {r["path"]: r["shops"] for r in webapi.api_coverage(con, cfg, {})["rows"]}
    assert cov["karabinki/ekspresowe"]["skalnik"]["n"] == 1
    pid = d["items"][0]["id"]
    assert webapi.api_history(con, cfg, {"id": pid})["points"]
    with pytest.raises(ValueError):
        webapi.build_query(cfg, {"cat": "nie-ma"})



@pytest.mark.parametrize("name,specs,mem,lay", [
    ("Kurtka Arc'teryx Beta AR Jacket Gore-Tex Pro", {}, "Gore-Tex Pro", "3L"),
    ("Kurtka Mammut Nordwand GTX", {}, "Gore-Tex", None),
    ("Kurtka Marmot PreCip Paclite", {}, "Gore-Tex Paclite", "2,5L"),
    ("Kurtka The North Face Summit Futurelight", {}, "Futurelight", None),
    ("Kurtka Patagonia Torrentshell 3L", {}, "własna/inna", "3L"),
    ("Kurtka Rab Downpour", {"Membrana": "Pertex Shield 2.5L"}, "Pertex Shield", "2,5L"),
    ("Kurtka TNF Quest DryVent", {}, "DryVent", None),
    ("Kurtka X", {"Materiał": "eVent DVstorm, trzywarstwowy"}, "eVent", "3L"),
    ("Kurtka fineline stretch", {}, None, None),
])
def test_membrane_and_layers(name, specs, mem, lay):
    from gw.params import layers, membrane
    m = membrane(name, "", specs)
    assert m == mem and layers(name, "", specs, m) == lay


def test_shell_filters():
    from gw.query import shell_ok
    gtx3 = {"membrana": "Gore-Tex Pro", "warstwy": "3L", "wodoodpornosc_mm": 28000}
    assert shell_ok(gtx3, "gore-tex", "3L", 20000) == (True, [])
    assert shell_ok({"membrana": "Futurelight"}, "gore-tex")[0] is False
    assert shell_ok({}, "gore-tex") == (True, ["membrana ?"])
    assert shell_ok({}, "gore-tex", strict=True)[0] is False
    assert shell_ok({"wodoodpornosc_mm": 10000}, wodo_min=20000)[0] is False


@pytest.mark.parametrize("name,specs,sizes,expected", [
    ("Śpiwór radical 4z long-red-red", {}, [], True),
    ("Śpiwór radical 4z regular-red-red", {}, [], True),
    ("Śpiwór x", {"Maksymalny wzrost": "175 cm"}, [], False),
    ("Śpiwór y", {"Długość": "215 x 80 cm"}, [], True),
    ("Śpiwór y", {"Długość": "190 cm"}, [], False),
    ("Śpiwór z", {}, ["Regular", "Long"], True),
    ("Śpiwór dusk light-gray", {}, [], None),
    ("Materac neoair xlite nxt regular short-solar flare", {}, [], False),
])
def test_height_fit_180(cfg, name, specs, sizes, expected):
    from gw.params import body_fit_params
    from gw.query import height_ok
    sub = cfg.subcategory("karimaty/inne" if name.startswith("Materac") else "spiwory/zimowe")
    assert height_ok(cfg, sub, body_fit_params(name, "", specs, sizes))[0] is expected
