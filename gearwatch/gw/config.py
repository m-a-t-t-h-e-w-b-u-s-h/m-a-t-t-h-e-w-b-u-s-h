"""Wczytywanie wishlist.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WISHLIST = ROOT / "wishlist.yaml"


@dataclass
class Subcategory:
    category: str
    name: str
    keywords: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    require_brand: bool = False
    params: list[str] = field(default_factory=list)
    wanted: bool = True
    season: str | None = None
    temp: tuple[float, float] | None = None
    size: dict | None = None
    filters: dict = field(default_factory=dict)
    param_range: dict = field(default_factory=dict)
    shops: list[str] | None = None
    alert_below: float | None = None

    @property
    def path(self) -> str:
        return f"{self.category}/{self.name}"


@dataclass
class Category:
    name: str
    keywords: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    exclude_brands: list[str] = field(default_factory=list)
    fallback: str | None = None
    subcategories: dict[str, Subcategory] = field(default_factory=dict)


@dataclass
class Shop:
    name: str
    hosts: list[str]
    catalog_factor: float | None


@dataclass
class Config:
    categories: dict[str, Category]
    shops: dict[str, Shop]
    settings: dict

    def shop_for_url(self, url: str) -> str | None:
        host = (urlparse(url).hostname or "").lower()
        for shop in self.shops.values():
            if host in shop.hosts:
                return shop.name
        return None

    def subcategory(self, path: str) -> Subcategory | None:
        cat, _, sub = path.partition("/")
        c = self.categories.get(cat)
        return c.subcategories.get(sub) if c else None

    def all_brands(self) -> list[str]:
        out = set()
        for c in self.categories.values():
            out.update(c.exclude_brands)
            for s in c.subcategories.values():
                out.update(s.brands)
        return sorted(out, key=len, reverse=True)


def _strs(v) -> list[str]:
    return [str(x) for x in (v or [])]


def load(path: str | Path | None = None) -> Config:
    raw = yaml.safe_load(Path(path or DEFAULT_WISHLIST).read_text(encoding="utf-8"))
    cats: dict[str, Category] = {}
    for cname, c in (raw.get("categories") or {}).items():
        cat = Category(
            name=cname,
            keywords=_strs(c.get("keywords")),
            exclude=_strs(c.get("exclude")),
            exclude_brands=_strs(c.get("exclude_brands")),
            fallback=c.get("fallback"),
        )
        for sname, s in (c.get("subcategories") or {}).items():
            s = s or {}
            temp = s.get("temp")
            cat.subcategories[sname] = Subcategory(
                category=cname,
                name=sname,
                keywords=_strs(s.get("keywords")),
                exclude=_strs(s.get("exclude")),
                brands=_strs(s.get("brands")),
                require_brand=bool(s.get("require_brand")),
                params=s.get("params") or [],
                wanted=s.get("wanted", True),
                season=s.get("season"),
                temp=(float(temp[0]), float(temp[1])) if temp else None,
                size=s.get("size"),
                filters=s.get("filters") or {},
                param_range=s.get("param_range") or {},
                shops=s.get("shops"),
                alert_below=s.get("alert_below"),
            )
        if cat.fallback and cat.fallback not in cat.subcategories:
            raise ValueError(f"{cname}: fallback '{cat.fallback}' nie jest podkategorią")
        cats[cname] = cat
    shops = {
        name: Shop(name=name, hosts=[h.lower() for h in s["hosts"]], catalog_factor=s.get("catalog_factor"))
        for name, s in (raw.get("shops") or {}).items()
    }
    return Config(categories=cats, shops=shops, settings=raw.get("settings") or {})
