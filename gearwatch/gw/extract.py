"""Wyciąganie produktów ze zrzutu strony (bookmarklet lub zapisany HTML).

Kolejność źródeł: JSON-LD (schema.org) -> microdata -> znaczniki Magento
(oba sklepy wyglądają na Magento/Adobe Commerce) -> ogólna heurystyka kafelków.

UWAGA: selektory Magento i heurystyka nie były sprawdzone na żywych stronach
(sklepy blokują automatyczny dostęp). Każdy rekord ma pole `method`, a import
ostrzega, gdy z pliku nie wyciągnięto nic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

PRICE_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[  .]\d{3})*|\d+)(?:[,.](\d{2}))?\s*(?:zł|zl|PLN)", re.I)


@dataclass
class Record:
    url: str
    name: str
    price: float | None = None
    catalog_price: float | None = None
    brand: str | None = None
    available: bool | None = None
    description: str = ""
    specs: dict = field(default_factory=dict)
    sizes: list[str] = field(default_factory=list)
    context: str = ""
    image: str = ""
    method: str = ""
    kind: str = "listing"  # listing | product


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme or "https", (p.hostname or "").lower(), path, "", ""))


def parse_price(v) -> float | None:
    p = _parse_price(v)
    return p if p and p > 0 else None  # 0,00 zł = błąd odczytu / produkt bez ceny


def _parse_price(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    m = PRICE_RE.search(s)
    if m:
        whole = re.sub(r"[  .]", "", m.group(1))
        return float(f"{whole}.{m.group(2) or '00'}")
    s = s.replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d+([.,]\d+)?", s):
        return float(s.replace(",", "."))
    return None


def _img_url(scope, base_url: str) -> str:
    """Adres zdjęcia z kafelka/strony – z pominięciem placeholderów leniwego ładowania."""
    for img in scope.find_all("img"):
        for attr in ("data-src", "data-original", "data-lazy", "src", "data-srcset", "srcset"):
            v = (img.get(attr) or "").strip().split(",")[0].split(" ")[0]
            if v and not v.startswith("data:") and not v.endswith((".svg", ".gif")) and "placeholder" not in v:
                return urljoin(base_url, v)
    return ""


def _ld_image(node) -> str:
    img = node.get("image")
    if isinstance(img, list) and img:
        img = img[0]
    if isinstance(img, dict):
        img = img.get("url") or img.get("contentUrl")
    return img if isinstance(img, str) else ""


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


# --------------------------------------------------------------------- JSON-LD

def _jsonld_nodes(soup: BeautifulSoup, extra: list[str] | None = None):
    blobs = [s.string or s.get_text() for s in soup.find_all("script", type="application/ld+json")]
    blobs += extra or []
    for raw in blobs:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            yield node
            for key in ("@graph", "itemListElement", "item", "mainEntity", "hasVariant"):
                if key in node:
                    stack.append(node[key])


def _types(node) -> set[str]:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t}


def _brand(node) -> str | None:
    b = node.get("brand")
    if isinstance(b, dict):
        return b.get("name")
    if isinstance(b, list) and b:
        return _brand({"brand": b[0]})
    return b if isinstance(b, str) else None


def _offers(node):
    offers = node.get("offers") or []
    if isinstance(offers, dict):
        if offers.get("@type") == "AggregateOffer" and "offers" in offers:
            return list(offers["offers"]) or [offers]
        return [offers]
    return offers


def _record_from_jsonld(node, base_url: str) -> Record | None:
    name = node.get("name")
    if not name:
        return None
    offers = _offers(node)
    prices, catalog, sizes, available = [], None, [], None
    for o in offers:
        if not isinstance(o, dict):
            continue
        p = parse_price(o.get("price") or o.get("lowPrice"))
        if p is not None:
            prices.append(p)
        spec = o.get("priceSpecification")
        for ps in spec if isinstance(spec, list) else [spec] if spec else []:
            if isinstance(ps, dict) and "ListPrice" in str(ps.get("priceType", "")):
                catalog = parse_price(ps.get("price"))
        avail = str(o.get("availability", ""))
        if avail:
            ok = "InStock" in avail or "LimitedAvailability" in avail
            available = ok or bool(available)
        if o.get("size"):
            sizes.append(str(o["size"]))
    url = node.get("url") or (offers[0].get("url") if offers and isinstance(offers[0], dict) else None) or base_url
    return Record(
        url=canonical_url(urljoin(base_url, url)),
        name=str(name).strip(),
        price=min(prices) if prices else None,
        catalog_price=catalog,
        brand=_brand(node),
        available=available,
        description=re.sub(r"<[^>]+>", " ", str(node.get("description") or "")),
        sizes=sizes,
        image=urljoin(base_url, _ld_image(node)) if _ld_image(node) else "",
        method="jsonld",
    )


def _breadcrumbs(soup: BeautifulSoup, nodes) -> str:
    for node in nodes:
        if "BreadcrumbList" in _types(node):
            names = []
            for el in node.get("itemListElement") or []:
                if isinstance(el, dict):
                    item = el.get("item")
                    n = el.get("name") or (item.get("name") if isinstance(item, dict) else None)
                    if n:
                        names.append(str(n))
            if names:
                return " > ".join(names)
    bc = soup.select_one(".breadcrumbs, nav.breadcrumb, [aria-label=breadcrumb], .breadcrumb")
    if not bc:
        return ""
    lst = bc.find(["ol", "ul"])
    lis = lst.find_all("li", recursive=False) if lst else []
    items = []
    for li in lis:  # tylko bezpośredni tekst/link elementu, bez zagnieżdżonych podmenu
        a = li.find("a", recursive=False)
        t = _text(a) if a else " ".join(x.strip() for x in li.find_all(string=True, recursive=False))
        if t.strip() and len(t) <= 40:
            items.append(t.strip())
    text = " > ".join(items) if lis else _text(bc)
    # zbyt długi "breadcrumb" to zwykle całe menu sklepu – psułby klasyfikację
    return text if len(text) <= 200 else ""


BADGE_RE = re.compile(r"%|\bblack\s+(month|week|friday)\b|\b(nowosc|nowość|promocja|bestseller|outlet|"
                      r"wyprzedaz|wyprzedaż|darmowa dostawa|ostatnie sztuki)\b", re.I)


def _plausible_name(t: str) -> bool:
    t = (t or "").strip()
    return len(t) >= 6 and len(re.findall(r"[^\W\d_]", t)) >= 4 and not BADGE_RE.search(t) \
        and not PRICE_RE.search(t)


def _slug_name(url: str) -> str:
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.html?$", "", slug)
    slug = re.sub(r"-\d{4,}$", "", slug)
    return slug.replace("-", " ").strip().capitalize()


def _tile_name(tile, url: str, base_url: str) -> str:
    """Nazwa produktu z kafelka; omija plakietki typu '-27%' / 'BLACK MONTH'."""
    for el in tile.select(".product-item-name, .product-name, [itemprop=name], a.product-item-link, "
                          ".product-title, .name, h2, h3, h4"):
        t = _text(el) or el.get("content") or ""
        if _plausible_name(t):
            return t
    cands = []
    for a in tile.find_all("a", href=True):
        if canonical_url(urljoin(base_url, a["href"])) == url:
            cands += [_text(a), a.get("title") or "", a.get("aria-label") or ""]
    cands += [img.get("alt") or img.get("title") or "" for img in tile.find_all("img")]
    good = [c.strip() for c in cands if _plausible_name(c)]
    return max(good, key=len) if good else _slug_name(url)


# ------------------------------------------------------------- strona produktu

def _specs(soup: BeautifulSoup) -> dict:
    specs = {}
    tables = soup.select("#product-attribute-specs-table, table.additional-attributes, .product-specs table, table.data")
    for table in tables or soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) == 2:
                k, v = _text(cells[0]), _text(cells[1])
                if k and v and len(k) < 80:
                    specs.setdefault(k.rstrip(":"), v)
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                specs.setdefault(_text(dt).rstrip(":"), _text(dd))
    return specs


def _sizes(soup: BeautifulSoup) -> list[str]:
    out = []
    for el in soup.select("[data-option-label], .swatch-option.text, .swatch-option"):
        if "disabled" in (el.get("class") or []) or el.get("aria-disabled") == "true":
            continue
        label = el.get("data-option-label") or el.get("aria-label") or _text(el)
        if label:
            out.append(label.strip())
    form = soup.select_one("#product_addtocart_form, form[action*='cart']")
    for opt in (form or soup).select("select option"):
        t = _text(opt)
        if t and opt.get("value") and not opt.has_attr("disabled") and re.search(r"\d", t):
            out.append(t)
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _magento_prices(scope) -> tuple[float | None, float | None]:
    final = old = None
    for el in scope.select("[data-price-type][data-price-amount]"):
        amount = parse_price(el.get("data-price-amount"))
        kind = el.get("data-price-type")
        if kind == "finalPrice" and final is None:
            final = amount
        elif kind == "oldPrice" and old is None:
            old = amount
    if final is None:
        meta = scope.select_one("meta[itemprop=price], meta[property='product:price:amount']")
        if meta:
            final = parse_price(meta.get("content"))
    return final, old


def _is_product_page(soup: BeautifulSoup, products: list) -> bool:
    if soup.select_one("meta[property='og:type'][content='product']"):
        return True
    if soup.select_one("#product_addtocart_form, .catalog-product-view, body.catalog-product-view"):
        return True
    return len(products) == 1 and not soup.select(".product-item, .products-grid")


# ------------------------------------------------------------------- listingi

def _magento_tiles(soup: BeautifulSoup, base_url: str, context: str) -> list[Record]:
    out, seen = [], set()
    for tile in soup.select("li.product-item, .product-item-info, div.product-item"):
        link = tile.select_one("a.product-item-link, .product-item-name a, a.product-item-photo")
        if not link or not link.get("href"):
            continue
        url = canonical_url(urljoin(base_url, link["href"]))
        if url in seen:
            continue
        seen.add(url)
        final, old = _magento_prices(tile)
        if final is None:
            final, old = _prices_from_text(_text(tile))
        out.append(Record(
            url=url,
            name=_tile_name(tile, url, base_url),
            price=final, catalog_price=old, context=context, image=_img_url(tile, base_url),
            method="magento-tile",
        ))
    return [r for r in out if r.name]


def _prices_from_text(text: str) -> tuple[float | None, float | None]:
    prices = sorted({parse_price(m.group(0)) for m in PRICE_RE.finditer(text)} - {None})
    if not prices:
        return None, None
    if len(prices) >= 2:
        return prices[0], prices[-1]
    return prices[0], None


def _generic_tiles(soup: BeautifulSoup, base_url: str, context: str) -> list[Record]:
    """Heurystyka: tekst z ceną -> najbliższy przodek z linkiem o sensownej nazwie."""
    host = urlsplit(base_url).hostname
    found: dict[str, Record] = {}
    for node in soup.find_all(string=PRICE_RE):
        el = node.parent
        for _ in range(8):
            if el is None or el.name in ("body", "html"):
                break
            links = [a for a in el.find_all("a", href=True)
                     if len(_text(a)) >= 8 and (urlsplit(urljoin(base_url, a["href"])).hostname == host)]
            hrefs = {canonical_url(urljoin(base_url, a["href"])) for a in links}
            if len(hrefs) == 1:
                url = hrefs.pop()
                if url not in found:
                    final, old = _prices_from_text(_text(el))
                    name = _tile_name(el, url, base_url)
                    found[url] = Record(url=url, name=name, price=final, catalog_price=old, context=context,
                                        image=_img_url(el, base_url), method="generic-tile")
                break
            if len(hrefs) > 1:
                break
            el = el.parent
    return list(found.values())


# ----------------------------------------------------------------------- API

def extract(capture: dict) -> list[Record]:
    html = capture.get("html") or ""
    soup = BeautifulSoup(html, "html.parser")
    canon = soup.select_one("link[rel=canonical]") or soup.select_one("meta[property='og:url']")
    base_url = capture.get("url") or (canon.get("href") or canon.get("content") if canon else "") or ""
    nodes = list(_jsonld_nodes(soup, capture.get("jsonld")))
    context = _breadcrumbs(soup, nodes)
    h1 = _text(soup.find("h1"))[:120]

    ld_products = [n for n in nodes if "Product" in _types(n) or "ProductGroup" in _types(n)]

    if _is_product_page(soup, ld_products):
        rec = None
        for n in ld_products:
            rec = _record_from_jsonld(n, base_url)
            if rec:
                break
        main = soup.select_one(".product-info-main, .product-view, main") or soup
        final, old = _magento_prices(main)
        if rec is None:
            name = h1 or _text(soup.find("title"))
            rec = Record(url=canonical_url(base_url), name=name, method="magento-product")
        if rec.price is None:
            rec.price = final
        if old and (rec.catalog_price is None):
            rec.catalog_price = old
        if canon is not None and (canon.get("href") or canon.get("content")):
            rec.url = canonical_url(urljoin(base_url, canon.get("href") or canon.get("content")))
        if not rec.description:
            desc = soup.select_one(".product.attribute.description, #description, [itemprop=description]")
            rec.description = _text(desc)
        rec.specs = _specs(soup)
        rec.sizes = rec.sizes or _sizes(soup)
        rec.context = context
        rec.kind = "product"
        if not rec.image:
            og = soup.select_one("meta[property='og:image']")
            rec.image = urljoin(base_url, og.get("content")) if og and og.get("content") else _img_url(main, base_url)
        if not rec.brand:
            for k, v in rec.specs.items():
                if k.lower() in ("marka", "producent", "brand"):
                    rec.brand = v
        return [rec] if rec.name else []

    listing_context = " > ".join(x for x in (context, h1) if x)
    out = [r for n in ld_products if (r := _record_from_jsonld(n, base_url))]
    for r in out:
        r.context = listing_context
    if not out or all(r.price is None for r in out):
        tiles = _magento_tiles(soup, base_url, listing_context) or _generic_tiles(soup, base_url, listing_context)
        by_url = {r.url: r for r in out}
        for t in tiles:
            if t.url in by_url:
                r = by_url[t.url]
                r.price, r.catalog_price = t.price, r.catalog_price or t.catalog_price
                r.image = r.image or t.image
                r.method += "+" + t.method
            else:
                by_url[t.url] = t
        out = list(by_url.values())
    return out
