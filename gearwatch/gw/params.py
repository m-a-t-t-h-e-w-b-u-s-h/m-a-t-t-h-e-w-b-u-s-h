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

    dl = _spec(specs, "dlugosc", "length")
    p["dlugosc_cm"] = _first(NUM + r"\s*cm\b", dl or n) or _first(NUM + r"\s*cm\b", full)

    cap = _spec(specs, "pojemnosc", "capacity", "litraz")
    p["pojemnosc_l"] = _first(NUM + r"\s*(?:l|litr\w*)\b", cap or n) or _first(NUM + r"\s*(?:l|litr\w*)\b", full)
    if p["pojemnosc_l"] is None:  # np. "Osprey Talon 44"
        p["pojemnosc_l"] = _first(r"talon\s+(\d{2})\b", n)

    p["czas_gotowania_min"] = _boil_minutes(full)
    p["temp_komfortu_c"] = _temp(full, r"(?:temp\w*\s+)?komfort\w*|t\s?comf\w*|comfort")
    p["temp_limit_c"] = _temp(full, r"(?:temp\w*\s+)?limit\w*|t\s?lim\w*")
    p["r_value"] = _first(r"r[\s\-]?value[^0-9]{0,10}" + NUM, full) or _first(r"\br\s*[=:]\s*" + NUM, full)

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
