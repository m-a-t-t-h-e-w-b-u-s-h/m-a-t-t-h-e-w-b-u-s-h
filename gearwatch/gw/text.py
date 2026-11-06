"""Normalizacja tekstu i dopasowanie słów kluczowych."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_PL = str.maketrans({"ł": "l", "Ł": "l", "’": "'", "`": "'", "–": "-", "—": "-", " ": " "})


def normalize(s: str | None) -> str:
    """Małe litery, bez polskich znaków i apostrofów, pojedyncze spacje."""
    if not s:
        return ""
    s = s.translate(_PL).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("'", "")
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=4096)
def compile_keyword(kw: str) -> re.Pattern:
    """`stem*` = prefiks, inaczej całe słowo/fraza. Spacja w frazie pasuje też do '-'."""
    k = normalize(kw)
    prefix = k.endswith("*")
    if prefix:
        k = k[:-1]
    body = r"[\s\-]+".join(re.escape(part) for part in k.split(" "))
    tail = "" if prefix else r"(?![a-z0-9])"
    return re.compile(r"(?<![a-z0-9])" + body + tail)


def has_keyword(text_norm: str, kw: str) -> bool:
    return bool(compile_keyword(kw).search(text_norm))


def matching_keywords(text_norm: str, keywords) -> list[str]:
    return [kw for kw in (keywords or []) if has_keyword(text_norm, kw)]
