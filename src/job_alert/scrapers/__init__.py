"""Scraper adapters. Each adapter turns one company's careers source into list[Job]."""

from __future__ import annotations

from job_alert.scrapers import eightfold, greenhouse, lever
from job_alert.scrapers.base import Scraper

REGISTRY: dict[str, Scraper] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "eightfold": eightfold.fetch,
    # later: "ashby", "workday", ...
}


def get_scraper(type_: str) -> Scraper:
    try:
        return REGISTRY[type_]
    except KeyError:
        raise ValueError(f"Unknown scraper type {type_!r}; known: {sorted(REGISTRY)}") from None
