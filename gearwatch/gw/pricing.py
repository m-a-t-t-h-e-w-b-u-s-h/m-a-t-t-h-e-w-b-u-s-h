"""Cena efektywna."""
from __future__ import annotations

from .config import Config


def effective_price(cfg: Config, shop: str, price: float | None, catalog: float | None) -> float | None:
    """Skalnik: min(aktualna, katalogowa * 0.7); 8a: aktualna.

    Gdy sklep nie pokazuje ceny katalogowej (brak przekreślonej), przyjmujemy,
    że katalogowa = aktualna.
    """
    if price is None:
        return None
    factor = cfg.shops[shop].catalog_factor if shop in cfg.shops else None
    if not factor:
        return round(price, 2)
    base = catalog if catalog and catalog >= price else price
    return round(min(price, base * factor), 2)
