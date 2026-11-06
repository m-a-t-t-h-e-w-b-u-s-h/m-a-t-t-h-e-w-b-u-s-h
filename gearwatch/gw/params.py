"""Wyciąganie parametrów technicznych z nazwy, specyfikacji i opisu."""
from __future__ import annotations

import re

from .text import normalize

NUM = r"(\d+(?:[.,]\d+)?)"


def _f(s: str) -> float:
    return float(s.replace(",", ".").replace(" ", ""))


def _spec(specs: dict, *keys: str) -> str | None:
    for k, v in specs.items():
        nk = normalize(k)
        if any(key in nk for key in keys):
            return normalize(v)
    return None


def _weight_g(text: str) -> float | None:
    m = re.search(r"(?:waga|masa|weight|ciezar)[^0-9]{0,40}?" + NUM + r"\s*(kg|g)\b", text)
    if not m:
        m = re.search(NUM + r"\s*(kg|g)\b", text)
    if not m:
        return None
    v = _f(m.group(1))
    return round(v * 1000) if m.group(2) == "kg" else round(v)


def _first(pattern: str, text: str, conv=_f):
    m = re.search(pattern, text)
    return conv(m.group(1)) if m else None


def _temp(text: str, label: str) -> float | None:
    m = re.search(r"(?:" + label + r")[^0-9\-+]{0,40}?([\-+−]?\s?\d+(?:[.,]\d+)?)\s*°?\s*c\b", text)
    if not m:
        return None
    return _f(m.group(1).replace("−", "-").replace("+", ""))


def _boil_minutes(text: str) -> float | None:
    text = re.sub(r"(?<![\d.,])\d+(?:[.,]\d+)?\s*(?:l|litr\w*|ml)\b(?:\s*wody)?", " ", text)  # "1 l wody"
    m = re.search(r"(?:czas (?:za)?gotowania|zagotowani\w*|boil(?:ing)? time)[^0-9]{0,60}?(\d+)\s*[:']\s*(\d{2})", text)
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 60, 2)
    m = re.search(r"(?:czas (?:za)?gotowania|zagotowani\w*|boil(?:ing)? time)[^0-9]{0,60}?" + NUM + r"\s*(min|s|sek)", text)
    if m:
        v = _f(m.group(1))
        return round(v / 60, 2) if m.group(2) in ("s", "sek") else v
    return None


def _gate(text: str) -> str | None:
    for label, kws in (
        ("triact", ["triact"]),
        ("twistlock", ["twistlock", "twist lock", "twist-lock"]),
        ("ball lock", ["ball lock", "ball-lock"]),
        ("magnetron", ["magnetron"]),
        ("automatyczny", ["auto lock", "autolock", "automatyczn"]),
        ("zakręcany", ["screwgate", "screw gate", "zakrec", "screw-lock", "screwlock", "screw"]),
        ("automatyczny (triple)", ["triplex", "triple"]),
    ):
        if any(k in text for k in kws):
            return label
    return None


def _shaft(text: str) -> str | None:
    if re.search(r"zakrzywion|wygiet|curved|krzyw", text):
        return "zakrzywiona"
    if re.search(r"prost|straight", text):
        return "prosta"
    return None


def _season(text: str) -> str | None:
    m = re.search(r"\b([1-4])\s*-?\s*(?:sezon|season)", text)
    if m:
        return f"{m.group(1)}-sezonowy"
    for k, v in (("zimow", "zima"), ("winter", "zima"), ("letni", "lato"), ("summer", "lato"), ("calorocz", "całoroczny")):
        if k in text:
            return v
    return None


def parse_size(label: str) -> float | None:
    """'46', '46,5', '46 2/3', 'EU 45.5' -> liczba (rozmiar EU)."""
    s = normalize(label).replace("eu", " ")
    m = re.search(r"(\d{2})(?:\s+(\d)/(\d)|[.,](\d))?", s)
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2):
        v += int(m.group(2)) / int(m.group(3))
    elif m.group(4):
        v += int(m.group(4)) / 10
    return round(v, 2)


def extract_params(name: str, description: str = "", specs: dict | None = None, sizes=None) -> dict:
    specs = specs or {}
    n = normalize(name)
    spec_text = normalize(" ; ".join(f"{k}: {v}" for k, v in specs.items()))
    d = normalize(description)
    full = " ; ".join(x for x in (n, spec_text, d) if x)
    p: dict = {}

    w = _spec(specs, "waga", "masa", "weight")
    p["waga_g"] = _weight_g("waga " + w) if w else _weight_g(full)

    kn = _spec(specs, "wytrzymal", "strength")
    vals = [_f(x) for x in re.findall(NUM + r"\s*kn\b", kn or full)]
    p["wytrzymalosc_kn"] = max(vals) if vals else None

    p["typ_zamka"] = _gate(_spec(specs, "zamek", "zamk", "gate") or full)

    nn = normalize(name)
    if re.search(r"spiwor|sleeping bag|quilt|karimat|mata|materac|pad", nn):
        m2 = re.search(r"(?<![\d.,])(1[5-9]\d|2[0-3]\d)\s*cm", nn)  # 8a: "Śpiwór ... (190 cm)"
        if m2:
            out["dlugosc_spec_cm"] = float(m2.group(1))
    dl = _spec(specs, "dlugosc", "length")
    p["dlugosc_cm"] = _first(NUM + r"\s*cm\b", dl or n) or _first(NUM + r"\s*cm\b", full)

    cap = _spec(specs, "pojemnosc", "capacity", "litraz")
    p["pojemnosc_l"] = _first(NUM + r"\s*(?:l|litr\w*)\b", cap or n) or _first(NUM + r"\s*(?:l|litr\w*)\b", full)
    if p["pojemnosc_l"] is None and re.search(r"plecak|backpack", n):
        # np. "Plecak Osprey Talon 44", "Deuter Aircontact 45+10" – liczba bez jednostki w nazwie plecaka
        m = re.search(r"(?<![\d.,])(\d{2,3})(?:\s*\+\s*(\d{1,2}))?(?![\d.,]|\s*(?:cm|mm|g|kg|%|zl|m)\b)", n)
        if m and 15 <= int(m.group(1)) <= 120:
            p["pojemnosc_l"] = float(int(m.group(1)) + int(m.group(2) or 0))

    p["czas_gotowania_min"] = _boil_minutes(full)
    p["temp_komfortu_c"] = _temp(full, r"(?:temp\w*\s+)?komfort\w*|t\s?comf\w*|comfort")
    p["temp_limit_c"] = _temp(full, r"(?:temp\w*\s+)?limit\w*|t\s?lim\w*")
    p["r_value"] = (_first(r"r[\s\-]?value[^0-9]{0,10}" + NUM, full) or _first(r"\br\s*[=:]\s*" + NUM, full)
                    or _first(r"(?<![a-z0-9])r\s?(\d(?:[.,]\d)?)(?![\d.,]|\s*(?:cm|mm|l)\b)", n))  # "materac ... r 3.5"
    if p["temp_komfortu_c"] is None and re.search(r"spiwor|sleeping bag|quilt", n):
        t = re.search(r"(?<![\w])([\-−]\d{1,2})(?:\s*°?\s*c)?(?![\d\w])", n)  # "puez rds down -12"
        if t:
            p["temp_komfortu_c"] = _f(t.group(1).replace("−", "-"))

    wp = _spec(specs, "wodoodpor", "slup wody", "water column", "waterproof")
    m = re.search(r"(\d{1,3}(?:[ .]\d{3})+|\d{4,6})\s*mm", wp or full)
    p["wodoodpornosc_mm"] = int(re.sub(r"[ .]", "", m.group(1))) if m else None

    p["liczba_zebow"] = _first(r"(\d{1,2})\s*(?:-\s*)?(?:zeb\w*|points?|ostrz\w*)", full, int)
    p["ksztalt_rekojesci"] = _shaft(_spec(specs, "trzonek", "rekojes", "shaft") or n)
    p["sezon"] = _season(_spec(specs, "sezon", "season") or full)

    zk = re.search(NUM + r"\s*[-–]\s*" + NUM + r"\s*mm", _spec(specs, "zakres", "range") or full)
    p["zakres_mm"] = f"{zk.group(1)}–{zk.group(2)} mm" if zk else None
    r = re.search(r"(?:#|nr\.?\s?|rozmiar\s)(\d+(?:[.,]\d+)?)", n)
    p["rozmiar"] = r.group(1) if r else (_spec(specs, "rozmiar", "size") or None)
    rz = re.search(r"rozmiar\w*[^0-9]{0,10}(\d+\s*[-–]\s*\d+)", full)
    p["rozmiary"] = ", ".join(sizes) if sizes else (rz.group(1) if rz else None)
    return {k: v for k, v in p.items() if v not in (None, "")}


GENDER_WORDS = {
    "k": [r"damsk\w*", r"women\w*", r"woman", r"wmn", r"ws", r"lady", r"ladies", r"female", r"kobiet\w*", r"kobiec\w*"],
    "m": [r"mesk\w*", r"men", r"mens", r"ms", r"male", r"mezczyz\w*"],
    "d": [r"dzieci\w*", r"dzieciec\w*", r"kids?", r"junior\w*", r"jr", r"chlopiec\w*", r"dziewczyn\w*", r"youth"],
}


def _gender_in(text: str) -> set[str]:
    return {g for g, pats in GENDER_WORDS.items()
            if any(re.search(r"(?<![a-z0-9])" + p + r"(?![a-z0-9])", text) for p in pats)}


def detect_gender(name: str, context: str = "", specs: dict | None = None) -> str:
    """'m' męskie, 'k' damskie, 'd' dziecięce, 'u' unisex/nieokreślone.

    Kolejność: specyfikacja (Płeć: …) -> nazwa -> kontekst listingu (gdy wskazuje jedną płeć).
    """
    spec = _spec(specs or {}, "plec", "gender", "przeznaczenie")
    for text in (spec or "", normalize(name), normalize(context)):
        if "unisex" in text:
            return "u"
        found = _gender_in(text)
        if len(found) == 1:
            return found.pop()
        if found:  # np. "męskie i damskie" albo menu z kilkoma płciami
            return "u"
    return "u"


LENGTH_CLASSES = {
    "long": ["long", "xl", "large", "lg", "l", "dlugi", "dluga", "wide long", "xlong"],
    "regular": ["regular", "reg", "standard", "std", "medium", "m"],
    "short": ["short", "small", "s", "krotki", "krotka", "kids", "junior"],
}


def length_class(text: str) -> str | None:
    """'long' / 'regular' / 'short' z nazwy lub etykiety wariantu (śpiwory, karimaty)."""
    t = normalize(text)
    for cls in ("long", "short", "regular"):  # long przed regular: "regular wide long"
        for w in LENGTH_CLASSES[cls]:
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t):
                return cls
    return None


def body_fit_params(name: str, description: str = "", specs: dict | None = None, sizes=None) -> dict:
    specs = specs or {}
    full = normalize(" ; ".join([name, description, *[f"{k}: {v}" for k, v in specs.items()]]))
    out = {}
    m = re.search(r"(?:wzrost\w*|dla osob\w*|height)[^0-9;]{0,30}?(?:do\s*|max\.?\s*)?(1\d{2}|2[0-2]\d)\s*cm", full) \
        or re.search(r"(?:do|max\.?)\s*(1\d{2}|2[0-2]\d)\s*cm\s*wzrost", full)
    if m:
        out["wzrost_max_cm"] = int(m.group(1))
    nn = normalize(name)
    if re.search(r"spiwor|sleeping bag|quilt|karimat|mata|materac|pad", nn):
        m2 = re.search(r"(?<![\d.,])(1[5-9]\d|2[0-3]\d)\s*cm", nn)  # 8a: "Śpiwór ... (190 cm)"
        if m2:
            out["dlugosc_spec_cm"] = float(m2.group(1))
    dl = _spec(specs, "dlugosc", "length")
    if dl:
        vals = [_f(v) for v in re.findall(r"(\d{2,3}(?:[.,]\d)?)\s*(?:x\s*\d{2,3}(?:[.,]\d)?\s*)*cm", dl)]
        vals = [v for v in vals if 100 <= v <= 260]
        if vals:
            out["dlugosc_spec_cm"] = max(vals)
    classes = [c for c in (length_class(x) for x in (sizes or [])) if c]
    if classes:
        out["dlugosci"] = sorted(set(classes))
    else:
        c = length_class(name)
        if c:
            out["dlugosci"] = [c]
    return out


# (etykieta, wzorce) – kolejność ma znaczenie: od najbardziej szczegółowej
MEMBRANES = [
    ("Gore-Tex Pro", [r"gore[\s\-]?tex\s+pro", r"gtx\s+pro", r"goretex\s+pro"]),
    ("Gore-Tex Paclite", [r"paclite"]),
    ("Gore-Tex Active", [r"gore[\s\-]?tex\s+active", r"gtx\s+active", r"shakedry"]),
    ("Gore-Tex ePE", [r"gore[\s\-]?tex\s+epe", r"\bepe\b"]),
    ("Gore-Tex", [r"gore[\s\-]?tex", r"goretex", r"(?<![a-z0-9])gtx(?![a-z0-9])"]),
    ("eVent", [r"(?<![a-z0-9])event\s+(?:dv|dvl|dvstretch|dvexpedition|dvstorm)", r"membran\w*\s+event"]),
    ("Futurelight", [r"futurelight"]),
    ("H2No", [r"h2no"]),
    ("DryVent", [r"dryvent"]),
    ("Pertex Shield", [r"pertex\s+shield"]),
]
OWN_MEMBRANE = [r"membran\w*", r"ascentshell", r"neoshell", r"aquafoil", r"hydroshell", r"dermizax", r"omni[\s\-]?tech",
                r"hyvent", r"dry\.?q", r"proshell", r"storm[\s\-]?shell", r"nieprzemakal\w*", r"(?<![a-z0-9])(?:2[.,]5|3)\s?l\b"]


def membrane(name: str, description: str = "", specs: dict | None = None) -> str | None:
    """Membrana z nazwy/specyfikacji (opis tylko dla jednoznacznych nazw własnych)."""
    head = normalize(name + " ; " + " ; ".join(f"{k}: {v}" for k, v in (specs or {}).items()))
    desc = normalize(description)
    for label, pats in MEMBRANES:
        for p in pats:
            if re.search(p, head) or (label not in ("eVent", "Gore-Tex ePE") and re.search(p, desc)):
                return label
    if any(re.search(p, head) for p in OWN_MEMBRANE):
        return "własna/inna"
    return None


def layers(name: str, description: str = "", specs: dict | None = None, membrane_label: str | None = None) -> str | None:
    text = normalize(" ; ".join([name, *[f"{k}: {v}" for k, v in (specs or {}).items()], description]))
    m = re.search(r"(?<![a-z0-9.,])(2[.,]5|2|3)\s?-?\s?(?:l|warstw\w*|layer\w*)(?![a-z0-9])", text)
    if m:
        return m.group(1).replace(".", ",") + "L"
    if re.search(r"trzywarstw|three[\s\-]layer", text):
        return "3L"
    if re.search(r"dwuipol|2\s?1/2", text):
        return "2,5L"
    if re.search(r"dwuwarstw|two[\s\-]layer", text):
        return "2L"
    return {"Gore-Tex Pro": "3L", "Gore-Tex Active": "3L", "Gore-Tex Paclite": "2,5L"}.get(membrane_label)


# R-value znanych mat (dane producentów) – używane tylko, gdy nazwa/specyfikacja nie podaje R
KNOWN_R = [
    (r"xtherm\s+nxt", 7.3), (r"xtherm", 6.9), (r"xlite\s+nxt", 4.5), (r"uberlite", 2.3), (r"z\s?lite\s+sol", 2.0),
]


def mat_r_value(name: str) -> float | None:
    n = normalize(name)
    if not re.search(r"karimat|mata|materac|pad|neoair|z\s?lite", n):
        return None
    m = re.search(r"(?<![a-z0-9.,])(\d(?:[.,]\d)?)\s?r(?![a-z0-9])", n)  # Exped "Ultra 5R"
    if m:
        return _f(m.group(1))
    for pat, r in KNOWN_R:
        if re.search(pat, n):
            return r
    return None
